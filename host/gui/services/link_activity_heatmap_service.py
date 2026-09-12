"""Runtime link-activity smoothing and heatmap generation."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from .kalman_filter_service import ScalarKalmanService


@dataclass
class LinkActivityInput:
    client_key: str
    client_label: str
    anchor_id: str
    anchor_pos: Tuple[float, float]
    client_pos: Tuple[float, float]
    activity: float
    timestamp: float


class LinkActivityHeatmapService:
    """Aggregate smoothed link activity into a room-level 2D heatmap."""

    def __init__(self) -> None:
        self._latest_inputs_by_link: Dict[Tuple[str, str], Dict] = {}
        self._norm_history: Deque[float] = deque(maxlen=160)
        self._last_extent: Optional[Tuple[float, float, float, float]] = None
        self._last_top_links: List[Dict] = []
        self._kalman = ScalarKalmanService()
        self.kalman_enabled = True
        self.link_expire_s = 3.0
        self.grid_size = 64
        self.band_sigma_m = 2.2
        self.display_floor = 0.20
        self.display_gamma = 1.8
        self.activity_gain_gamma = 2.2

    def reset(self) -> None:
        self._latest_inputs_by_link.clear()
        self._norm_history.clear()
        self._last_extent = None
        self._last_top_links = []
        self._kalman.reset()

    def set_kalman_enabled(self, enabled: bool) -> None:
        self.kalman_enabled = bool(enabled)
        self._kalman.reset()

    def update(self, inputs: List[Dict], anchors_2d: List[List[float]], timestamp: float) -> Dict:
        timestamp = float(timestamp or 0.0)
        fresh_link_keys = set()
        for item in inputs:
            client_key = str(item.get("client_key") or "")
            anchor_id = str(item.get("anchor_id") or "")
            key = (client_key, anchor_id)
            fresh_link_keys.add(key)

            raw_activity = float(item.get("activity") or 0.0)
            raw_activity = float(np.clip(raw_activity, 0.0, 1.0))
            smooth = self._kalman.update(key, raw_activity, timestamp) if self.kalman_enabled else raw_activity

            stored = dict(item)
            stored["activity_smoothed"] = smooth
            stored["timestamp"] = timestamp
            self._latest_inputs_by_link[key] = stored

        expired_keys = []
        for key, item in self._latest_inputs_by_link.items():
            age = timestamp - float(item.get("timestamp") or 0.0)
            if age > self.link_expire_s:
                expired_keys.append(key)

        for key in expired_keys:
            self._latest_inputs_by_link.pop(key, None)

        if self.kalman_enabled:
            decayed = self._kalman.decay_stale(timestamp)
            for key, value in decayed.items():
                if key in self._latest_inputs_by_link and key not in fresh_link_keys:
                    self._latest_inputs_by_link[key]["activity_smoothed"] = value

        extent = self._build_extent(anchors_2d, list(self._latest_inputs_by_link.values()))
        heatmap = self._build_heatmap(extent, list(self._latest_inputs_by_link.values()))

        peak = float(np.max(heatmap)) if heatmap.size else 0.0
        if peak > 1e-6:
            self._norm_history.append(peak)
        scale = np.percentile(self._norm_history, 85) if self._norm_history else 1.0
        scale = max(float(scale), 1e-3)
        heatmap_norm = np.clip(heatmap / scale, 0.0, 1.0)
        heatmap_norm = np.clip((heatmap_norm - self.display_floor) / max(1e-6, 1.0 - self.display_floor), 0.0, 1.0)
        heatmap_norm = np.power(heatmap_norm, self.display_gamma)

        self._last_extent = extent
        self._last_top_links = self._build_top_links(list(self._latest_inputs_by_link.values()))
        return {
            "heatmap": heatmap_norm,
            "extent": extent,
            "top_links": self._last_top_links,
            "anchors_2d": [list(pt) for pt in anchors_2d],
        }

    def _build_extent(self, anchors_2d: List[List[float]], link_items: List[Dict]) -> Tuple[float, float, float, float]:
        points = []
        for pt in anchors_2d or []:
            if len(pt) >= 2:
                points.append((float(pt[0]), float(pt[1])))
        for item in link_items:
            a = item.get("anchor_pos") or ()
            c = item.get("client_pos") or ()
            if len(a) >= 2:
                points.append((float(a[0]), float(a[1])))
            if len(c) >= 2:
                points.append((float(c[0]), float(c[1])))
        if not points:
            return (0.0, 50.0, 0.0, 50.0)

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        margin = 5.0
        x0, x1 = min(xs) - margin, max(xs) + margin
        y0, y1 = min(ys) - margin, max(ys) + margin
        if abs(x1 - x0) < 1e-6:
            x1 = x0 + 1.0
        if abs(y1 - y0) < 1e-6:
            y1 = y0 + 1.0
        return (x0, x1, y0, y1)

    def _build_heatmap(self, extent: Tuple[float, float, float, float], link_items: List[Dict]) -> np.ndarray:
        x0, x1, y0, y1 = extent
        xs = np.linspace(x0, x1, self.grid_size)
        ys = np.linspace(y0, y1, self.grid_size)
        grid_x, grid_y = np.meshgrid(xs, ys)
        heat = np.zeros_like(grid_x, dtype=np.float64)

        sigma2 = max(self.band_sigma_m ** 2, 1e-6)
        for item in link_items:
            activity = float(item.get("activity_smoothed") or 0.0)
            if activity <= 1e-4:
                continue
            activity_weight = float(np.power(np.clip(activity, 0.0, 1.0), self.activity_gain_gamma))
            a = item.get("anchor_pos") or ()
            c = item.get("client_pos") or ()
            if len(a) < 2 or len(c) < 2:
                continue
            ax, ay = float(a[0]), float(a[1])
            cx, cy = float(c[0]), float(c[1])
            dx = cx - ax
            dy = cy - ay
            seg_len2 = dx * dx + dy * dy
            if seg_len2 <= 1e-9:
                continue
            t = ((grid_x - ax) * dx + (grid_y - ay) * dy) / seg_len2
            t = np.clip(t, 0.0, 1.0)
            proj_x = ax + t * dx
            proj_y = ay + t * dy
            dist2 = (grid_x - proj_x) ** 2 + (grid_y - proj_y) ** 2
            heat += activity_weight * np.exp(-0.5 * dist2 / sigma2)
        return heat

    def _build_top_links(self, link_items: List[Dict]) -> List[Dict]:
        ranked = []
        for item in link_items:
            score = float(item.get("activity_smoothed") or 0.0)
            if score <= 1e-4:
                continue
            ranked.append({
                "anchor_id": str(item.get("anchor_id") or ""),
                "client_key": str(item.get("client_key") or ""),
                "client_label": str(item.get("client_label") or item.get("client_key") or ""),
                "score": score,
            })
        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked[:6]
