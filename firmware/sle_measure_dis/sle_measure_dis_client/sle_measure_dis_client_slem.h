/**
 * Copyright (c) HiSilicon (Shanghai) Technologies Co., Ltd. 2023-2023. All rights reserved.
 *
 * Description: SLE MEASURE_DIS sample of client. \n
 *
 * History: \n
 * 2023-04-03, Create file. \n
 */
#ifndef SLE_MEASURE_DIS_CLIENT_SLEM_H
#define SLE_MEASURE_DIS_CLIENT_SLEM_H

#include "sle_hadm_manager.h"

#define MEASURE_DIS_IQ_REPORT_CNT_MAX 1
#define POSALG_DATA_NUM 79
#define IQ_DATA_MAX (MEASURE_DIS_IQ_REPORT_CNT_MAX * SLE_CS_IQ_REPORT_COUNT)

typedef struct {
    uint16_t i_data; /* 一个采样点的 I 分量。 */
    uint16_t q_data; /* 一个采样点的 Q 分量。 */
} measure_dis_stored_qte_trans_t;

typedef struct {
    uint8_t samp_cnt;                              /* 当前完整报告包含的 IQ 点数。 */
    uint8_t rssi;                                  /* SDK 报告的 RSSI 原始字节。 */
    uint16_t es_sn;                                /* SDK 的测量事件序号。 */
    uint32_t timestamp_sn;                         /* 本次 Channel Sounding 时间戳。 */
    measure_dis_stored_qte_trans_t data[IQ_DATA_MAX]; /* 拼接后的 IQ 数据。 */
#if (defined(GLE_CS_MODE3_SUPPORT))
    uint32_t tof_result;                           /* Mode3 的 TOF 测量结果。 */
#endif
} measure_dis_stored_iq_data_t;

typedef struct {
    uint16_t i_data;
    uint16_t q_data;
} sle_channel_sounding_qte_trans_t;

typedef struct {
    uint8_t samp_cnt;                                  /* 有效 IQ 点数。 */
    uint8_t rssi;                                      /* SDK 报告的 RSSI 原始字节。 */
    uint16_t es_sn;                                    /* 测量事件序号。 */
    uint32_t timestamp_sn;                             /* Channel Sounding 时间戳。 */
    sle_channel_sounding_qte_trans_t data[IQ_DATA_MAX]; /* 在线路上传输的 IQ 数据。 */
    uint32_t tof_result;                               /* Mode3 的 TOF 测量结果。 */
} sle_channel_sounding_iq_trans_t;

errcode_t measure_dis_reg_callbacks(void);
void measure_dis_clear_local_iq_slot(uint16_t conn_id);

#endif
