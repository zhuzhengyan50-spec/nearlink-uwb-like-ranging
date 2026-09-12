"""Dataset export using the same research pipeline as nearlink_music_serial.py."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .nearlink_research_export import (
    DEFAULT_DYNAMIC_WINDOW_SIZE,
    DEFAULT_FIRST_PATH_THRESHOLD_DB,
    DEFAULT_MUSIC_GUARD_NS,
    DEFAULT_PATHS,
    DEFAULT_POINTS,
    DEFAULT_SUBSPACE_ROWS,
    CompleteSample,
    FeatureExtractor,
    IQRecord,
    LinkConfidenceScorer,
    MetaRecord,
)


IQ_SAMPLE_COUNT = DEFAULT_POINTS


@dataclass
class DatasetExportConfig:
    scene_label: str
    anchor_configs: Dict[str, Dict[str, object]]


def _base_fieldnames() -> List[str]:
    return [
        "snapshot_time", "scene_label", "distance_label_m", "sample_group",
        "anchor", "client", "conn_id", "sdk_dist_m", "sdk_rssi",
        "local_timestamp", "remote_timestamp", "local_rssi", "remote_rssi",
        "true_distance_m", "raw_abs_error_m",
    ]


def _raw_fieldnames(points: int) -> List[str]:
    cols = list(_base_fieldnames())
    for idx in range(points):
        cols.extend([f"client_i_{idx}", f"client_q_{idx}"])
    for idx in range(points):
        cols.extend([f"server_i_{idx}", f"server_q_{idx}"])
    return cols


def _feature_fieldnames() -> List[str]:
    return _base_fieldnames() + [
        "phase_rmse", "magnitude_cv",
        "frame_mag_diff_mean", "frame_mag_corr", "mag_time_var", "time_fluctuation",
        "music_direct_ratio", "music_mean_excess_delay_ns", "music_rms_delay_spread_ns",
        "music_entropy", "music_first_delay_ns", "music_strongest_delay_ns",
        "blockage_score", "dynamic_score", "link_reliability_score",
    ]


def _time_feature_fieldnames() -> List[str]:
    return [
        "snapshot_time", "scene_label", "distance_label_m", "sample_group",
        "anchor", "client", "conn_id", "sdk_dist_m", "sdk_rssi",
        "local_timestamp", "remote_timestamp", "local_rssi", "remote_rssi",
        "window_size", "frame_mag_diff_mean", "frame_mag_corr",
        "mag_time_var", "time_fluctuation", "spatial_jumpiness",
    ]


def _normalize_pairs(i_vals: List[float], q_vals: List[float], target_len: int = IQ_SAMPLE_COUNT) -> Tuple[List[float], List[float]]:
    ii = [float(v) for v in list(i_vals or [])[:target_len]]
    qq = [float(v) for v in list(q_vals or [])[:target_len]]
    if len(ii) < target_len:
        ii.extend([0.0] * (target_len - len(ii)))
    if len(qq) < target_len:
        qq.extend([0.0] * (target_len - len(qq)))
    return ii, qq


def _record_to_tuple(record: Dict, points: int) -> Tuple[MetaRecord, IQRecord, IQRecord, float]:
    anchor_id = int(str(record.get("anchor_id") or "A0").lstrip("A") or 0)
    client_id = int(record.get("source_addr_byte") or 0)
    anchor_meta = dict(record.get("anchor_meta") or {})
    client_meta = dict(record.get("client_meta") or {})
    local_iq = dict(record.get("local_iq") or {})
    remote_iq = dict(record.get("remote_iq") or {})
    client_i, client_q = _normalize_pairs(local_iq.get("i") or [], local_iq.get("q") or [], target_len=points)
    server_i, server_q = _normalize_pairs(remote_iq.get("i") or [], remote_iq.get("q") or [], target_len=points)
    meta = MetaRecord(
        anchor=anchor_id,
        client=client_id,
        conn_id=int(anchor_meta.get("conn_id") or client_meta.get("conn_id") or 0),
        sdk_dist_mm=int(round(float(record.get("distance") or 0.0) * 1000.0)),
        sdk_rssi=int(record.get("rssi") or 0),
        local_timestamp=int(client_meta.get("timestamp_sn") or 0),
        remote_timestamp=int(anchor_meta.get("timestamp_sn") or 0),
        local_rssi=int(client_meta.get("rssi_raw_u8") or 0),
        remote_rssi=int(anchor_meta.get("rssi_raw_u8") or 0),
    )
    client_iq = IQRecord(
        kind="CLIENT_IQ",
        anchor=anchor_id,
        client=client_id,
        timestamp=meta.local_timestamp,
        rssi=meta.local_rssi,
        samp_cnt=int(client_meta.get("sample_cnt") or points),
        iq_pairs=[(int(round(i)), int(round(q))) for i, q in zip(client_i, client_q)],
    )
    server_iq = IQRecord(
        kind="SERVER_IQ",
        anchor=anchor_id,
        client=client_id,
        timestamp=meta.remote_timestamp,
        rssi=meta.remote_rssi,
        samp_cnt=int(anchor_meta.get("sample_cnt") or points),
        iq_pairs=[(int(round(i)), int(round(q))) for i, q in zip(server_i, server_q)],
    )
    snapshot_time = float(record.get("timestamp") or 0.0)
    return meta, client_iq, server_iq, snapshot_time


def export_dataset(records: List[Dict], output_dir: str, prefix: str, config: DatasetExportConfig, calibers: Optional[Dict[str, bool]] = None) -> List[Tuple[str, str, str, str]]:
    if calibers is None:
        calibers = {"raw": True, "features": True, "time_features": True}
    export_raw = calibers.get("raw", True)
    export_features = calibers.get("features", True)
    export_time = calibers.get("time_features", True)
    os.makedirs(output_dir, exist_ok=True)
    grouped: Dict[str, List[Dict]] = {}
    for record in records:
        anchor_id = str(record.get("anchor_id") or "")
        if anchor_id:
            grouped.setdefault(anchor_id, []).append(record)

    outputs: List[Tuple[str, str, str, str]] = []

    for anchor_id, anchor_records in sorted(grouped.items()):
        anchor_cfg = dict((config.anchor_configs or {}).get(anchor_id) or {})
        anchor_dir = os.path.join(output_dir, anchor_id.upper())
        os.makedirs(anchor_dir, exist_ok=True)
        anchor_prefix = str(anchor_cfg.get("sample_group") or f"{prefix}_{anchor_id.upper()}")
        raw_path = os.path.join(anchor_dir, f"{anchor_prefix}_raw.csv")
        feat_path = os.path.join(anchor_dir, f"{anchor_prefix}_features.csv")
        time_path = os.path.join(anchor_dir, f"{anchor_prefix}_time_features.csv")

        extractor = FeatureExtractor(
            points=DEFAULT_POINTS,
            n_paths=DEFAULT_PATHS,
            rows=DEFAULT_SUBSPACE_ROWS,
            delay_min_ns=0.0,
            delay_max_ns=120.0,
            delay_step_ns=0.1,
            music_guard_ns=DEFAULT_MUSIC_GUARD_NS,
            first_path_threshold_db=DEFAULT_FIRST_PATH_THRESHOLD_DB,
        )
        scorer = LinkConfidenceScorer(dynamic_window_size=DEFAULT_DYNAMIC_WINDOW_SIZE)

        samples: List[CompleteSample] = []
        for record in anchor_records:
            meta, client_iq, server_iq, snapshot_time_val = _record_to_tuple(record, DEFAULT_POINTS)
            sample = extractor.estimate(meta, client_iq, server_iq, enable_music=export_features)
            sample.snapshot_time = snapshot_time_val
            sample = scorer.apply(sample)
            samples.append(sample)

        raw_fh = open(raw_path, "w", encoding="utf-8-sig", newline="") if export_raw else None
        feat_fh = open(feat_path, "w", encoding="utf-8-sig", newline="") if export_features else None
        time_fh = open(time_path, "w", encoding="utf-8-sig", newline="") if export_time else None

        try:
            raw_writer = csv.DictWriter(raw_fh, fieldnames=_raw_fieldnames(DEFAULT_POINTS)) if raw_fh else None
            feat_writer = csv.DictWriter(feat_fh, fieldnames=_feature_fieldnames()) if feat_fh else None
            time_writer = csv.DictWriter(time_fh, fieldnames=_time_feature_fieldnames()) if time_fh else None
            if raw_writer:
                raw_writer.writeheader()
            if feat_writer:
                feat_writer.writeheader()
            if time_writer:
                time_writer.writeheader()

            previous_distance = None
            window_count = 0
            for sample in samples:
                base = {
                    "snapshot_time": sample.snapshot_time,
                    "scene_label": config.scene_label,
                    "distance_label_m": str(anchor_cfg.get("distance_label_m") or ""),
                    "sample_group": str(anchor_cfg.get("sample_group") or anchor_prefix),
                    "anchor": sample.meta.anchor,
                    "client": sample.meta.client,
                    "conn_id": sample.meta.conn_id,
                    "sdk_dist_m": sample.meta.sdk_dist_mm / 1000.0,
                    "sdk_rssi": sample.meta.sdk_rssi,
                    "local_timestamp": sample.meta.local_timestamp,
                    "remote_timestamp": sample.meta.remote_timestamp,
                    "local_rssi": sample.meta.local_rssi,
                    "remote_rssi": sample.meta.remote_rssi,
                    "true_distance_m": anchor_cfg.get("reference_distance_m", ""),
                    "raw_abs_error_m": (
                        abs(sample.meta.sdk_dist_mm / 1000.0 - float(anchor_cfg["reference_distance_m"]))
                        if anchor_cfg.get("reference_distance_m") is not None else ""
                    ),
                }

                if raw_writer:
                    raw_row = dict(base)
                    client_complex = sample.client_iq.iq_pairs[:DEFAULT_POINTS]
                    server_complex = sample.server_iq.iq_pairs[:DEFAULT_POINTS]
                    for idx in range(DEFAULT_POINTS):
                        ci, cq = client_complex[idx] if idx < len(client_complex) else (0, 0)
                        si, sq = server_complex[idx] if idx < len(server_complex) else (0, 0)
                        raw_row[f"client_i_{idx}"] = ci
                        raw_row[f"client_q_{idx}"] = cq
                        raw_row[f"server_i_{idx}"] = si
                        raw_row[f"server_q_{idx}"] = sq
                    raw_writer.writerow(raw_row)

                if feat_writer:
                    feat_row = dict(base)
                    feat_row.update({
                        "phase_rmse": sample.phase_rmse,
                        "magnitude_cv": sample.magnitude_cv,
                        "frame_mag_diff_mean": sample.frame_mag_diff_mean,
                        "frame_mag_corr": sample.frame_mag_corr,
                        "mag_time_var": sample.mag_time_var,
                        "time_fluctuation": sample.time_fluctuation,
                        "music_direct_ratio": sample.music_direct_ratio,
                        "music_mean_excess_delay_ns": sample.music_mean_excess_delay_ns,
                        "music_rms_delay_spread_ns": sample.music_rms_delay_spread_ns,
                        "music_entropy": sample.music_entropy,
                        "music_first_delay_ns": sample.music_first_delay_ns,
                        "music_strongest_delay_ns": sample.music_strongest_delay_ns,
                        "blockage_score": sample.blockage_score,
                        "dynamic_score": sample.dynamic_score,
                        "link_reliability_score": sample.link_reliability_score,
                    })
                    feat_writer.writerow(feat_row)

                window_count += 1
                measured_distance = sample.meta.sdk_dist_mm / 1000.0
                spatial_jumpiness = 0.0 if previous_distance is None else abs(measured_distance - previous_distance)
                previous_distance = measured_distance

                if time_writer:
                    time_row = {
                        "snapshot_time": sample.snapshot_time,
                        "scene_label": config.scene_label,
                        "distance_label_m": str(anchor_cfg.get("distance_label_m") or ""),
                        "sample_group": str(anchor_cfg.get("sample_group") or anchor_prefix),
                        "anchor": sample.meta.anchor,
                        "client": sample.meta.client,
                        "conn_id": sample.meta.conn_id,
                        "sdk_dist_m": sample.meta.sdk_dist_mm / 1000.0,
                        "sdk_rssi": sample.meta.sdk_rssi,
                        "local_timestamp": sample.meta.local_timestamp,
                        "remote_timestamp": sample.meta.remote_timestamp,
                        "local_rssi": sample.meta.local_rssi,
                        "remote_rssi": sample.meta.remote_rssi,
                        "window_size": min(window_count, 5),
                        "frame_mag_diff_mean": sample.frame_mag_diff_mean,
                        "frame_mag_corr": sample.frame_mag_corr,
                        "mag_time_var": sample.mag_time_var,
                        "time_fluctuation": sample.time_fluctuation,
                        "spatial_jumpiness": spatial_jumpiness,
                    }
                    time_writer.writerow(time_row)
        finally:
            if raw_fh:
                raw_fh.close()
            if feat_fh:
                feat_fh.close()
            if time_fh:
                time_fh.close()

        outputs.append((anchor_id, raw_path if export_raw else "", feat_path if export_features else "", time_path if export_time else ""))

    return outputs
