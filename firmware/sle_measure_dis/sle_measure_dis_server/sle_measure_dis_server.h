/**
 * Copyright (c) HiSilicon (Shanghai) Technologies Co., Ltd. 2023-2023. All rights reserved.
 *
 * Description: SLE measure_dis server Config. \n
 *
 * History: \n
 * 2023-07-17, Create file. \n
 */

#ifndef SLE_MEASURE_DIS_SERVER_H
#define SLE_MEASURE_DIS_SERVER_H

#include <stdint.h>
#include <securec.h>
#include "errcode.h"
#include "std_def.h"
#include "soc_osal.h"
#include "common_def.h"
#include "sle_ssap_server.h"
#include "sle_measure_dis_protocol.h"

#ifdef __cplusplus
#if __cplusplus
extern "C" {
#endif /* __cplusplus */
#endif /* __cplusplus */

#define MEASURE_DIS_MSG_EVENT 1
#define MEASURE_DIS_MSG_QUEUE_SIZE 64
#define MEASURE_DIS_MAX_CLIENTS 6
#define MEASURE_DIS_RX_STREAM_BUF_SIZE 1024
#define MEASURE_DIS_COLLECTOR_SEND_RETRY_MAX 2
#define MEASURE_DIS_COLLECTOR_SEND_RETRY_DELAY_MS 5
#define MEASURE_DIS_COLLECTOR_SEND_FAIL_LOG_INTERVAL 64
#ifndef MEASURE_DIS_ANCHOR_ID
#define MEASURE_DIS_ANCHOR_ID 4
#endif

extern osal_event measure_dis_evt;

typedef enum {
    MEASURE_DIS_CONN_ROLE_UNKNOWN = 0,
    MEASURE_DIS_CONN_ROLE_RANGING = 1,
    MEASURE_DIS_CONN_ROLE_COLLECTOR2 = 2,
} measure_dis_conn_role_t;

typedef enum {
    SLEM_MSG_LOCAL_IQ,
    SLEM_MSG_REMOTE_IQ,
} slem_msg_node_type_t;

typedef struct server_data {
    uint8_t property_uuid[SLE_UUID_LEN]; /* 测距数据属性 UUID。 */
    uint8_t server_uuid[SLE_UUID_LEN];   /* Anchor 应用 UUID。 */
    uint8_t service_uuid[SLE_UUID_LEN];  /* 测距服务 UUID。 */
    uint16_t begin_hdl;                  /* 服务句柄范围起点。 */
    uint16_t end_hdl;                    /* 服务句柄范围终点。 */
    uint16_t property_handle;            /* 测距数据属性句柄。 */
} measure_dis_server_data_t;

typedef struct {
    uint16_t            conn_id;                          /*!< 连接句柄 */
    uint16_t            type;                             /*!< 消息类型 */
    uint16_t            result;                           /*!< 执行结果 */
    void                *data;
} measure_dis_msg_node_t;

#define check_rc_return_rc(rc, err)                                                             \
    do {                                                                                         \
        if ((rc) != ERRCODE_SUCC) {                                                              \
            osal_printk("MEASURE_DIS ERROR: %s fail!: call %s return 0x%x!\n", err, __FUNCTION__, rc); \
        }                                                                                        \
    } while (0)

int measure_dis_server_write_conn(uint16_t conn_id, uint32_t type, uint8_t *data, uint32_t data_len);
int measure_dis_server_write_collectors(uint32_t type, uint8_t *data, uint32_t data_len);
int measure_dis_server_init(void);
errcode_t sle_measure_dis_msg_add(measure_dis_msg_node_t *msg);
void sle_measure_dis_msg_proc(void);
int sle_measure_recv_dis(uint8_t *value, uint16_t len);
measure_dis_conn_role_t measure_dis_get_conn_role(uint16_t conn_id);
uint8_t measure_dis_get_conn_client_id(uint16_t conn_id);
errcode_t measure_dis_alg_reset_conn(uint16_t conn_id);

#ifdef __cplusplus
#if __cplusplus
}
#endif /* __cplusplus */
#endif /* __cplusplus */

#endif
