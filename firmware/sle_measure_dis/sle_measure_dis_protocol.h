/**
 * Copyright (c) HiSilicon (Shanghai) Technologies Co., Ltd. 2023-2023. All rights reserved.
 *
 * Description: Shared wire protocol for the SLE multi-anchor ranging sample. \n
 */
#ifndef SLE_MEASURE_DIS_PROTOCOL_H
#define SLE_MEASURE_DIS_PROTOCOL_H

#include <stdint.h>

/* Four anchors are used because five-anchor operation is not stable on the tested platform. */
#define MEASURE_DIS_MAX_ANCHORS 4
#define MEASURE_DIS_ANCHOR_ID_MIN 1
#define MEASURE_DIS_ANCHOR_ID_MAX MEASURE_DIS_MAX_ANCHORS

#define MEASURE_DIS_CLIENT_ROLE_RANGING 1
#define MEASURE_DIS_CLIENT_ROLE_COLLECTOR2 2
#define MEASURE_DIS_DEFAULT_RANGING_CLIENT_ADDR_BYTE 3
#define MEASURE_DIS_COLLECTOR_CLIENT_ADDR_BYTE 4
#define MEASURE_DIS_INVALID_CONN_ID 0xFFFF

/* Compatibility names used by the original SDK sample implementation. */
#define MAX_SERVERS MEASURE_DIS_MAX_ANCHORS
#define SLEM_CONNET_INVAILD MEASURE_DIS_INVALID_CONN_ID

typedef enum {
    SLEM_PROFILE_MSG_IQ = 0xFFFFFFEA,
} slem_profile_msg_type_t;

#define SLEM_MSG_DIST_RESULT 0x10
#define SLEM_MSG_FINAL_RESULT 0x11
#define SLEM_MSG_COLLECT_LOCAL_IQ 0x12
#define SLEM_MSG_COLLECT_REMOTE_IQ 0x13
#define SLEM_MSG_SERVER_LOCAL_IQ 0x14
#define SLEM_MSG_COLLECT_DIST_RESULT 0x15

#define SLEM_MSG_DIST_LEN ((uint32_t)sizeof(uint32_t))
#define SLEM_MSG_DIST_RSSI_LEN (SLEM_MSG_DIST_LEN + (uint32_t)sizeof(int8_t))
#define SLEM_MSG_FINAL_RESULT_VER 0x01
#define SLEM_MSG_FINAL_RESULT_HDR_LEN 3
#define SLEM_MSG_FINAL_RESULT_ITEM_LEN 6

/* All multi-byte fields use the BS21E native little-endian representation. */
typedef struct {
    uint32_t type;    /* SLEM_MSG_* 消息类型。 */
    uint32_t len;     /* 紧随消息头之后的负载字节数。 */
    uint8_t data[0];  /* 变长负载起始位置。 */
} measure_ids_msg_t;

typedef struct {
    uint8_t anchor_id;     /* 产生该 IQ 的 Anchor 编号。 */
    uint8_t reserved;      /* 历史字段名；当前承载 Ranging Client 地址标识。 */
    uint16_t conn_id;      /* Anchor 与 Ranging Client 的连接句柄。 */
    uint8_t iq_payload[0]; /* 完整 IQ 结构体的起始位置。 */
} measure_dis_collect_iq_hdr_t;

typedef struct {
    uint8_t anchor_id;            /* Anchor 编号。 */
    uint8_t client_id;            /* Ranging Client 地址标识。 */
    int8_t sdk_rssi;              /* 测距算法输出的有符号 RSSI。 */
    uint8_t reserved;             /* 对齐保留字段。 */
    uint16_t conn_id;             /* Anchor 与 Client 的连接句柄。 */
    uint16_t reserved2;           /* 对齐保留字段。 */
    uint32_t dist_mm;             /* 测距结果，单位为毫米。 */
    uint32_t local_timestamp_sn;  /* Anchor 本地 IQ 时间戳。 */
    uint32_t remote_timestamp_sn; /* Client 远端 IQ 时间戳。 */
    uint32_t local_tof_result;    /* Anchor 本地 TOF 结果。 */
    uint32_t remote_tof_result;   /* Client 远端 TOF 结果。 */
    uint8_t local_rssi;           /* Anchor 本地 IQ 报告 RSSI。 */
    uint8_t remote_rssi;          /* Client 远端 IQ 报告 RSSI。 */
    uint16_t reserved3;           /* 对齐保留字段。 */
} measure_dis_collect_dist_result_t;

typedef char measure_dis_frame_header_size_must_be_8[(sizeof(measure_ids_msg_t) == 8) ? 1 : -1];
typedef char measure_dis_iq_header_size_must_be_4[(sizeof(measure_dis_collect_iq_hdr_t) == 4) ? 1 : -1];
typedef char measure_dis_result_size_must_be_32[(sizeof(measure_dis_collect_dist_result_t) == 32) ? 1 : -1];

#endif
