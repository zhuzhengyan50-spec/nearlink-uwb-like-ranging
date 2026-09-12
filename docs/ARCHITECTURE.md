# 系统架构

## 角色划分

系统将测距、汇集和分析拆分为三个嵌入式角色与一个桌面端程序：

- **Anchor / Server**：参与 SLE Channel Sounding，提供锚点侧测量结果和 IQ；地址前缀固定，末字节用于区分 Anchor。
- **Ranging Client**：主动连接 Anchor 并完成测距；设备地址由工程配置指定，用于区分多个移动终端。
- **Collector**：作为独立接收端汇集数据，不参与 Channel Sounding；它将完整样本按既有文本协议输出到串口。
- **Research GUI**：解析 Collector 数据，完成距离显示、定位、IQ 分析、链路感知、标注和数据集导出。

这种拆分避免所有数据都经由 Ranging Client 的串口输出，使移动端专注于连接与测距，同时为多终端实验保留统一的数据入口。

## 数据路径

1. Ranging Client 按配置的身份地址扫描并连接 Anchor。
2. 每条有效链路执行 Channel Sounding，产生距离、RSSI、ToF、时间戳及双向 IQ。
3. Anchor 与 Ranging Client 侧数据被汇集至 Collector。
4. Collector 先输出一行 `COLLECT_SAMPLE_META`，再输出对应的 `COLLECT_LOCAL_IQ` 与 `COLLECT_REMOTE_IQ` 分片。
5. GUI 以元数据行划分样本，按 `seq` 排序并重组 IQ 分片，然后按 Anchor/Client 链路更新定位、分析与感知状态。

串口字段和 IQ payload 的精确定义以 [固件协议文档](../firmware/sle_measure_dis/PROTOCOL.md) 为准。

## 配置边界

- 固件默认最多同时使用 4 个 Anchor，这是当前硬件实测较稳定的设置。
- 上位机 Anchor 数量是动态配置，不被默认值限制。
- 每个 Ranging Client 必须使用不同的配置地址，否则 Collector 和上位机无法可靠区分终端。
- Collector 是否打印 IQ 由固件编译选项控制；Ranging Client 不持续输出 IQ 日志。

## 上位机内部结构

```text
serial input
    └── parse_iq_raw.py
        ├── distance / RSSI updates ──> positioning and plots
        └── paired local/remote IQ
            ├── CFR / phase / MUSIC features
            ├── disturbance / blockage / reliability scores
            └── JSONL session store ──> labeled CSV exports
```

定位、IQ 分析、链路感知和数据采集以页面分离，但共享同一份解析结果和链路状态，避免重复解码或维护互相不一致的数据副本。
