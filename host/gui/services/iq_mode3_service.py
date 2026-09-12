"""Mode3 IQ stream service for paired anchor/client analysis."""

from collections import deque
from dataclasses import asdict
from typing import Deque, Dict, List, Optional, Tuple
import time
import numpy as np

from parse_iq_raw import StreamParser, extract_iq_arrays
from gui.services.iq_quality_rules import evaluate_pair_quality
from gui.services.nearlink_research_export import (
    DEFAULT_DYNAMIC_WINDOW_SIZE,
    DEFAULT_FIRST_PATH_THRESHOLD_DB,
    DEFAULT_MUSIC_GUARD_NS,
    DEFAULT_PATHS,
    DEFAULT_POINTS,
    DEFAULT_SUBSPACE_ROWS,
    FeatureExtractor,
    IQRecord,
    LinkConfidenceScorer,
    MetaRecord,
)


class IQMode3Service:
    """Consume serial text lines, build anchor-client IQ pairs, and keep per-anchor history."""

    def __init__(self, max_history: int = 200):
        self._max_history = max_history
        self._anchor_count = 4
        self.reset()

    def reset(self) -> None:
        self._parser = StreamParser()
        self._measurement_history: Deque[Dict] = deque(maxlen=4000)
        self._match_window_s = 0.20
        self._histories: Dict[str, Deque[Dict]] = {
            f"A{index}": deque(maxlen=self._max_history)
            for index in range(1, self._anchor_count + 1)
        }
        self._latest_by_anchor: Dict[str, Optional[Dict]] = {k: None for k in self._histories}
        self._latest_snapshot_cache: Dict[Tuple[str, int], Dict] = {}
        self._feature_extractor = FeatureExtractor(
            points=DEFAULT_POINTS,
            n_paths=DEFAULT_PATHS,
            rows=DEFAULT_SUBSPACE_ROWS,
            delay_min_ns=0.0,
            delay_max_ns=120.0,
            delay_step_ns=0.1,
            music_guard_ns=DEFAULT_MUSIC_GUARD_NS,
            first_path_threshold_db=DEFAULT_FIRST_PATH_THRESHOLD_DB,
        )
        self._confidence_scorer = LinkConfidenceScorer(dynamic_window_size=DEFAULT_DYNAMIC_WINDOW_SIZE)

    def set_anchor_count(self, count: int) -> None:
        """Apply the configured anchor count and clear incompatible history."""
        count = max(1, int(count))
        if count == self._anchor_count:
            return
        self._anchor_count = count
        self.reset()

    def push_measurement(
        self,
        timestamp: float,
        distances: Dict[str, float],
        rssis: Dict[str, int],
        cost_ms: int,
        client_key: Optional[str] = None,
        client_label: Optional[str] = None,
        source_addr_byte: Optional[int] = None,
    ) -> None:
        """Push one positioning measurement for later nearest-time IQ matching."""
        ts = float(timestamp if timestamp is not None else time.time())
        self._measurement_history.append(
            {
                "timestamp": ts,
                "distances": dict(distances or {}),
                "rssis": dict(rssis or {}),
                "cost_ms": int(cost_ms or 0),
                "client_key": client_key,
                "client_label": client_label,
                "source_addr_byte": source_addr_byte,
            }
        )

    def _match_measurement(self, timestamp: float, client_key: Optional[str] = None) -> Optional[Dict]:
        if not self._measurement_history:
            return None

        best = None
        best_dt = None
        for item in reversed(self._measurement_history):
            if client_key and item.get("client_key") and item.get("client_key") != client_key:
                continue
            dt = abs(float(item.get("timestamp", 0.0)) - timestamp)
            if best_dt is None or dt < best_dt:
                best = item
                best_dt = dt
            if best_dt is not None and best_dt <= 0.001:
                break

        if best is None or best_dt is None or best_dt > self._match_window_s:
            return None

        return {
            "measurement": best,
            "match_dt_ms": round(best_dt * 1000.0, 3),
        }

    def ingest_lines(self, lines: List[str], timestamp: Optional[float] = None) -> List[Dict]:
        """Feed serial lines and return newly completed pair records for persistence."""
        if not lines:
            flushed = self._parser.flush_collect_if_idle(now_ts=timestamp)
            return self._build_pair_records(flushed, float(timestamp if timestamp is not None else time.time())) if flushed else []

        ts = float(timestamp if timestamp is not None else time.time())
        new_records: List[Dict] = []

        for line in lines:
            completed = self._parser.feed_line(line, now_ts=ts)
            if completed is None:
                continue
            new_records.extend(self._build_pair_records(completed, ts))

        flushed = self._parser.flush_collect_if_idle(now_ts=ts)
        if flushed is not None:
            new_records.extend(self._build_pair_records(flushed, ts))

        return new_records

    def get_anchor_history(self, anchor_id: str, limit: int = 200) -> List[Dict]:
        records = list(self._histories.get(anchor_id, []))
        if limit <= 0:
            return records
        return records[-limit:]

    def get_latest_anchor_snapshot(self, anchor_id: str, limit: int = 200) -> Dict:
        cache_key = (anchor_id, int(limit))
        cached = self._latest_snapshot_cache.get(cache_key)
        latest = self._latest_by_anchor.get(anchor_id)
        if cached and cached.get("latest_record") is latest:
            return cached

        history = self.get_anchor_history(anchor_id, limit=limit)
        snapshot = {
            "anchor_id": anchor_id,
            "record_count": len(history),
            "latest_record": latest,
            "history": history,
        }
        self._latest_snapshot_cache[cache_key] = snapshot
        return snapshot

    def get_multi_anchor_snapshots(self, limit: int = 200) -> Dict[str, Dict]:
        return {
            anchor_id: self.get_latest_anchor_snapshot(anchor_id, limit=limit)
            for anchor_id in self._histories
        }

    def get_latest_link_record(self, anchor_id: str, client_key: str) -> Optional[Dict]:
        """Return the newest record for one exact Anchor–Client link."""
        history = self._histories.get(anchor_id, ())
        return next(
            (record for record in reversed(history) if record.get("client_key") == client_key),
            None,
        )

    def _build_pair_records(self, frame, timestamp: float) -> List[Dict]:
        frame_client_key = frame.client_key
        matched = self._match_measurement(timestamp, client_key=frame_client_key)
        frame_distances = dict(frame.distances)
        frame_rssis = dict(frame.rssis)
        frame_cost_ms = int(frame.cost_ms or 0)
        client_key = frame_client_key
        client_label = frame.client_label
        source_addr_byte = frame.source_addr_byte
        match_dt_ms = None
        if matched:
            measurement = matched["measurement"]
            measured_distances = dict(measurement.get("distances") or {})
            measured_rssis = dict(measurement.get("rssis") or {})
            if measured_distances:
                frame_distances = measured_distances
            if measured_rssis:
                frame_rssis = measured_rssis
            measured_cost = int(measurement.get("cost_ms") or 0)
            if measured_cost > 0:
                frame_cost_ms = measured_cost
            client_key = client_key or measurement.get("client_key")
            client_label = client_label or measurement.get("client_label")
            source_addr_byte = source_addr_byte if source_addr_byte is not None else measurement.get("source_addr_byte")
            match_dt_ms = matched.get("match_dt_ms")

        records: List[Dict] = []

        def _pack_packet(packet):
            feats = asdict(packet.features) if packet.features else {}
            i_vals, q_vals = extract_iq_arrays(packet.data_hex) if packet.data_hex else ([], [])
            return feats, i_vals, q_vals

        pending_client = None
        for packet in frame.iq_packets:
            if str(packet.source).lower().startswith("client"):
                pending_client = packet
                client_key = client_key or str(packet.source).lower()
                client_label = client_label or packet.source
                continue

            anchor_id = packet.source
            if anchor_id not in self._histories:
                continue

            if pending_client is None:
                continue

            client_packet = pending_client
            anchor_packet = packet
            anchor_features, anchor_i, anchor_q = _pack_packet(anchor_packet)
            client_features, client_i, client_q = _pack_packet(client_packet)
            quality = evaluate_pair_quality(anchor_features, client_features)
            meta = MetaRecord(
                anchor=int(str(anchor_id).lstrip("A") or 0),
                client=int(source_addr_byte or 0),
                conn_id=int(anchor_packet.conn_id or client_packet.conn_id or 0),
                sdk_dist_mm=int(round(float(frame_distances.get(anchor_id) or 0.0) * 1000.0)),
                sdk_rssi=int(frame_rssis.get(anchor_id) or 0),
                local_timestamp=int(client_packet.timestamp_sn or 0),
                remote_timestamp=int(anchor_packet.timestamp_sn or 0),
                local_rssi=int(client_packet.rssi_raw_u8 or 0),
                remote_rssi=int(anchor_packet.rssi_raw_u8 or 0),
            )
            sample_client = IQRecord(
                kind="CLIENT_IQ",
                anchor=meta.anchor,
                client=meta.client,
                timestamp=meta.local_timestamp,
                rssi=meta.local_rssi,
                samp_cnt=int(client_packet.sample_cnt or len(client_i)),
                iq_pairs=[(int(round(i)), int(round(q))) for i, q in zip(client_i, client_q)],
            )
            sample_server = IQRecord(
                kind="SERVER_IQ",
                anchor=meta.anchor,
                client=meta.client,
                timestamp=meta.remote_timestamp,
                rssi=meta.remote_rssi,
                samp_cnt=int(anchor_packet.sample_cnt or len(anchor_i)),
                iq_pairs=[(int(round(i)), int(round(q))) for i, q in zip(anchor_i, anchor_q)],
            )
            sample = self._feature_extractor.estimate(meta, sample_client, sample_server)
            sample.snapshot_time = float(timestamp)
            sample = self._confidence_scorer.apply(sample)
            cfr_info = {
                "valid": True,
                "state_label": ("NLOS" if sample.blockage_score >= 0.5 else "LOS") + "_" + ("WI" if sample.dynamic_score >= 0.5 else "ST"),
                "blockage_score": sample.blockage_score,
                "dynamic_score": sample.dynamic_score,
                "link_reliability_score": sample.link_reliability_score,
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
                "music_peak_count": sample.music_peak_count,
                "music_peak_gap_ns": sample.music_peak_gap_ns,
                "freq_mhz": (sample.freqs_hz / 1e6).astype(float).tolist(),
                "cfr_mag": np.abs(sample.cfr).astype(float).tolist(),
                "cfr_phase": np.unwrap(np.angle(sample.cfr)).astype(float).tolist(),
                "music_delay_ns": sample.music_delay_ns.astype(float).tolist(),
                "music_score": sample.music_score.astype(float).tolist(),
            }

            record = {
                "timestamp": timestamp,
                "frame_index": frame.frame_index,
                "client_key": client_key,
                "client_label": client_label,
                "source_addr_byte": source_addr_byte,
                "anchor_id": anchor_id,
                "distance": frame_distances.get(anchor_id),
                "rssi": frame_rssis.get(anchor_id),
                "cost_ms": frame_cost_ms,
                "distances": frame_distances,
                "rssis": frame_rssis,
                "measurement_match_dt_ms": match_dt_ms,
                "anchor_packet": {
                    "source": anchor_packet.source,
                    "msg_type": anchor_packet.msg_type,
                    "expected_len": anchor_packet.expected_len,
                    "actual_len": anchor_packet.actual_len,
                    "complete": anchor_packet.complete,
                    "anchor_id": anchor_packet.anchor_id,
                    "conn_id": anchor_packet.conn_id,
                    "sample_cnt": anchor_packet.sample_cnt,
                    "rssi_raw_u8": anchor_packet.rssi_raw_u8,
                    "es_sn": anchor_packet.es_sn,
                    "timestamp_sn": anchor_packet.timestamp_sn,
                    "data_hex": anchor_packet.data_hex,
                    "i_values": anchor_i,
                    "q_values": anchor_q,
                },
                "client_packet": {
                    "source": client_packet.source,
                    "msg_type": client_packet.msg_type,
                    "expected_len": client_packet.expected_len,
                    "actual_len": client_packet.actual_len,
                    "complete": client_packet.complete,
                    "anchor_id": client_packet.anchor_id,
                    "conn_id": client_packet.conn_id,
                    "sample_cnt": client_packet.sample_cnt,
                    "rssi_raw_u8": client_packet.rssi_raw_u8,
                    "es_sn": client_packet.es_sn,
                    "timestamp_sn": client_packet.timestamp_sn,
                    "data_hex": client_packet.data_hex,
                    "i_values": client_i,
                    "q_values": client_q,
                },
                "anchor_features": anchor_features,
                "client_features": client_features,
                "quality": quality,
                "cfr": cfr_info,
            }

            self._histories[anchor_id].append(record)
            self._latest_by_anchor[anchor_id] = record
            self._latest_snapshot_cache.clear()
            records.append(record)
            pending_client = None

        return records
