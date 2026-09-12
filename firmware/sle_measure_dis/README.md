# SLE Multi-Anchor Ranging

基于星闪 SLE Channel Sounding 的多锚点测距与双向 IQ 采集固件。

本项目面向室内定位、信道测量和测距算法研究：Ranging Client 同时连接多个 Anchor，Anchor 完成距离计算，并可将距离、RSSI、TOF、时间戳以及链路两端 IQ 集中发送到 Collector。使用 BearPi-Pico H2821E 开发板和外接 3 dBi 胶棒天线，无需重复校准参数，在露天无遮挡环境中实测距离可超过 100 米。

> 当前版本为 `v0.1.0-alpha`，主要用于实验和研究。代码已在 BearPi-Pico H2821E 上完成多角色编译与实机功能验证，不建议未经评估直接用于生产环境。

## 主要特性

- 同时连接 **4 个 Anchor** 的多锚点测距。
- 采集 Ranging Client 与 Anchor 两端 IQ。
- 支持多个 Ranging Client，通过设备地址区分身份。
- 使用独立 Collector 汇总数据，避免全部数据经 Ranging Client 中转。
- Collector 按 `Client ID + Anchor ID + 时间戳` 配对距离和双向 IQ。
- Collector IQ 串口输出可在编译时关闭，减少串口阻塞对测距时序的影响。
- 按连接分别维护服务句柄、IQ 缓存和接收流缓存，支持异步回调及分包/粘包处理。

## 系统架构

```text
 +------------------+       Channel Sounding / Client IQ       +------------------+
 | Ranging Client 3 | ---------------------------------------> |                  |
 +------------------+ <--------------- distance -------------- |   Anchor 1...4   |
                                                               | local IQ + calc  |
 +------------------+       Channel Sounding / Client IQ       |                  |
 | Ranging Client 5 | ---------------------------------------> |                  |
 +------------------+ <--------------- distance -------------- +---------+--------+
                                                                         |
                                                distance + RSSI + TOF + bidirectional IQ
                                                                         |
                                                               +---------v--------+
                                                               |    Collector     |
                                                               | serial data out  |
                                                               +------------------+
```

三种固件角色各自独立编译和烧录：

| 角色 | 主要职责 | 是否参与测距 | 串口输出 |
|---|---|---:|---|
| Anchor | 广播、接收 Client IQ、采集本地 IQ、计算距离、转发数据 | 是 | 启动、连接和异常信息 |
| Ranging Client | 连接多个 Anchor、启动 Channel Sounding、上传本地 IQ | 是 | 连接状态及每条连接的首帧提示 |
| Collector | 连接 Anchor、配对并集中输出实验数据 | 否 | 距离元数据；可选双向 IQ |

## 已验证环境

| 项目 | 已验证配置 |
|---|---|
| 开发板 | BearPi-Pico H2821E |
| 天线 | 外接 3 dBi 增益胶棒天线，未使用板载 PCB 天线 |
| RTOS | LiteOS（由官方 SDK 提供） |
| 构建目标 | `standard-bs21e-1100e` |
| 开发工具 | HiSpark Studio |
| Anchor 数量 | 4 |
| Collector 可跟踪的 Ranging Client | 2 |
| 单条 Client-Anchor 链路采样率 | 实测约 2 Hz |

4 个 Anchor 时，每个 Ranging Client 每秒可获得约 8 次分链路测距结果。实际频率会受到无线环境、连接状态和串口负载影响。

## 快速开始

### 1. 准备 SDK

本项目依赖官方 BS2X SDK 提供的 SLE、SSAP、Channel Sounding、LiteOS 和测距算法接口，不能脱离 SDK 单独编译。

- 官方代码仓：[HiSpark/fbb_bs2x](https://gitee.com/HiSpark/fbb_bs2x)
- 官方在线文档：[fbb_bs2x 开发文档](https://docs.hisilicon.com/repos/fbb_bs2x/zh-CN/master/)

将本目录复制到 SDK：

```text
application/samples/products/sle_measure_dis
```

并确认父级构建文件包含以下接入项：

```cmake
# application/samples/products/CMakeLists.txt
if(DEFINED CONFIG_SAMPLE_SUPPORT_SLE_MEASURE_DIS)
    add_subdirectory_if_exist(sle_measure_dis)
endif()
```

```Kconfig
# application/samples/products/Kconfig
config SAMPLE_SUPPORT_SLE_MEASURE_DIS
    bool "Support SLE Measure Dis sample."
    default n
    depends on ENABLE_PRODUCTS_SAMPLE

if SAMPLE_SUPPORT_SLE_MEASURE_DIS
menu "SLE MEASURE Dis Sample Configuration"
    osource "application/samples/products/sle_measure_dis/Kconfig"
endmenu
endif
```

### 2. 准备硬件

已验证的完整实验系统需要准备：

- 4 块 BearPi-Pico H2821E 开发板作为 Anchor；
- 至少 1 块 BearPi-Pico H2821E 开发板作为 Ranging Client；
- 1 块 BearPi-Pico H2821E 开发板作为 Collector（仅需要集中采集时使用）；
- 每块参与测距的开发板使用外接 3 dBi 增益胶棒天线；
- 烧录器、USB/串口连接和稳定电源。

### 3. 编译三种固件

在 HiSpark Studio 配置页面中进入：

```text
Application
└─ Enable Sample
   └─ Enable the Sample of products
      └─ Support SLE Measure Dis sample
```

每次只选择一个角色，保存后重新编译。

#### Anchor

```text
SAMPLE_SUPPORT_SLE_MEASURE_DIS=y
SAMPLE_SUPPORT_SLE_MEASURE_DIS_SERVER=y
```

每块 Anchor 必须使用不同的 `MEASURE_DIS_ANCHOR_ID`，有效值为 `1` 到 `4`。当前配置位于：

```c
// sle_measure_dis_server/sle_measure_dis_server.h
#define MEASURE_DIS_ANCHOR_ID 4
```

分别设置为 `1`、`2`、`3`、`4`，每次重新编译并烧录对应开发板。Anchor 地址格式为：

```text
01:01:01:01:01:<Anchor ID>
```

#### Ranging Client

```text
SAMPLE_SUPPORT_SLE_MEASURE_DIS=y
SAMPLE_SUPPORT_SLE_MEASURE_DIS_CLIENT=y
SAMPLE_SUPPORT_SLE_MEASURE_DIS_CLIENT_ROLE_RANGING=y
SAMPLE_SUPPORT_SLE_MEASURE_DIS_RANGING_CLIENT_ADDR_BYTE=3
```

默认地址为 `03:03:03:03:03:03`。部署多个 Ranging Client 时，每个固件必须设置不同的地址字节，例如 `3`、`5`、`6`。

有效范围为 `2` 到 `254`；数值 `4` 固定保留给 Collector，编译时会拒绝冲突配置。

#### Collector

```text
SAMPLE_SUPPORT_SLE_MEASURE_DIS=y
SAMPLE_SUPPORT_SLE_MEASURE_DIS_CLIENT=y
SAMPLE_SUPPORT_SLE_MEASURE_DIS_CLIENT_ROLE_COLLECTOR2=y
```

Collector 固定使用地址：

```text
04:04:04:04:04:04
```

需要输出双向 IQ 时，再打开：

```text
SAMPLE_SUPPORT_SLE_MEASURE_DIS_COLLECTOR_IQ_PRINT=y
```

这是编译期开关。关闭后 Collector 仍然接收并配对 IQ，只是不向串口输出 `COLLECT_LOCAL_IQ` 和 `COLLECT_REMOTE_IQ` 数据流。

### 4. 执行构建

可以直接在 HiSpark Studio 中执行 **Build**，也可以在 SDK 的 `src` 目录（即 `build.py` 所在目录）运行：

```powershell
python build.py standard-bs21e-1100e -ninja
```

完整固件通常生成在：

```text
tools/pkg/fwpkg/bs21e/bs21e_all.fwpkg
```

### 5. 烧录与启动

推荐按以下顺序部署：

1. 将 Anchor ID 1～4 固件分别烧录到 4 块 Anchor；
2. 烧录并启动 Collector；
3. 最后烧录并启动 Ranging Client；
4. 烧录工具显示 `Connecting, please reset device...` 时复位对应开发板；
5. 观察串口中的地址、角色和连接状态，确认烧录的是正确固件。

## 工作流程

1. Anchor 持续广播，允许 Ranging Client 和 Collector 接入。
2. Ranging Client 扫描目标地址并分别连接 4 个 Anchor。
3. 服务发现、MTU 交换和通知订阅完成后，Ranging Client 为每条连接启动 Channel Sounding。
4. Ranging Client 收齐本地 IQ 分片后，将完整 IQ 上传到对应 Anchor。
5. Anchor 将 Client IQ 与本地 IQ 按时间戳配对并计算距离。
6. Anchor 将距离返回 Ranging Client，同时将距离元数据和双向 IQ 转发给 Collector。
7. Collector 按 Client、Anchor 和时间戳组合完整样本，再通过串口输出。

## 串口输出

固件固定日志使用英文，便于上位机稳定匹配。Ranging Client 不打印 IQ 内容。

### Ranging Client

连接建立并完成 Channel Sounding 初始化时：

```text
[LINK] anchor=1 connected conn=0
[CS] anchor=1 ready conn=0 handle=12
```

每条连接只在收到第一帧有效距离数据时打印一次：

```text
[DATA] anchor=1 first frame received conn=0
```

断线时打印：

```text
[LINK] anchor=1 disconnected conn=0 reason=0x...
```

### Collector

每份完整样本首先输出元数据和距离结构：

```text
COLLECT_SAMPLE_META anchor=1 client=3 conn_id=0 sdk_dist_mm=1000 sdk_rssi=-45 ...
COLLECT_DIST seq=0 hex=...
```

打开 IQ 输出开关后，继续按既有格式输出：

```text
COLLECT_LOCAL_IQ seq=0 hex=...
COLLECT_LOCAL_IQ seq=1 hex=...
COLLECT_REMOTE_IQ seq=0 hex=...
COLLECT_REMOTE_IQ seq=1 hex=...
```

IQ 数据量远大于距离数据。正式测距或串口带宽不足时，应关闭 IQ 输出开关。

## 地址与身份规则

地址不仅用于建立连接，也直接承担设备身份编码：

| 设备 | 地址规则 | 身份来源 |
|---|---|---|
| Anchor | `01:01:01:01:01:<ID>` | 最后一个字节为 Anchor ID |
| Ranging Client | 六个字节使用同一可配置值 | 地址字节即 Client ID |
| Collector | `04:04:04:04:04:04` | 固定地址 4 |

不要让两个同时工作的 Ranging Client 使用相同地址，否则 Collector 无法可靠区分数据来源。

## 数据协议

公共协议定义位于 [`sle_measure_dis_protocol.h`](sle_measure_dis_protocol.h)，详细帧格式和字段偏移见 [`PROTOCOL.md`](PROTOCOL.md)。

当前协议具有以下约束：

- 统一业务帧头为 8 字节：`type` 和 `len` 各占 4 字节；
- 多字节字段使用 BS21E 原生小端序；
- Collector 距离元数据结构固定为 32 字节；
- IQ 结构布局必须与固件所使用的 BS21E SDK 保持一致；
- 上位机应校验消息类型、负载长度、设备 ID 和时间戳匹配关系。

Collector 串口中的 `hex=` 是结构体原始字节的大写十六进制表示，每行最多 24 字节。同一标签的多行需要按 `seq=0, 1, 2, ...` 顺序拼接：`COLLECT_DIST` 拼成 32 字节，`COLLECT_LOCAL_IQ` 和 `COLLECT_REMOTE_IQ` 各拼成 332 字节。IQ 字段偏移、I/Q 排列方式以及 Python 解析示例均收录在 [`PROTOCOL.md`](PROTOCOL.md#上位机解析建议) 中。

## Anchor 校准

当前实测使用外接 3 dBi 胶棒天线，保持 SDK 原始校准量不变即可正常工作。露天无遮挡、视距传播条件下，实测测距距离可超过 100 米。

这里的 100 米以上是特定开发板、天线和测试环境下的实验结果，不代表所有硬件布置和无线环境都能达到相同距离。更换天线、馈线、外壳或安装方式后，仍建议重新验证；只有出现稳定的系统性距离偏差时，再调整校准量。

如需自行重新校准，建议每块 Anchor 单独进行：

1. 在无遮挡、无大型金属物的环境中固定 Anchor；
2. 在三个方向的 1 m 位置分别测量；
3. 计算测量平均值相对 1 m 的偏差；
4. 调整 `sle_measure_dis_server_alg.c` 中的 `calib_val`；
5. 记录 Anchor ID、环境、固件版本和校准值。

不同天线、外壳、安装方向和周边材料都可能改变校准结果。

## 项目结构

```text
sle_measure_dis/
├─ sle_measure_dis.c                   # RTOS 任务与统一入口
├─ sle_measure_dis_protocol.h          # Client、Anchor、Collector 公共协议
├─ Kconfig                             # 角色、Client 地址和 IQ 输出配置
├─ CMakeLists.txt                      # SDK 构建接入
├─ sle_measure_dis_client/
│  ├─ sle_measure_dis_client.c         # 扫描、连接、服务发现及 Collector 汇总
│  └─ sle_measure_dis_client_slem.c    # Client Channel Sounding 与 IQ 上传
├─ sle_measure_dis_server/
│  ├─ sle_measure_dis_server.c         # Anchor 服务、连接与接收流解析
│  ├─ sle_measure_dis_server_adv.c     # Anchor 广播配置
│  └─ sle_measure_dis_server_alg.c     # IQ 配对、距离计算与数据转发
├─ README.md
└─ PROTOCOL.md
```

## 看门狗配置

当前工程将 BS21E 平台主循环及精简日志循环的周期设置为 7 秒：

```c
#define KICK_DOG_INTERVAL_MS       7000
#define TASK_COMMON_APP_DELAY_MS   7000
```

对应文件：

```text
drivers/chips/bs2x/main_init/app_os_init.c
```

这是 SDK 层配置，不属于无线协议。如果使用的官方 SDK 已包含等效设置，不需要重复修改。

## 常见问题

### 编译成功，但签名阶段找不到 `riscv32-linux-secmain.exe`

厂商定制 `objcopy` 会按程序名启动签名辅助工具。确认 `riscv32-linux-secmain.exe` 实际存在，并把它所在目录加入构建进程的 `PATH`，然后重新启动 HiSpark Studio 或终端。


### `build.py` 找不到工程或工具

确保命令从 SDK 的 `src` 目录执行，而不是源码包的上一级目录。HiSpark Studio、Python、CMake、Ninja、编译器和签名工具可能分别来自 SDK 内部目录与外部工具目录，实际位置由 SDK 构建脚本和环境变量共同决定。

### 第五个 Anchor 连接不稳定

当前版本固定为 4 个 Anchor。实测加入第 5 个 Anchor 后，第五条链路存在间歇性中断，因此没有开放 5 Anchor 配置。

## 已知限制

- 当前只在 BearPi-Pico H2821E、外接 3 dBi 胶棒天线和 `standard-bs21e-1100e` 目标上完成验证；
- 4 Anchor 稳定性优于 5 Anchor，当前上限固定为 4；
- 协议直接使用 BS21E 原生结构布局，不支持跨字节序平台直接解析；
- IQ 串口输出可能显著增加任务负载，影响测距实时性；
- 依赖厂商 SDK、工具链、签名工具和预编译测距算法库；
- 尚未建立硬件在环自动化测试。

## 参与贡献

欢迎提交问题、实验数据和改进建议。为了便于复现，请在 Issue 中提供：

- 芯片和开发板型号；
- SDK 版本及构建目标；
- 固件角色与地址配置；
- Anchor 数量和部署方式；
- 完整启动日志及最小复现步骤。

涉及线上消息结构的修改，请同步更新 `sle_measure_dis_protocol.h` 和 `PROTOCOL.md`，并避免直接改变现有字段偏移。

## 开源与许可边界

本项目计划只发布自定义功能代码、必要的接入说明和配置补丁，不重新分发完整厂商 SDK、编译器、签名工具或预编译库。

发布前请保留源文件中的原始版权与许可声明，并根据所使用的官方 SDK 版本核对相关文件和依赖的再分发条件。厂商 SDK 及第三方组件分别受其各自许可约束。
