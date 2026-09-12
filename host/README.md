# NearLink UWB-Like Ranging — Research GUI

面向星闪（NearLink）双向 IQ、多锚点测距与定位实验的桌面端研究工具。

它接收 collector 固件输出的串口数据，同时完成多 client 距离监控、2D/3D 定位、双向 IQ 配对、CFR/MUSIC 特征分析、链路活动感知热图以及带标签的数据集导出。软件不包含测距纠偏模型，保留的是原始测距、定位与研究特征链路，便于复现实验和继续开发。

## 核心能力

- 多 client、多 anchor 实时测距；anchor 默认 4 个，可在界面中自由增加或删除。
- 2D/3D 定位、轨迹显示和可选的 Kalman 位置平滑。
- client/anchor 双向 IQ 自动配对与质量检查。
- CFR、相位、MUSIC 多径指标，以及遮挡、动态、可靠性三类链路评分。
- 独立感知页面：单条链路即可显示 Anchor×Client 评分矩阵和时间曲线，不依赖定位结果。
- 有足够 anchor 得到终端坐标后，可将所选链路评分投影为空间热图，并可选 Kalman 平滑。
- 独立的数据采集页面：场景标签、真实距离、样本组、目标数量与采集进度。
- 定位 CSV、配对 IQ JSONL，以及按 anchor 划分的 Raw/Feature/Temporal CSV 导出。
- 串口实测与模拟数据两种运行模式。

## 页面结构

1. **定位**：锚点配置、多 client 距离及 2D/3D 位置。
2. **感知**：Anchor×Client 链路评分矩阵、选中链路历史，以及可选的空间投影热图。
3. **IQ 分析**：所有已配置 anchor 的状态概览，以及选中链路的 IQ/CFR/MUSIC 指标。
4. **数据采集**：面向学术实验的数据标注、目标样本计数与数据集导出。

感知评分的输入、公式、适用范围和空间投影条件见 [`docs/sensing.md`](docs/sensing.md)。

## 快速开始

建议使用 Python 3.10 或 3.11。

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python run_gui.py
```

进入软件后：

1. 在 Anchor 配置中添加或删除锚点，填写坐标后点击“应用配置”。默认配置为 4 个 anchor，但程序不限制为 4 个。
2. 选择串口及波特率并连接 collector。
3. 在“数据采集”页面设置实验标签；如果只做定位，可暂停数据记录或关闭 IQ 解析。
4. 返回“定位”页面开始运行。

二维解算至少需要 3 个有效且不共线的 anchor。三维解算至少需要 4 个有效且不共面的 anchor；如果所有 anchor 高度相同，不能可靠估计独立的高度值。

## 串口协议与 IQ 编码

GUI 只解析 collector 当前使用的文本协议，不兼容旧版 `FINAL_* / IQ RAW` 日志：

```text
COLLECT_SAMPLE_META anchor=1 client=3 conn_id=... sdk_dist_mm=... sdk_rssi=... local_timestamp=... remote_timestamp=... local_rssi=... remote_rssi=...
COLLECT_LOCAL_IQ seq=0 hex=...
COLLECT_REMOTE_IQ seq=0 hex=...
```

- `COLLECT_SAMPLE_META` 标识一组 anchor/client 样本及 SDK 测距结果。
- `COLLECT_LOCAL_IQ` 和 `COLLECT_REMOTE_IQ` 分别携带本地端与远端 IQ；`seq` 是十六进制文本分片序号。
- 解析器按 `seq` 排序并拼接同类分片，得到完整二进制 payload。
- IQ payload 头为 `sample_cnt(1) + rssi(1) + es_sn(2, LE) + timestamp(4, LE)`，尾部保留 4 字节 ToF 数据。
- 中间 IQ 区在当前 Mode 3 中每 4 字节表示一个样本：`I_low, I_high, Q_low, Q_high`。I/Q 优先按 11-bit 有符号数解释；超出该编码范围时回退为 little-endian `int16`。
- 实际样本数由 `sample_cnt` 截断。GUI 当前研究流水线默认使用前 79 个频点。

`hex=` 是为了安全穿过串口文本日志的传输编码：每个原始字节会展开为两个 ASCII 十六进制字符，因此并非最节省带宽的二进制协议。后续若改为二进制帧，建议增加固定帧头、协议版本、payload 长度、样本标识、分片序号、分片总数与 CRC。

独立解析已有日志：

```bash
python parse_iq_raw.py --input collector.log --out-dir parsed
```

解析器会从实际出现的 `A1...An` 动态生成汇总列，不限制为 4 或 5 个 anchor。

## 数据输出

启用数据采集后，完整配对记录以 `iq_pair_research_v3` JSONL 写入 `data/gui_sessions/`，包含测距/RSSI、三类评分、时序与多径特征以及双向原始 I/Q。研究数据集还可按需导出三种 CSV：

- `*_raw.csv`：元数据以及 client/anchor 双向原始 I/Q。
- `*_features.csv`：CFR、相位稳定性、MUSIC 多径和链路质量特征。
- `*_time_features.csv`：跨帧变化、相关性、波动和原始测距跳变量。

导出目录与运行数据默认被 `.gitignore` 排除，避免把实验数据或隐私信息误提交到仓库。

## 项目结构

```text
gui/                       Qt 界面、绘图与研究服务
algorithm.py               ULS + 单步 Gauss–Newton 定位
parse_iq_raw.py            串口/日志流及 IQ 解码器
anchor_layout.ini          默认锚点与真值配置
tests/                     核心解析和动态锚点回归测试
nearlink_gui.spec          可选的 PyInstaller 打包配置
```

## 已知边界

- 遮挡、动态、可靠性评分及热图是研究特征与可视化结果，不应直接视为经过认证的人员检测结论。
- 当前文本十六进制协议强调可调试性，会占用更多串口带宽；高采样率场景应评估二进制协议。
- 定位精度取决于 anchor 几何、同步、射频环境和 SDK 测距质量。

## License

Apache License 2.0。第三方库分别遵循其自身许可证。
