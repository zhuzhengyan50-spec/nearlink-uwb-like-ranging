# 数据协议

## 基本帧

Client 与 Anchor 之间的应用帧由 8 字节头部和负载组成：

| 偏移 | 长度 | 字段 | 说明 |
|---:|---:|---|---|
| 0 | 4 | `type` | `uint32_t` 消息类型，小端序 |
| 4 | 4 | `len` | `uint32_t` 负载长度，小端序 |
| 8 | len | `data` | 消息负载 |

接收端必须先检查完整帧长度，再解析负载。

## 消息类型

| 值 | 名称 | 方向 | 说明 |
|---:|---|---|---|
| `0xFFFFFFEA` | `SLEM_PROFILE_MSG_IQ` | Ranging Client → Anchor | Client 侧 IQ |
| `0x10` | `SLEM_MSG_DIST_RESULT` | Anchor → Ranging Client | 距离，可附带 RSSI |
| `0x11` | `SLEM_MSG_FINAL_RESULT` | Collector → Anchor | 一轮结果文本 |
| `0x12` | `SLEM_MSG_COLLECT_LOCAL_IQ` | Anchor → Collector | Anchor 本地 IQ |
| `0x13` | `SLEM_MSG_COLLECT_REMOTE_IQ` | Anchor → Collector | Ranging Client 远端 IQ |
| `0x14` | `SLEM_MSG_SERVER_LOCAL_IQ` | Anchor → Collector | 保留的 Server IQ 类型 |
| `0x15` | `SLEM_MSG_COLLECT_DIST_RESULT` | Anchor → Collector | 完整距离元数据 |

## 距离结果

`SLEM_MSG_DIST_RESULT` 负载兼容两种长度：

- 4 字节：`uint32_t dist_mm`；
- 5 字节：`uint32_t dist_mm` + `int8_t rssi_dbm`。

距离单位为毫米。

## Collector 距离元数据

`SLEM_MSG_COLLECT_DIST_RESULT` 当前负载固定为 32 字节：

| 偏移 | 长度 | 字段 |
|---:|---:|---|
| 0 | 1 | Anchor ID |
| 1 | 1 | Client ID |
| 2 | 1 | SDK RSSI，`int8_t` |
| 3 | 1 | 保留 |
| 4 | 2 | Connection ID |
| 6 | 2 | 保留 |
| 8 | 4 | 距离，毫米 |
| 12 | 4 | Local timestamp SN |
| 16 | 4 | Remote timestamp SN |
| 20 | 4 | Local TOF result |
| 24 | 4 | Remote TOF result |
| 28 | 1 | Local RSSI 原始字节 |
| 29 | 1 | Remote RSSI 原始字节 |
| 30 | 2 | 保留 |

## IQ 数据

IQ 数据会经过两层编码：设备之间传输的是二进制应用帧，Collector 最终输出的是便于串口采集的十六进制文本。上位机通常只需要解析第二层。

### 设备间二进制编码

Anchor 转发给 Collector 的 IQ 应用帧结构如下：

| 偏移 | 长度 | 字段 |
|---:|---:|---|
| 0 | 1 | Anchor ID |
| 1 | 1 | Client ID（结构体中的历史字段名为 `reserved`） |
| 2 | 2 | Connection ID，小端序 |
| 4 | 332 | `sle_channel_sounding_iq_trans_t` |

以上 336 字节是应用帧的负载，前面还有 8 字节基本帧头。Local IQ 使用消息类型 `0x12`，Remote IQ 使用消息类型 `0x13`。

Ranging Client 向 Anchor 上传 IQ 时不带前述 4 字节身份头，应用帧负载直接是 332 字节的 `sle_channel_sounding_iq_trans_t`。

当前构建中 `MEASURE_DIS_IQ_REPORT_CNT_MAX=1`、`SLE_CS_IQ_REPORT_COUNT=80`，因此 `IQ_DATA_MAX=80`。IQ 结构按以下固定布局传输：

| 偏移 | 长度 | 类型 | 字段 | 说明 |
|---:|---:|---|---|---|
| 0 | 1 | `uint8_t` | `samp_cnt` | 有效 IQ 点数，解析时不得超过 80 |
| 1 | 1 | `uint8_t` | `rssi` | SDK 上报的 RSSI 原始字节 |
| 2 | 2 | `uint16_t` | `es_sn` | 测量事件序号，小端序 |
| 4 | 4 | `uint32_t` | `timestamp_sn` | Channel Sounding 时间戳，小端序 |
| 8 | 320 | 80 × (`uint16_t I` + `uint16_t Q`) | `data` | 每个 IQ 点占 4 字节，I 在前、Q 在后，均为小端序 |
| 328 | 4 | `uint32_t` | `tof_result` | Mode 3 TOF 结果，小端序 |

结构固定保留 80 个 IQ 点的位置，但只有前 `samp_cnt` 对 I/Q 有效。I/Q 在固件结构中声明为 `uint16_t`，建议采集程序先无损保存为 0～65535 的原始值；只有后续算法明确要求有符号输入时，才按 16 位补码转换为 `int16_t`。

### Collector 串口编码

Collector 完成“距离 + Local IQ + Remote IQ”配对后，按以下顺序输出一份样本：

```text
COLLECT_SAMPLE_META ...
COLLECT_DIST seq=0 hex=<最多 24 字节>
COLLECT_DIST seq=1 hex=<剩余字节>
COLLECT_LOCAL_IQ seq=0 hex=<最多 24 字节>
...
COLLECT_REMOTE_IQ seq=0 hex=<最多 24 字节>
...
```

编码规则：

- `hex=` 后使用大写十六进制，每 2 个字符表示 1 个原始字节，没有空格或分隔符；
- 每行最多承载 24 字节，`seq` 表示同一数据块内的行序号，并从 0 开始连续递增；
- `COLLECT_DIST` 固定为 32 字节，因此通常是 2 行；
- 每个 IQ 数据块固定为 332 字节，因此通常是 14 行；
- `COLLECT_LOCAL_IQ` 表示 Anchor 侧 IQ，`COLLECT_REMOTE_IQ` 表示 Ranging Client 侧 IQ；
- `seq` 只用于拼接同一标签的数据行，不是 Channel Sounding 的测量序号；
- IQ 输出开关关闭时，Collector 只输出元数据和 `COLLECT_DIST`。

Collector 已经移除了设备间 IQ 负载的 4 字节身份头。串口输出的 332 字节 IQ 数据从 `samp_cnt` 开始，不应再次跳过 4 字节。样本身份从紧邻其前的 `COLLECT_SAMPLE_META` 或 `COLLECT_DIST` 中取得。

## 上位机解析建议

推荐按“逐行识别、分块拼接、定长校验、字段解包、样本落盘”五步处理：

1. 读到 `COLLECT_SAMPLE_META` 时创建一份新样本，保存 Anchor ID、Client ID、距离及时间戳；
2. 对三个 `COLLECT_*` 标签分别维护缓冲区，遇到 `seq=0` 时清空对应缓冲区；
3. 要求后续 `seq` 连续，把 `hex` 解码后的字节按顺序追加；
4. `COLLECT_DIST` 收到 32 字节、IQ 收到 332 字节后再执行结构解析；
5. 使用 `local_timestamp_sn` 和 `remote_timestamp_sn` 检查 IQ 是否属于同一次测量，然后以 `(client_id, anchor_id, timestamp)` 为主键保存。

Python 中可以使用显式小端格式解析，避免依赖上位机自身的字节序和结构体对齐：

```python
import struct

DIST_FORMAT = "<BBbBHHIIIII BBH".replace(" ", "")
IQ_HEADER_FORMAT = "<BBHI"
IQ_POINT_FORMAT = "<HH"
DIST_SIZE = 32
IQ_SIZE = 332
IQ_CAPACITY = 80


def parse_iq(blob: bytes) -> dict:
    if len(blob) != IQ_SIZE:
        raise ValueError(f"IQ length must be {IQ_SIZE}, got {len(blob)}")

    samp_cnt, rssi_raw, es_sn, timestamp_sn = struct.unpack_from(IQ_HEADER_FORMAT, blob, 0)
    if samp_cnt > IQ_CAPACITY:
        raise ValueError(f"invalid samp_cnt: {samp_cnt}")

    iq = [struct.unpack_from(IQ_POINT_FORMAT, blob, 8 + index * 4)
          for index in range(samp_cnt)]
    tof_result = struct.unpack_from("<I", blob, 328)[0]
    return {
        "samp_cnt": samp_cnt,
        "rssi_raw": rssi_raw,
        "es_sn": es_sn,
        "timestamp_sn": timestamp_sn,
        "iq": iq,
        "tof_result": tof_result,
    }
```

不要直接在 Python 中使用本机原生格式（例如省略 `<` 的 `struct` 格式），也不要仅凭换行判断数据块结束。串口丢行时应丢弃当前不完整样本，等待下一次 `seq=0` 重新同步，而不是把前后两次 IQ 拼在一起。

如果后续需要长期保存和跨版本分析，建议将原始串口日志原样保留，同时把解析结果保存为带协议版本的 CSV、NPZ 或 Parquet 文件。这样即使解析算法更新，也可以从原始数据重新生成结果。

## 兼容性规则

- 当前协议版本保持既有固件的原生结构布局，不改变线上字节数。
- 所有多字节整数按 BS21E 小端序解析。
- 新增字段时应新增协议版本，不得直接改变现有字段偏移。
- 上位机必须验证消息类型、负载长度、Anchor ID 范围和时间戳配对关系。
