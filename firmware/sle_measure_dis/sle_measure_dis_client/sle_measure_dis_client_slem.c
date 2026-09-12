/*
 * Copyright (c) HiSilicon (Shanghai) Technologies Co., Ltd. 2023-2023. All rights reserved.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
#include "sle_measure_dis_client.h"
#include "sle_errcode.h"
#include "sle_common.h"
#include "sle_ssap_client.h"
#include "sle_hadm_manager.h"
#include "cmsis_os2.h"
#include "sle_measure_dis_client_slem.h"

typedef struct {
    uint16_t conn_id;                       /* IQ 所属 Anchor 连接。 */
    uint8_t next_idx;                       /* 下一片期望的 report_idx。 */
    measure_dis_stored_iq_data_t iq_data;   /* 正在拼接的完整本地 IQ。 */
} measure_dis_local_iq_slot_t;

/* 每条 Anchor 连接独立使用一个 IQ 拼接槽，防止多链路数据混合。 */
static measure_dis_local_iq_slot_t g_local_iq_slots[MAX_SERVERS] = {0};
/* 链路尚未准备完成时丢弃 IQ 的累计次数，用于限频告警。 */
static uint32_t g_iq_drop_not_ready_cnt = 0;

/* 按连接查找本地 IQ 缓存；需要时为新的 Anchor 连接分配空闲槽。 */
static int measure_dis_find_local_iq_slot(uint16_t conn_id, uint8_t alloc_if_missing)
{
    int free_slot = -1;
    for (int i = 0; i < MAX_SERVERS; i++) {
        if (g_local_iq_slots[i].conn_id == conn_id) {
            return i;
        }
        if (free_slot < 0 && g_local_iq_slots[i].conn_id == SLEM_CONNET_INVAILD) {
            free_slot = i;
        }
    }
    if (!alloc_if_missing || free_slot < 0) {
        return -1;
    }
    g_local_iq_slots[free_slot].conn_id = conn_id;
    g_local_iq_slots[free_slot].next_idx = 0;
    (void)memset_s(&g_local_iq_slots[free_slot].iq_data,
                   sizeof(g_local_iq_slots[free_slot].iq_data),
                   0,
                   sizeof(g_local_iq_slots[free_slot].iq_data));
    return free_slot;
}

/* 连接断开时释放对应 IQ 缓存，避免重连后继续使用上一条链路的分片。 */
void measure_dis_clear_local_iq_slot(uint16_t conn_id)
{
    int slot = measure_dis_find_local_iq_slot(conn_id, 0);
    if (slot < 0) {
        return;
    }
    g_local_iq_slots[slot].conn_id = SLEM_CONNET_INVAILD;
    g_local_iq_slots[slot].next_idx = 0;
    (void)memset_s(&g_local_iq_slots[slot].iq_data,
                   sizeof(g_local_iq_slots[slot].iq_data),
                   0,
                   sizeof(g_local_iq_slots[slot].iq_data));
}

/*
 * SDK 会把一次 Channel Sounding 的 IQ 拆成多个 report_idx 回调。
 * 这里按 conn_id 隔离缓存，并校验 report_idx 连续性和 timestamp_sn 一致性，
 * 收齐最后一片后才向 Anchor 上传完整 IQ。
 */
/* 按 report_idx 顺序拼接 SDK 分片，并校验同一次采样的时间戳和分片连续性。 */
errcode_t measure_dis_store_local_iq(uint16_t conn_id, sle_channel_sounding_iq_report_t *report)
{
    int slot = measure_dis_find_local_iq_slot(conn_id, 1);
    if (slot < 0) {
        osal_printk("[ERROR] no local IQ slot, conn:%u\r\n", conn_id);
        return ERRCODE_FAIL;
    }
    measure_dis_stored_iq_data_t *local_iq = &g_local_iq_slots[slot].iq_data;

    if (report->report_idx == 0) {
        local_iq->samp_cnt = 0;
        local_iq->rssi = report->rssi[0];
        local_iq->es_sn = report->es_sn;
        local_iq->timestamp_sn = report->timestamp_sn;
#if (defined(GLE_CS_MODE3_SUPPORT))
        local_iq->tof_result = report->tof_result;
#endif
        g_local_iq_slots[slot].next_idx = 0;
    }
    if ((report->report_idx >= MEASURE_DIS_IQ_REPORT_CNT_MAX || report->timestamp_sn != local_iq->timestamp_sn) ||
        (g_local_iq_slots[slot].next_idx != report->report_idx)) {
        osal_printk("[ERROR] store local IQ failed, conn:%u report:%u timestamp:%u expected:%u\r\n",
                    conn_id, report->report_idx, report->timestamp_sn, g_local_iq_slots[slot].next_idx);
        return ERRCODE_INVALID_PARAM;
    }
    local_iq->samp_cnt += report->samp_cnt;
    uint8_t offset = report->report_idx * SLE_CS_IQ_REPORT_COUNT;
    for (uint8_t i = 0; i < report->samp_cnt; i++) {
        local_iq->data[offset + i].i_data = report->i_data[i];
        local_iq->data[offset + i].q_data = report->q_data[i];
    }
    g_local_iq_slots[slot].next_idx = report->report_idx + 1;

    return ERRCODE_SUCC;
}

/* 收齐本地 IQ 后将完整数据上传给 Anchor；Client 本身不向串口打印 IQ。 */
errcode_t measure_dis_recv_local_iq(uint16_t conn_id, sle_channel_sounding_iq_report_t *report)
{
    errcode_t ret = ERRCODE_SUCC;

    ret = measure_dis_store_local_iq(conn_id, report);
    if (ret != ERRCODE_SUCC) {
        return ERRCODE_INVALID_PARAM;
    }

    if (report->report_idx + 1 == MEASURE_DIS_IQ_REPORT_CNT_MAX) {
        if (!measure_dis_client_can_send(conn_id)) {
            g_iq_drop_not_ready_cnt++;
            if ((g_iq_drop_not_ready_cnt & 0x3FU) == 1U) {
                osal_printk("[WARN] local IQ dropped before link ready, conn:%u total:%u\r\n",
                            conn_id, g_iq_drop_not_ready_cnt);
            }
            return ERRCODE_SUCC;
        }
        int slot = measure_dis_find_local_iq_slot(conn_id, 0);
        if (slot < 0) {
            return ERRCODE_SUCC;
        }
        measure_dis_client_write_server(conn_id, SLEM_PROFILE_MSG_IQ,
                                        (uint8_t *)&g_local_iq_slots[slot].iq_data,
                                        sizeof(sle_channel_sounding_iq_trans_t));
    }
    return ret;
}

void measure_dis_read_local_cs_caps_cb(sle_channel_sounding_caps_t *caps, errcode_t status)
{
    UNUSED(caps);
    if (status != ERRCODE_SUCC) {
        osal_printk("[ERROR] read local CS capabilities failed, status:0x%x\r\n", status);
        return;
    }
}

void measure_dis_read_remote_cs_caps_cb(uint16_t conn_id, sle_channel_sounding_caps_t *caps, errcode_t status)
{
    UNUSED(caps);
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

/* Channel Sounding IQ 回调入口，把 SDK 上报交给本地 IQ 拼接与上传流程。 */
void measure_dis_cs_iq_report_cb(uint16_t conn_id, sle_channel_sounding_iq_report_t *report)
{
    measure_dis_recv_local_iq(conn_id, report);
}

/* 初始化每条连接的 IQ 缓存，并注册 Channel Sounding 相关 SDK 回调。 */
errcode_t measure_dis_reg_callbacks(void)
{
    sle_hadm_callbacks_t scd_cbks = {0};

    for (int i = 0; i < MAX_SERVERS; i++) {
        g_local_iq_slots[i].conn_id = SLEM_CONNET_INVAILD;
        g_local_iq_slots[i].next_idx = 0;
        (void)memset_s(&g_local_iq_slots[i].iq_data,
                       sizeof(g_local_iq_slots[i].iq_data),
                       0,
                       sizeof(g_local_iq_slots[i].iq_data));
    }

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
