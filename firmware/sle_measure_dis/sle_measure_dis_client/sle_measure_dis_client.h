/**
 * Copyright (c) HiSilicon (Shanghai) Technologies Co., Ltd. 2023-2023. All rights reserved.
 *
 * Description: SLE MEASURE_DIS sample of client. \n
 *
 * History: \n
 * 2023-04-03, Create file. \n
 */
#ifndef SLE_MEASURE_DIS_CLIENT_H
#define SLE_MEASURE_DIS_CLIENT_H

#include <stdint.h>
#include <securec.h>
#include "errcode.h"
#include "std_def.h"
#include "soc_osal.h"
#include "common_def.h"
#include "sle_ssap_client.h"
#include "sle_measure_dis_client_slem.h"
#include "sle_measure_dis_protocol.h"

#if defined(CONFIG_SAMPLE_SUPPORT_SLE_MEASURE_DIS_COLLECTOR_IQ_PRINT)
#define COLLECTOR_IQ_PRINT_ENABLED 1
#else
#define COLLECTOR_IQ_PRINT_ENABLED 0
#endif

/* Multi-anchor indoor profile: high scan coverage and low blocking delays. */
#define MEASURE_DIS_SCAN_FILTER_DUPLICATES 0
#define MEASURE_DIS_SCAN_FILTER_POLICY 0
#define MEASURE_DIS_SCAN_INTERVAL 0x0640
#define MEASURE_DIS_SCAN_WINDOW 0x0500
#define MEASURE_DIS_POST_CONNECT_DISCOVER_DELAY_MS 50
#define MEASURE_DIS_PRE_CS_PARAM_DELAY_MS 20
#define MEASURE_DIS_PRE_CS_ENABLE_DELAY_MS 20
#define MEASURE_DIS_DISCOVER_RETRY_MAX 2
#define MEASURE_DIS_DISCOVER_RETRY_DELAY_MS 80
#define MEASURE_DIS_CONNECTING_MAX MEASURE_DIS_MAX_ANCHORS
#define MEASURE_DIS_RECONNECT_COOLDOWN_MS 800
#define MEASURE_DIS_CONNECT_ATTEMPT_TIMEOUT_MS 3000
#define MEASURE_DIS_SCAN_RETRY_INTERVAL_MS 500
#define MEASURE_DIS_CLIENT_TASK_INTERVAL_MS 10

#if defined(CONFIG_SAMPLE_SUPPORT_SLE_MEASURE_DIS_CLIENT_ROLE_COLLECTOR2)
#define MEASURE_DIS_CLIENT_ROLE MEASURE_DIS_CLIENT_ROLE_COLLECTOR2
#elif defined(CONFIG_SAMPLE_SUPPORT_SLE_MEASURE_DIS_CLIENT_ROLE_RANGING)
#define MEASURE_DIS_CLIENT_ROLE MEASURE_DIS_CLIENT_ROLE_RANGING
#endif

#ifndef MEASURE_DIS_CLIENT_ROLE
#define MEASURE_DIS_CLIENT_ROLE MEASURE_DIS_CLIENT_ROLE_RANGING
#endif

#if defined(CONFIG_SAMPLE_SUPPORT_SLE_MEASURE_DIS_RANGING_CLIENT_ADDR_BYTE)
#define MEASURE_DIS_RANGING_CLIENT_ADDR_BYTE CONFIG_SAMPLE_SUPPORT_SLE_MEASURE_DIS_RANGING_CLIENT_ADDR_BYTE
#else
#define MEASURE_DIS_RANGING_CLIENT_ADDR_BYTE MEASURE_DIS_DEFAULT_RANGING_CLIENT_ADDR_BYTE
#endif

#if (MEASURE_DIS_RANGING_CLIENT_ADDR_BYTE == MEASURE_DIS_COLLECTOR_CLIENT_ADDR_BYTE)
#error "Ranging Client address byte 4 is reserved for the Collector"
#endif

typedef struct {
    uint8_t anchor_id;                    /* IQ 所属 Anchor 编号。 */
    uint8_t reserved;                     /* 历史字段名；当前承载 Ranging Client 地址标识。 */
    uint16_t conn_id;                     /* Anchor 与 Ranging Client 的连接句柄。 */
    sle_channel_sounding_iq_trans_t iq;   /* Anchor 转发给 Collector 的完整 IQ。 */
} measure_dis_collect_iq_msg_t;

typedef struct server_data {
    uint8_t property_uuid[SLE_UUID_LEN]; /* 测距数据属性 UUID。 */
    uint8_t server_uuid[SLE_UUID_LEN];   /* Anchor 应用 UUID。 */
    uint8_t service_uuid[SLE_UUID_LEN];  /* 测距服务 UUID。 */
    uint16_t begin_hdl;                  /* 远端服务起始句柄。 */
    uint16_t end_hdl;                    /* 远端服务结束句柄。 */
    uint16_t property_handle;            /* 当前发现的测距属性句柄。 */
} measure_dis_server_data_t;

#define check_rc_return_rc(rc, err)                                                             \
    do {                                                                                         \
        if ((rc) != ERRCODE_SUCC) {                                                              \
            osal_printk("MEASURE_DIS ERROR: %s fail!: call %s return 0x%x!\n", err, __FUNCTION__, rc); \
        }                                                                                        \
    } while (0)

int measure_dis_client_write_server(uint16_t conn_id, uint32_t type, uint8_t *data, uint32_t data_len);
uint8_t measure_dis_client_can_send(uint16_t conn_id);
int measure_dis_client_init(void);
void measure_dis_client_periodic(void);
int measure_dis_start_scan(void);

#endif
