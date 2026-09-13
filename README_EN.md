# NearLink UWB-Like Ranging & Positioning Suite

<p align="right">English | <a href="README.md">简体中文</a></p>

**A research platform for multi-anchor ranging, bidirectional IQ acquisition, positioning, and link sensing using NearLink SLE Channel Sounding.**

<p align="center">
  <a href="docs/assets/gui-positioning.png"><img src="docs/assets/gui-positioning.png" alt="NearLink real-time multi-anchor positioning interface" width="900"></a>
</p>

| Validated setup | Raw observations | Positioning and sensing | LOS test range |
| --- | --- | --- | --- |
| **4 Anchors + multi-client support** | **Bidirectional IQ / RSSI / ToF** | **2D / 3D / CFR / MUSIC / link scores** | **>100 m** |

> **Why “UWB-Like”?** The term refers to the usage model—multi-anchor ranging, raw channel observations, and positioning. The underlying radio technology is **NearLink SLE Channel Sounding**, not UWB, and this project does not implement the UWB PHY or protocol.

▶ **[Watch the field test on Bilibili](https://www.bilibili.com/video/BV11wYQ6BEQ1/)**

## Why This Project?

The HiSpark/BS2X SDK provides SLE Channel Sounding and a ranging-algorithm interface. Turning an individual ranging link into a research platform, however, still requires multi-node connection management, client identities, bidirectional IQ aggregation, data transport, positioning, visualization, and experiment labeling.

This project asks:

> **How can a communication-oriented Channel Sounding capability be extended into a reproducible multi-node ranging, positioning, and wireless-sensing platform?**

The resulting design separates ranging nodes from the data output path through a dedicated Collector and connects embedded link management and bidirectional IQ transport to host-side positioning, channel analysis, and research dataset generation.

## What I Built

Built on the HiSpark/BS2X SLE ranging sample and SDK-provided ranging interface, this project adds the following components.

### Embedded & Protocol

- Organized Anchor, Ranging Client, and Collector roles into a multi-node experimental topology.
- Implemented multi-Anchor connection state and per-link Channel Sounding startup flows.
- Added configurable device identities for distinguishing multiple Ranging Clients.
- Stored Anchor-side and Client-side IQ per connection and associated observations from the same measurement by timestamp.
- Defined Collector transport, fragmentation, and serial output formats for ranging metadata and bidirectional IQ.
- Confined high-volume IQ logging to the Collector so that serial output does not block the Ranging Client.

### Host, Positioning & Sensing

- Implemented streaming parsing of the current Collector protocol, IQ fragment reassembly, and bidirectional pairing.
- Added dynamic Anchor configuration, per-client state, and distance-trend visualization.
- Implemented 2D/3D multilateration using ULS followed by one Gauss–Newton refinement step, with optional Kalman smoothing.
- Built IQ, CFR, phase, and MUSIC multipath analysis pipelines.
- Built blockage, dynamic-disturbance, and link-reliability scores with spatial heatmaps.
- Added scene labels, reference distances, sample groups, progress tracking, and Raw/Feature/Temporal dataset exports.

### System Engineering

- Completed the `Embedded → Protocol → Collector → Host → Positioning/Sensing` pipeline.
- Built, flashed, and tested all three roles on BearPi-Pico H2821E boards.
- Established four Anchors as the current stable setup while retaining multi-client identities and dynamic host-side Anchor configuration.
- Preserved low-level observations for subsequent NLOS, channel-variation, and positioning research.

## System Architecture

<p align="center">
  <img src="docs/assets/system-topology.png" alt="System links among Anchors, Ranging Clients, the Collector, and the host application" width="760">
</p>

| Role | Responsibility | Channel Sounding |
| --- | --- | --- |
| Anchor / Server | Responds to ranging, provides Anchor-side IQ, and produces the SDK distance result | Yes |
| Ranging Client | Connects to multiple Anchors, starts per-link ranging, and uploads Client-side IQ | Yes |
| Collector | Aggregates distance, RSSI, ToF, timestamps, and bidirectional IQ, then outputs them over serial | No |
| Research GUI | Parses data, positions clients, analyzes the channel, senses link activity, labels samples, and exports datasets | N/A |

The Collector does not participate in Channel Sounding. It provides a dedicated aggregation and output path, reducing processing and logging pressure on the Ranging Client. See [System Architecture](docs/ARCHITECTURE.md) for the full data flow.

## Experimental Results

| Item | Current result |
| --- | --- |
| Development board | BearPi-Pico H2821E |
| Stable Anchor connections | **4**; intermittent connectivity was observed with a fifth Anchor |
| Multi-client support | Configurable Ranging Client identities with independent host-side state |
| Observed update rate | Approximately **2 Hz per link** with the current parameters; about eight link results per second across four Anchors |
| Raw observations | Bidirectional Anchor/Client IQ, RSSI, ToF, and timestamps |
| Positioning | Real-time 2D/3D multilateration and trajectory visualization |
| LOS range | **>100 m** outdoors with unobstructed line of sight, external 3 dBi whip antennas, and the original SDK calibration values |

These are experimental observations from a specific board, antenna arrangement, SDK configuration, and RF environment. They do not guarantee the same range or update rate for other setups. A systematic positioning-accuracy benchmark has not yet been published.

<p align="center">
  <img src="docs/assets/anchor-deployment.jpg" alt="Indoor multi-Anchor experimental deployment" width="60%">
  <img src="docs/assets/handheld-terminal.jpg" alt="BearPi-Pico H2821E handheld terminals" width="25%">
</p>

<p align="center"><em>Multi-Anchor experimental deployment and BearPi-Pico H2821E handheld terminals</em></p>

## Technical Boundary

### Division of responsibility between the SDK and this project

The SDK provides the SLE protocol stack, Channel Sounding callbacks, and the `slem_alg_calc_smoothed_dis(...)` ranging interface. The firmware supplies the SDK algorithm with bidirectional IQ, RSSI, and ToF observations from the same measurement and uses its distance output.

This project does not claim to reimplement the vendor's low-level ranging algorithm. Its contributions are multi-node connection and state orchestration, bidirectional observation aggregation, the Collector data path, host-side positioning from SDK distance results, and IQ-based research analysis.

### IQ frequency mapping

The current host research pipeline maps the first 79 IQ points to 2402–2480 MHz for CFR, phase, and MUSIC feature extraction. This is the current analysis configuration and should be validated against the exact SDK Channel Sounding configuration before being treated as a fixed protocol guarantee.

### NearLink SLE and UWB

“UWB-Like” describes the system workflow, not waveform equivalence. The goal is not to replace UWB, but to explore the ranging, positioning, and sensing capabilities available from NearLink SLE Channel Sounding, network design, and the associated signal-processing pipeline.

## Software Interface

| Real-time multi-anchor positioning | Link sensing and spatial heatmap |
| --- | --- |
| [![2D/3D positioning, distance trends, and dynamic Anchor configuration](docs/assets/gui-positioning.png)](docs/assets/gui-positioning.png) | [![Blockage, dynamic disturbance, reliability scores, and link activity heatmap](docs/assets/gui-sensing.png)](docs/assets/gui-sensing.png) |

The application also provides dedicated IQ-analysis and research-data-collection pages. See the [Host Application Guide](host/README.md) for operation and data-format details.

## Quick Start

### 1. Integrate the firmware

Prepare a HiSpark/BS2X SDK and build environment compatible with the BearPi-Pico H2821E, then follow the [SDK Integration Guide](docs/SDK_INTEGRATION.md) to add the sample and configure its three roles separately.

- [Firmware Guide](firmware/sle_measure_dis/README.md)
- [Collector Serial and IQ Protocol](firmware/sle_measure_dis/PROTOCOL.md)

This repository intentionally excludes the complete SDK, compiler, signing tools, and vendor binary dependencies.

### 2. Run the host application

Python 3.10 or 3.11 is recommended.

```powershell
cd host
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python run_gui.py
```

Use simulated data to explore the interface without hardware, or connect to a Collector serial port for live measurements.

## Repository Layout

```text
nearlink-uwb-like-ranging/
├── firmware/
│   └── sle_measure_dis/   # Firmware sample for integration into the HiSpark/BS2X SDK
├── host/                  # Complete desktop research application
│   ├── gui/               # User interface, plotting, and research services
│   ├── tests/             # Parser, export, and dynamic-Anchor regression tests
│   ├── algorithm.py       # ULS + one-step Gauss–Newton positioning
│   ├── parse_iq_raw.py    # Collector log and IQ decoder
│   └── run_gui.py         # Application entry point
└── docs/                  # System and SDK documentation
```

## Development Status

### Phase 1 — End-to-End Prototype ✅

- [x] Multi-Anchor and multi-Ranging-Client measurement pipeline
- [x] Bidirectional IQ acquisition and dedicated Collector
- [x] 2D/3D positioning and real-time visualization
- [x] IQ/CFR/MUSIC analysis
- [x] Link activity, blockage sensing, and heatmaps
- [x] Research data labeling and export

### Phase 2 — Reproducibility & Evaluation

- [ ] Pin and document the validated SDK and IDE versions
- [ ] Publish sanitized sample data and a hardware-free demonstration workflow
- [ ] Add quantitative tests across environments, motion states, and NLOS conditions
- [ ] Add continuous integration for the host application

### Phase 3 — Protocol & Performance Optimization

- [ ] Introduce a versioned binary protocol with lengths, sample identifiers, and CRC protection
- [ ] Evaluate serial bandwidth and fragment loss at higher sampling rates
- [ ] Investigate connection stability with a fifth and additional Anchors

## Current Limitations

- The firmware defaults to four Anchors. The host can add or remove Anchors dynamically, but this does not mean that arbitrary firmware-side Anchor counts have been validated.
- The hexadecimal text-fragment protocol prioritizes serial debugging and readable logs rather than bandwidth efficiency.
- High-volume serial IQ output can block the embedded system. The Ranging Client therefore does not continuously print IQ, and a Collector build option controls IQ output.
- Link scores and heatmaps are research features and should not be treated as certified human-presence detection results.
- Positioning, blockage, and dynamic-sensing performance still require systematic cross-environment validation.

## License & Acknowledgements

New code in this repository is licensed under the [Apache License 2.0](LICENSE). The project is built on SLE samples and interfaces from the HiSpark/BS2X SDK. Files derived from or modified from the upstream SDK retain their original copyright and license notices; see [NOTICE](NOTICE). Users remain responsible for complying with the licenses of the SDK, toolchain, and third-party dependencies.
