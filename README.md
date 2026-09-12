# NearLink UWB-Like Ranging & Positioning Suite

基于星闪（NearLink）SLE Channel Sounding 的多锚点测距、双向 IQ 采集、定位与链路感知研究套件。

> [!IMPORTANT]
> “UWB-Like”描述的是多锚点测距与定位的使用形态。本项目使用 **NearLink SLE Channel Sounding**，不是 UWB，也不实现 UWB 协议。

## 项目组成

本仓库包含一条可复现实验链路：嵌入式端负责多角色测距与 IQ 汇集，桌面端负责接收、定位、分析、感知和数据集标注。

| 模块 | 主要能力 |
| --- | --- |
| `firmware/sle_measure_dis` | Anchor、Ranging Client、Collector；多锚点测距与双向 IQ 采集 |
| `host` | 串口接收、多 Client 距离监控、2D/3D 定位、IQ/CFR/MUSIC 分析、链路感知与数据集导出 |
| `docs` | SDK 接入和系统架构说明 |

```text
Anchor(s) <── SLE Channel Sounding ──> Ranging Client
    │                                      │
    └──────────── SLE data ────────────────┤
                                           ▼
                                      Collector
                                           │ serial
                                           ▼
                                      Research GUI
```

Collector 不参与信道探测，只负责汇集并输出实验数据，从而降低 Ranging Client 的处理与串口压力。更完整的数据流见 [系统架构](docs/ARCHITECTURE.md)。

## 主要特性

- Ranging Client 可同时连接多个 Anchor，当前固件默认 4 个；
- 支持多个 Ranging Client，并通过可配置设备地址区分身份；
- 同时采集 Ranging Client 与 Anchor 两端 IQ；
- Collector 汇总距离、RSSI、ToF、时间戳和双向 IQ；
- 上位机中的 Anchor 数量可自由增减，默认显示 4 个；
- 支持 2D/3D 定位、轨迹显示和可选的 Kalman 位置平滑；
- 支持双向 IQ 配对、CFR、相位、MUSIC 多径指标；
- 提供遮挡、动态、可靠性三类链路评分与活动感知热图；
- 提供面向研究的数据标签、采集进度和 Raw/Feature/Temporal 数据集导出。

## 硬件与实测环境

- 开发板：BearPi-Pico H2821E；
- 天线：外接 3 dBi 胶棒天线，非板载 PCB 天线；
- 实测环境：露天、无遮挡、视距传播；
- 实测结果：沿用 SDK 原始校准量时，测距距离可超过 100 米。

以上结果来自特定硬件、天线布置和射频环境，不代表所有组合均可达到相同距离。天线安装、遮挡、干扰、Anchor 几何和校准都会影响结果。

## 快速开始

### 1. 集成固件

准备与 BearPi-Pico H2821E 匹配的 HiSpark/BS2X SDK 和构建环境，然后按照 [SDK 接入说明](docs/SDK_INTEGRATION.md) 放入示例并配置三个角色。

- [固件使用说明](firmware/sle_measure_dis/README.md)
- [Collector 串口与 IQ 协议](firmware/sle_measure_dis/PROTOCOL.md)

本仓库不包含完整 SDK、编译器、签名工具和厂商二进制依赖。

### 2. 启动上位机

建议使用 Python 3.10 或 3.11：

```bash
cd host
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python run_gui.py
```

详细操作、页面说明和数据格式见 [上位机文档](host/README.md)。

## 仓库结构

```text
nearlink-uwb-like-ranging/
├── firmware/
│   └── sle_measure_dis/   # 可集成到 HiSpark/BS2X SDK 的固件示例
├── host/                  # 完整桌面端研究工具
│   ├── gui/               # 界面、绘图与研究服务
│   ├── tests/             # 解析、导出与动态 Anchor 回归测试
│   ├── algorithm.py       # 2D/3D 定位算法
│   ├── parse_iq_raw.py    # Collector 日志与 IQ 解码器
│   └── run_gui.py         # 程序入口
└── docs/                  # 系统与 SDK 文档
```

## 当前边界

- 固件实测中 4 个 Anchor 较稳定；连接第 5 个时曾观察到间歇性中断，因此默认配置为 4，但不限制 Anchor 数量。
- Ranging Client 不持续打印 IQ，避免大量串口输出阻塞系统；IQ 输出由 Collector 的编译选项控制。
- 当前协议使用十六进制文本分片，优先保证串口调试和日志可读性，并非带宽最优方案。
- 链路评分和热图是研究特征，不应直接视为经过认证的人员检测结果。

## Roadmap

- [x] 多 Anchor、多 Ranging Client 测距
- [x] 双向 IQ 采集与 Collector 汇总
- [x] 2D/3D 定位和实时可视化
- [x] IQ/CFR/MUSIC 分析
- [x] 链路活动与遮挡感知
- [x] 研究数据标注与导出
- [ ] 带版本、长度和 CRC 的二进制传输协议
- [ ] 更系统的不同环境与天线组合评测

## License

本仓库新增代码采用 [Apache License 2.0](LICENSE)。源自或修改自上游 SDK 的文件保留其原始版权和许可声明，详情见 [NOTICE](NOTICE)。使用者仍需遵守 SDK、工具链及第三方依赖各自的许可条款。
