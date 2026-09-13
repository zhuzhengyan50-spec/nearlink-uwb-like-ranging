# NearLink UWB-Like Ranging & Positioning Suite

<p align="right"><a href="README_EN.md">English</a> | 简体中文</p>

**一套基于星闪（NearLink）SLE Channel Sounding 的多锚点测距、双向 IQ 采集、定位与链路感知研究平台。**

<p align="center">
  <a href="docs/assets/gui-positioning.png"><img src="docs/assets/gui-positioning.png" alt="NearLink 多锚点实时定位界面" width="900"></a>
</p>

| 已验证组网 | 原始观测量 | 定位与感知 | LOS 实测距离 |
| --- | --- | --- | --- |
| **4 Anchor + 多 Client 支持** | **双向 IQ / RSSI / ToF** | **2D / 3D / CFR / MUSIC / 链路评分** | **>100 m** |

> **为什么叫 UWB-Like？** 这里指多锚点测距、原始信道观测和定位的使用形态；底层无线技术是 **NearLink SLE Channel Sounding**，不是 UWB，也不实现 UWB PHY 或协议。

▶ **[在哔哩哔哩观看实测视频](https://www.bilibili.com/video/BV11wYQ6BEQ1/)**

## Why This Project?

HiSpark/BS2X SDK 已提供 SLE Channel Sounding 与测距算法接口，但从单条测距链路走向可用于研究的系统，还需要解决多节点连接、终端身份、双端 IQ 汇集、数据传输、定位、可视化和实验标注等问题。

本项目关注的是：

> **如何把一个面向通信的 Channel Sounding 能力，扩展成可复现的多节点测距、定位与无线感知平台？**

为此，项目把测距节点与数据出口解耦，引入独立 Collector，并打通从嵌入式连接管理、双向 IQ 传输到 PC 端定位、信道分析和研究数据集生成的完整链路。

## What I Built

本项目基于 HiSpark/BS2X SLE 测距示例及 SDK 提供的测距接口开发，新增工作主要包括：

### Embedded & Protocol

- 组织 Anchor、Ranging Client、Collector 三种角色，形成多节点实验拓扑；
- 实现多 Anchor 连接状态管理和逐链路 Channel Sounding 启动流程；
- 通过可配置设备地址区分多个 Ranging Client；
- 按连接保存 Anchor/Client 两端 IQ，并依据时间戳归并同一次测量；
- 设计距离元数据与双向 IQ 的 Collector 传输、分片和串口输出格式；
- 将大量 IQ 日志限制在 Collector，避免 Ranging Client 因持续串口打印而阻塞。

### Host, Positioning & Sensing

- 实现当前 Collector 协议的流式解析、IQ 分片重组与双端配对；
- 实现 Anchor 数量动态配置、多 Client 状态管理和距离趋势显示；
- 使用 ULS 与单步 Gauss–Newton 完成 2D/3D 多边定位，并提供可选 Kalman 平滑；
- 构建 IQ、CFR、相位和 MUSIC 多径分析流程；
- 构建遮挡、动态扰动和链路可靠性评分及空间热图；
- 提供场景标签、真实距离、样本组、采集进度和 Raw/Feature/Temporal 数据集导出。

### System Engineering

- 打通 `Embedded → Protocol → Collector → Host → Positioning/Sensing` 端到端链路；
- 在 BearPi-Pico H2821E 上完成三角色编译、烧录与多 Anchor 实测；
- 以 4 个 Anchor 作为当前稳定配置，同时保留多 Client 身份与上位机动态 Anchor 能力；
- 保留底层观测量，便于后续开展 NLOS、信道变化和定位算法研究。

## System Architecture

<p align="center">
  <img src="docs/assets/system-topology.png" alt="Anchor、Ranging Client、Collector 与上位机之间的系统链路" width="760">
</p>

| 角色 | 职责 | Channel Sounding |
| --- | --- | --- |
| Anchor / Server | 响应测距，提供 Anchor 侧 IQ，并输出 SDK 距离结果 | 是 |
| Ranging Client | 连接多个 Anchor、启动逐链路测距并上传 Client 侧 IQ | 是 |
| Collector | 独立汇集距离、RSSI、ToF、时间戳和双向 IQ，并通过串口输出 | 否 |
| Research GUI | 解析、定位、信道分析、链路感知、标注和数据集导出 | 不适用 |

Collector 不参与信道探测，只承担数据汇集与输出，从而降低 Ranging Client 的处理和串口压力。更完整的数据路径见 [系统架构文档](docs/ARCHITECTURE.md)。

## Experimental Results

| 项目 | 当前结果 |
| --- | --- |
| 开发板 | BearPi-Pico H2821E |
| 稳定 Anchor 连接 | **4 个**；第 5 个曾出现间歇性连接 |
| 多终端支持 | 使用可配置地址区分 Ranging Client，并按 Client 独立维护状态 |
| 实测更新率 | 当前参数下约 **2 Hz/链路**；4 Anchor 时合计约 8 条链路结果/秒 |
| 原始观测量 | Anchor/Client 双向 IQ、RSSI、ToF、时间戳 |
| 定位能力 | 实时 2D/3D 多边定位与轨迹显示 |
| LOS 测距 | 外接 3 dBi 胶棒天线、沿用 SDK 原始校准量时，露天无遮挡实测 **>100 m** |

以上数据是特定开发板、天线布置、SDK 参数和射频环境下的实验结果，不代表所有硬件组合均可达到相同距离或更新率。目前尚未发布系统化定位精度基准。

<p align="center">
  <img src="docs/assets/anchor-deployment.jpg" alt="多 Anchor 室内实验布置" width="60%">
  <img src="docs/assets/handheld-terminal.jpg" alt="BearPi-Pico H2821E 手持终端" width="25%">
</p>

<p align="center"><em>多 Anchor 实验布置与基于 BearPi-Pico H2821E 的手持终端</em></p>

## Technical Boundary

### SDK 与本项目的分工

SDK 提供 SLE 协议栈、Channel Sounding 回调和 `slem_alg_calc_smoothed_dis(...)` 测距接口。固件将同一次测量中的双端 IQ、RSSI 和 ToF 交给 SDK 算法，并使用其输出的距离结果。

本项目没有宣称重新实现厂商底层测距算法；它完成的是多节点连接与状态组织、双端观测量汇集、Collector 数据路径，以及基于 SDK 距离结果的上位机定位和基于 IQ 的研究分析。

### IQ 频率映射

当前上位机研究流程将前 79 个 IQ 点映射到 2402–2480 MHz，用于 CFR、相位和 MUSIC 特征计算。该映射是当前分析配置，在把它视为固定协议保证之前，还需要结合具体 SDK Channel Sounding 配置继续验证。

### NearLink SLE 与 UWB

“UWB-Like”只描述系统的使用方式，而非波形等价。该项目的目标不是替代 UWB，而是探索能从 NearLink SLE Channel Sounding、网络设计和信号处理链路中获得怎样的测距、定位与感知能力。

## Software Interface

| 多锚点实时定位 | 链路感知与空间热图 |
| --- | --- |
| [![2D/3D 定位、距离趋势和动态 Anchor 配置](docs/assets/gui-positioning.png)](docs/assets/gui-positioning.png) | [![遮挡、动态、可靠性评分和链路活动热图](docs/assets/gui-sensing.png)](docs/assets/gui-sensing.png) |

上位机还包括独立 IQ 分析与研究数据采集页面。详细操作和数据格式见 [上位机文档](host/README.md)。

## Quick Start

### 1. 集成固件

准备与 BearPi-Pico H2821E 匹配的 HiSpark/BS2X SDK 和构建环境，然后按照 [SDK 接入说明](docs/SDK_INTEGRATION.md) 将示例加入 SDK 并分别配置三个角色。

- [固件使用说明](firmware/sle_measure_dis/README.md)
- [Collector 串口与 IQ 协议](firmware/sle_measure_dis/PROTOCOL.md)

本仓库不包含完整 SDK、编译器、签名工具和厂商二进制依赖。

### 2. 启动上位机

建议使用 Python 3.10 或 3.11：

```powershell
cd host
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python run_gui.py
```

进入软件后可以使用模拟数据体验界面，或连接 Collector 串口接收实测数据。

## Repository Layout

```text
nearlink-uwb-like-ranging/
├── firmware/
│   └── sle_measure_dis/   # 可集成到 HiSpark/BS2X SDK 的固件示例
├── host/                  # 完整桌面端研究工具
│   ├── gui/               # 界面、绘图与研究服务
│   ├── tests/             # 解析、导出与动态 Anchor 回归测试
│   ├── algorithm.py       # ULS + 单步 Gauss–Newton 定位
│   ├── parse_iq_raw.py    # Collector 日志与 IQ 解码器
│   └── run_gui.py         # 程序入口
└── docs/                  # 系统与 SDK 文档
```

## Development Status

### Phase 1 — End-to-End Prototype ✅

- [x] 多 Anchor、多 Ranging Client 测距链路
- [x] 双向 IQ 采集与独立 Collector
- [x] 2D/3D 定位与实时可视化
- [x] IQ/CFR/MUSIC 分析
- [x] 链路活动、遮挡感知与热图
- [x] 研究数据标注与导出

### Phase 2 — Reproducibility & Evaluation

- [ ] 固定并记录经过验证的 SDK/IDE 版本
- [ ] 发布脱敏示例数据和无需硬件的演示流程
- [ ] 补充多环境、运动状态和 NLOS 定量测试
- [ ] 建立上位机持续集成测试

### Phase 3 — Protocol & Performance Optimization

- [ ] 带版本、长度、样本标识和 CRC 的二进制传输协议
- [ ] 更高采样率下的串口带宽与丢片评估
- [ ] 第 5 个及更多 Anchor 的连接稳定性研究

## Current Limitations

- 固件当前默认 4 个 Anchor；上位机 Anchor 数量可自由增减，但这不代表固件已验证任意数量。
- 文本十六进制分片协议优先保证串口调试和日志可读性，并非带宽最优方案。
- 大量 IQ 串口输出可能阻塞嵌入式系统，因此 Ranging Client 不持续打印 IQ，IQ 输出由 Collector 编译选项控制。
- 链路评分和热图是研究特征，不应直接视为经过认证的人员检测结论。
- 定位、遮挡和动态感知效果仍需要更系统的跨环境数据验证。

## License & Acknowledgements

本仓库新增代码采用 [Apache License 2.0](LICENSE)。项目基于 HiSpark/BS2X SDK 的 SLE 示例和接口开发；源自或修改自上游 SDK 的文件保留其原始版权与许可声明，详情见 [NOTICE](NOTICE)。使用者仍需遵守 SDK、工具链及第三方依赖各自的许可条款。
