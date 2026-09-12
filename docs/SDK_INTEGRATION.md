# SDK 接入说明

本仓库只发布测距功能及其文档，不包含完整的 HiSpark/BS2X SDK、编译器或签名工具。以下路径均以 SDK 的 `src` 目录为基准。

## 1. 复制固件目录

将本仓库中的：

```text
firmware/sle_measure_dis
```

复制到 SDK：

```text
application/samples/products/sle_measure_dis
```

## 2. 添加 CMake 入口

在 SDK 文件 `application/samples/products/CMakeLists.txt` 中加入：

```cmake
if(DEFINED CONFIG_SAMPLE_SUPPORT_SLE_MEASURE_DIS)
    add_subdirectory_if_exist(sle_measure_dis)
endif()
```

将其放在其他产品示例的 `add_subdirectory_if_exist(...)` 条目附近即可。

## 3. 添加 Kconfig 入口

在 `application/samples/products/Kconfig` 的 `config ENABLE_ALL_SAMPLE` 配置中加入：

```kconfig
select SAMPLE_SUPPORT_SLE_MEASURE_DIS
```

随后在同一文件的其他产品示例配置附近加入：

```kconfig
config SAMPLE_SUPPORT_SLE_MEASURE_DIS
    bool
    prompt "Support SLE Measure Dis sample."
    default n
    depends on ENABLE_PRODUCTS_SAMPLE
    help
        Enable the SLE multi-anchor ranging and IQ collection sample.

if SAMPLE_SUPPORT_SLE_MEASURE_DIS
menu "SLE Measure Dis Sample Configuration"
    osource "application/samples/products/sle_measure_dis/Kconfig"
endmenu
endif
```

## 4. 配置三个角色

打开 SDK 工程配置界面，依次进入产品示例和 SLE Measure Dis 配置。三个角色需要分别配置、编译和烧录：

- **Anchor / Server**：参与 Channel Sounding，计算距离并向 Collector 转发数据；
- **Ranging Client**：连接 Anchor、发起测距并上传本端 IQ；
- **Collector**：不参与测距，集中接收并通过串口输出实验数据。

详细的地址规则、编译选项和串口输出格式见固件目录中的 `README.md` 与 `PROTOCOL.md`。

## 5. 环境注意事项

构建和签名由 SDK 自带脚本及外部工具链完成。本仓库不提供这些二进制工具。若编译成功而签名阶段提示找不到 `riscv32-linux-secmain.exe`，请确认该程序实际存在，并确保其所在目录能被构建进程找到；具体路径以所使用的 SDK/IDE 版本为准。

