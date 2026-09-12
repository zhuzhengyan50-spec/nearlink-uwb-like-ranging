#!/usr/bin/env python3
"""
Parse paired IQ data from the collector's COLLECT_* log protocol.

Supports:
1) File mode: python parse_iq_raw.py --input log.txt
2) Serial mode: python parse_iq_raw.py --serial-port COM6 --baud 921600

Protocol:
    COLLECT_SAMPLE_META anchor=1 client=3 conn_id=... sdk_dist_mm=... sdk_rssi=...
    COLLECT_LOCAL_IQ seq=0 hex=...
    COLLECT_REMOTE_IQ seq=0 hex=...
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import re
import time
from datetime import datetime
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Dict, Tuple


COLLECT_META_RE = re.compile(
    r".*?COLLECT_SAMPLE_META\s+anchor=(\d+)\s+client=(\d+)\s+conn_id=(\d+)\s+"
    r"sdk_dist_mm=(\d+)\s+sdk_rssi=(-?\d+)\s+local_timestamp=(\d+)\s+remote_timestamp=(\d+)\s+"
    r"local_rssi=(\d+)\s+remote_rssi=(\d+)"
)
COLLECT_HEX_RE = re.compile(r".*?(COLLECT_LOCAL_IQ|COLLECT_REMOTE_IQ)\s+seq=(\d+)\s+hex=([0-9A-Fa-f]+)")

@dataclass
class RangingResult:
    """One complete ranging frame with all data."""
    frame_index: int
    distances: Dict[str, float]
    rssis: Dict[str, int]
    cost_ms: int
    client_key: Optional[str] = None
    client_label: Optional[str] = None
    source_addr_byte: Optional[int] = None
    iq_packets: List["IQPacket"] = field(default_factory=list)


@dataclass
class IQPacket:
    """Single IQ packet (client or anchor)."""
    source: str
    msg_type: int
    expected_len: int
    actual_len: int
    complete: bool
    data_hex: str
    data_dec: str
    anchor_id: Optional[int] = None
    conn_id: Optional[int] = None
    sample_cnt: Optional[int] = None
    rssi_raw_u8: Optional[int] = None
    es_sn: Optional[int] = None
    timestamp_sn: Optional[int] = None
    features: Optional["IQFeatures"] = None


@dataclass
class IQFeatures:
    """Extracted features from IQ data."""
    # Time domain
    mean_amplitude: float
    std_amplitude: float
    mean_i: float
    mean_q: float
    std_i: float
    std_q: float
    peak_amplitude: float
    papr: float  # Peak-to-average power ratio
    zero_crossing_i: int
    zero_crossing_q: int
    # Constellation
    constellation_spread: float
    phase_jitter: float
    amplitude_imbalance: float
    iq_correlation: float
    # Frequency domain
    fft_peak_freq: float
    fft_peak_magnitude: float
    fft_bandwidth: float
    spectral_centroid: float
    # Signal quality
    snr_estimate: float
    # Statistics
    skewness: float
    kurtosis: float


def extract_iq_arrays(data_hex: str) -> Tuple[List[float], List[float]]:
    """Decode Mode 3 IQ pairs from one collector payload."""
    if not data_hex:
        return [], []
    values = [int(x, 16) for x in data_hex.split()]
    if len(values) < 12:
        return [], []

    # Supported layouts:
    # 1) wrapped collect payload: [anchor_id(1), pad(1), conn_id(2), iq_payload...]
    # 2) direct iq payload: [samp_cnt(1), rssi(1), es_sn(2), timestamp(4), iq..., tof(4)]
    base = 0
    if len(values) >= 16 and values[1] == 0 and values[3] == 0 and 1 <= values[4] <= 200:
        base = 4

    sample_cnt = values[base]
    iq_start = base + 8
    iq_end = len(values) - 4 if len(values) > (iq_start + 4) else len(values)
    iq_data = values[iq_start:iq_end]

    I, Q = [], []
    for i in range(0, len(iq_data) - 3, 4):
        i_val = iq_data[i] | (iq_data[i + 1] << 8)
        q_val = iq_data[i + 2] | (iq_data[i + 3] << 8)
        if i_val <= 0x7FF:
            I.append(float(i_val - 0x800 if i_val >= 0x400 else i_val))
        else:
            I.append(float(i_val - 0x10000 if i_val >= 0x8000 else i_val))
        if q_val <= 0x7FF:
            Q.append(float(q_val - 0x800 if q_val >= 0x400 else q_val))
        else:
            Q.append(float(q_val - 0x10000 if q_val >= 0x8000 else q_val))

    # Keep only valid IQ samples reported by firmware.
    if sample_cnt > 0:
        keep = min(sample_cnt, len(I), len(Q))
        I = I[:keep]
        Q = Q[:keep]

    return I, Q


def calc_zero_crossing(arr: List[float]) -> int:
    """Count zero crossings."""
    if len(arr) < 2:
        return 0
    count = 0
    for i in range(1, len(arr)):
        if (arr[i-1] >= 0 and arr[i] < 0) or (arr[i-1] < 0 and arr[i] >= 0):
            count += 1
    return count


def calc_stats(arr: List[float]) -> Tuple[float, float, float, float]:
    """Calculate mean, std, skewness, kurtosis."""
    if not arr:
        return 0.0, 0.0, 0.0, 0.0
    n = len(arr)
    mean = sum(arr) / n
    var = sum((x - mean) ** 2 for x in arr) / n
    std = math.sqrt(var) if var > 0 else 0.0
    if std == 0:
        return mean, std, 0.0, 0.0
    skew = sum((x - mean) ** 3 for x in arr) / (n * std ** 3) if std > 0 else 0.0
    kurt = sum((x - mean) ** 4 for x in arr) / (n * std ** 4) if std > 0 else 0.0
    return mean, std, skew, kurt


def extract_features(data_hex: str) -> Optional[IQFeatures]:
    """Extract all features from IQ hex data."""
    I, Q = extract_iq_arrays(data_hex)
    if len(I) < 8 or len(Q) < 8:
        return None

    # Amplitude
    amplitude = [math.sqrt(i*i + q*q) for i, q in zip(I, Q)]
    mean_amp = sum(amplitude) / len(amplitude)
    std_amp = math.sqrt(sum((a - mean_amp)**2 for a in amplitude) / len(amplitude))
    peak_amp = max(amplitude)
    papr = peak_amp / mean_amp if mean_amp > 0 else 0.0

    # I/Q stats
    mean_i, std_i, skew_i, kurt_i = calc_stats(I)
    mean_q, std_q, skew_q, kurt_q = calc_stats(Q)

    # Zero crossing
    zc_i = calc_zero_crossing(I)
    zc_q = calc_zero_crossing(Q)

    # Constellation features
    # Spread: variance of distance from center
    spread = sum((i*i + q*q - mean_amp**2)**2 for i, q in zip(I, Q)) / len(I)
    spread = math.sqrt(spread) if spread > 0 else 0.0

    # Phase jitter
    phases = [math.atan2(q, i) for i, q in zip(I, Q)]
    phase_mean = sum(phases) / len(phases)
    phase_jitter = math.sqrt(sum((p - phase_mean)**2 for p in phases) / len(phases))

    # Amplitude imbalance
    amp_imbalance = abs(std_i - std_q)

    # I/Q correlation
    if std_i > 0 and std_q > 0:
        iq_corr = sum((i - mean_i) * (q - mean_q) for i, q in zip(I, Q)) / (len(I) * std_i * std_q)
    else:
        iq_corr = 0.0

    # FFT features
    n = len(I)
    iq_complex = [I[i] + 1j * Q[i] for i in range(n)]
    # Simple DFT for peak frequency
    fft_mag = []
    for k in range(n):
        s = 0j
        for m in range(n):
            s += iq_complex[m] * complex(math.cos(-2*math.pi*k*m/n), math.sin(-2*math.pi*k*m/n))
        fft_mag.append(abs(s))
    peak_idx = fft_mag.index(max(fft_mag))
    peak_freq = (peak_idx - n//2) / n if peak_idx > n//2 else peak_idx / n
    peak_mag = max(fft_mag)
    # Bandwidth (simple: width at half max)
    half_max = peak_mag / 2
    bw_count = sum(1 for m in fft_mag if m > half_max)
    bandwidth = bw_count / n
    # Spectral centroid
    total_mag = sum(fft_mag)
    centroid = sum(k * fft_mag[k] for k in range(n)) / total_mag if total_mag > 0 else 0
    centroid = centroid / n

    # SNR estimate (simple: signal power / noise floor estimate)
    sorted_mag = sorted(fft_mag)
    noise_floor = sum(sorted_mag[:n//4]) / (n//4) if n >= 4 else 1
    signal_power = peak_mag
    snr = 20 * math.log10(signal_power / noise_floor) if noise_floor > 0 else 0.0

    # Combined skewness and kurtosis
    skewness = (skew_i + skew_q) / 2
    kurtosis = (kurt_i + kurt_q) / 2

    return IQFeatures(
        mean_amplitude=mean_amp,
        std_amplitude=std_amp,
        mean_i=mean_i, mean_q=mean_q,
        std_i=std_i, std_q=std_q,
        peak_amplitude=peak_amp, papr=papr,
        zero_crossing_i=zc_i, zero_crossing_q=zc_q,
        constellation_spread=spread,
        phase_jitter=phase_jitter,
        amplitude_imbalance=amp_imbalance,
        iq_correlation=iq_corr,
        fft_peak_freq=peak_freq,
        fft_peak_magnitude=peak_mag,
        fft_bandwidth=bandwidth,
        spectral_centroid=centroid,
        snr_estimate=snr,
        skewness=skewness, kurtosis=kurtosis
    )


class StreamParser:
    """Incrementally parse the collector's paired-IQ text protocol."""

    def __init__(self):
        self.results: List[RangingResult] = []
        self.frame_idx = 0
        self._collect_frame = None
        self._collect_last_update_ts: Optional[float] = None

    def _flush_collect_frame(self) -> Optional[RangingResult]:
        frame = self._collect_frame
        self._collect_frame = None
        self._collect_last_update_ts = None
        if not frame:
            return None

        meta = frame.get("meta") or {}
        local_hex = "".join(
            part for _, part in sorted((frame.get("local_hex_parts") or {}).items(), key=lambda item: item[0])
        )
        remote_hex = "".join(
            part for _, part in sorted((frame.get("remote_hex_parts") or {}).items(), key=lambda item: item[0])
        )
        if not local_hex or not remote_hex:
            return None

        client_id = int(meta.get("client_id", 0) or 0)
        anchor_id = int(meta.get("anchor_id", 0) or 0)
        anchor_name = f"A{anchor_id}"
        client_label = f"client{client_id}"

        result = RangingResult(
            frame_index=self.frame_idx,
            distances={anchor_name: float(int(meta.get("sdk_dist_mm", 0) or 0)) / 1000.0},
            rssis={anchor_name: int(meta.get("sdk_rssi", 0) or 0)},
            cost_ms=0,
            client_key=client_label,
            client_label=client_label,
            source_addr_byte=client_id,
        )
        self.frame_idx += 1

        local_raw = bytes.fromhex(local_hex)
        remote_raw = bytes.fromhex(remote_hex)
        local_packet = IQPacket(
            source=client_label,
            msg_type=0x12,
            expected_len=len(local_raw),
            actual_len=len(local_raw),
            complete=True,
            data_hex=local_raw.hex(" "),
            data_dec=" ".join(str(b) for b in local_raw),
            anchor_id=anchor_id,
            conn_id=int(meta.get("conn_id", 0) or 0),
        )
        remote_packet = IQPacket(
            source=anchor_name,
            msg_type=0x13,
            expected_len=len(remote_raw),
            actual_len=len(remote_raw),
            complete=True,
            data_hex=remote_raw.hex(" "),
            data_dec=" ".join(str(b) for b in remote_raw),
            anchor_id=anchor_id,
            conn_id=int(meta.get("conn_id", 0) or 0),
        )
        local_packet.features = extract_features(local_packet.data_hex)
        remote_packet.features = extract_features(remote_packet.data_hex)
        local_meta = parse_metadata(local_raw)
        remote_meta = parse_metadata(remote_raw)
        for k, v in local_meta.items():
            setattr(local_packet, k, v)
        for k, v in remote_meta.items():
            setattr(remote_packet, k, v)

        result.iq_packets.append(local_packet)
        result.iq_packets.append(remote_packet)
        return result

    def _collect_frame_ready(self) -> bool:
        frame = self._collect_frame
        if not frame:
            return False
        return bool(frame.get("local_hex_parts")) and bool(frame.get("remote_hex_parts"))

    def flush_collect_if_idle(self, now_ts: Optional[float] = None, idle_s: float = 0.1) -> Optional[RangingResult]:
        """Flush COLLECT_* frame after the stream has been idle for a short period.

        This avoids prematurely completing a frame when local/remote IQ arrives
        across multiple polling cycles while still allowing the last frame in a
        stream to be emitted without waiting for the next COLLECT_SAMPLE_META.
        """
        if not self._collect_frame_ready():
            return None
        if self._collect_last_update_ts is None:
            return None
        ts = float(now_ts if now_ts is not None else time.time())
        if ts - float(self._collect_last_update_ts) < float(idle_s):
            return None
        return self._flush_collect_frame()

    def feed_line(self, line: str, now_ts: Optional[float] = None) -> Optional[RangingResult]:
        """Feed one line, return completed RangingResult if any."""
        line = line.strip()
        if not line:
            return None

        ts = float(now_ts if now_ts is not None else time.time())

        m_collect_meta = COLLECT_META_RE.match(line)
        if m_collect_meta:
            flushed = self._flush_collect_frame()
            self._collect_frame = {
                "meta": {
                    "anchor_id": int(m_collect_meta.group(1)),
                    "client_id": int(m_collect_meta.group(2)),
                    "conn_id": int(m_collect_meta.group(3)),
                    "sdk_dist_mm": int(m_collect_meta.group(4)),
                    "sdk_rssi": int(m_collect_meta.group(5)),
                    "local_timestamp": int(m_collect_meta.group(6)),
                    "remote_timestamp": int(m_collect_meta.group(7)),
                    "local_rssi": int(m_collect_meta.group(8)),
                    "remote_rssi": int(m_collect_meta.group(9)),
                },
                "local_hex_parts": {},
                "remote_hex_parts": {},
            }
            self._collect_last_update_ts = ts
            return flushed

        m_collect_hex = COLLECT_HEX_RE.match(line)
        if m_collect_hex and self._collect_frame is not None:
            tag = m_collect_hex.group(1)
            seq = int(m_collect_hex.group(2))
            hex_data = m_collect_hex.group(3).strip()
            if tag == "COLLECT_LOCAL_IQ":
                self._collect_frame["local_hex_parts"][seq] = hex_data
            elif tag == "COLLECT_REMOTE_IQ":
                self._collect_frame["remote_hex_parts"][seq] = hex_data
            self._collect_last_update_ts = ts
            return None

        return None

    def flush(self) -> Optional[RangingResult]:
        """Flush any remaining data."""
        collect_result = self._flush_collect_frame()
        if collect_result is not None:
            self.results.append(collect_result)
            return collect_result
        return None


def parse_metadata(data: bytes) -> dict:
    """Parse metadata from IQ payload."""
    if len(data) < 12:
        return {}

    def u16_le(off):
        return int.from_bytes(data[off:off+2], 'little') if len(data) >= off + 2 else None

    def u32_le(off):
        return int.from_bytes(data[off:off+4], 'little') if len(data) >= off + 4 else None

    wrapped = (len(data) >= 16 and data[1] == 0 and data[3] == 0 and 1 <= data[4] <= 200)
    base = 4 if wrapped else 0

    return {
        "anchor_id": data[0] if wrapped else None,
        "conn_id": u16_le(2) if wrapped else None,
        "sample_cnt": data[base] if len(data) >= base + 1 else None,
        "rssi_raw_u8": data[base + 1] if len(data) >= base + 2 else None,
        "es_sn": u16_le(base + 2),
        "timestamp_sn": u32_le(base + 4),
    }


def parse_log(text: str) -> List[RangingResult]:
    """Parse complete log file."""
    parser = StreamParser()
    for line in text.splitlines():
        parser.feed_line(line)
    parser.flush()
    return parser.results


def _anchor_sort_key(anchor_id: str):
    text = str(anchor_id or "")
    suffix = text[1:] if text[:1].upper() == "A" else ""
    return (0, int(suffix)) if suffix.isdigit() else (1, text)


def read_from_serial(port: str, baud: int, timeout: float, duration: float, max_frames: int) -> List[RangingResult]:
    """Read data from serial port."""
    try:
        import serial
    except ImportError:
        raise RuntimeError("pyserial is required for serial capture")

    parser = StreamParser()
    t_start = time.time()

    with serial.Serial(port=port, baudrate=baud, timeout=timeout) as ser:
        print(f"[Serial] Opened {port} @ {baud}")
        try:
            while True:
                if duration > 0 and (time.time() - t_start) >= duration:
                    print("[Serial] Duration reached")
                    break
                if max_frames > 0 and len(parser.results) >= max_frames:
                    print("[Serial] Max frames reached")
                    break

                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue

                result = parser.feed_line(line)
                if result:
                    distances = " ".join(
                        f"{anchor}={value:.3f}"
                        for anchor, value in sorted(result.distances.items(), key=_anchor_sort_key)
                    )
                    print(f"[Frame {result.frame_index}] {distances} | IQ={len(result.iq_packets)}pkts")

        except KeyboardInterrupt:
            print("\n[Serial] Interrupted")

    parser.flush()
    return parser.results


def write_outputs(results: List[RangingResult], out_dir: pathlib.Path, prefix: str) -> None:
    """Write parsed results to files."""
    out_dir.mkdir(parents=True, exist_ok=True)

    anchor_ids = sorted(
        {anchor for result in results for anchor in (*result.distances.keys(), *result.rssis.keys())},
        key=_anchor_sort_key,
    )

    # Summary CSV
    summary_path = out_dir / f"{prefix}_ranging_summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["frame_index", "cost_ms"]
            + [f"{anchor}_distance" for anchor in anchor_ids]
            + [f"{anchor}_rssi" for anchor in anchor_ids]
            + ["client_complete"]
            + [f"{anchor}_complete" for anchor in anchor_ids]
        )
        for r in results:
            row = [r.frame_index, r.cost_ms]
            row.extend(r.distances.get(anchor, "") for anchor in anchor_ids)
            row.extend(r.rssis.get(anchor, "") for anchor in anchor_ids)
            client_packets = [p for p in r.iq_packets if p.source == r.client_key]
            row.append(client_packets[0].complete if client_packets else False)
            for src in anchor_ids:
                pkts = [p for p in r.iq_packets if p.source == src]
                row.append(pkts[0].complete if pkts else False)
            writer.writerow(row)
    print(f"[OK] Summary: {summary_path}")

    # IQ packets CSV
    iq_path = out_dir / f"{prefix}_iq_packets.csv"
    with iq_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "frame_index", "source", "msg_type_hex", "expected_len", "actual_len",
            "complete", "anchor_id", "conn_id", "sample_cnt", "rssi_raw_u8", "es_sn", "timestamp_sn"
        ])
        for r in results:
            for p in r.iq_packets:
                writer.writerow([
                    r.frame_index, p.source, f"0x{p.msg_type:02X}",
                    p.expected_len, p.actual_len, p.complete,
                    p.anchor_id or "", p.conn_id or "", p.sample_cnt or "",
                    p.rssi_raw_u8 or "", p.es_sn or "", p.timestamp_sn or ""
                ])
    print(f"[OK] IQ packets: {iq_path}")

    # Features CSV
    features_path = out_dir / f"{prefix}_features.csv"
    feature_cols = [
        "mean_amplitude", "std_amplitude", "mean_i", "mean_q", "std_i", "std_q",
        "peak_amplitude", "papr", "zero_crossing_i", "zero_crossing_q",
        "constellation_spread", "phase_jitter", "amplitude_imbalance", "iq_correlation",
        "fft_peak_freq", "fft_peak_magnitude", "fft_bandwidth", "spectral_centroid",
        "snr_estimate", "skewness", "kurtosis"
    ]
    with features_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["frame_index", "source"] + feature_cols)
        for r in results:
            for p in r.iq_packets:
                if p.features:
                    row = [r.frame_index, p.source]
                    row.extend([getattr(p.features, col, "") for col in feature_cols])
                    writer.writerow(row)
    print(f"[OK] Features: {features_path}")

    # IQ decimal (for viz)
    dec_path = out_dir / f"{prefix}_iq_dec.txt"
    with dec_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(f"# Frame {r.frame_index}\n")
            dist_text = " ".join(f"{anchor}={r.distances.get(anchor, 0):.3f}" for anchor in anchor_ids)
            rssi_text = " ".join(f"{anchor}={r.rssis.get(anchor, 0)}" for anchor in anchor_ids)
            f.write(f"# Dist: {dist_text}\n")
            f.write(f"# RSSI: {rssi_text} dBm\n")
            f.write(f"# Cost: {r.cost_ms}ms\n\n")
            for p in r.iq_packets:
                f.write(f"source={p.source} type=0x{p.msg_type:02X} "
                        f"len={p.actual_len}/{p.expected_len} complete={p.complete}\n")
                f.write(p.data_dec + "\n\n")
            f.write("-" * 60 + "\n\n")
    print(f"[OK] IQ decimal: {dec_path}")

    # JSON
    json_path = out_dir / f"{prefix}_complete.json"
    with json_path.open("w", encoding="utf-8") as f:
        data = []
        for r in results:
            frame_data = {
                "frame_index": r.frame_index,
                "distances": r.distances,
                "rssis": r.rssis,
                "cost_ms": r.cost_ms,
                "iq_packets": []
            }
            for p in r.iq_packets:
                pkt_dict = {
                    "source": p.source,
                    "msg_type": p.msg_type,
                    "expected_len": p.expected_len,
                    "actual_len": p.actual_len,
                    "complete": p.complete,
                    "data_hex": p.data_hex,
                    "features": asdict(p.features) if p.features else None
                }
                frame_data["iq_packets"].append(pkt_dict)
            data.append(frame_data)
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[OK] JSON: {json_path}")


def print_summary(results: List[RangingResult]) -> None:
    """Print summary."""
    print("\n" + "=" * 60)
    print("Data Summary")
    print("=" * 60)
    print(f"Total frames: {len(results)}")

    total_pkts = sum(len(r.iq_packets) for r in results)
    complete_pkts = sum(1 for r in results for p in r.iq_packets if p.complete)
    print(f"IQ packets: {total_pkts} ({complete_pkts} complete)")

    anchor_ids = sorted(
        {anchor for result in results for anchor in (*result.distances.keys(), *result.rssis.keys())},
        key=_anchor_sort_key,
    )
    print("\nDistances:")
    for anchor in anchor_ids:
        dists = [r.distances.get(anchor, 0) for r in results if anchor in r.distances]
        if dists:
            zeros = sum(1 for d in dists if d == 0)
            print(f"  {anchor}: mean={sum(dists)/len(dists):.3f}m, zeros={zeros}")

    print("\nRSSI (dBm):")
    for anchor in anchor_ids:
        rssis = [r.rssis.get(anchor, 0) for r in results if anchor in r.rssis]
        if rssis:
            print(f"  {anchor}: mean={sum(rssis)/len(rssis):.1f}, range=[{min(rssis)}, {max(rssis)}]")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse NearLink ranging logs with paired IQ data")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", "-i", help="Input log file")
    src.add_argument("--serial-port", help="Serial port (e.g. COM6)")
    parser.add_argument("--baud", type=int, default=921600, help="Serial baud rate")
    parser.add_argument("--timeout", type=float, default=0.5, help="Serial timeout (s)")
    parser.add_argument("--duration", type=float, default=0, help="Capture duration (0=unlimited)")
    parser.add_argument("--max-frames", type=int, default=0, help="Max frames to capture (0=unlimited)")
    parser.add_argument("--out-dir", "-o", default=None, help="Output directory (default: data/<timestamp>)")
    parser.add_argument("--prefix", "-p", default="ranging", help="Output filename prefix")
    args = parser.parse_args()

    # Default output directory: data/<timestamp>
    if args.out_dir:
        out_dir = pathlib.Path(args.out_dir)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = pathlib.Path("data") / timestamp

    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {out_dir}")

    if args.input:
        in_path = pathlib.Path(args.input)
        if not in_path.exists():
            print(f"Error: File not found: {in_path}")
            return 1
        print(f"Reading: {in_path}")
        text = in_path.read_text(encoding="utf-8", errors="ignore")
        results = parse_log(text)
    else:
        results = read_from_serial(
            port=args.serial_port,
            baud=args.baud,
            timeout=args.timeout,
            duration=args.duration,
            max_frames=args.max_frames,
        )

    if not results:
        print("Error: No data")
        return 1

    print_summary(results)
    write_outputs(results, out_dir, args.prefix)
    print(f"\nDone! Files saved to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
