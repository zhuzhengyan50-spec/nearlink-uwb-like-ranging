"""Shared state for link-level NearLink sensing scores."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Tuple


SCORE_FIELDS = ("blockage_score", "dynamic_score", "link_reliability_score")


@dataclass(frozen=True)
class LinkScoreSample:
    timestamp: float
    anchor_id: str
    client_key: str
    client_label: str
    blockage_score: float
    dynamic_score: float
    link_reliability_score: float


class SensingStateService:
    """Store the latest score and bounded history for every Anchor–Client link."""

    def __init__(self, history_size: int = 300):
        self.history_size = max(1, int(history_size))
        self._histories: Dict[Tuple[str, str], Deque[LinkScoreSample]] = {}

    def reset(self) -> None:
        self._histories.clear()

    def ingest_records(self, records: Iterable[Dict]) -> List[LinkScoreSample]:
        added = []
        for record in records:
            cfr = record.get("cfr") or {}
            if not all(field in cfr for field in SCORE_FIELDS):
                continue
            sample = LinkScoreSample(
                timestamp=float(record["timestamp"]),
                anchor_id=str(record["anchor_id"]),
                client_key=str(record["client_key"]),
                client_label=str(record.get("client_label") or record["client_key"]),
                blockage_score=float(cfr["blockage_score"]),
                dynamic_score=float(cfr["dynamic_score"]),
                link_reliability_score=float(cfr["link_reliability_score"]),
            )
            key = (sample.anchor_id, sample.client_key)
            history = self._histories.setdefault(key, deque(maxlen=self.history_size))
            history.append(sample)
            added.append(sample)
        return added

    def link_keys(self) -> List[Tuple[str, str]]:
        return sorted(self._histories, key=lambda key: (self._anchor_number(key[0]), key[1]))

    def clients(self) -> List[Tuple[str, str]]:
        labels = {}
        for history in self._histories.values():
            if history:
                labels[history[-1].client_key] = history[-1].client_label
        return sorted(labels.items())

    def latest(self, anchor_id: str, client_key: str) -> LinkScoreSample | None:
        history = self._histories.get((anchor_id, client_key))
        return history[-1] if history else None

    def history(self, anchor_id: str, client_key: str) -> List[LinkScoreSample]:
        return list(self._histories.get((anchor_id, client_key), ()))

    @staticmethod
    def _anchor_number(anchor_id: str) -> int:
        suffix = str(anchor_id)[1:]
        return int(suffix) if suffix.isdigit() else 2**31 - 1

