/**
 * Copyright (c) HiSilicon (Shanghai) Technologies Co., Ltd. 2023-2023. All rights reserved.
 *
 * Description: SLE multi-anchor ranging server. \n
 *
 * History: \n
 * 2023-07-17, Create file. \n
 */
#include "sle_measure_dis_server.h"
#include "sle_errcode.h"
#include "sle_common.h"
#include "sle_device_manager.h"
#include "sle_connection_manager.h"
#include "sle_device_discovery.h"
#include "sle_ssap_server.h"
#include "sle_hadm_manager.h"
#include "sle_measure_dis_server_adv.h"
#include "sle_measure_dis_server_alg.h"

#define DATA_LEN 2
#define ADV_TO_CLIENT 1
#define BLE_SLE_TAG_TASK_DURATION_MS 10
#define SLEM_IQ_DATALEN 512

#if (MEASURE_DIS_ANCHOR_ID < MEASURE_DIS_ANCHOR_ID_MIN) || \
    (MEASURE_DIS_ANCHOR_ID > MEASURE_DIS_ANCHOR_ID_MAX)
#error "MEASURE_DIS_ANCHOR_ID must be in range [1, 4]"
#endif

/* SLE 协议栈已使能标志，Anchor 初始化等待回调把它置为 1。 */
static uint8_t g_stack_enable_status = 0;

/* SSAP Server、测距服务和通知属性由协议栈分配的句柄。 */
static uint8_t g_server_id = 0;
static uint16_t g_service_handle = 0;
static uint16_t g_property_handle = 0;

/* UUID只支持2字节和16字节 */
#define SLEM_UUID_LEN SLE_UUID_LEN
/*
 * 地址同时承担设备身份编码：Anchor 使用 01:01:01:01:01:<anchor_id>，
 * Collector 固定使用 04:04:04:04:04:04，其他地址均视为 Ranging Client。
 */
uint8_t g_measure_dis_server_addr[SLE_ADDR_LEN] = { 1, 1, 1, 1, 1, MEASURE_DIS_ANCHOR_ID };
static uint8_t g_measure_dis_collector_addr[SLE_ADDR_LEN] = { 4, 4, 4, 4, 4, 4 };

typedef struct {
    uint16_t conn_id;       /* SDK 分配的连接句柄。 */
    uint8_t role;           /* 对端是 Ranging Client、Collector 或未知设备。 */
    uint8_t client_id;      /* 对端地址末字节，用作 Ranging Client 身份。 */
    uint16_t rx_stream_len; /* 当前接收缓存内尚未解析的字节数。 */
    uint8_t rx_stream_buf[MEASURE_DIS_RX_STREAM_BUF_SIZE]; /* 每连接独立的拆包缓存。 */
} measure_dis_conn_state_t;

/* Anchor 可同时维护多条 Ranging Client 和 Collector 连接。 */
static measure_dis_conn_state_t g_measure_dis_conns[MEASURE_DIS_MAX_CLIENTS] = {0};
/* 转发给 Collector 的累计失败次数，用于限制重复错误日志。 */
static uint32_t g_collect_send_fail_cnt = 0;

static void measure_dis_reset_conn_state(measure_dis_conn_state_t *conn_state)
{
    if (conn_state == NULL) {
        return;
    }
    conn_state->conn_id = SLEM_CONNET_INVAILD;
    conn_state->role = MEASURE_DIS_CONN_ROLE_UNKNOWN;
    conn_state->client_id = 0;
    conn_state->rx_stream_len = 0;
}

static int measure_dis_find_conn_slot(uint16_t conn_id)
{
    for (int i = 0; i < MEASURE_DIS_MAX_CLIENTS; i++) {
        if (g_measure_dis_conns[i].conn_id == conn_id) {
            return i;
        }
    }
    return -1;
}

static int measure_dis_alloc_conn_slot(void)
{
    for (int i = 0; i < MEASURE_DIS_MAX_CLIENTS; i++) {
        if (g_measure_dis_conns[i].conn_id == SLEM_CONNET_INVAILD) {
            return i;
        }
    }
    return -1;
}

static measure_dis_conn_state_t *measure_dis_get_conn_state(uint16_t conn_id)
{
    int idx = measure_dis_find_conn_slot(conn_id);
    if (idx < 0) {
        return NULL;
    }
    return &g_measure_dis_conns[idx];
}

static measure_dis_conn_state_t *measure_dis_get_or_alloc_conn_state(uint16_t conn_id)
{
    int idx = measure_dis_find_conn_slot(conn_id);
    if (idx < 0) {
        idx = measure_dis_alloc_conn_slot();
    }
    if (idx < 0) {
        return NULL;
    }
    if (g_measure_dis_conns[idx].conn_id == SLEM_CONNET_INVAILD) {
        measure_dis_reset_conn_state(&g_measure_dis_conns[idx]);
        g_measure_dis_conns[idx].conn_id = conn_id;
    }
    return &g_measure_dis_conns[idx];
}

/* 根据对端地址识别 Ranging Client 或 Collector，后续消息按角色分别处理。 */
static measure_dis_conn_role_t measure_dis_detect_conn_role(const sle_addr_t *addr)
{
    if (addr == NULL) {
        return MEASURE_DIS_CONN_ROLE_UNKNOWN;
    }
    if (memcmp(addr->addr, g_measure_dis_collector_addr, SLE_ADDR_LEN) == 0) {
        return MEASURE_DIS_CONN_ROLE_COLLECTOR2;
    }
    return MEASURE_DIS_CONN_ROLE_RANGING;
}

static const char *measure_dis_conn_role_name(measure_dis_conn_role_t role)
{
    return (role == MEASURE_DIS_CONN_ROLE_COLLECTOR2) ? "COLLECTOR" :
           (role == MEASURE_DIS_CONN_ROLE_RANGING) ? "RANGING" : "UNKNOWN";
}

/* 通过连接句柄查询已登记的对端角色，供算法与消息处理层判断数据去向。 */
measure_dis_conn_role_t measure_dis_get_conn_role(uint16_t conn_id)
{
    measure_dis_conn_state_t *conn_state = measure_dis_get_conn_state(conn_id);
    if (conn_state == NULL) {
        return MEASURE_DIS_CONN_ROLE_UNKNOWN;
    }
    return (measure_dis_conn_role_t)conn_state->role;
}

/* 通过连接句柄取得 Ranging Client 的地址标识，写入 Collector 采集结果。 */
uint8_t measure_dis_get_conn_client_id(uint16_t conn_id)
{
    measure_dis_conn_state_t *conn_state = measure_dis_get_conn_state(conn_id);
    if (conn_state == NULL) {
        return 0;
    }
    return conn_state->client_id;
}

/* IQ 回调通知 Anchor 主任务处理队列的事件对象。 */
osal_event measure_dis_evt;
/* 保存本地和远端 IQ 工作项的消息队列句柄及单次读取缓存。 */
unsigned long g_measure_dis_queue;
measure_dis_msg_node_t g_msg_data;

/* SSAP Server、服务和属性使用的固定 128 位 UUID。 */
measure_dis_server_data_t g_measure_dis_server_data = {
    .server_uuid = {0x11, 0x22, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
    .service_uuid = {0x11, 0x33, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0},
    .property_uuid = {0x11, 0x44, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0},
};

/* 建立连接时登记角色和 client_id；断开时清理算法及收包状态并恢复广播。 */
static void measure_dis_cm_conn_state_cbk(uint16_t conn_id, const sle_addr_t *addr,
                                          sle_acb_state_t conn_state,
                                          sle_pair_state_t pair_state, sle_disc_reason_t disc_reason)
{
    unused(pair_state);
    if (conn_state == SLE_ACB_STATE_CONNECTED) {
        measure_dis_conn_role_t role = measure_dis_detect_conn_role(addr);
        uint8_t client_id = (addr != NULL) ? addr->addr[SLE_ADDR_LEN - 1] : 0;
        measure_dis_conn_state_t *conn_state_info = measure_dis_get_or_alloc_conn_state(conn_id);
        if (conn_state_info != NULL) {
            conn_state_info->role = (uint8_t)role;
            conn_state_info->client_id = client_id;
            conn_state_info->rx_stream_len = 0;
        } else {
            osal_printk("[ERROR] connection table full, conn:%u\r\n", conn_id);
        }
        osal_printk("[LINK] connected role=%s client=%u conn=%u\r\n",
                    measure_dis_conn_role_name(role), client_id, conn_id);
        /* 连接建立后继续广播，使多个 Ranging Client 和 Collector 仍能接入同一 Anchor。 */
        measure_dis_start_adv(ADV_TO_CLIENT);
    } else if (conn_state == SLE_ACB_STATE_DISCONNECTED) {
        int idx = measure_dis_find_conn_slot(conn_id);
        uint8_t client_id = 0;
        measure_dis_conn_role_t role = MEASURE_DIS_CONN_ROLE_UNKNOWN;
        if (idx >= 0) {
            client_id = g_measure_dis_conns[idx].client_id;
            role = (measure_dis_conn_role_t)g_measure_dis_conns[idx].role;
        }
        (void)measure_dis_alg_reset_conn(conn_id);
        if (idx >= 0) {
            measure_dis_reset_conn_state(&g_measure_dis_conns[idx]);
        }
        osal_printk("[LINK] disconnected role=%s client=%u conn=%u reason=0x%x\r\n",
                    measure_dis_conn_role_name(role), client_id, conn_id, disc_reason);
        measure_dis_start_adv(ADV_TO_CLIENT);
    }
}

errcode_t measure_dis_cm_register_cbks(void)
{
    sle_connection_callbacks_t cm_cbks = {0};
    cm_cbks.connect_state_changed_cb = measure_dis_cm_conn_state_cbk;
    cm_cbks.connect_param_update_req_cb = NULL;
    cm_cbks.connect_param_update_cb = NULL;
    cm_cbks.auth_complete_cb = NULL;
    cm_cbks.pair_complete_cb = NULL;
    cm_cbks.read_rssi_cb = NULL;

    return sle_connection_register_callbacks(&cm_cbks);
}

static void measure_dis_dd_enable_cbk(uint8_t status)
{
    unused(status);
    g_stack_enable_status = 1;
}

static void measure_dis_dd_disenable_cbk(uint8_t status)
{
    unused(status);
    g_stack_enable_status = 0;
}

static void measure_dis_dd_announce_enable_cbk(uint32_t discovery_id, errcode_t status)
{
    unused(discovery_id);
    unused(status);
}

errcode_t measure_dis_dm_register_cbks(void)
{
    sle_dev_manager_callbacks_t dm_cbks  = {
        .sle_enable_cb = measure_dis_dd_enable_cbk,
        .sle_disable_cb = measure_dis_dd_disenable_cbk,
    };
    return sle_dev_manager_register_callbacks(&dm_cbks);
}

errcode_t measure_dis_dd_register_cbks(void)
{
    sle_announce_seek_callbacks_t dd_cbks  = {
        .announce_enable_cb = measure_dis_dd_announce_enable_cbk,
        .announce_disable_cb = NULL,
        .announce_terminal_cb = NULL,
        .seek_enable_cb = NULL,
        .seek_disable_cb = NULL,
        .seek_result_cb = NULL,
    };
    return sle_announce_seek_register_callbacks(&dd_cbks);
}

static void measure_dis_ssaps_read_request_cbk(uint8_t server_id, uint16_t conn_id, ssaps_req_read_cb_t *read_cb_para,
    errcode_t status)
{
    unused(server_id);
    unused(conn_id);
    unused(read_cb_para);
    unused(status);
}

/* 接收 Collector 回传的最终文本结果，并按原内容输出到 Anchor 串口。 */
static errcode_t measure_dis_server_handle_final_result(uint16_t data_len, uint8_t *data)
{
    char *text = NULL;

    if (data == NULL || data_len == 0) {
        return ERRCODE_INVALID_PARAM;
    }

    text = (char *)osal_kmalloc((uint32_t)data_len + 1, 0);
    if (text == NULL) {
        return ERRCODE_MALLOC;
    }
    if (memcpy_s(text, (uint32_t)data_len + 1, data, data_len) != EOK) {
        osal_kfree(text);
        return ERRCODE_MEMCPY;
    }
    text[data_len] = '\0';

    osal_printk("%s", text);
    osal_kfree(text);

    return ERRCODE_SUCC;
}

/* 校验完整业务帧，并把 IQ 或 Collector 最终结果分派到对应处理函数。 */
void measure_dis_server_msg_proc(uint16_t conn_id, uint8_t *data, uint16_t data_len)
{
    measure_ids_msg_t msg_hdr = {0};
    uint8_t *payload = NULL;

    if (data == NULL) {
        return;
    }

    if (data_len < sizeof(measure_ids_msg_t)) {
        osal_printk("[ERROR] drop short frame, len:%u\r\n", data_len);
        return;
    }

    if (memcpy_s(&msg_hdr, sizeof(msg_hdr), data, sizeof(measure_ids_msg_t)) != EOK) {
        osal_printk("[ERROR] copy frame header failed, len:%u\r\n", data_len);
        return;
    }

    uint32_t ret = ERRCODE_SLE_FAIL;
    uint16_t payload_max = (uint16_t)(data_len - sizeof(measure_ids_msg_t));
    payload = data + sizeof(measure_ids_msg_t);

    if (msg_hdr.len > payload_max) {
        osal_printk("[ERROR] invalid frame length, type:0x%x message:%u payload:%u\r\n",
                    msg_hdr.type, (uint16_t)msg_hdr.len, payload_max);
        return;
    }

    if (msg_hdr.type != SLEM_PROFILE_MSG_IQ && msg_hdr.type != SLEM_MSG_FINAL_RESULT) {
        osal_printk("[ERROR] unsupported frame type:0x%x\r\n", msg_hdr.type);
        return;
    }

    switch (msg_hdr.type) {
        case SLEM_PROFILE_MSG_IQ:
            if (measure_dis_get_conn_role(conn_id) != MEASURE_DIS_CONN_ROLE_RANGING) {
                ret = ERRCODE_INVALID_PARAM;
            } else {
                ret = measure_dis_remote_iq(conn_id, (uint16_t)msg_hdr.len, payload);
            }
            break;
        case SLEM_MSG_FINAL_RESULT:
            if (measure_dis_get_conn_role(conn_id) != MEASURE_DIS_CONN_ROLE_COLLECTOR2) {
                ret = ERRCODE_SUCC;
            } else {
                ret = measure_dis_server_handle_final_result((uint16_t)msg_hdr.len, payload);
            }
            break;
        default:
            break;
    }

    if (unlikely(ret != ERRCODE_SLE_SUCCESS)) {
        osal_printk("[ERROR] process client message failed, type:0x%x ret:0x%x\r\n", msg_hdr.type, ret);
    }
}

/* 按连接缓存 SSAP 写入数据，处理半帧、粘连多帧，再逐帧交给业务解析。 */
static void measure_dis_ssaps_write_request_cbk(uint8_t server_id, uint16_t conn_id,
    ssaps_req_write_cb_t *write_cb_para, errcode_t status)
{
    ssaps_req_write_cb_t write_local = {0};
    uint16_t frame_len;

    unused(server_id);
    unused(status);

    if (write_cb_para == NULL) {
        return;
    }

    if (memcpy_s(&write_local, sizeof(write_local), write_cb_para, sizeof(ssaps_req_write_cb_t)) != EOK) {
        return;
    }

    /* CCCD 等描述符写入不属于本业务数据，直接忽略。 */
    if (write_local.handle != g_property_handle) {
        return;
    }

    if (write_local.length == 0 || write_local.value == NULL) {
        return;
    }

    measure_dis_conn_state_t *conn_state = measure_dis_get_or_alloc_conn_state(conn_id);
    if (conn_state == NULL) {
        osal_printk("[ERROR] receive stream has no connection slot, conn:%u\r\n", conn_id);
        return;
    }

    /*
     * SSAP 写回调不是消息边界：一次回调可能只有半帧，也可能包含连续多帧。
     * 因此每条连接单独缓存，按 8 字节头部中的长度字段逐帧取出，剩余数据留待下次回调。
     */
    if ((uint32_t)conn_state->rx_stream_len + write_local.length > MEASURE_DIS_RX_STREAM_BUF_SIZE) {
        osal_printk("[ERROR] receive stream overflow, cached:%u incoming:%u\r\n",
                    conn_state->rx_stream_len, write_local.length);
        conn_state->rx_stream_len = 0;
    }

    if ((uint32_t)conn_state->rx_stream_len + write_local.length <= MEASURE_DIS_RX_STREAM_BUF_SIZE) {
        if (memcpy_s(conn_state->rx_stream_buf + conn_state->rx_stream_len,
                     MEASURE_DIS_RX_STREAM_BUF_SIZE - conn_state->rx_stream_len,
                     write_local.value,
                     write_local.length) != EOK) {
            conn_state->rx_stream_len = 0;
            return;
        }
        conn_state->rx_stream_len = (uint16_t)(conn_state->rx_stream_len + write_local.length);
    }

    while (conn_state->rx_stream_len >= sizeof(measure_ids_msg_t)) {
        measure_ids_msg_t *msg = (measure_ids_msg_t *)conn_state->rx_stream_buf;
        frame_len = (uint16_t)(sizeof(measure_ids_msg_t) + msg->len);

        if (frame_len < sizeof(measure_ids_msg_t)) {
            osal_printk("[ERROR] invalid receive frame length:%u\r\n", frame_len);
            conn_state->rx_stream_len = 0;
            return;
        }

        if (frame_len > MEASURE_DIS_RX_STREAM_BUF_SIZE) {
            osal_printk("[ERROR] receive frame too large:%u\r\n", frame_len);
            conn_state->rx_stream_len = 0;
            return;
        }

        if (frame_len > conn_state->rx_stream_len) {
            break;
        }

        measure_dis_server_msg_proc(conn_id, conn_state->rx_stream_buf, frame_len);

        if (conn_state->rx_stream_len > frame_len) {
            if (memmove_s(conn_state->rx_stream_buf,
                          MEASURE_DIS_RX_STREAM_BUF_SIZE,
                          conn_state->rx_stream_buf + frame_len,
                          conn_state->rx_stream_len - frame_len) != EOK) {
                conn_state->rx_stream_len = 0;
                return;
            }
        }
        conn_state->rx_stream_len = (uint16_t)(conn_state->rx_stream_len - frame_len);
    }
}

static void measure_dis_ssaps_mtu_changed_cbk(uint8_t server_id, uint16_t conn_id,  ssap_exchange_info_t *mtu_size,
    errcode_t status)
{
    unused(server_id);
    unused(conn_id);
    unused(mtu_size);
    unused(status);
}

static void measure_dis_ssaps_start_service_cbk(uint8_t server_id, uint16_t handle, errcode_t status)
{
    if (status != ERRCODE_SUCC) {
        osal_printk("[ERROR] start SLE service failed, server:%u handle:%u status:0x%x\r\n",
                    server_id, handle, status);
        return;
    }
}

static void measure_dis_ssaps_register_cbks(void)
{
    ssaps_callbacks_t ssaps_cbk = {0};
    ssaps_cbk.start_service_cb = measure_dis_ssaps_start_service_cbk;
    ssaps_cbk.mtu_changed_cb = measure_dis_ssaps_mtu_changed_cbk;
    ssaps_cbk.read_request_cb = measure_dis_ssaps_read_request_cbk;
    ssaps_cbk.write_request_cb = measure_dis_ssaps_write_request_cbk;
    ssaps_register_callbacks(&ssaps_cbk);
}

/* 向 SSAP Server 注册测距主服务，并保存协议栈分配的服务句柄。 */
static errcode_t measure_dis_server_service_add(void)
{
    errcode_t ret;
    sle_uuid_t service_uuid = {0};
    service_uuid.len = SLEM_UUID_LEN;
    if (memcpy_s(service_uuid.uuid, SLE_UUID_LEN, g_measure_dis_server_data.service_uuid, SLEM_UUID_LEN) != EOK) {
        return ERRCODE_MEMCPY;
    }
    ret = ssaps_add_service_sync(g_server_id, &service_uuid, 1, &g_service_handle);
    if (ret != ERRCODE_SLE_SUCCESS) {
        return ERRCODE_SLE_FAIL;
    }
    return ERRCODE_SLE_SUCCESS;
}

/* 添加支持读、写和通知的数据属性及其客户端配置描述符。 */
static errcode_t measure_dis_server_property_add(void)
{
    errcode_t ret;
    uint8_t property_data[DATA_LEN] = {11, 11};
    uint8_t descriptor_data[DATA_LEN] = {0x01, 0x00};
    ssaps_property_info_t property = {0};
    ssaps_desc_info_t descriptor = {0};

    property.uuid.len = SLEM_UUID_LEN;
    if (memcpy_s(property.uuid.uuid, SLE_UUID_LEN, g_measure_dis_server_data.property_uuid, SLEM_UUID_LEN) != EOK) {
        return ERRCODE_MEMCPY;
    }
    property.operate_indication = SSAP_OPERATE_INDICATION_BIT_READ | 
                                SSAP_OPERATE_INDICATION_BIT_WRITE | 
                                SSAP_OPERATE_INDICATION_BIT_NOTIFY;
    property.value = property_data;
    property.value_len = DATA_LEN;

    ret = ssaps_add_property_sync(g_server_id, g_service_handle, &property,  &g_property_handle);
    if (ret != ERRCODE_SLE_SUCCESS) {
        return ERRCODE_SLE_FAIL;
    }
    descriptor.permissions = SSAP_PERMISSION_READ | SSAP_PERMISSION_WRITE;
    descriptor.value = descriptor_data;
    descriptor.value_len = DATA_LEN;
    descriptor.type = SSAP_DESCRIPTOR_CLIENT_CONFIGURATION;

    ret = ssaps_add_descriptor_sync(g_server_id, g_service_handle, g_property_handle, &descriptor);
    if (ret != ERRCODE_SLE_SUCCESS) {
        return ERRCODE_SLE_FAIL;
    }

    return ERRCODE_SLE_SUCCESS;
}

/* 在建立连接前设置 Server MTU，使完整 IQ 消息能够通过 SSAP 传输。 */
int measure_dis_server_set_mtu(uint16_t mtu_size, uint16_t version)
{
    ssap_exchange_info_t info = {
        .mtu_size = mtu_size,
        .version = version
    };

    return ssaps_set_info(g_server_id, &info);
}

/* 完成 MTU、回调、Server、服务和属性注册，最后启动测距服务。 */
int measure_dis_server_add(void)
{
    errcode_t ret;
    sle_uuid_t app_uuid = {0};

    measure_dis_server_set_mtu(SLEM_IQ_DATALEN, 1);  /* 需要在连接建立之前 */
    measure_dis_ssaps_register_cbks();
    app_uuid.len = SLEM_UUID_LEN;
    if (memcpy_s(app_uuid.uuid, SLE_UUID_LEN, g_measure_dis_server_data.server_uuid, SLEM_UUID_LEN) != EOK) {
        return ERRCODE_SLE_FAIL;
    }
    ssaps_register_server(&app_uuid, &g_server_id);

    if (measure_dis_server_service_add() != ERRCODE_SLE_SUCCESS) {
        ssaps_unregister_server(g_server_id);
        return ERRCODE_SLE_FAIL;
    }

    if (measure_dis_server_property_add() != ERRCODE_SLE_SUCCESS) {
        ssaps_unregister_server(g_server_id);
        return ERRCODE_SLE_FAIL;
    }
    ret = ssaps_start_service(g_server_id, g_service_handle);
    if (ret != ERRCODE_SLE_SUCCESS) {
        return ERRCODE_SLE_FAIL;
    }
    return ERRCODE_SLE_SUCCESS;
}

errcode_t measure_dis_set_local_addr(uint8_t *addr)
{
    sle_addr_t sle_addr = {0};
    if (memcpy_s(sle_addr.addr, SLE_ADDR_LEN, addr, SLE_ADDR_LEN) != EOK) {
        return ERRCODE_MEMCPY;
    };
    return sle_set_local_addr(&sle_addr);
}

errcode_t measure_dis_set_local_name(uint8_t *name, uint8_t len)
{
    return sle_set_local_name(name, len);
}

/* 注册设备与连接回调，启动 SLE 协议栈，再设置 Anchor 本地地址和名称。 */
void measure_dis_protocol_stack_init(uint8_t *addr, uint8_t *name)
{
    uint32_t ret = ERRCODE_SLE_SUCCESS;

    ret |= measure_dis_dm_register_cbks();
    ret |= measure_dis_cm_register_cbks();
    ret |= measure_dis_dd_register_cbks();
    ret = enable_sle();
    while (g_stack_enable_status != 1) {
        osal_msleep(BLE_SLE_TAG_TASK_DURATION_MS);
    }
    measure_dis_set_local_addr(addr);
    measure_dis_set_local_name(name, strlen((char *)name));
}

/* 使用已注册的服务 UUID，通过通知向指定连接发送原始业务帧。 */
int measure_dis_sle_server_ntf_by_addr(uint16_t conn_id, uint16_t len, uint8_t *data)
{
    /* type must be 0 */
    errcode_t ret = ERRCODE_FAIL;
    ssaps_ntf_ind_by_uuid_t param = {
        .uuid.len = SLEM_UUID_LEN,
        .start_handle = g_service_handle,
        .end_handle = g_property_handle,
        .type = 0,
        .value_len = len,
        .value = data,
    };
    if (memcpy_s(param.uuid.uuid, SLE_UUID_LEN, g_measure_dis_server_data.property_uuid, SLEM_UUID_LEN) != EOK) {
        return ERRCODE_MEMCPY;
    }
    ret = ssaps_notify_indicate_by_uuid(g_server_id, conn_id, &param);

    return ret;
}

/* 封装统一消息头，并通过通知向指定连接发送一条业务消息。 */
int measure_dis_server_write_conn(uint16_t conn_id, uint32_t type, uint8_t *data, uint32_t data_len)
{
    if (conn_id == SLEM_CONNET_INVAILD) {
        return ERRCODE_INVALID_PARAM;
    }
    if ((data == NULL) && (data_len > 0)) {
        return ERRCODE_INVALID_PARAM;
    }
    if (data_len > (uint32_t)(0xFFFFU - sizeof(measure_ids_msg_t))) {
        return ERRCODE_INVALID_PARAM;
    }
    uint16_t len = sizeof(measure_ids_msg_t) + data_len;
    measure_ids_msg_t *slem_msg = (measure_ids_msg_t *)osal_kmalloc(len, 0);
    if (slem_msg == NULL) {
        return ERRCODE_MALLOC;
    }
    slem_msg->type = type;
    slem_msg->len = data_len;
    if (memcpy_s(slem_msg->data, data_len, data, data_len) != EOK) {
        osal_kfree(slem_msg);
        return ERRCODE_MEMCPY;
    }
    uint32_t ret = measure_dis_sle_server_ntf_by_addr(conn_id, len, (uint8_t *)(slem_msg));
    if (ret != ERRCODE_SUCC) {
        osal_printk("[ERROR] server send failed, conn:%u ret:0x%x\r\n", conn_id, ret);
    }
    osal_kfree(slem_msg);

    return ret;
}

/* 将距离或 IQ 数据转发给当前已连接的所有 Collector，并执行有限重试。 */
int measure_dis_server_write_collectors(uint32_t type, uint8_t *data, uint32_t data_len)
{
    int ret = ERRCODE_SUCC;
    for (int i = 0; i < MEASURE_DIS_MAX_CLIENTS; i++) {
        int single_ret = ERRCODE_SUCC;
        if (g_measure_dis_conns[i].conn_id == SLEM_CONNET_INVAILD) {
            continue;
        }
        if (g_measure_dis_conns[i].role != MEASURE_DIS_CONN_ROLE_COLLECTOR2) {
            continue;
        }
        for (int retry = 0; retry <= MEASURE_DIS_COLLECTOR_SEND_RETRY_MAX; retry++) {
            single_ret = measure_dis_server_write_conn(g_measure_dis_conns[i].conn_id, type, data, data_len);
            if (single_ret == ERRCODE_SUCC) {
                break;
            }
            if (retry < MEASURE_DIS_COLLECTOR_SEND_RETRY_MAX) {
                osal_msleep(MEASURE_DIS_COLLECTOR_SEND_RETRY_DELAY_MS);
            }
        }
        if (single_ret != ERRCODE_SUCC) {
            g_collect_send_fail_cnt++;
            if ((g_collect_send_fail_cnt % MEASURE_DIS_COLLECTOR_SEND_FAIL_LOG_INTERVAL) == 1) {
                osal_printk("[ERROR] Collector send failed, conn:%u type:0x%x ret:0x%x total:%u\r\n",
                            g_measure_dis_conns[i].conn_id,
                            type,
                            single_ret,
                            g_collect_send_fail_cnt);
            }
            ret = single_ret;
        }
    }
    return ret;
}

/* 从消息队列取出一项本地或远端 IQ 任务，并在 Anchor 任务上下文中处理。 */
void sle_measure_dis_msg_proc(void)
{
    measure_dis_msg_node_t *msg_node = NULL;
    uint32_t msg_data_size = sizeof(measure_dis_msg_node_t);
    errcode_t ret = ERRCODE_SUCC;
    ret = osal_msg_queue_read_copy(g_measure_dis_queue, &g_msg_data, &msg_data_size, 0);
    if (ret != ERRCODE_SUCC) {
        return;
    }
    msg_node = &g_msg_data;
    ret = measure_dis_match_msg(msg_node);
    if (ret != ERRCODE_SUCC) {
        osal_printk("[ERROR] queued message failed, type:%u\r\n", msg_node->type);
    }
}

/* 将 SDK 回调产生的 IQ 工作项放入队列，避免在回调上下文执行完整测距计算。 */
errcode_t sle_measure_dis_msg_add(measure_dis_msg_node_t *msg)
{
    errcode_t ret = ERRCODE_FAIL;

    do {
        if ((msg == NULL) || (g_measure_dis_queue == 0)) {
            break;
        }
        if (osal_msg_queue_write_copy(g_measure_dis_queue,
                                      (void *)msg, sizeof(measure_dis_msg_node_t), 0) != OSAL_SUCCESS) {
            ret = ERRCODE_FAIL;
            break;
        }
        if (osal_event_write(&measure_dis_evt, MEASURE_DIS_MSG_EVENT) != OSAL_SUCCESS) {
            ret = ERRCODE_FAIL;
            break;
        }
        ret = ERRCODE_SUCC;
    } while (0);

    if (ret != ERRCODE_SUCC) {
        uint8_t msg_num = osal_msg_queue_get_msg_num(g_measure_dis_queue);
        osal_printk("[ERROR] enqueue message failed, queued:%u ret:0x%x\r\n", msg_num, ret);
    }

    return ret;
}


/* 初始化连接表、事件和 IQ 消息队列，为 Anchor 主任务准备运行环境。 */
void sle_measure_dis_init(void)
{
    for (int i = 0; i < MEASURE_DIS_MAX_CLIENTS; i++) {
        measure_dis_reset_conn_state(&g_measure_dis_conns[i]);
    }

    if (osal_event_init(&measure_dis_evt) != ERRCODE_SUCC) {
        osal_printk("[ERROR] initialize ranging event failed\r\n");
        return;
    }

    if (osal_msg_queue_create("measure_dis_queue", MEASURE_DIS_MSG_QUEUE_SIZE,
                              &g_measure_dis_queue, 0, sizeof(measure_dis_msg_node_t)) != ERRCODE_SUCC) {
        osal_printk("[ERROR] initialize ranging queue failed\r\n");
        return;
    }
}

/* Anchor 总初始化入口：启动协议栈、算法回调、SSAP 服务和持续广播。 */
int measure_dis_server_init(void)
{
    uint32_t ret = ERRCODE_SLE_SUCCESS;
    uint8_t measure_dis_name[SLE_NAME_MAX_LEN] = {'s', 'l', 'e', 'm', '-', 's', '\0'};
    sle_measure_dis_init();
    osal_printk("[BOOT] role=ANCHOR id=%u addr=%02X:%02X:%02X:%02X:%02X:%02X\r\n",
                MEASURE_DIS_ANCHOR_ID,
                g_measure_dis_server_addr[0], g_measure_dis_server_addr[1], g_measure_dis_server_addr[2],
                g_measure_dis_server_addr[3], g_measure_dis_server_addr[4], g_measure_dis_server_addr[5]);
    measure_dis_protocol_stack_init(g_measure_dis_server_addr, measure_dis_name);
    measure_dis_reg_callbacks();
    ret = measure_dis_server_add();
    check_rc_return_rc(ret, "server add");
    measure_dis_sle_set_adv(ADV_TO_CLIENT, g_measure_dis_server_addr);
    measure_dis_start_adv(ADV_TO_CLIENT);
    if (ret == ERRCODE_SUCC) {
        osal_printk("[READY] Anchor advertising\r\n");
    }
    return ret;
}
