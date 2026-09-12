"""Shared NearLink research feature pipeline reused by GUI dataset export."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, List, Optional, Tuple

import numpy as np


FREQ_START_MHZ = 2402.0
FREQ_STOP_MHZ = 2480.0
DEFAULT_POINTS = 79
DEFAULT_PATHS = 3
DEFAULT_SUBSPACE_ROWS = 32
DEFAULT_FIRST_PATH_THRESHOLD_DB = -10.0
DEFAULT_MUSIC_GUARD_NS = 1.0
DEFAULT_DYNAMIC_WINDOW_SIZE = 5

BLOCKAGE_FEATURE_SPECS: List[Tuple[str, float, bool, float, float]] = [
    ("magnitude_cv", 0.35, False, 0.671801, 0.371343),
    ("local_rssi", 0.30, True, 192.0, 30.0),
    ("remote_rssi", 0.30, True, 192.0, 30.0),
    ("phase_rmse", 0.05, False, 3.314183, 0.997683),
]

DYNAMIC_FEATURE_SPECS: List[Tuple[str, float, bool, float, float]] = [
    ("frame_mag_corr", 0.35, True, 0.955127, 0.141813),
    ("frame_mag_diff_mean", 0.20, False, 0.063527, 0.098083),
    ("mag_time_var", 0.20, False, 0.007943, 0.014243),
    ("time_fluctuation", 0.25, False, 0.077692, 0.088631),
]

BLOCKAGE_SCORE_CALIBRATION = {
    "center": -0.009702602939929451,
    "scale": 0.5038470201228503,
    "sig_q01": 0.27512809154103807,
    "sig_q99": 0.9989065431459226,
}

DYNAMIC_SCORE_CALIBRATION = {
    "center": 0.0577960325050535,
    "scale": 0.6443864245134969,
    "sig_q01": 0.2805809332889186,
    "sig_q99": 0.9976727163960653,
}


@dataclass
class MetaRecord:
    anchor: int
    client: int
    conn_id: int
    sdk_dist_mm: int
    sdk_rssi: int
    local_timestamp: int
    remote_timestamp: int
    local_rssi: int
    remote_rssi: int


@dataclass
class IQRecord:
    kind: str
    anchor: int
    client: int
    timestamp: int
    rssi: int
    samp_cnt: int
    iq_pairs: List[Tuple[int, int]]

    def to_complex(self, points: int = DEFAULT_POINTS) -> np.ndarray:
        trimmed = self.iq_pairs[:points]
        return np.asarray([complex(i, q) for i, q in trimmed], dtype=np.complex128)


@dataclass
class CompleteSample:
    meta: MetaRecord
    client_iq: IQRecord
    server_iq: IQRecord
    cfr: np.ndarray
    freqs_hz: np.ndarray
    phase_rmse: float
    magnitude_cv: float
    music_delay_ns: np.ndarray
    music_score: np.ndarray
    music_first_delay_ns: float
    music_strongest_delay_ns: float
    music_peak_count: int
    music_peak_gap_ns: float
    music_entropy: float
    music_direct_ratio: float
    music_mean_excess_delay_ns: float
    music_rms_delay_spread_ns: float
    frame_mag_diff_mean: float = 0.0
    frame_mag_corr: float = 1.0
    mag_time_var: float = 0.0
    time_fluctuation: float = 0.0
    blockage_score: float = 0.0
    dynamic_score: float = 0.0
    link_reliability_score: float = 0.0
    snapshot_time: float = field(default_factory=time.time)


@dataclass
class LinkTemporalState:
    history: Deque[np.ndarray]
    prev_norm_mag: Optional[np.ndarray] = None


class FeatureExtractor:
    def __init__(
        self,
        points: int = DEFAULT_POINTS,
        n_paths: int = DEFAULT_PATHS,
        rows: int = DEFAULT_SUBSPACE_ROWS,
        delay_min_ns: float = 0.0,
        delay_max_ns: float = 120.0,
        delay_step_ns: float = 0.1,
        music_guard_ns: float = DEFAULT_MUSIC_GUARD_NS,
        first_path_threshold_db: float = DEFAULT_FIRST_PATH_THRESHOLD_DB,
    ) -> None:
        self.points = points
        self.n_paths = n_paths
        self.rows = rows
        self.music_guard_ns = music_guard_ns
        self.first_path_threshold_db = first_path_threshold_db
        self.freqs_hz = np.linspace(FREQ_START_MHZ, FREQ_STOP_MHZ, points, dtype=np.float64) * 1e6
        self.delays_ns = np.arange(delay_min_ns, delay_max_ns + delay_step_ns * 0.5, delay_step_ns, dtype=np.float64)
        sub_freqs = self.freqs_hz[:rows] - self.freqs_hz[0]
        tau = self.delays_ns[None, :] * 1e-9
        self.steering = np.exp(-1j * 2.0 * np.pi * sub_freqs[:, None] * tau)

    def estimate(self, meta: MetaRecord, client_iq: IQRecord, server_iq: IQRecord, enable_music: bool = True) -> CompleteSample:
        cfr = build_cfr(client_iq, server_iq, self.points)
        freqs_hz = self.freqs_hz[: len(cfr)]
        phase_rmse = phase_fit_rmse(cfr, freqs_hz)
        mag_cv = magnitude_cv(cfr)
        if enable_music:
            music_score, music_score_db, music_spectrum = self.music_delay_spectrum(cfr)
            (
                music_first_delay_ns,
                music_strongest_delay_ns,
                peak_count,
                peak_gap_ns,
                entropy,
                direct_ratio,
                mean_excess_delay_ns,
                rms_delay_spread_ns,
            ) = music_multipath_features(
                self.delays_ns,
                music_score,
                music_score_db,
                music_spectrum,
                threshold_db=self.first_path_threshold_db,
                guard_ns=self.music_guard_ns,
            )
        else:
            music_score = np.zeros_like(self.delays_ns)
            music_first_delay_ns = 0.0
            music_strongest_delay_ns = 0.0
            peak_count = 0
            peak_gap_ns = 0.0
            entropy = 0.0
            direct_ratio = 0.0
            mean_excess_delay_ns = 0.0
            rms_delay_spread_ns = 0.0
        return CompleteSample(
            meta=meta,
            client_iq=client_iq,
            server_iq=server_iq,
            cfr=cfr,
            freqs_hz=freqs_hz,
            phase_rmse=phase_rmse,
            magnitude_cv=mag_cv,
            music_delay_ns=self.delays_ns,
            music_score=music_score,
            music_first_delay_ns=music_first_delay_ns,
            music_strongest_delay_ns=music_strongest_delay_ns,
            music_peak_count=peak_count,
            music_peak_gap_ns=peak_gap_ns,
            music_entropy=entropy,
            music_direct_ratio=direct_ratio,
            music_mean_excess_delay_ns=mean_excess_delay_ns,
            music_rms_delay_spread_ns=rms_delay_spread_ns,
        )

    def music_delay_spectrum(self, cfr: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        if len(cfr) <= self.rows:
            zeros = np.zeros_like(self.delays_ns)
            return zeros, np.full_like(zeros, -120.0), zeros
        mag = np.abs(cfr)
        phase_only = cfr / np.maximum(mag, 1e-9)
        rows = min(self.rows, max(2, len(phase_only) - 1))
        snapshots = build_hankel_snapshots(phase_only, rows)
        covariance = snapshots @ snapshots.conj().T / snapshots.shape[1]
        _eigvals, eigvecs = np.linalg.eigh(covariance)
        noise_space = eigvecs[:, : max(rows - self.n_paths, 1)]
        projection = noise_space.conj().T @ self.steering
        denom = np.sum(np.abs(projection) ** 2, axis=0)
        spectrum = 1.0 / np.maximum(denom, 1e-12)
        spectrum_db = 10.0 * np.log10(np.maximum(spectrum / np.max(spectrum), 1e-12))
        span = float(np.max(spectrum) - np.min(spectrum))
        if span <= 1e-12:
            return np.zeros_like(spectrum), spectrum_db, spectrum
        return (spectrum - np.min(spectrum)) / span, spectrum_db, spectrum


def build_cfr(client_iq: IQRecord, server_iq: IQRecord, points: int) -> np.ndarray:
    client = client_iq.to_complex(points)
    server = server_iq.to_complex(points)
    length = min(len(client), len(server))
    if length <= 0:
        return np.asarray([], dtype=np.complex128)
    return server[:length] * np.conj(client[:length])


def phase_fit_rmse(cfr: np.ndarray, freqs_hz: np.ndarray) -> float:
    length = min(len(cfr), len(freqs_hz))
    if length < 2:
        return 0.0
    cfr = cfr[:length]
    freqs_hz = freqs_hz[:length]
    phase = np.unwrap(np.angle(cfr))
    weights = np.maximum(np.abs(cfr), 1e-6)
    slope, intercept = np.polyfit(freqs_hz, phase, deg=1, w=weights)
    fit = slope * freqs_hz + intercept
    return float(np.sqrt(np.average((phase - fit) ** 2, weights=weights)))


def magnitude_cv(cfr: np.ndarray) -> float:
    if len(cfr) == 0:
        return 0.0
    mag = np.abs(cfr)
    mean = float(np.mean(mag))
    if mean <= 1e-9:
        return 0.0
    return float(np.std(mag) / mean)


def normalized_magnitude(cfr: np.ndarray) -> np.ndarray:
    mag = np.abs(cfr).astype(np.float64, copy=False)
    if mag.size == 0:
        return np.asarray([], dtype=np.float64)
    scale = max(float(np.max(mag)), 1e-12)
    return mag / scale


def safe_corrcoef(x: np.ndarray, y: np.ndarray) -> float:
    x_std = float(np.std(x))
    y_std = float(np.std(y))
    if x_std <= 1e-12 or y_std <= 1e-12:
        return 1.0 if np.allclose(x, y, atol=1e-12, rtol=0.0) else 0.0
    return float(np.corrcoef(x, y)[0, 1])


def frame_mag_diff_mean(curr: np.ndarray, prev: Optional[np.ndarray]) -> float:
    if prev is None or len(curr) == 0 or len(prev) == 0:
        return 0.0
    length = min(len(curr), len(prev))
    curr = curr[:length]
    prev = prev[:length]
    return float(np.mean(np.abs(curr - prev)))


def frame_mag_corr(curr: np.ndarray, prev: Optional[np.ndarray]) -> float:
    if prev is None or len(curr) == 0 or len(prev) == 0:
        return 1.0
    length = min(len(curr), len(prev))
    curr = curr[:length]
    prev = prev[:length]
    return safe_corrcoef(curr, prev)


def _align_frame_stack(history: Iterable[np.ndarray]) -> np.ndarray:
    arrays = [np.asarray(arr, dtype=np.float64).ravel() for arr in history if arr is not None and len(arr) > 0]
    if len(arrays) <= 1:
        return np.asarray(arrays, dtype=object)
    min_len = min(len(a) for a in arrays)
    return np.asarray([a[:min_len] for a in arrays], dtype=np.float64)


def mag_time_var(history: Iterable[np.ndarray]) -> float:
    frames = _align_frame_stack(history)
    if frames.dtype == object or frames.shape[0] <= 1:
        return 0.0
    per_bin_var = np.var(frames, axis=0)
    return float(np.mean(per_bin_var))


def time_fluctuation(history: Iterable[np.ndarray]) -> float:
    frames = _align_frame_stack(history)
    if frames.dtype == object or frames.shape[0] <= 1:
        return 0.0
    per_bin_std = np.std(frames, axis=0)
    return float(np.mean(per_bin_std))


def sigmoid(x: float) -> float:
    if x >= 0:
        z = np.exp(-x)
        return float(1.0 / (1.0 + z))
    z = np.exp(x)
    return float(z / (1.0 + z))


def calibrated_sigmoid(linear: float, params: Dict[str, float]) -> float:
    center = float(params["center"])
    scale = max(float(params["scale"]), 1e-9)
    sig_q01 = float(params["sig_q01"])
    sig_q99 = float(params["sig_q99"])
    raw = sigmoid((linear - center) / scale)
    denom = max(sig_q99 - sig_q01, 1e-9)
    return float(min(max((raw - sig_q01) / denom, 0.0), 1.0))


def find_local_peaks(values: np.ndarray) -> np.ndarray:
    if len(values) < 3:
        return np.asarray([], dtype=int)
    peaks = []
    for idx in range(1, len(values) - 1):
        if values[idx] >= values[idx - 1] and values[idx] >= values[idx + 1]:
            peaks.append(idx)
    return np.asarray(peaks, dtype=int)


def build_hankel_snapshots(cfr: np.ndarray, rows: int) -> np.ndarray:
    rows = min(int(rows), len(cfr) - 1)
    cols = len(cfr) - rows + 1
    if cols <= 1:
        raise ValueError("Subspace rows too large for available CFR samples")
    return np.column_stack([cfr[i:i + rows] for i in range(cols)])


def music_multipath_features(
    delays_ns: np.ndarray,
    score: np.ndarray,
    score_db: np.ndarray,
    spectrum: np.ndarray,
    threshold_db: float = DEFAULT_FIRST_PATH_THRESHOLD_DB,
    guard_ns: float = DEFAULT_MUSIC_GUARD_NS,
) -> Tuple[float, float, int, float, float, float, float, float]:
    peaks = find_local_peaks(score)
    peaks = peaks[delays_ns[peaks] >= guard_ns]
    if peaks.size == 0:
        valid = np.where(delays_ns >= guard_ns)[0]
        strongest_idx = int(valid[np.argmax(score[valid])]) if valid.size else int(np.argmax(score))
        first_idx = strongest_idx
        path_indices = np.asarray([strongest_idx], dtype=int)
    else:
        levels = spectrum[peaks]
        peak_levels_db = score_db[peaks]
        significant = peaks[peak_levels_db >= threshold_db]
        if significant.size == 0:
            significant = peaks[np.argsort(levels)[-1:]]
        first_idx = int(np.min(significant))
        strongest_idx = int(peaks[int(np.argmax(levels))])
        path_indices = np.asarray(np.sort(significant), dtype=int)

    peak_count = int(path_indices.size)
    if peak_count >= 2:
        peak_gap_ns = float(delays_ns[path_indices[1]] - delays_ns[path_indices[0]])
    else:
        peak_gap_ns = 0.0

    valid_mask = delays_ns >= guard_ns
    power = np.maximum(spectrum[valid_mask], 0.0)
    total = float(np.sum(power))
    if power.size == 0 or total <= 1e-12:
        entropy = 0.0
    else:
        prob = power / total
        if len(prob) <= 1:
            entropy = 0.0
        else:
            entropy = float(-np.sum(prob * np.log(prob + 1e-12)) / np.log(len(prob)))

    first_delay = float(delays_ns[first_idx])
    strongest_delay = float(delays_ns[strongest_idx])
    path_powers = np.maximum(spectrum[path_indices], 0.0)
    path_delays = delays_ns[path_indices]
    path_power_total = float(np.sum(path_powers))
    if path_power_total <= 1e-12:
        direct_ratio = 0.0
        mean_excess_delay_ns = 0.0
        rms_delay_spread_ns = 0.0
    else:
        direct_ratio = float(path_powers[0] / path_power_total)
        excess_delays = path_delays - path_delays[0]
        mean_excess_delay_ns = float(np.sum(path_powers * excess_delays) / path_power_total)
        second_moment = float(np.sum(path_powers * (excess_delays ** 2)) / path_power_total)
        variance = max(second_moment - mean_excess_delay_ns ** 2, 0.0)
        rms_delay_spread_ns = float(np.sqrt(variance))
    return (
        first_delay,
        strongest_delay,
        peak_count,
        peak_gap_ns,
        entropy,
        direct_ratio,
        mean_excess_delay_ns,
        rms_delay_spread_ns,
    )


class LinkConfidenceScorer:
    def __init__(self, dynamic_window_size: int = DEFAULT_DYNAMIC_WINDOW_SIZE) -> None:
        self.dynamic_window_size = max(int(dynamic_window_size), 1)
        self.states: Dict[Tuple[int, int, int], LinkTemporalState] = {}

    def _get_state(self, sample: CompleteSample) -> LinkTemporalState:
        key = (sample.meta.anchor, sample.meta.client, sample.meta.conn_id)
        state = self.states.get(key)
        if state is None:
            state = LinkTemporalState(history=deque(maxlen=self.dynamic_window_size))
            self.states[key] = state
        return state

    @staticmethod
    def _weighted_linear(feature_values: Dict[str, float], specs: List[Tuple[str, float, bool, float, float]]) -> float:
        linear = 0.0
        for name, weight, invert, median, iqr in specs:
            raw = float(feature_values.get(name, 0.0))
            scale = iqr if abs(iqr) > 1e-12 else 1.0
            transformed = -raw if invert else raw
            transformed_median = -median if invert else median
            linear += weight * ((transformed - transformed_median) / scale)
        return float(linear)

    def apply(self, sample: CompleteSample) -> CompleteSample:
        state = self._get_state(sample)
        curr_norm_mag = normalized_magnitude(sample.cfr)
        state.history.append(curr_norm_mag)
        sample.frame_mag_diff_mean = frame_mag_diff_mean(curr_norm_mag, state.prev_norm_mag)
        sample.frame_mag_corr = frame_mag_corr(curr_norm_mag, state.prev_norm_mag)
        sample.mag_time_var = mag_time_var(state.history)
        sample.time_fluctuation = time_fluctuation(state.history)
        blockage_features = {
            "magnitude_cv": sample.magnitude_cv,
            "local_rssi": float(sample.meta.local_rssi),
            "remote_rssi": float(sample.meta.remote_rssi),
            "phase_rmse": sample.phase_rmse,
        }
        dynamic_features = {
            "frame_mag_corr": sample.frame_mag_corr,
            "frame_mag_diff_mean": sample.frame_mag_diff_mean,
            "mag_time_var": sample.mag_time_var,
            "time_fluctuation": sample.time_fluctuation,
        }
        blockage_linear = self._weighted_linear(blockage_features, BLOCKAGE_FEATURE_SPECS)
        dynamic_linear = self._weighted_linear(dynamic_features, DYNAMIC_FEATURE_SPECS)
        sample.blockage_score = calibrated_sigmoid(blockage_linear, BLOCKAGE_SCORE_CALIBRATION)
        sample.dynamic_score = calibrated_sigmoid(dynamic_linear, DYNAMIC_SCORE_CALIBRATION)
        combined_risk = min(max(0.6 * sample.blockage_score + 0.4 * sample.dynamic_score, 0.0), 1.0)
        sample.link_reliability_score = 1.0 - combined_risk
        state.prev_norm_mag = curr_norm_mag
        return sample
