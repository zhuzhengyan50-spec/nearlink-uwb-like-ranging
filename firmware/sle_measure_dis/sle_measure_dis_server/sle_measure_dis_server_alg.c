/**
 * Copyright (c) HiSilicon (Shanghai) Technologies Co., Ltd. 2023-2023. All rights reserved.
 *
 * Description: SLE ranging algorithm integration. \n
 *
 * History: \n
 * 2023-07-17, Create file. \n
 */
#include "sle_measure_dis_server.h"
#include "sle_common.h"
#include "slem_smooth.h"
#include "slem_alg_smooth_dis.h"
#include "tcxo.h"
#include "sle_measure_dis_server_alg.h"

#define TOF_DEFAULT 2070
#define DIS_ALG_MODE 5
#define DIS_ALG_RSSI_LIMIT (-120)
#define DIS_ALG_THRESHOULD_COND2 20
#define DIS_ALG_R_START 2
#define MEASURE_DIS_ALG_KEY_NUM 2

#ifndef MEASURE_DIS_COLLECTOR_FORWARD_IQ
#define MEASURE_DIS_COLLECTOR_FORWARD_IQ 1
#endif

typedef struct {
    uint16_t conn_id;                           /* 算法状态所属 Client 连接。 */
    uint8_t local_iq_complete;                  /* Anchor 本地 IQ 是否已经收齐。 */
    uint8_t next_idx;                           /* 下一片期望的本地 IQ report_idx。 */
    uint8_t key_id;                             /* 平滑算法使用的状态槽编号。 */
    uint8_t key_shared_logged;                  /* 是否已提示多个连接共享算法槽。 */
    uint32_t range_count;                       /* 该连接累计完成的测距次数。 */
    measure_dis_stored_iq_data_t local_iq_data; /* 当前一次 Anchor 本地 IQ。 */
} measure_dis_alg_conn_slot_t;

/* 每条 Client 连接独立保存 IQ 拼接和距离平滑所需的算法上下文。 */
static measure_dis_alg_conn_slot_t g_measure_dis_alg_slots[MEASURE_DIS_MAX_CLIENTS] = {0};

static void measure_dis_alg_reset_slot(measure_dis_alg_conn_slot_t *slot)
{
    if (slot == NULL) {
        return;
    }
    slot->conn_id = SLEM_CONNET_INVAILD;
    slot->local_iq_complete = false;
    slot->next_idx = 0;
    slot->key_id = 0;
    slot->key_shared_logged = 0;
    slot->range_count = 0;
    (void)memset_s(&slot->local_iq_data, sizeof(slot->local_iq_data), 0, sizeof(slot->local_iq_data));
}

static int measure_dis_alg_find_slot(uint16_t conn_id, uint8_t alloc_if_missing)
{
    int free_slot = -1;

    for (int i = 0; i < MEASURE_DIS_MAX_CLIENTS; i++) {
        if (g_measure_dis_alg_slots[i].conn_id == conn_id) {
            return i;
        }
        if (free_slot < 0 && g_measure_dis_alg_slots[i].conn_id == SLEM_CONNET_INVAILD) {
            free_slot = i;
        }
    }

    if (!alloc_if_missing || free_slot < 0) {
        return -1;
    }

    measure_dis_alg_reset_slot(&g_measure_dis_alg_slots[free_slot]);
    g_measure_dis_alg_slots[free_slot].conn_id = conn_id;
    g_measure_dis_alg_slots[free_slot].key_id = (uint8_t)(free_slot % MEASURE_DIS_ALG_KEY_NUM);
    return free_slot;
}

static measure_dis_alg_conn_slot_t *measure_dis_alg_get_slot(uint16_t conn_id, uint8_t alloc_if_missing)
{
    int slot = measure_dis_alg_find_slot(conn_id, alloc_if_missing);
    if (slot < 0) {
        return NULL;
    }

    if ((slot >= MEASURE_DIS_ALG_KEY_NUM) && (g_measure_dis_alg_slots[slot].key_shared_logged == 0)) {
        g_measure_dis_alg_slots[slot].key_shared_logged = 1;
        osal_printk("[WARN] ranging key shared, conn:%u slot:%d key:%u\r\n",
                    conn_id, slot, g_measure_dis_alg_slots[slot].key_id);
    }

    return &g_measure_dis_alg_slots[slot];
}

/* 连接断开时清空对应算法槽，释放其中的 IQ、序号和平滑状态。 */
errcode_t measure_dis_alg_reset_conn(uint16_t conn_id)
{
    measure_dis_alg_conn_slot_t *slot = measure_dis_alg_get_slot(conn_id, 0);
    if (slot != NULL) {
        measure_dis_alg_reset_slot(slot);
    }
    return ERRCODE_SUCC;
}

/* 给 IQ 附加 Anchor、Client 和连接标识，再转发给所有 Collector。 */
static errcode_t measure_dis_send_collect_iq(uint16_t conn_id, uint32_t type,
                                             const sle_channel_sounding_iq_trans_t *iq)
{
#if !MEASURE_DIS_COLLECTOR_FORWARD_IQ
    unused(conn_id);
    unused(type);
    unused(iq);
    return ERRCODE_SUCC;
#else
    uint8_t payload[sizeof(measure_dis_collect_iq_hdr_t) + sizeof(sle_channel_sounding_iq_trans_t)] = {0};
    measure_dis_collect_iq_hdr_t *hdr = (measure_dis_collect_iq_hdr_t *)payload;
    hdr->anchor_id = MEASURE_DIS_ANCHOR_ID;
    hdr->reserved = measure_dis_get_conn_client_id(conn_id);
    hdr->conn_id = conn_id;
    if (memcpy_s(payload + sizeof(measure_dis_collect_iq_hdr_t),
                 sizeof(sle_channel_sounding_iq_trans_t),
                 iq,
                 sizeof(sle_channel_sounding_iq_trans_t)) != EOK) {
        return ERRCODE_MEMCPY;
    }
    return (errcode_t)measure_dis_server_write_collectors(type, payload, sizeof(payload));
#endif
}

/* 填充测距算法每次计算都需要的标定值、TOF 默认值和算法模式。 */
void slem_posalg_set_base_para(slem_alg_para_dis *alg_para, uint8_t key_id)
{
    unused(key_id);
    alg_para->calib_val = 0.8;
    alg_para->tof_calib = TOF_DEFAULT;
    alg_para->ranging_method = DIS_ALG_MODE;
}

void measure_dis_print_cal_dis(float dist_first, float dist_ori, float prob, uint32_t time)
{
    unused(dist_first);
    unused(dist_ori);
    unused(prob);
    unused(time);
}

static void measure_dis_posalg_set_distance(slem_smoothed_dis_result *dis,
    measure_dis_profile_msg_dis_t *measure_dis_temp)
{
    measure_dis_temp->dist_first = dis->dis_smoothed;
    measure_dis_temp->dist_second = dis->dis_ori;
    measure_dis_temp->dist_double = dis->dis_slight_smoothed;
    measure_dis_temp->high = dis->height;
    measure_dis_temp->prob = dis->prob;
    measure_dis_temp->rssi = dis->rssi;
    measure_dis_temp->smooth_num = dis->smooth_num;
}

/* 将同一次本地和远端 IQ 输入测距算法，并把距离分别发给 Client 与 Collector。 */
static void measure_dis_posalg_get_distance(uint16_t conn_id,
                                            measure_dis_alg_conn_slot_t *conn_slot,
                                            measure_dis_profile_msg_dis_t *measure_dis_temp,
                                            sle_channel_sounding_iq_trans_t *remote_iq_data)
{
    slem_alg_para_dis *alg_para = NULL;
    slem_para_pair para_limit = {.rssi_limit = DIS_ALG_RSSI_LIMIT,
                                 .threshold_cond2 = DIS_ALG_THRESHOULD_COND2,
                                 .r_start = DIS_ALG_R_START};
    slem_smoothed_dis_result result_dist;
    uint32_t time_start;
    uint32_t time_end;
    uint32_t dist_mm;
    int8_t rssi_dbm;
    int send_ret;
    uint8_t dist_rssi_payload[SLEM_MSG_DIST_RSSI_LEN] = {0};
    measure_dis_collect_dist_result_t collect_result = {0};

    if (conn_slot == NULL || measure_dis_temp == NULL || remote_iq_data == NULL) {
        return;
    }

    alg_para = (slem_alg_para_dis *)osal_kmalloc(sizeof(slem_alg_para_dis), 0);
    if (alg_para == NULL) {
        return;
    }

    slem_posalg_set_base_para(alg_para, conn_slot->key_id);
    alg_para->rssi_rtd = conn_slot->local_iq_data.rssi;
    alg_para->rssi_dut = remote_iq_data[0].rssi;
#if (defined(GLE_CS_MODE3_SUPPORT))
#if (SLEM_TOF_DATA_ENABLE)
    alg_para->tof_rtd = conn_slot->local_iq_data.tof_result;
    alg_para->tof_dut = remote_iq_data[0].tof_result;
#else
    alg_para->tof_rtd = TOF_DEFAULT;
    alg_para->tof_dut = TOF_DEFAULT;
#endif
#endif
    alg_para->iq_rtd = (slem_alg_iq *)&(conn_slot->local_iq_data.data[0]);
    alg_para->iq_dut = (slem_alg_iq *)&(remote_iq_data[0].data[0]);
    conn_slot->local_iq_complete = false;
    alg_para->para_limit = para_limit;
    alg_para->key_id = conn_slot->key_id;

    time_start = (uint32_t)uapi_tcxo_get_ms();
    alg_para->cur_count = conn_slot->range_count;
    alg_para->cur_time = time_start;
    slem_alg_calc_smoothed_dis(&result_dist, alg_para);
    conn_slot->range_count++;
    time_end = (uint32_t)uapi_tcxo_get_ms();
    measure_dis_print_cal_dis(result_dist.dis_smoothed, result_dist.dis_ori,
                              result_dist.prob, time_end - time_start);

    measure_dis_posalg_set_distance(&result_dist, measure_dis_temp);
    /* Reject negative, non-finite and uint32-overflowing results before conversion to millimetres. */
    if (!(result_dist.dis_smoothed >= 0.0f && result_dist.dis_smoothed <= 4294967.0f)) {
        osal_printk("[ERROR] invalid distance result, conn:%u\r\n", conn_id);
        osal_kfree(alg_para);
        return;
    }
    dist_mm = (uint32_t)(result_dist.dis_smoothed * 1000);
    rssi_dbm = (int8_t)(result_dist.rssi);
    if (memcpy_s(dist_rssi_payload, SLEM_MSG_DIST_LEN, &dist_mm, SLEM_MSG_DIST_LEN) != EOK) {
        osal_kfree(alg_para);
        return;
    }
    dist_rssi_payload[SLEM_MSG_DIST_LEN] = (uint8_t)rssi_dbm;

    send_ret = measure_dis_server_write_conn(conn_id, SLEM_MSG_DIST_RESULT,
                                             dist_rssi_payload, sizeof(dist_rssi_payload));
    if (send_ret != ERRCODE_SUCC) {
        osal_printk("[ERROR] distance send failed, conn:%u ret:0x%x\r\n", conn_id, send_ret);
    }
    collect_result.anchor_id = MEASURE_DIS_ANCHOR_ID;
    collect_result.client_id = measure_dis_get_conn_client_id(conn_id);
    collect_result.sdk_rssi = rssi_dbm;
    collect_result.reserved = 0;
    collect_result.conn_id = conn_id;
    collect_result.reserved2 = 0;
    collect_result.dist_mm = dist_mm;
    collect_result.local_timestamp_sn = conn_slot->local_iq_data.timestamp_sn;
    collect_result.remote_timestamp_sn = remote_iq_data[0].timestamp_sn;
#if (defined(GLE_CS_MODE3_SUPPORT))
    collect_result.local_tof_result = conn_slot->local_iq_data.tof_result;
    collect_result.remote_tof_result = remote_iq_data[0].tof_result;
#else
    collect_result.local_tof_result = 0;
    collect_result.remote_tof_result = 0;
#endif
    collect_result.local_rssi = conn_slot->local_iq_data.rssi;
    collect_result.remote_rssi = remote_iq_data[0].rssi;
    collect_result.reserved3 = 0;
    send_ret = measure_dis_server_write_collectors(SLEM_MSG_COLLECT_DIST_RESULT,
                                                   (uint8_t *)&collect_result,
                                                   sizeof(collect_result));
    if (send_ret != ERRCODE_SUCC) {
        osal_printk("[ERROR] Collector distance send failed, conn:%u ret:0x%x\r\n", conn_id, send_ret);
    }
    osal_kfree(alg_para);
}

/* 按连接拼接 Anchor 本地 IQ 分片，并检查 report_idx 与时间戳是否连续。 */
errcode_t measure_dis_store_local_iq(uint16_t conn_id, sle_channel_sounding_iq_report_t *report)
{
    measure_dis_alg_conn_slot_t *conn_slot = measure_dis_alg_get_slot(conn_id, 1);
    measure_dis_stored_iq_data_t *local_iq = NULL;

    if (conn_slot == NULL || report == NULL) {
        return ERRCODE_FAIL;
    }
    local_iq = &conn_slot->local_iq_data;

    if (report->report_idx == 0) {
        local_iq->samp_cnt = 0;
        local_iq->rssi = report->rssi[0];
        local_iq->es_sn = report->es_sn;
        local_iq->timestamp_sn = report->timestamp_sn;
#if (defined(GLE_CS_MODE3_SUPPORT))
        local_iq->tof_result = report->tof_result;
#endif
        conn_slot->next_idx = 0;
    }
    if ((report->report_idx >= MEASURE_DIS_IQ_REPORT_CNT_MAX ||
         report->timestamp_sn != local_iq->timestamp_sn) ||
        (conn_slot->next_idx != report->report_idx)) {
        osal_printk("[ERROR] store local IQ failed, conn:%u report:%u timestamp:%u expected:%u\r\n",
                    conn_id, report->report_idx, report->timestamp_sn, conn_slot->next_idx);
        return ERRCODE_INVALID_PARAM;
    }
    local_iq->samp_cnt += report->samp_cnt;
    uint8_t offset = report->report_idx * SLE_CS_IQ_REPORT_COUNT;
    for (uint8_t i = 0; i < report->samp_cnt; i++) {
        local_iq->data[offset + i].i_data = report->i_data[i];
        local_iq->data[offset + i].q_data = report->q_data[i];
    }
    conn_slot->next_idx = report->report_idx + 1;

    return ERRCODE_SUCC;
}

/* 处理一片 Anchor 本地 IQ；全部收齐后标记可计算并同步转发给 Collector。 */
errcode_t measure_dis_proc_local_iq(uint16_t conn_id, sle_channel_sounding_iq_report_t *report)
{
    errcode_t ret = ERRCODE_SUCC;
    measure_dis_alg_conn_slot_t *conn_slot = NULL;

    if (report == NULL) {
        return ERRCODE_INVALID_PARAM;
    }
    ret = measure_dis_store_local_iq(conn_id, report);
    if (ret != ERRCODE_SUCC) {
        return ERRCODE_INVALID_PARAM;
    }

    if (report->report_idx + 1 == MEASURE_DIS_IQ_REPORT_CNT_MAX) {
        conn_slot = measure_dis_alg_get_slot(conn_id, 0);
        if (conn_slot == NULL) {
            return ERRCODE_INVALID_PARAM;
        }
        conn_slot->local_iq_complete = true;
        if (measure_dis_get_conn_role(conn_id) == MEASURE_DIS_CONN_ROLE_RANGING) {
            (void)measure_dis_send_collect_iq(conn_id,
                                              SLEM_MSG_COLLECT_LOCAL_IQ,
                                              (const sle_channel_sounding_iq_trans_t *)(&conn_slot->local_iq_data));
        }
    }
    return ret;
}

/* 处理 Client 上传的完整 IQ，与本地 IQ 时间戳匹配后触发距离计算。 */
errcode_t measure_dis_proc_remote_iq(uint16_t conn_id, sle_channel_sounding_iq_trans_t *report)
{
    measure_dis_alg_conn_slot_t *conn_slot = measure_dis_alg_get_slot(conn_id, 1);

    if (conn_slot == NULL || report == NULL) {
        return ERRCODE_INVALID_PARAM;
    }

    if (measure_dis_get_conn_role(conn_id) == MEASURE_DIS_CONN_ROLE_RANGING) {
        (void)measure_dis_send_collect_iq(conn_id, SLEM_MSG_COLLECT_REMOTE_IQ, report);
    }
    if (abs((int32_t)(conn_slot->local_iq_data.timestamp_sn - report->timestamp_sn)) >= MEASURE_DIS_TIMESTAMP_DIFF_MAX) {
        osal_printk("[WARN] IQ timestamp mismatch, conn:%u local:%u remote:%u\r\n",
                    conn_id, conn_slot->local_iq_data.timestamp_sn, report->timestamp_sn);
        return ERRCODE_INVALID_PARAM;
    }

    if (conn_slot->local_iq_complete) {
        measure_dis_profile_msg_dis_t measure_dis_dis_temp = { report->timestamp_sn, 0, 0, 0, 0, 0, 0, 0 };
        measure_dis_posalg_get_distance(conn_id, conn_slot, &measure_dis_dis_temp, report);
    }

    return ERRCODE_SUCC;
}

void measure_dis_read_local_cs_caps_cb(sle_channel_sounding_caps_t *caps, errcode_t status)
{
    unused(caps);
    if (status != ERRCODE_SUCC) {
        osal_printk("[ERROR] read local CS capabilities failed, status:0x%x\r\n", status);
        return;
    }
}

void measure_dis_read_remote_cs_caps_cb(uint16_t conn_id, sle_channel_sounding_caps_t *caps, errcode_t status)
{
    unused(caps);
    if (status != ERRCODE_SUCC) {
        osal_printk("[ERROR] read remote CS capabilities failed, conn:%u status:0x%x\r\n", conn_id, status);
        return;
    }
}

void measure_dis_set_cs_param_cb(uint16_t conn_id, errcode_t status)
{
    if (status != ERRCODE_SUCC) {
        osal_printk("[ERROR] set CS parameters failed, conn:%u status:0x%x\r\n", conn_id, status);
        return;
    }
}

void measure_dis_cs_state_changed_cb(uint8_t slem_status, errcode_t status)
{
    if (status != ERRCODE_SUCC) {
        osal_printk("[ERROR] CS state change failed, state:%u status:0x%x\r\n", slem_status, status);
        return;
    }
}

/* SDK 本地 IQ 回调入口：复制报告并投递队列，避免阻塞协议栈回调。 */
void measure_dis_cs_iq_report_cb(uint16_t conn_id, sle_channel_sounding_iq_report_t *report)
{
    errcode_t ret = ERRCODE_FAIL;
    sle_channel_sounding_iq_report_t *report_local = NULL;
    uint32_t len = sizeof(sle_channel_sounding_iq_report_t);

    report_local = (sle_channel_sounding_iq_report_t *)osal_kmalloc(len, 0);
    if (report_local == NULL) {
        return;
    }
    if (memcpy_s(report_local, sizeof(sle_channel_sounding_iq_report_t), report, len) != EOK) {
        osal_kfree(report_local);
        return;
    }
    measure_dis_msg_node_t msg_node = {conn_id, SLEM_MSG_LOCAL_IQ, 0, report_local};
    ret = sle_measure_dis_msg_add(&msg_node);
    if (ret != ERRCODE_SUCC) {
        osal_kfree(report_local);
    }
}

/* 初始化算法状态并注册 Channel Sounding 能力、状态和 IQ 回调。 */
errcode_t measure_dis_reg_callbacks(void)
{
    sle_hadm_callbacks_t scd_cbks = {0};

    for (int i = 0; i < MEASURE_DIS_MAX_CLIENTS; i++) {
        measure_dis_alg_reset_slot(&g_measure_dis_alg_slots[i]);
    }
    slem_init_smooth();

    scd_cbks.read_local_cs_caps_cb = measure_dis_read_local_cs_caps_cb;
    scd_cbks.read_remote_cs_caps_cb = measure_dis_read_remote_cs_caps_cb;
    scd_cbks.cs_state_changed_cb = measure_dis_cs_state_changed_cb;
    scd_cbks.cs_iq_report_cb = measure_dis_cs_iq_report_cb;

    errcode_t ret = sle_hadm_register_callbacks(&scd_cbks);
    if (ret != ERRCODE_SUCC) {
        osal_printk("[ERROR] register CS callbacks failed, ret:0x%x\r\n", ret);
    }
    return ret;
}

errcode_t measure_dis_recv_local_iq(measure_dis_msg_node_t *msg_node)
{
    errcode_t ret = measure_dis_proc_local_iq(msg_node->conn_id, (sle_channel_sounding_iq_report_t *)(msg_node->data));
    osal_kfree(msg_node->data);
    osal_event_write(&measure_dis_evt, MEASURE_DIS_MSG_EVENT);
    return ret;
}

errcode_t measure_dis_recv_remote_iq(measure_dis_msg_node_t *msg_node)
{
    errcode_t ret = measure_dis_proc_remote_iq(msg_node->conn_id, (sle_channel_sounding_iq_trans_t *)(msg_node->data));
    osal_kfree(msg_node->data);
    osal_event_write(&measure_dis_evt, MEASURE_DIS_MSG_EVENT);
    return ret;
}

/* 根据队列消息类型选择本地 IQ 或远端 IQ 处理路径。 */
errcode_t measure_dis_match_msg(measure_dis_msg_node_t *msg_node)
{
    errcode_t ret = ERRCODE_FAIL;

    switch (msg_node->type) {
        case SLEM_MSG_LOCAL_IQ:
            ret = measure_dis_recv_local_iq(msg_node);
            break;
        case SLEM_MSG_REMOTE_IQ:
            ret = measure_dis_recv_remote_iq(msg_node);
            break;
        default:
            break;
    }
    return ret;
}

/* 校验 Client 上传的完整 IQ 长度并复制到队列，随后由 Anchor 任务处理。 */
errcode_t measure_dis_remote_iq(uint16_t conn_id, uint16_t len, uint8_t *value)
{
    errcode_t ret = ERRCODE_FAIL;
    sle_channel_sounding_iq_trans_t *report = NULL;

    report = (sle_channel_sounding_iq_trans_t *)osal_kmalloc(sizeof(sle_channel_sounding_iq_trans_t), 0);
    if (report == NULL) {
        return ERRCODE_MALLOC;
    }
    if (memcpy_s(report, sizeof(sle_channel_sounding_iq_trans_t), value, len) != EOK) {
        osal_kfree(report);
        return ERRCODE_MEMCPY;
    }
    measure_dis_msg_node_t msg_node = {conn_id, SLEM_MSG_REMOTE_IQ, 0, report};
    ret = sle_measure_dis_msg_add(&msg_node);
    if (ret != ERRCODE_SUCC) {
        osal_kfree(report);
    }

    return ret;
}
