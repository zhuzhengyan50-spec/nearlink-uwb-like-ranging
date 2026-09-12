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
#include "sle_device_manager.h"
#include "sle_connection_manager.h"
#include "sle_device_discovery.h"
#include "sle_ssap_client.h"
#include "sle_hadm_manager.h"
#include "sle_measure_dis_client_slem.h"
#include "tcxo.h"

#define BLE_SLE_TAG_TASK_DURATION_MS 10 /*表示SLE任务（如扫描、连接等）的持续时间,以毫秒为单位;*/
#define ADV_TO_SERVER 2
/* UUID只支持2字节和16字节 */
#define SLEM_UUID_LEN SLE_UUID_LEN
#define SLEM_IQ_DATALEN 512
#define ANCHOR_ID_MIN 1
#define ANCHOR_ID_MAX MAX_SERVERS
#define MEASURE_DIS_PARTIAL_RESULT_TIMEOUT_MS 180
#define MEASURE_DIS_FAST_VALID_MIN 3
#define MEASURE_DIS_COLLECT_MAX_CLIENTS 2
#define MEASURE_DIS_COLLECT_MAX_SAMPLES (MEASURE_DIS_COLLECT_MAX_CLIENTS * MAX_SERVERS)
#define MEASURE_DIS_IQ_SEND_RETRY_MAX 2
#define MEASURE_DIS_COLLECT_SAMPLE_STALE_MS 1000
#define MEASURE_DIS_IQ_FLIP_BARRIER 0x03ff
#define MEASURE_DIS_IQ_FLIP_OFFSET 0x0800
#define MEASURE_DIS_COLLECT_HEX_BYTES_PER_LINE 24U
#define MEASURE_DIS_CS_STAGE_IDLE 0
#define MEASURE_DIS_CS_STAGE_WAIT_PARAM 1
#define MEASURE_DIS_CS_STAGE_WAIT_ENABLE 2
#define MEASURE_DIS_CS_START_RETRY_MAX 2
#define MEASURE_DIS_CS_START_RETRY_DELAY_MS 80

/* SLE 协议栈已使能标志，初始化流程等待回调把它置为 1。 */
static uint8_t g_stack_enable_status = 0;

/* Ranging Client 当前一轮中，每个 Anchor 最近一次返回的距离和 RSSI。 */
static uint32_t g_distance_results[MAX_SERVERS] = {0};
static int8_t g_rssi_results[MAX_SERVERS] = {0};
/* 已收到结果与本轮期望结果的 Anchor 位图，第 n 位对应第 n+1 个 Anchor。 */
static uint8_t g_result_received_mask = 0;
static uint8_t g_round_expected_mask = 0;
/* 当前测距轮次第一帧和最近一帧的到达时间，用于判断残缺轮次超时。 */
static uint32_t g_round_first_result_time = 0;
static uint32_t g_round_last_result_time = 0;
/* IQ 上传连续失败次数，只用于对发送错误日志进行限频。 */
static uint32_t g_iq_send_fail_cnt = 0;
/* 每个 Anchor 是否正在连接，以及当前同时进行的连接请求数量。 */
static uint8_t g_anchor_connecting[MAX_SERVERS] = {0};
static uint8_t g_connecting_in_progress = 0;
/* 每个 Anchor 的重连冷却截止时间和本次连接尝试截止时间。 */
static uint32_t g_anchor_reconnect_after_ms[MAX_SERVERS] = {0};
static uint32_t g_anchor_connect_deadline_ms[MAX_SERVERS] = {0};
/* 最近一次自动补扫时间，避免周期任务过于频繁地重启扫描。 */
static uint32_t g_last_scan_retry_ms = 0;

/* 一条 Anchor 连接从建立、发现服务到开启 CS 所需的全部状态。 */
typedef struct {
    uint16_t conn_id;              /* SDK 分配的连接句柄。 */
    uint16_t property_handle;      /* Anchor 测距数据属性句柄。 */
    uint8_t mtu_exchanged;         /* MTU 交换是否完成。 */
    uint8_t cs_enabled;            /* Channel Sounding 是否已经使能。 */
    uint8_t notify_enabled;        /* 是否已订阅 Anchor 通知。 */
    uint8_t discover_retry;        /* 当前服务发现重试次数。 */
    uint8_t discover_pending;      /* 是否存在待执行的服务发现。 */
    uint8_t exchange_pending;      /* 服务发现后是否还需要交换 MTU。 */
    uint8_t cs_start_stage;        /* CS 非阻塞启动状态机的当前阶段。 */
    uint8_t cs_start_retry;        /* CS 启动重试次数。 */
    uint8_t first_data_received;   /* 本连接是否已打印过首帧到达提示。 */
    uint32_t setup_due_ms;         /* 延迟执行服务发现的时刻。 */
    uint32_t cs_due_ms;            /* 执行下一步 CS 操作的时刻。 */
} client_conn_state_t;
/* 数组下标与 Anchor ID-1 对应，每个 Anchor 独立维护连接状态。 */
client_conn_state_t g_conn_state[MAX_SERVERS] = {0};

/* Collector 按 client_id 独立维护一轮多锚点距离，避免不同移动端的数据相互覆盖。 */
typedef struct {
    uint8_t used;                              /* 该槽是否已分配。 */
    uint8_t client_id;                         /* Ranging Client 地址标识。 */
    uint8_t expected_mask;                     /* 本轮预期参与的 Anchor 位图。 */
    uint8_t result_mask;                       /* 本轮已经返回距离的 Anchor 位图。 */
    uint32_t distance_results[MAX_SERVERS];    /* 各 Anchor 的距离结果。 */
    int8_t rssi_results[MAX_SERVERS];          /* 各 Anchor 的 RSSI 结果。 */
    uint32_t first_result_time;                /* 本轮第一条距离的到达时间。 */
    uint32_t last_result_time;                 /* 本轮最近一条距离的到达时间。 */
    uint32_t last_complete_time;               /* 上一完整轮次的完成时间。 */
} measure_dis_collect_client_state_t;

/* Collector 最多同时跟踪两个 Ranging Client 的多锚点轮次。 */
static measure_dis_collect_client_state_t g_collect_clients[MEASURE_DIS_COLLECT_MAX_CLIENTS] = {0};

/*
 * 一份完整样本由距离、本地 IQ 和远端 IQ 三部分组成。
 * Collector 以 (client_id, anchor_id) 定位槽位，再用时间戳确认三部分属于同一次测距。
 */
typedef struct {
    uint8_t client_id;                         /* 样本所属 Ranging Client。 */
    uint8_t anchor_id;                         /* 样本所属 Anchor。 */
    uint8_t has_dist;                          /* 距离元数据是否已到达。 */
    uint8_t has_local_iq;                      /* Anchor 本地 IQ 是否已到达。 */
    uint8_t has_remote_iq;                     /* Client 远端 IQ 是否已到达。 */
    uint16_t conn_id;                          /* Anchor 上记录的 Client 连接句柄。 */
    uint16_t reserved;
    uint32_t last_update_ms;                   /* 最近一次更新，用于清理过期样本。 */
    measure_dis_collect_dist_result_t dist;    /* 距离及时间戳、RSSI 元数据。 */
    sle_channel_sounding_iq_trans_t local_iq;  /* Anchor 侧采集的 IQ。 */
    sle_channel_sounding_iq_trans_t remote_iq; /* Ranging Client 侧采集的 IQ。 */
} measure_dis_collect_sample_state_t;

/* 每个 Client-Anchor 组合占用一个槽，保存尚未配齐的完整采集样本。 */
static measure_dis_collect_sample_state_t g_collect_samples[MEASURE_DIS_COLLECT_MAX_SAMPLES] = {0};

/* Channel Sounding 分阶段启动，避免在协议栈回调中阻塞等待。 */
errcode_t measure_dis_slem_set_param(uint16_t conn_id);
errcode_t measure_dis_slem_set_enable(uint16_t conn_id);
static int measure_dis_client_discover_key_for_conn(uint16_t conn_id, uint8_t type);
static void measure_dis_client_try_start_cs(uint16_t conn_id);
static void measure_dis_collect_handle_dist_result(uint16_t conn_id, const uint8_t *payload, uint16_t payload_len);
static void measure_dis_collect_handle_iq_result(uint32_t type, uint16_t conn_id, const uint8_t *payload, uint16_t payload_len);


/* 地址字节就是 client_id；多个 Ranging Client 必须在 Kconfig 中配置不同的值。 */
static uint8_t g_measure_dis_client_addr[SLE_ADDR_LEN] = {
#if (MEASURE_DIS_CLIENT_ROLE == MEASURE_DIS_CLIENT_ROLE_COLLECTOR2)
    MEASURE_DIS_COLLECTOR_CLIENT_ADDR_BYTE, MEASURE_DIS_COLLECTOR_CLIENT_ADDR_BYTE,
    MEASURE_DIS_COLLECTOR_CLIENT_ADDR_BYTE, MEASURE_DIS_COLLECTOR_CLIENT_ADDR_BYTE,
    MEASURE_DIS_COLLECTOR_CLIENT_ADDR_BYTE, MEASURE_DIS_COLLECTOR_CLIENT_ADDR_BYTE
#else
    MEASURE_DIS_RANGING_CLIENT_ADDR_BYTE, MEASURE_DIS_RANGING_CLIENT_ADDR_BYTE,
    MEASURE_DIS_RANGING_CLIENT_ADDR_BYTE, MEASURE_DIS_RANGING_CLIENT_ADDR_BYTE,
    MEASURE_DIS_RANGING_CLIENT_ADDR_BYTE, MEASURE_DIS_RANGING_CLIENT_ADDR_BYTE
#endif
};
/* Anchor ID 到 SDK 连接句柄的映射，下标 0 对应 Anchor 1。 */
uint16_t g_measure_dis_conn_id[MAX_SERVERS] = {SLEM_CONNET_INVAILD};
/* 当前已经建立的 Anchor 连接数量。 */
int g_connected_count = 0;

static int measure_dis_get_index_by_conn_id(uint16_t conn_id)
{
    for (int i = 0; i < MAX_SERVERS; i++) {
        if (g_measure_dis_conn_id[i] == conn_id) {
            return i;
        }
    }
    return -1;
}

static uint8_t measure_dis_need_scan_more(void)
{
    if (g_connected_count < MAX_SERVERS) {
        return 1;
    }
    return 0;
}

static uint8_t measure_dis_get_active_anchor_mask(void)
{
    uint8_t mask = 0;
    for (int i = 0; i < MAX_SERVERS; i++) {
        if (g_measure_dis_conn_id[i] != SLEM_CONNET_INVAILD) {
            mask |= (1U << i);
        }
    }
    return mask;
}

static uint8_t measure_dis_count_mask_bits(uint8_t mask)
{
    uint8_t count = 0;
    while (mask != 0) {
        count += (uint8_t)(mask & 0x01U);
        mask >>= 1;
    }
    return count;
}

static void measure_dis_collect_reset_state(measure_dis_collect_client_state_t *state)
{
    if (state == NULL) {
        return;
    }
    state->used = 0;
    state->client_id = 0;
    state->expected_mask = 0;
    state->result_mask = 0;
    state->first_result_time = 0;
    state->last_result_time = 0;
    state->last_complete_time = 0;
    (void)memset_s(state->distance_results, sizeof(state->distance_results), 0, sizeof(state->distance_results));
    (void)memset_s(state->rssi_results, sizeof(state->rssi_results), 0, sizeof(state->rssi_results));
}

static void measure_dis_collect_reset_sample_state(measure_dis_collect_sample_state_t *state)
{
    if (state == NULL) {
        return;
    }
    (void)memset_s(state, sizeof(*state), 0, sizeof(*state));
}

/* 按固定长度把二进制内容转换成多行十六进制文本，保持 Collector 既有串口格式不变。 */
static void measure_dis_collect_print_hex_blob(const char *tag, const uint8_t *bytes, uint16_t len)
{
    char line_buf[96] = {0};
    uint16_t offset = 0;
    uint16_t seq = 0;
    int ret;

    if (tag == NULL || bytes == NULL) {
        return;
    }
    while (offset < len) {
        uint16_t chunk_len = (uint16_t)(len - offset);
        uint16_t pos = 0;
        if (chunk_len > MEASURE_DIS_COLLECT_HEX_BYTES_PER_LINE) {
            chunk_len = MEASURE_DIS_COLLECT_HEX_BYTES_PER_LINE;
        }
        ret = sprintf_s(line_buf + pos, sizeof(line_buf) - pos, "%s seq=%u hex=", tag, seq);
        if (ret < 0) {
            return;
        }
        pos += (uint16_t)ret;
        for (uint16_t i = 0; i < chunk_len; i++) {
            ret = sprintf_s(line_buf + pos, sizeof(line_buf) - pos, "%02X", bytes[offset + i]);
            if (ret < 0) {
                return;
            }
            pos += (uint16_t)ret;
        }
        ret = sprintf_s(line_buf + pos, sizeof(line_buf) - pos, "\r\n");
        if (ret < 0) {
            return;
        }
        osal_printk("%s", line_buf);
        offset = (uint16_t)(offset + chunk_len);
        seq++;
    }
}

/* 定期丢弃长时间未集齐的数据，防止旧距离与下一次 IQ 被错误配成同一份样本。 */
static void measure_dis_collect_flush_stale_samples(uint32_t now)
{
    for (int i = 0; i < MEASURE_DIS_COLLECT_MAX_SAMPLES; i++) {
        if (g_collect_samples[i].client_id == 0 || g_collect_samples[i].last_update_ms == 0) {
            continue;
        }
        if ((now - g_collect_samples[i].last_update_ms) >= MEASURE_DIS_COLLECT_SAMPLE_STALE_MS) {
            measure_dis_collect_reset_sample_state(&g_collect_samples[i]);
        }
    }
}

/* 根据 client_id 和 anchor_id 找到唯一采集槽，使多 Client、多 Anchor 数据互不覆盖。 */
static int measure_dis_collect_get_pair_slot(int client_slot, uint8_t client_id, uint8_t anchor_id)
{
    int slot;
    if (client_slot < 0 || client_slot >= MEASURE_DIS_COLLECT_MAX_CLIENTS ||
        client_id == 0 || anchor_id < ANCHOR_ID_MIN || anchor_id > ANCHOR_ID_MAX) {
        return -1;
    }
    slot = client_slot * MAX_SERVERS + (anchor_id - ANCHOR_ID_MIN);
    if (slot < 0 || slot >= MEASURE_DIS_COLLECT_MAX_SAMPLES) {
        return -1;
    }
    if (g_collect_samples[slot].client_id != client_id || g_collect_samples[slot].anchor_id != anchor_id) {
        measure_dis_collect_reset_sample_state(&g_collect_samples[slot]);
        g_collect_samples[slot].client_id = client_id;
        g_collect_samples[slot].anchor_id = anchor_id;
    }
    return slot;
}

/* 判断距离、本地 IQ 和远端 IQ 的时间戳是否属于同一次 Channel Sounding。 */
static uint8_t measure_dis_collect_timestamp_match(uint32_t lhs, uint32_t rhs)
{
    int32_t diff;

    if (lhs == 0 || rhs == 0) {
        return 1;
    }
    diff = (int32_t)(lhs - rhs);
    if (diff < 0) {
        diff = -diff;
    }
    return (diff < 20) ? 1U : 0U;
}

/* 三部分数据集齐后输出一份完整样本；IQ 开关只影响两类 IQ 文本，不影响内部收集。 */
static void measure_dis_collect_finalize_sample(int sample_slot)
{
    measure_dis_collect_sample_state_t *state = NULL;

    if (sample_slot < 0 || sample_slot >= MEASURE_DIS_COLLECT_MAX_SAMPLES) {
        return;
    }
    state = &g_collect_samples[sample_slot];
    if (state->client_id == 0 || !state->has_dist || !state->has_local_iq || !state->has_remote_iq) {
        return;
    }
    osal_printk("COLLECT_SAMPLE_META anchor=%u client=%u conn_id=%u sdk_dist_mm=%u sdk_rssi=%d "
                "local_timestamp=%u remote_timestamp=%u local_rssi=%u remote_rssi=%u\r\n",
                state->anchor_id, state->client_id, state->dist.conn_id, state->dist.dist_mm, state->dist.sdk_rssi,
                state->dist.local_timestamp_sn, state->dist.remote_timestamp_sn,
                state->dist.local_rssi, state->dist.remote_rssi);
    measure_dis_collect_print_hex_blob("COLLECT_DIST", (const uint8_t *)&state->dist, sizeof(state->dist));
#if defined(CONFIG_SAMPLE_SUPPORT_SLE_MEASURE_DIS_COLLECTOR_IQ_PRINT)
    measure_dis_collect_print_hex_blob("COLLECT_LOCAL_IQ", (const uint8_t *)&state->local_iq, sizeof(state->local_iq));
    measure_dis_collect_print_hex_blob("COLLECT_REMOTE_IQ", (const uint8_t *)&state->remote_iq,
                                       sizeof(state->remote_iq));
#endif
    measure_dis_collect_reset_sample_state(state);
}

/* 检查指定采集槽是否已经满足“距离 + 本地 IQ + 远端 IQ”及时间戳匹配条件。 */
static void measure_dis_collect_try_finalize_pair(int sample_slot)
{
    measure_dis_collect_sample_state_t *state = NULL;
    if (sample_slot < 0 || sample_slot >= MEASURE_DIS_COLLECT_MAX_SAMPLES) {
        return;
    }
    state = &g_collect_samples[sample_slot];
    if (state->client_id == 0 || !state->has_dist || !state->has_local_iq || !state->has_remote_iq) {
        return;
    }
    if (!measure_dis_collect_timestamp_match(state->dist.local_timestamp_sn, state->local_iq.timestamp_sn)) {
        return;
    }
    if (!measure_dis_collect_timestamp_match(state->dist.remote_timestamp_sn, state->remote_iq.timestamp_sn)) {
        return;
    }
    measure_dis_collect_finalize_sample(sample_slot);
}

/* 为一个 Ranging Client 查找或分配独立状态槽，支持同时收集多个移动端。 */
static int measure_dis_collect_find_client_slot(uint8_t client_id)
{
    int free_slot = -1;

    if (client_id == 0) {
        return -1;
    }
    for (int i = 0; i < MEASURE_DIS_COLLECT_MAX_CLIENTS; i++) {
        if (g_collect_clients[i].used && g_collect_clients[i].client_id == client_id) {
            return i;
        }
        if (free_slot < 0 && !g_collect_clients[i].used) {
            free_slot = i;
        }
    }
    if (free_slot < 0) {
        return -1;
    }
    measure_dis_collect_reset_state(&g_collect_clients[free_slot]);
    g_collect_clients[free_slot].used = 1;
    g_collect_clients[free_slot].client_id = client_id;
    return free_slot;
}

/* 结束一个 Client 的本轮多锚点距离统计，并清空轮次掩码等待下一轮。 */
static void measure_dis_collect_finalize_client(int client_slot, uint32_t now)
{
    uint32_t round_time = 0;
    measure_dis_collect_client_state_t *state = NULL;

    if (client_slot < 0 || client_slot >= MEASURE_DIS_COLLECT_MAX_CLIENTS) {
        return;
    }
    state = &g_collect_clients[client_slot];
    if (!state->used) {
        return;
    }
    if (state->last_complete_time != 0) {
        round_time = now - state->last_complete_time;
    }
    state->last_complete_time = now;
    unused(round_time);
    state->result_mask = 0;
    state->expected_mask = 0;
    state->first_result_time = 0;
    state->last_result_time = 0;
}

/* 本轮长期未集齐全部 Anchor 时结束残缺轮次，避免状态一直占用。 */
static void measure_dis_collect_try_flush_partial(int client_slot, uint32_t now)
{
    measure_dis_collect_client_state_t *state = NULL;
    uint8_t received_count;

    if (client_slot < 0 || client_slot >= MEASURE_DIS_COLLECT_MAX_CLIENTS) {
        return;
    }
    state = &g_collect_clients[client_slot];
    if (!state->used || state->expected_mask == 0 || state->result_mask == 0 || state->last_result_time == 0) {
        return;
    }
    if ((state->result_mask & state->expected_mask) == state->expected_mask) {
        return;
    }
    if ((now - state->last_result_time) < MEASURE_DIS_PARTIAL_RESULT_TIMEOUT_MS) {
        return;
    }
    received_count = measure_dis_count_mask_bits((uint8_t)(state->result_mask & state->expected_mask));
    if (received_count > 0) {
        measure_dis_collect_finalize_client(client_slot, now);
    }
}

static void measure_dis_client_finalize_round(uint32_t now)
{
    unused(now);
    g_round_first_result_time = 0;
    g_round_last_result_time = 0;
    g_result_received_mask = 0;
    g_round_expected_mask = 0;
}

static void measure_dis_reset_conn_state_by_index(int index)
{
    if (index < 0 || index >= MAX_SERVERS) {
        return;
    }
    g_conn_state[index].conn_id = SLEM_CONNET_INVAILD;
    g_conn_state[index].property_handle = 0;
    g_conn_state[index].mtu_exchanged = 0;
    g_conn_state[index].cs_enabled = 0;
    g_conn_state[index].notify_enabled = 0;
    g_conn_state[index].discover_retry = 0;
    g_conn_state[index].discover_pending = 0;
    g_conn_state[index].exchange_pending = 0;
    g_conn_state[index].cs_start_stage = MEASURE_DIS_CS_STAGE_IDLE;
    g_conn_state[index].cs_start_retry = 0;
    g_conn_state[index].first_data_received = 0;
    g_conn_state[index].setup_due_ms = 0;
    g_conn_state[index].cs_due_ms = 0;
}

/* 在属性句柄、MTU 和通知均准备完成后安排启动该连接的 Channel Sounding。 */
static void measure_dis_client_try_start_cs(uint16_t conn_id)
{
    int index;

    if (MEASURE_DIS_CLIENT_ROLE != MEASURE_DIS_CLIENT_ROLE_RANGING) {
        return;
    }

    index = measure_dis_get_index_by_conn_id(conn_id);
    if (index < 0) {
        return;
    }

    if (g_conn_state[index].cs_enabled ||
        g_conn_state[index].cs_start_stage != MEASURE_DIS_CS_STAGE_IDLE) {
        return;
    }

    if (g_conn_state[index].property_handle == 0 ||
        g_conn_state[index].mtu_exchanged == 0 ||
        g_conn_state[index].notify_enabled == 0) {
        return;
    }

    g_conn_state[index].cs_start_retry = 0;
    g_conn_state[index].cs_start_stage = MEASURE_DIS_CS_STAGE_WAIT_PARAM;
    g_conn_state[index].cs_due_ms = (uint32_t)uapi_tcxo_get_ms() + MEASURE_DIS_PRE_CS_PARAM_DELAY_MS;
}

static uint8_t measure_dis_anchor_in_cooldown(uint8_t index, uint32_t now)
{
    uint32_t due;
    if (index >= MAX_SERVERS) {
        return 0;
    }
    due = g_anchor_reconnect_after_ms[index];
    if (due == 0) {
        return 0;
    }
    if ((int32_t)(now - due) >= 0) {
        g_anchor_reconnect_after_ms[index] = 0;
        return 0;
    }
    return 1;
}

static void measure_dis_clear_stale_connecting(uint32_t now)
{
    for (int i = 0; i < MAX_SERVERS; i++) {
        if (!g_anchor_connecting[i]) {
            continue;
        }
        if (g_measure_dis_conn_id[i] != SLEM_CONNET_INVAILD) {
            g_anchor_connecting[i] = 0;
            g_anchor_connect_deadline_ms[i] = 0;
            continue;
        }
        if ((g_anchor_connect_deadline_ms[i] != 0) && ((int32_t)(now - g_anchor_connect_deadline_ms[i]) >= 0)) {
            g_anchor_connecting[i] = 0;
            g_anchor_connect_deadline_ms[i] = 0;
            if (g_connecting_in_progress > 0) {
                g_connecting_in_progress--;
            }
            osal_printk("[WARN] Anchor %d connection timed out\r\n", i + 1);
        }
    }
}

static void measure_dis_client_try_flush_partial_result(uint32_t now)
{
    uint8_t expected_mask = g_round_expected_mask;
    uint8_t received_count;
    if (expected_mask == 0 || g_round_first_result_time == 0 || g_round_last_result_time == 0) {
        return;
    }
    if (g_result_received_mask == 0) {
        return;
    }
    if ((g_result_received_mask & expected_mask) == expected_mask) {
        return;
    }

    received_count = measure_dis_count_mask_bits((uint8_t)(g_result_received_mask & expected_mask));
    if (received_count >= MEASURE_DIS_FAST_VALID_MIN) {
        return;
    }

    if ((now - g_round_last_result_time) < MEASURE_DIS_PARTIAL_RESULT_TIMEOUT_MS) {
        return;
    }

    measure_dis_client_finalize_round(now);
}

/* 解析 Anchor 上报的距离 / RSSI，并把结果放入对应 Client 与 Anchor 的采集状态。 */
static void measure_dis_collect_handle_dist_result(uint16_t conn_id, const uint8_t *payload, uint16_t payload_len)
{
    measure_dis_collect_dist_result_t result = {0};
    int anchor_index;
    int client_slot;
    int sample_slot;
    uint32_t now;
    uint8_t active_mask;
    uint8_t expected_count;
    uint8_t received_count;
    measure_dis_collect_client_state_t *state = NULL;
    measure_dis_collect_sample_state_t *sample_state = NULL;

    if (MEASURE_DIS_CLIENT_ROLE != MEASURE_DIS_CLIENT_ROLE_COLLECTOR2) {
        return;
    }
    if (payload == NULL || payload_len != sizeof(measure_dis_collect_dist_result_t)) {
        return;
    }
    if (memcpy_s(&result, sizeof(result), payload, payload_len) != EOK) {
        return;
    }

    if (result.anchor_id >= ANCHOR_ID_MIN && result.anchor_id <= ANCHOR_ID_MAX) {
        anchor_index = result.anchor_id - 1;
    } else {
        anchor_index = measure_dis_get_index_by_conn_id(conn_id);
    }
    if (anchor_index < 0 || anchor_index >= MAX_SERVERS) {
        return;
    }

    client_slot = measure_dis_collect_find_client_slot(result.client_id);
    if (client_slot < 0) {
        osal_printk("[WARN] Collector has no free slot for client:%u\r\n", result.client_id);
        return;
    }
    state = &g_collect_clients[client_slot];
    now = (uint32_t)uapi_tcxo_get_ms();

    if ((state->expected_mask == 0) && (state->result_mask != 0)) {
        state->result_mask = 0;
        state->first_result_time = 0;
        state->last_result_time = 0;
    }
    if (state->result_mask == 0) {
        active_mask = measure_dis_get_active_anchor_mask();
        if (active_mask == 0) {
            active_mask = (uint8_t)(1U << anchor_index);
        }
        state->expected_mask = active_mask;
        state->first_result_time = now;
        for (int i = 0; i < MAX_SERVERS; i++) {
            if (state->expected_mask & (1U << i)) {
                state->distance_results[i] = 0;
                state->rssi_results[i] = 0;
            }
        }
    }

    state->distance_results[anchor_index] = result.dist_mm;
    state->rssi_results[anchor_index] = result.sdk_rssi;
    state->result_mask |= (uint8_t)(1U << anchor_index);
    state->last_result_time = now;

    sample_slot = measure_dis_collect_get_pair_slot(client_slot, result.client_id, result.anchor_id);
    if (sample_slot >= 0) {
        sample_state = &g_collect_samples[sample_slot];
        sample_state->dist = result;
        sample_state->conn_id = result.conn_id;
        sample_state->has_dist = 1;
        sample_state->last_update_ms = now;
        measure_dis_collect_try_finalize_pair(sample_slot);
    }

    expected_count = measure_dis_count_mask_bits(state->expected_mask);
    received_count = measure_dis_count_mask_bits((uint8_t)(state->result_mask & state->expected_mask));
    if ((state->expected_mask != 0) && (received_count >= expected_count)) {
        measure_dis_collect_finalize_client(client_slot, now);
    } else {
        measure_dis_collect_try_flush_partial(client_slot, now);
    }
    measure_dis_collect_flush_stale_samples(now);
}

/* 接收 Anchor 转发的 IQ，并按 client_id、anchor_id 和时间戳写入对应采集槽。 */
static void measure_dis_collect_handle_iq_result(uint32_t type, uint16_t conn_id, const uint8_t *payload, uint16_t payload_len)
{
    measure_dis_collect_iq_msg_t collect_msg;
    int client_slot;
    int sample_slot;
    uint8_t client_id;
    uint8_t anchor_id;
    uint32_t now;
    measure_dis_collect_sample_state_t *sample_state = NULL;

    if (MEASURE_DIS_CLIENT_ROLE != MEASURE_DIS_CLIENT_ROLE_COLLECTOR2) {
        return;
    }
    if (payload == NULL || payload_len != sizeof(measure_dis_collect_iq_msg_t)) {
        return;
    }
    if (memcpy_s(&collect_msg, sizeof(collect_msg), payload, payload_len) != EOK) {
        return;
    }

    client_id = collect_msg.reserved;
    anchor_id = collect_msg.anchor_id;
    if (anchor_id < ANCHOR_ID_MIN || anchor_id > ANCHOR_ID_MAX) {
        int anchor_index = measure_dis_get_index_by_conn_id(conn_id);
        if (anchor_index >= 0) {
            anchor_id = (uint8_t)(anchor_index + 1);
        }
    }
    if (client_id == 0 || anchor_id < ANCHOR_ID_MIN || anchor_id > ANCHOR_ID_MAX) {
        return;
    }

    client_slot = measure_dis_collect_find_client_slot(client_id);
    if (client_slot < 0) {
        return;
    }

    sample_slot = measure_dis_collect_get_pair_slot(client_slot, client_id, anchor_id);
    if (sample_slot < 0) {
        return;
    }
    sample_state = &g_collect_samples[sample_slot];
    sample_state->conn_id = collect_msg.conn_id;
    sample_state->last_update_ms = (uint32_t)uapi_tcxo_get_ms();
    now = sample_state->last_update_ms;

    if (type == SLEM_MSG_COLLECT_LOCAL_IQ) {
        sample_state->local_iq = collect_msg.iq;
        sample_state->has_local_iq = 1;
    } else if (type == SLEM_MSG_COLLECT_REMOTE_IQ) {
        sample_state->remote_iq = collect_msg.iq;
        sample_state->has_remote_iq = 1;
    } else {
        return;
    }

    measure_dis_collect_try_finalize_pair(sample_slot);
    measure_dis_collect_flush_stale_samples(now);
}

measure_dis_server_data_t g_measure_dis_server_data = {
    .server_uuid = {0x11, 0x22, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
    .service_uuid = {0x11, 0x33, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0},
    .property_uuid = {0x11, 0x44, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0},
};

/* 为指定 Anchor 连接设置多锚点 Channel Sounding 参数。 */
errcode_t measure_dis_slem_set_param(uint16_t conn_id)
{
    if (conn_id == SLEM_CONNET_INVAILD) {
        return ERRCODE_INVALID_PARAM;
    }
    sle_set_channel_sounding_param_ex_t param = {
        .acb_interval = 0,
        /* 实测四锚点稳定；五锚点时第五条链路存在间歇性中断。 */
        .con_anchor_num = MAX_SERVERS,
        .cs_interval = 1,     /* 当前配置下，每条 Client-Anchor 链路实测约 2 Hz。 */
        .freq_space = 0,
        .is_cs_param_chg = 0,
        .refresh_rate = 1,    /* 多 Client 同时测距时降低上报拥塞。 */
    };
    errcode_t ret = sle_set_channel_sounding_param_ex(conn_id, &param);
    if (ret != ERRCODE_SUCC) {
        osal_printk("[ERROR] set CS parameters failed, conn:%u ret:0x%x\r\n", conn_id, ret);
        return ret;
    }
    return ret;
}

/* 请求协议栈在指定 Anchor 连接上正式启动 Channel Sounding。 */
errcode_t measure_dis_slem_set_enable(uint16_t conn_id)
{
    if (conn_id == SLEM_CONNET_INVAILD) {
        return ERRCODE_INVALID_PARAM;
    }
    errcode_t ret = sle_set_channel_sounding_enable(conn_id);
    /* 使能动作可能失败或触发断链，由外层状态机延时重试。 */
    if (ret != ERRCODE_SUCC) {
        osal_printk("[ERROR] enable CS failed, conn:%u ret:0x%x\r\n", conn_id, ret);
    }
    return ret;
}

/* 在指定连接上发现 Anchor 的服务或数据属性，结果由 SSAP 回调异步返回。 */
static int measure_dis_client_discover_key_for_conn(uint16_t conn_id, uint8_t type)
{
    /* 每条 Anchor 连接独立发现属性，不能复用其他连接返回的 handle。 */
    ssapc_find_structure_param_t param = {0};
    param.type = type;
    param.start_hdl = 1;
    param.end_hdl = 0xFFFF;
    param.uuid.len = SLEM_UUID_LEN;
    if (type == SSAP_FIND_TYPE_PRIMARY_SERVICE) {
        memcpy_s(param.uuid.uuid, SLEM_UUID_LEN,
                 g_measure_dis_server_data.service_uuid, SLEM_UUID_LEN);
    } else if (type == SSAP_FIND_TYPE_PROPERTY) {
        memcpy_s(param.uuid.uuid, SLEM_UUID_LEN,
                 g_measure_dis_server_data.property_uuid, SLEM_UUID_LEN);
    }
    return ssapc_find_structure(0, conn_id, &param);
}

static void measure_dis_client_schedule_discovery(int index, uint32_t now, uint32_t delay_ms,
                                                  uint8_t exchange_mtu)
{
    if (index < 0 || index >= MAX_SERVERS) {
        return;
    }
    g_conn_state[index].discover_pending = 1;
    g_conn_state[index].exchange_pending = exchange_mtu;
    g_conn_state[index].setup_due_ms = now + delay_ms;
}

static void measure_dis_client_schedule_cs_retry(int index, uint32_t now, errcode_t ret)
{
    g_conn_state[index].cs_enabled = 0;
    if (g_conn_state[index].cs_start_retry >= MEASURE_DIS_CS_START_RETRY_MAX) {
        g_conn_state[index].cs_start_stage = MEASURE_DIS_CS_STAGE_IDLE;
        g_conn_state[index].cs_due_ms = 0;
        osal_printk("[ERROR] CS start failed after retries, conn:%u ret:0x%x\r\n",
                    g_conn_state[index].conn_id, ret);
        return;
    }
    g_conn_state[index].cs_start_retry++;
    g_conn_state[index].cs_start_stage = MEASURE_DIS_CS_STAGE_WAIT_PARAM;
    g_conn_state[index].cs_due_ms = now + MEASURE_DIS_CS_START_RETRY_DELAY_MS;
}

/* 在周期任务中推进服务发现和 CS 启动状态机，避免在 SDK 回调中阻塞等待。 */
static void measure_dis_client_process_deferred(uint32_t now)
{
    for (int index = 0; index < MAX_SERVERS; index++) {
        client_conn_state_t *state = &g_conn_state[index];
        errcode_t ret;

        if (state->conn_id == SLEM_CONNET_INVAILD) {
            continue;
        }

        if (state->discover_pending && (int32_t)(now - state->setup_due_ms) >= 0) {
            uint8_t exchange_mtu = state->exchange_pending;
            state->discover_pending = 0;
            state->exchange_pending = 0;
            state->setup_due_ms = 0;

            ret = (errcode_t)measure_dis_client_discover_key_for_conn(state->conn_id,
                                                                      SSAP_FIND_TYPE_PROPERTY);
            if (ret != ERRCODE_SUCC && state->discover_retry < MEASURE_DIS_DISCOVER_RETRY_MAX) {
                state->discover_retry++;
                measure_dis_client_schedule_discovery(index, now,
                                                      MEASURE_DIS_DISCOVER_RETRY_DELAY_MS, 0);
            }

            if (exchange_mtu) {
                ssap_exchange_info_t info = { 0 };
                info.mtu_size = SLEM_IQ_DATALEN;
                info.version = 1;
                ret = ssapc_exchange_info_req(0, state->conn_id, &info);
                if (ret != ERRCODE_SUCC) {
                    osal_printk("[ERROR] MTU exchange request failed, conn:%u ret:0x%x\r\n",
                                state->conn_id, ret);
                }
            }
        }

        if (state->cs_start_stage == MEASURE_DIS_CS_STAGE_IDLE ||
            (int32_t)(now - state->cs_due_ms) < 0) {
            continue;
        }

        if (state->cs_start_stage == MEASURE_DIS_CS_STAGE_WAIT_PARAM) {
            ret = measure_dis_slem_set_param(state->conn_id);
            if (ret != ERRCODE_SUCC) {
                measure_dis_client_schedule_cs_retry(index, now, ret);
                continue;
            }
            state->cs_start_stage = MEASURE_DIS_CS_STAGE_WAIT_ENABLE;
            state->cs_due_ms = now + MEASURE_DIS_PRE_CS_ENABLE_DELAY_MS;
            continue;
        }

        ret = measure_dis_slem_set_enable(state->conn_id);
        if (ret != ERRCODE_SUCC) {
            measure_dis_client_schedule_cs_retry(index, now, ret);
            continue;
        }
        state->cs_enabled = 1;
        state->cs_start_stage = MEASURE_DIS_CS_STAGE_IDLE;
        state->cs_due_ms = 0;
        osal_printk("[CS] anchor=%d ready conn=%u handle=%u\r\n",
                    index + 1, state->conn_id, state->property_handle);
    }
}

/* 维护 Anchor 连接表；连接后启动服务发现，断线后清理状态并重新扫描。 */
static void measure_dis_cm_conn_state_cbk(uint16_t conn_id, const sle_addr_t *addr,
                                          sle_acb_state_t conn_state,
                                          sle_pair_state_t pair_state, sle_disc_reason_t disc_reason)
{
    int index;

    unused(pair_state);
    if (conn_state == SLE_ACB_STATE_CONNECTED) {
        uint8_t anchor_id = addr->addr[SLE_ADDR_LEN - 1];
        if (anchor_id >= ANCHOR_ID_MIN && anchor_id <= ANCHOR_ID_MAX) {
            index = anchor_id - 1;
            g_anchor_connecting[index] = 0;
            g_anchor_connect_deadline_ms[index] = 0;
            if (g_connecting_in_progress > 0) {
                g_connecting_in_progress--;
            }
            g_anchor_reconnect_after_ms[index] = 0;
            if (g_measure_dis_conn_id[index] != conn_id) {
                if (g_measure_dis_conn_id[index] == SLEM_CONNET_INVAILD) {
                    g_connected_count++;
                }
                g_measure_dis_conn_id[index] = conn_id;
            }
            g_conn_state[index].conn_id = conn_id;
            osal_printk("[LINK] anchor=%u connected conn=%u\r\n", anchor_id, conn_id);
        } else {
            osal_printk("[ERROR] invalid Anchor ID:%u, conn:%u\r\n", anchor_id, conn_id);
            return;
        }
        measure_dis_client_schedule_discovery(index,
                                              (uint32_t)uapi_tcxo_get_ms(),
                                              MEASURE_DIS_POST_CONNECT_DISCOVER_DELAY_MS,
                                              1);
        /* 一个 Client 可并行连接多个 Anchor，未集齐前持续扫描剩余地址。 */
        if (measure_dis_need_scan_more()) {
            measure_dis_start_scan();
        }
    } else if (conn_state == SLE_ACB_STATE_DISCONNECTED) {
        uint8_t disconnected_anchor = 0;
        for (int i = 0; i < MAX_SERVERS; i++)
        {
            if (g_measure_dis_conn_id[i] == conn_id)
            {
                g_measure_dis_conn_id[i] = SLEM_CONNET_INVAILD;
                g_anchor_connecting[i] = 0;
                g_anchor_connect_deadline_ms[i] = 0;
                g_anchor_reconnect_after_ms[i] = (uint32_t)uapi_tcxo_get_ms() + MEASURE_DIS_RECONNECT_COOLDOWN_MS;
                if (g_connected_count > 0) {
                    g_connected_count--;
                }
                g_result_received_mask &= (uint8_t)(~(1U << i));
                g_round_expected_mask &= (uint8_t)(~(1U << i));
                if (g_round_expected_mask == 0) {
                    g_result_received_mask = 0;
                    g_round_first_result_time = 0;
                    g_round_last_result_time = 0;
                }
                measure_dis_clear_local_iq_slot(conn_id);
                measure_dis_reset_conn_state_by_index(i);
                disconnected_anchor = (uint8_t)(i + 1);
                break;
            }
        }
        osal_printk("[LINK] anchor=%u disconnected conn=%u reason=0x%x\r\n",
                    disconnected_anchor, conn_id, disc_reason);

        if (g_connecting_in_progress > MEASURE_DIS_CONNECTING_MAX) {
            g_connecting_in_progress = MEASURE_DIS_CONNECTING_MAX;
        }

        if (measure_dis_need_scan_more()) {
            measure_dis_start_scan();
        }
    }
}

errcode_t measure_dis_cm_register_cbks(void)
{
    sle_connection_callbacks_t cm_cbks = { 0 };
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

/* 过滤扫描结果中的 Anchor 地址，避免重复连接，并逐个建立所需链路。 */
static void measure_dis_dd_seek_result_cbk(sle_seek_result_info_t *seek_result_data)
{
    uint32_t now;
    if (seek_result_data == NULL) {
        return;
    }

    uint8_t anchor_id = seek_result_data->addr.addr[SLE_ADDR_LEN - 1];
    if (anchor_id < ANCHOR_ID_MIN || anchor_id > ANCHOR_ID_MAX) {
        return;
    }
    int index = anchor_id - 1;
    now = (uint32_t)uapi_tcxo_get_ms();
    measure_dis_clear_stale_connecting(now);

    if (!measure_dis_need_scan_more()) {
        sle_stop_seek();
        return;
    }
    if (g_measure_dis_conn_id[index] != SLEM_CONNET_INVAILD) {
        return;
    }
    if (measure_dis_anchor_in_cooldown((uint8_t)index, now)) {
        return;
    }
    if (g_anchor_connecting[index] || g_connecting_in_progress >= MEASURE_DIS_CONNECTING_MAX) {
        return;
    }

    g_anchor_connecting[index] = 1;
    g_connecting_in_progress++;
    g_anchor_connect_deadline_ms[index] = now + MEASURE_DIS_CONNECT_ATTEMPT_TIMEOUT_MS;
    sle_stop_seek();
    errcode_t ret = sle_connect_remote_device(&(seek_result_data->addr));
    if (ret != ERRCODE_SUCC) {
        g_anchor_connecting[index] = 0;
        g_anchor_connect_deadline_ms[index] = 0;
        if (g_connecting_in_progress > 0) {
            g_connecting_in_progress--;
        }
        g_anchor_reconnect_after_ms[index] = now + MEASURE_DIS_RECONNECT_COOLDOWN_MS;
        osal_printk("[ERROR] connect Anchor %u failed, ret:0x%x\r\n", anchor_id, ret);
    } else if (measure_dis_need_scan_more()) {
        (void)measure_dis_start_scan();
    }
}

errcode_t measure_dis_dm_register_cbks(void)
{
    sle_dev_manager_callbacks_t dm_cbks = {
        .sle_power_on_cb = NULL,
        .sle_enable_cb = measure_dis_dd_enable_cbk,
        .sle_disable_cb = measure_dis_dd_disenable_cbk,
    };
    return sle_dev_manager_register_callbacks(&dm_cbks);
}

errcode_t measure_dis_dd_register_cbks(void)
{
    sle_announce_seek_callbacks_t dd_cbks  = {
        .announce_enable_cb = NULL,
        .announce_disable_cb = NULL,
        .announce_terminal_cb = NULL,
        .seek_enable_cb = NULL,
        .seek_disable_cb = NULL,
        .seek_result_cb = measure_dis_dd_seek_result_cbk,
    };
    return sle_announce_seek_register_callbacks(&dd_cbks);
}

/* 保存服务发现得到的句柄范围，供后续属性发现使用。 */
STATIC void measure_dis_ssapc_find_structure_cbk(uint8_t client_id, uint16_t conn_id,
    ssapc_find_service_result_t *service, errcode_t status)
{
    unused(client_id);
    unused(status);
    if (service == NULL) {
        osal_printk("[ERROR] service discovery returned no service, conn:%u\r\n", conn_id);
        return;
    }
    g_measure_dis_server_data.begin_hdl= service->start_hdl;
    g_measure_dis_server_data.end_hdl = service->end_hdl;
}

/* 保存每条连接独立的业务属性句柄，后续通知订阅和数据发送都使用该句柄。 */
STATIC void measure_dis_ssapc_find_property_cbk(uint8_t client_id, uint16_t conn_id,
    ssapc_find_property_result_t *property, errcode_t status)
{
    unused(client_id);
    unused(status);
    if (property == NULL) {
        osal_printk("[ERROR] property discovery returned no property, conn:%u\r\n", conn_id);
        return;
    }
    int index = measure_dis_get_index_by_conn_id(conn_id);
    if (index >= 0) {
        g_conn_state[index].property_handle = property->handle;
        g_conn_state[index].discover_retry = 0;
        measure_dis_client_try_start_cs(conn_id);
    }
}

/* 服务发现完成后订阅 Anchor 通知，并在连接条件齐备时启动 Channel Sounding。 */
STATIC void measure_dis_ssapc_find_structure_complete_cbk(uint8_t client_id, uint16_t conn_id,
    ssapc_find_structure_result_t *structure_result, errcode_t status)
{
    unused(client_id);
    if (structure_result == NULL) {
        return;
    }
    int index = measure_dis_get_index_by_conn_id(conn_id);
    if (index < 0) {
        return;
    }
    if (status != ERRCODE_SUCC || g_conn_state[index].property_handle == 0) {
        if (g_conn_state[index].discover_retry < MEASURE_DIS_DISCOVER_RETRY_MAX) {
            g_conn_state[index].discover_retry++;
            measure_dis_client_schedule_discovery(index,
                                                  (uint32_t)uapi_tcxo_get_ms(),
                                                  MEASURE_DIS_DISCOVER_RETRY_DELAY_MS,
                                                  0);
        } else {
            osal_printk("[ERROR] property discovery failed after retries, conn:%u\r\n", conn_id);
        }
        return;
    }
    /* 向 CCCD 写入 0x0100 后，Anchor 才能主动上报距离和转发数据。 */
    ssapc_write_param_t param = {0};
    uint8_t data[2] = {0x01, 0x00};
    if (g_conn_state[index].notify_enabled) {
        measure_dis_client_try_start_cs(conn_id);
        return;
    }
    param.handle = g_conn_state[index].property_handle + 1;

    param.type = SSAP_PROPERTY_TYPE_VALUE;
    param.data = data;
    param.data_len = 2;
    
    errcode_t ret = ssapc_write_cmd(0, conn_id, &param);
    if (ret != ERRCODE_SUCC) {
        osal_printk("[ERROR] enable notifications failed, conn:%u ret:0x%x\r\n", conn_id, ret);
    } else {
        g_conn_state[index].notify_enabled = 1;
        measure_dis_client_try_start_cs(conn_id);
    }
}

/* 解析 Anchor 下发的业务帧，并分别交给 Ranging Client 或 Collector 数据流程。 */
void measure_dis_client_msg_proc(uint16_t conn_id, uint8_t *data, uint16_t data_len)
{
    if (data == NULL || data_len < sizeof(measure_ids_msg_t)) {
        return;
    }
    measure_ids_msg_t *msg = (measure_ids_msg_t *)data;
    uint32_t payload_max_len = (uint32_t)(data_len - sizeof(measure_ids_msg_t));
    if (msg->len > payload_max_len) {
        osal_printk("[ERROR] invalid message length, conn:%u type:0x%x len:%u max:%u\r\n",
                    conn_id, msg->type, msg->len, payload_max_len);
        return;
    }
    switch (msg->type) {
        case SLEM_PROFILE_MSG_IQ:

            break;
        case SLEM_MSG_COLLECT_DIST_RESULT:
            measure_dis_collect_handle_dist_result(conn_id, msg->data, (uint16_t)msg->len);
            break;
        case SLEM_MSG_DIST_RESULT:
        {
            uint32_t dist_mm;
            int8_t rssi_dbm = 0;
            uint8_t parse_ok = 0;
            if (MEASURE_DIS_CLIENT_ROLE == MEASURE_DIS_CLIENT_ROLE_COLLECTOR2) {
                break;
            }
            if (msg->len == SLEM_MSG_DIST_LEN) {
                parse_ok = (memcpy_s(&dist_mm, sizeof(dist_mm), msg->data, SLEM_MSG_DIST_LEN) == EOK) ? 1 : 0;
            } else if (msg->len == SLEM_MSG_DIST_RSSI_LEN) {
                parse_ok = (memcpy_s(&dist_mm, sizeof(dist_mm), msg->data, SLEM_MSG_DIST_LEN) == EOK) ? 1 : 0;
                if (parse_ok) {
                    parse_ok = (memcpy_s(&rssi_dbm, sizeof(rssi_dbm), msg->data + SLEM_MSG_DIST_LEN,
                                         sizeof(rssi_dbm)) == EOK) ? 1 : 0;
                }
            }
            if (parse_ok) {
                int index = measure_dis_get_index_by_conn_id(conn_id);
                if (index >= 0) {
                    uint32_t now = (uint32_t)uapi_tcxo_get_ms();
                    if (!g_conn_state[index].first_data_received) {
                        g_conn_state[index].first_data_received = 1;
                        osal_printk("[DATA] anchor=%u first frame received conn=%u\r\n",
                                    (uint8_t)(index + 1), conn_id);
                    }
                    if ((g_round_expected_mask == 0) && (g_result_received_mask != 0)) {
                        g_result_received_mask = 0;
                        g_round_first_result_time = 0;
                        g_round_last_result_time = 0;
                    }
                    if (g_result_received_mask == 0) {
                        uint8_t active_mask = measure_dis_get_active_anchor_mask();
                        g_round_expected_mask = active_mask;
                        for (int i = 0; i < MAX_SERVERS; i++) {
                            if (g_round_expected_mask & (1U << i)) {
                                g_distance_results[i] = 0;
                            }
                        }
                        g_round_first_result_time = now;
                        g_round_last_result_time = now;
                    }
                    g_distance_results[index] = dist_mm;
                    g_rssi_results[index] = rssi_dbm;
                    g_result_received_mask |= (1 << index);
                    g_round_last_result_time = now;
                    /* Finalize a complete round, or a partial round with enough valid anchors. */
                    uint8_t expected_count = measure_dis_count_mask_bits(g_round_expected_mask);
                    uint8_t received_count = measure_dis_count_mask_bits((uint8_t)(g_result_received_mask & g_round_expected_mask));
                    if ((g_round_expected_mask != 0) && (received_count >= expected_count)) {
                        measure_dis_client_finalize_round(now);
                    } else if ((expected_count >= MEASURE_DIS_FAST_VALID_MIN) &&
                               (received_count >= MEASURE_DIS_FAST_VALID_MIN)) {
                        measure_dis_client_finalize_round(now);
                    } else {
                        measure_dis_client_try_flush_partial_result(now);
                    }
                } else {
                    osal_printk("[WARN] data received from unknown conn:%u\r\n", conn_id);
                }
            }
            break;
        }
        case SLEM_MSG_SERVER_LOCAL_IQ:
        case SLEM_MSG_COLLECT_LOCAL_IQ:
        case SLEM_MSG_COLLECT_REMOTE_IQ:
            if (MEASURE_DIS_CLIENT_ROLE == MEASURE_DIS_CLIENT_ROLE_COLLECTOR2) {
                measure_dis_collect_handle_iq_result(msg->type, conn_id, msg->data, (uint16_t)msg->len);
            }
            break;
        default:
            osal_printk("[ERROR] unsupported message type:0x%x len:%u\r\n", msg->type, data_len);
            break;
    }
}

/**
 * @brief  数据通知处理函数
 */
STATIC void measure_dis_ssapc_notification_cbk(uint8_t client_id, uint16_t conn_id, ssapc_handle_value_t *data,
    errcode_t status)
{
    unused(client_id);
    unused(status);
    if (data == NULL || data->data == NULL || data->data_len < sizeof(measure_ids_msg_t)) {
        return;
    }
    measure_dis_client_msg_proc(conn_id, data->data, data->data_len);
}

/**
 * @brief  数据指示处理函数
 */
STATIC void measure_dis_ssapc_indication_cb(uint8_t client_id, uint16_t conn_id, ssapc_handle_value_t *data,
    errcode_t status)
{
    unused(client_id);
    unused(conn_id);
    unused(status);
    if (data == NULL) {
        return;
    }
}

/**
 * @brief  MTU信息交换响应处理函数
 */
STATIC void measure_dis_ssapc_exchange_info_cbk(uint8_t client_id, uint16_t conn_id, ssap_exchange_info_t *param,
    errcode_t status)
{
    unused(client_id);
    if (param == NULL) {
        return;
    }
    if (status == ERRCODE_SUCC) {
        int index = measure_dis_get_index_by_conn_id(conn_id);
        if (index >= 0) {
            g_conn_state[index].mtu_exchanged = 1;
            measure_dis_client_try_start_cs(conn_id);
        }
    }
}

/* 注册服务发现、通知、指示和 MTU 交换等 SSAP Client 回调。 */
errcode_t measure_dis_ssapc_register_cbks(void)
{
    ssapc_callbacks_t ssapc_cbks;

    ssapc_cbks.find_structure_cb = measure_dis_ssapc_find_structure_cbk;
    ssapc_cbks.ssapc_find_property_cbk = measure_dis_ssapc_find_property_cbk;
    ssapc_cbks.find_structure_cmp_cb = measure_dis_ssapc_find_structure_complete_cbk;
    ssapc_cbks.read_cfm_cb = NULL;
    ssapc_cbks.read_by_uuid_cmp_cb = NULL;
    ssapc_cbks.write_cfm_cb = NULL;
    ssapc_cbks.exchange_info_cb = measure_dis_ssapc_exchange_info_cbk;
    ssapc_cbks.notification_cb = measure_dis_ssapc_notification_cbk;
    ssapc_cbks.indication_cb = measure_dis_ssapc_indication_cb;
    return ssapc_register_callbacks(&ssapc_cbks);
}

errcode_t measure_dis_set_local_addr(uint8_t *addr)
{
    sle_addr_t sle_addr = {0};
    if (memcpy_s(sle_addr.addr, SLE_ADDR_LEN, addr, SLE_ADDR_LEN) != EOK) {
        return ERRCODE_MEMCPY;
    }
    return sle_set_local_addr(&sle_addr);
}

errcode_t measure_dis_set_local_name(uint8_t *name, uint8_t len)
{
    return sle_set_local_name(name, len);
}

/* 注册设备与连接回调，启动 SLE 协议栈，再设置 Client 本地地址和名称。 */
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

/* 向指定 Anchor 写入已经封装好的 SSAP 数据，并仅对 IQ 消息执行有限重试。 */
static int measure_dis_client_write_proc(uint16_t conn_id, uint8_t type, uint16_t len, uint8_t *data)
{
    errcode_t ret = ERRCODE_FAIL;
    ssapc_write_param_t param = {0};
    int index = measure_dis_get_index_by_conn_id(conn_id);
    uint8_t retry_max = 0;
    measure_ids_msg_t *msg = NULL;
    if (index < 0 || g_conn_state[index].property_handle == 0 || g_conn_state[index].mtu_exchanged == 0) {
        return ERRCODE_FAIL;
    }
    param.handle = g_conn_state[index].property_handle;

    param.type = type;
    param.data_len = len;
    param.data = data;

    if (data != NULL && len >= sizeof(measure_ids_msg_t)) {
        msg = (measure_ids_msg_t *)data;
        if (msg->type == SLEM_PROFILE_MSG_IQ) {
            retry_max = MEASURE_DIS_IQ_SEND_RETRY_MAX;
        }
    }

    for (uint8_t retry = 0; retry <= retry_max; retry++) {
        ret = ssapc_write_cmd(0, conn_id, &param);
        if (ret == ERRCODE_SUCC) {
            break;
        }
    }
    if (ret != ERRCODE_SUCC) {
        g_iq_send_fail_cnt++;
        if ((g_iq_send_fail_cnt & 0x3FU) == 1) {
            osal_printk("[ERROR] client send failed, conn:%u handle:%u ret:0x%x total:%u\r\n",
                        conn_id, param.handle, ret, g_iq_send_fail_cnt);
        }
    }

    return ret;
}

/* 判断指定连接是否已取得属性句柄并完成 MTU 交换，满足 IQ 上传条件。 */
uint8_t measure_dis_client_can_send(uint16_t conn_id)
{
    int index = measure_dis_get_index_by_conn_id(conn_id);
    if (index < 0) {
        return 0;
    }
    if (g_conn_state[index].property_handle == 0 || g_conn_state[index].mtu_exchanged == 0) {
        return 0;
    }
    return 1;
}

/* 在业务数据前添加统一消息头，再交给底层写函数发送给 Anchor。 */
int measure_dis_client_write_server(uint16_t conn_id, uint32_t type, uint8_t *data, uint32_t data_len)
{
    uint32_t ret = ERRCODE_SUCC;
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
    ret = measure_dis_client_write_proc(conn_id, 0, len, (uint8_t *)(slem_msg));
    osal_kfree(slem_msg);

    return ret;
}

/* 配置扫描间隔、扫描窗口和过滤策略，为发现多个 Anchor 做准备。 */
errcode_t measure_dis_set_scan(void)
{
    errcode_t ret;
    sle_seek_param_t param = {0};
    param.own_addr_type = 0;
    param.filter_duplicates = MEASURE_DIS_SCAN_FILTER_DUPLICATES;
    param.seek_filter_policy = MEASURE_DIS_SCAN_FILTER_POLICY;
    param.seek_phys = 1;
    param.seek_type[0] = 1;
    param.seek_interval[0] = MEASURE_DIS_SCAN_INTERVAL;
    param.seek_window[0] = MEASURE_DIS_SCAN_WINDOW;

    if (param.seek_window[0] > param.seek_interval[0]) {
        osal_printk("[ERROR] invalid scan config: window(%u) > interval(%u)\r\n",
                    param.seek_window[0], param.seek_interval[0]);
        return ERRCODE_FAIL;
    }

    ret = sle_set_seek_param(&param);

    return ret;
}

/* 应用扫描参数并启动 SLE 搜索；实际连接在搜索结果回调中发起。 */
int measure_dis_start_scan(void)
{
    errcode_t ret;
    ret = measure_dis_set_scan();
    if (ret != ERRCODE_SLE_SUCCESS) {
        return ret;
    }
    ret = sle_start_seek();
    if (ret != ERRCODE_SLE_SUCCESS) {
        return ret;
    }
    return ERRCODE_SLE_SUCCESS;
}

/* Client 任务的周期入口，推进延迟操作、连接超时、重连和残缺轮次清理。 */
void measure_dis_client_periodic(void)
{
    uint32_t now = (uint32_t)uapi_tcxo_get_ms();

    measure_dis_client_process_deferred(now);

    if (MEASURE_DIS_CLIENT_ROLE != MEASURE_DIS_CLIENT_ROLE_COLLECTOR2) {
        return;
    }

    measure_dis_clear_stale_connecting(now);

    if (!measure_dis_need_scan_more()) {
        return;
    }
    if ((int32_t)(now - g_last_scan_retry_ms) < MEASURE_DIS_SCAN_RETRY_INTERVAL_MS) {
        return;
    }
    g_last_scan_retry_ms = now;
    (void)measure_dis_start_scan();
}

/* 初始化角色地址和所有运行状态，启动协议栈、注册回调并开始扫描 Anchor。 */
int measure_dis_client_init(void)
{
    uint32_t ret = ERRCODE_SLE_SUCCESS;
    uint8_t measure_dis_name[SLE_NAME_MAX_LEN] = {'s', 'l', 'e', 'm', '-', 'c', '\0'};
#if (MEASURE_DIS_CLIENT_ROLE == MEASURE_DIS_CLIENT_ROLE_COLLECTOR2)
    osal_printk("[BOOT] role=COLLECTOR client=%u addr=%02X:%02X:%02X:%02X:%02X:%02X anchors=%u iq_print=%s\r\n",
                g_measure_dis_client_addr[SLE_ADDR_LEN - 1],
                g_measure_dis_client_addr[0], g_measure_dis_client_addr[1], g_measure_dis_client_addr[2],
                g_measure_dis_client_addr[3], g_measure_dis_client_addr[4], g_measure_dis_client_addr[5],
                MAX_SERVERS, COLLECTOR_IQ_PRINT_ENABLED ? "on" : "off");
#else
    osal_printk("[BOOT] role=RANGING client=%u addr=%02X:%02X:%02X:%02X:%02X:%02X anchors=%u\r\n",
                g_measure_dis_client_addr[SLE_ADDR_LEN - 1],
                g_measure_dis_client_addr[0], g_measure_dis_client_addr[1], g_measure_dis_client_addr[2],
                g_measure_dis_client_addr[3], g_measure_dis_client_addr[4], g_measure_dis_client_addr[5],
                MAX_SERVERS);
#endif
    for (int i = 0; i < MAX_SERVERS; i++) {
        g_measure_dis_conn_id[i] = SLEM_CONNET_INVAILD;
        g_anchor_connecting[i] = 0;
        measure_dis_reset_conn_state_by_index(i);
    }
    g_connected_count = 0;
    g_result_received_mask = 0;
    g_round_expected_mask = 0;
    g_round_last_result_time = 0;
    g_connecting_in_progress = 0;
    g_last_scan_retry_ms = 0;
    if (MEASURE_DIS_CLIENT_ROLE == MEASURE_DIS_CLIENT_ROLE_COLLECTOR2) {
        (void)memset_s(g_collect_clients, sizeof(g_collect_clients), 0, sizeof(g_collect_clients));
        (void)memset_s(g_collect_samples, sizeof(g_collect_samples), 0, sizeof(g_collect_samples));
    }
    memset_s(g_anchor_connect_deadline_ms, sizeof(g_anchor_connect_deadline_ms), 0, sizeof(g_anchor_connect_deadline_ms));
    memset_s(g_anchor_reconnect_after_ms, sizeof(g_anchor_reconnect_after_ms), 0, sizeof(g_anchor_reconnect_after_ms));
    measure_dis_protocol_stack_init(g_measure_dis_client_addr, measure_dis_name);
    if (MEASURE_DIS_CLIENT_ROLE == MEASURE_DIS_CLIENT_ROLE_RANGING) {
        measure_dis_reg_callbacks();
    }
    ret = measure_dis_ssapc_register_cbks();
    measure_dis_start_scan();
    if (ret == ERRCODE_SUCC) {
        osal_printk("[READY] scanning for %u Anchors\r\n", MAX_SERVERS);
    }
    return ret;
}
