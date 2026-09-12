"""Reusable Kalman filtering helpers for positioning and sensing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np


def _clamp_dt(dt: float, default: float = 0.05) -> float:
    if dt is None or not np.isfinite(dt):
        return default
    return float(min(max(dt, 0.02), 0.25))


@dataclass
class _LinearKalmanState:
    x: np.ndarray
    P: np.ndarray
    last_ts: float
    stale_steps: int = 0


class ConstantVelocityKalmanService:
    """Per-key constant-velocity Kalman filters for 2D/3D position."""

    def __init__(self) -> None:
        self._states_2d: Dict[str, _LinearKalmanState] = {}
        self._states_3d: Dict[str, _LinearKalmanState] = {}
        self.process_var_xy = 1.2
        self.process_var_z = 0.8
        self.measurement_var_xy = 1.8
        self.measurement_var_z = 2.5
        self.max_predict_only_steps = 8
        # Pre-allocate constant matrices (never change for a given dims)
        self._I_2d = np.eye(4, dtype=np.float64)
        self._I_3d = np.eye(6, dtype=np.float64)
        self._H_2d = np.zeros((2, 4), dtype=np.float64)
        self._H_2d[0, 0] = 1.0
        self._H_2d[1, 1] = 1.0
        self._H_3d = np.zeros((3, 6), dtype=np.float64)
        self._H_3d[0, 0] = 1.0
        self._H_3d[1, 1] = 1.0
        self._H_3d[2, 2] = 1.0
        self._R_2d = np.diag([self.measurement_var_xy] * 2).astype(np.float64)
        self._R_3d = np.diag([self.measurement_var_xy, self.measurement_var_xy, self.measurement_var_z]).astype(np.float64)

    def reset(self) -> None:
        self._states_2d.clear()
        self._states_3d.clear()

    def update_position(self, key: str, position: Optional[List[float]], timestamp: float) -> Optional[List[float]]:
        key = str(key or "")
        timestamp = float(timestamp or 0.0)
        if position is None:
            out2 = self._predict_only(self._states_2d, key, timestamp, 2)
            out3 = self._predict_only(self._states_3d, key, timestamp, 3)
            return out3 if out3 is not None else out2

        dims = 3 if len(position) >= 3 else 2
        if dims == 2:
            return self._update(self._states_2d, key, position[:2], timestamp, dims=2,
                                identity=self._I_2d, H=self._H_2d, R=self._R_2d)
        return self._update(self._states_3d, key, position[:3], timestamp, dims=3,
                            identity=self._I_3d, H=self._H_3d, R=self._R_3d)

    def _update(self, store: Dict[str, _LinearKalmanState], key: str, z_list: List[float],
                timestamp: float, dims: int, identity: np.ndarray, H: np.ndarray, R: np.ndarray) -> List[float]:
        z = np.asarray(z_list, dtype=np.float64).reshape(dims, 1)
        state = store.get(key)
        if state is None:
            x0 = np.zeros((dims * 2, 1), dtype=np.float64)
            x0[:dims, 0] = z[:, 0]
            P0 = identity * 5.0
            state = _LinearKalmanState(x=x0, P=P0, last_ts=timestamp, stale_steps=0)
            store[key] = state
            return z[:, 0].astype(float).tolist()

        dt = _clamp_dt(timestamp - state.last_ts)
        F = identity.copy()
        for i in range(dims):
            F[i, dims + i] = dt
        Q = self._build_Q(dims, dt)

        x_pred = F @ state.x
        P_pred = F @ state.P @ F.T + Q

        y = z - H @ x_pred
        S = H @ P_pred @ H.T + R
        K = P_pred @ H.T @ np.linalg.inv(S)
        x_upd = x_pred + K @ y
        P_upd = (identity - K @ H) @ P_pred

        state.x = x_upd
        state.P = P_upd
        state.last_ts = timestamp
        state.stale_steps = 0
        return x_upd[:dims, 0].astype(float).tolist()

    def _predict_only(self, store: Dict[str, _LinearKalmanState], key: str,
                      timestamp: float, dims: int) -> Optional[List[float]]:
        state = store.get(key)
        if state is None:
            return None
        dt = _clamp_dt(timestamp - state.last_ts)
        identity = self._I_2d if dims == 2 else self._I_3d
        F = identity.copy()
        for i in range(dims):
            F[i, dims + i] = dt
        Q = self._build_Q(dims, dt)
        state.x = F @ state.x
        state.P = F @ state.P @ F.T + Q
        state.last_ts = timestamp
        state.stale_steps += 1
        if state.stale_steps > self.max_predict_only_steps:
            store.pop(key, None)
            return None
        return state.x[:dims, 0].astype(float).tolist()

    def _build_Q(self, dims: int, dt: float) -> np.ndarray:
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt3 * dt
        size = dims * 2
        Q = np.zeros((size, size), dtype=np.float64)
        for axis in range(dims):
            qv = self.process_var_z if (dims == 3 and axis == 2) else self.process_var_xy
            q_pos = dt4 / 4.0 * qv
            q_cross = dt3 / 2.0 * qv
            q_vel = dt2 * qv
            p_idx = axis
            v_idx = dims + axis
            Q[p_idx, p_idx] = q_pos
            Q[p_idx, v_idx] = q_cross
            Q[v_idx, p_idx] = q_cross
            Q[v_idx, v_idx] = q_vel
        return Q


class ScalarKalmanService:
    """Per-key scalar Kalman filters for link activity."""

    def __init__(self) -> None:
        self._states: Dict[Tuple[str, str], Tuple[float, float, float]] = {}
        self.process_var = 0.008
        self.measurement_var = 0.05
        self.expire_s = 3.0

    def reset(self) -> None:
        self._states.clear()

    def update(self, key: Tuple[str, str], measurement: float, timestamp: float) -> float:
        measurement = float(np.clip(measurement, 0.0, 1.0))
        timestamp = float(timestamp or 0.0)
        state = self._states.get(key)
        if state is None:
            self._states[key] = (measurement, 0.2, timestamp)
            return measurement

        x, P, last_ts = state
        dt = _clamp_dt(timestamp - last_ts)
        P_pred = P + self.process_var * max(dt / 0.05, 1.0)
        K = P_pred / max(P_pred + self.measurement_var, 1e-9)
        x_upd = x + K * (measurement - x)
        P_upd = (1.0 - K) * P_pred
        self._states[key] = (float(x_upd), float(P_upd), timestamp)
        return float(np.clip(x_upd, 0.0, 1.0))

    def decay_stale(self, timestamp: float) -> Dict[Tuple[str, str], float]:
        timestamp = float(timestamp or 0.0)
        out: Dict[Tuple[str, str], float] = {}
        expired = []
        for key, (x, P, last_ts) in self._states.items():
            age = timestamp - last_ts
            if age > self.expire_s:
                expired.append(key)
                continue
            if age > 0.0:
                x *= 0.92
                self._states[key] = (x, P + self.process_var, timestamp)
            out[key] = float(np.clip(x, 0.0, 1.0))
        for key in expired:
            self._states.pop(key, None)
        return out
