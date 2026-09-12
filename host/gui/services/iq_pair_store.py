"""Persistent store for anchor-client IQ pair records."""

import json
import os
import threading
from datetime import datetime
from typing import Dict, List


class IQPairStore:
    """Append pair records to a session-scoped JSONL file."""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.session_dir = ""
        self.jsonl_path = ""
        self._fh = None
        self._lock = threading.Lock()
        self.new_session()

    def new_session(self) -> str:
        with self._lock:
            if self._fh is not None:
                self._fh.flush()
            if self._fh is not None:
                self._fh.close()
                self._fh = None

            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            self.session_dir = os.path.join(self.base_dir, stamp)
            self.jsonl_path = os.path.join(self.session_dir, "anchor_iq_pairs.jsonl")
            return self.jsonl_path

    def append_records(self, records: List[Dict]) -> None:
        if not records:
            return
        with self._lock:
            if self._fh is None:
                os.makedirs(self.session_dir, exist_ok=True)
                self._fh = open(self.jsonl_path, "a", encoding="utf-8")
            for item in records:
                compact = self._to_compact_record(item)
                self._fh.write(json.dumps(compact, ensure_ascii=False) + "\n")

    def _to_compact_record(self, item: Dict) -> Dict:
        """Persist reproducible link scores and paired IQ without duplicate hex text."""
        anchor_packet = item.get("anchor_packet", {}) or {}
        client_packet = item.get("client_packet", {}) or {}
        cfr = item.get("cfr", {}) or {}

        return {
            "schema": "iq_pair_research_v3",
            "timestamp": item.get("timestamp"),
            "frame_index": item.get("frame_index"),
            "client_key": item.get("client_key"),
            "client_label": item.get("client_label"),
            "source_addr_byte": item.get("source_addr_byte"),
            "anchor_id": item.get("anchor_id"),
            "distance": item.get("distance"),
            "rssi": item.get("rssi"),
            "cost_ms": item.get("cost_ms"),
            "distances": item.get("distances", {}),
            "rssis": item.get("rssis", {}),
            "measurement_match_dt_ms": item.get("measurement_match_dt_ms"),
            "anchor_meta": {
                "source": anchor_packet.get("source"),
                "msg_type": anchor_packet.get("msg_type"),
                "expected_len": anchor_packet.get("expected_len"),
                "actual_len": anchor_packet.get("actual_len"),
                "complete": anchor_packet.get("complete"),
                "sample_cnt": anchor_packet.get("sample_cnt"),
                "conn_id": anchor_packet.get("conn_id"),
                "rssi_raw_u8": anchor_packet.get("rssi_raw_u8"),
                "timestamp_sn": anchor_packet.get("timestamp_sn"),
            },
            "client_meta": {
                "source": client_packet.get("source"),
                "msg_type": client_packet.get("msg_type"),
                "expected_len": client_packet.get("expected_len"),
                "actual_len": client_packet.get("actual_len"),
                "complete": client_packet.get("complete"),
                "sample_cnt": client_packet.get("sample_cnt"),
                "conn_id": client_packet.get("conn_id"),
                "rssi_raw_u8": client_packet.get("rssi_raw_u8"),
                "timestamp_sn": client_packet.get("timestamp_sn"),
            },
            "anchor_features": item.get("anchor_features", {}),
            "client_features": item.get("client_features", {}),
            "scores": {
                "blockage_score": cfr.get("blockage_score"),
                "dynamic_score": cfr.get("dynamic_score"),
                "link_reliability_score": cfr.get("link_reliability_score"),
                "state_label": cfr.get("state_label"),
            },
            "temporal_features": {
                "frame_mag_diff_mean": cfr.get("frame_mag_diff_mean"),
                "frame_mag_corr": cfr.get("frame_mag_corr"),
                "mag_time_var": cfr.get("mag_time_var"),
                "time_fluctuation": cfr.get("time_fluctuation"),
            },
            "multipath_features": {
                "phase_rmse": cfr.get("phase_rmse"),
                "magnitude_cv": cfr.get("magnitude_cv"),
                "music_direct_ratio": cfr.get("music_direct_ratio"),
                "music_mean_excess_delay_ns": cfr.get("music_mean_excess_delay_ns"),
                "music_rms_delay_spread_ns": cfr.get("music_rms_delay_spread_ns"),
                "music_first_delay_ns": cfr.get("music_first_delay_ns"),
                "music_strongest_delay_ns": cfr.get("music_strongest_delay_ns"),
            },
            "local_iq": {
                "i": client_packet.get("i_values", []),
                "q": client_packet.get("q_values", []),
            },
            "remote_iq": {
                "i": anchor_packet.get("i_values", []),
                "q": anchor_packet.get("q_values", []),
            },
        }

    def flush(self) -> None:
        with self._lock:
            if self._fh is not None:
                self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                self._fh.flush()
                self._fh.close()
                self._fh = None

    def get_current_path(self) -> str:
        with self._lock:
            return self.jsonl_path

    def read_records(self) -> List[Dict]:
        """Read the current session after queued writes have been flushed."""
        with self._lock:
            if self._fh is not None:
                self._fh.flush()
            if not self.jsonl_path or not os.path.exists(self.jsonl_path):
                return []
            with open(self.jsonl_path, "r", encoding="utf-8") as source:
                return [json.loads(line) for line in source if line.strip()]
