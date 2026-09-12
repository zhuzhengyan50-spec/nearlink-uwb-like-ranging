"""Quality rules for anchor/client IQ feature evaluation."""

from typing import Dict, List


_RULES = {
    "snr_estimate": {
        "display": "SNR",
        "higher_better": True,
        "good": 18.0,
        "warn": 10.0,
        "tip": "越高越好，低SNR通常意味着噪声大。",
    },
    "phase_jitter": {
        "display": "Phase Jitter",
        "higher_better": False,
        "good": 0.60,
        "warn": 1.20,
        "tip": "越低越好，抖动大通常表示时钟或信道不稳定。",
    },
    "constellation_spread": {
        "display": "Constellation Spread",
        "higher_better": False,
        "good": 65000.0,
        "warn": 160000.0,
        "tip": "越低越好，离散过大代表星座点扩散严重。",
    },
    "std_amplitude": {
        "display": "Std Amplitude",
        "higher_better": False,
        "good": 300.0,
        "warn": 700.0,
        "tip": "越低越稳定，过大表示包络波动明显。",
    },
    "iq_correlation": {
        "display": "IQ Correlation(|corr|)",
        "higher_better": False,
        "good": 0.35,
        "warn": 0.70,
        "tip": "绝对相关越低越理想，过高可能代表失衡或耦合。",
        "abs_value": True,
    },
}

_LEVEL_SCORE = {"good": 2, "warn": 1, "bad": 0}


def _judge_metric(metric: str, value: float) -> str:
    cfg = _RULES[metric]
    check_val = abs(value) if cfg.get("abs_value") else value
    good = cfg["good"]
    warn = cfg["warn"]
    if cfg["higher_better"]:
        if check_val >= good:
            return "good"
        if check_val >= warn:
            return "warn"
        return "bad"
    if check_val <= good:
        return "good"
    if check_val <= warn:
        return "warn"
    return "bad"


def evaluate_pair_quality(anchor_features: Dict, client_features: Dict) -> Dict:
    """Return metric-level and overall quality levels for anchor/client pair."""
    metrics = {}
    anchor_total = 0
    client_total = 0

    for key in _RULES:
        a_val = float(anchor_features.get(key, 0.0) or 0.0)
        c_val = float(client_features.get(key, 0.0) or 0.0)
        a_level = _judge_metric(key, a_val)
        c_level = _judge_metric(key, c_val)
        anchor_total += _LEVEL_SCORE[a_level]
        client_total += _LEVEL_SCORE[c_level]
        metrics[key] = {
            "anchor_value": a_val,
            "anchor_level": a_level,
            "client_value": c_val,
            "client_level": c_level,
        }

    max_score = len(_RULES) * 2
    score = (anchor_total + client_total) / float(max_score)
    if score >= 0.75:
        overall = "good"
        summary = "链路质量较好，IQ特征稳定。"
    elif score >= 0.45:
        overall = "warn"
        summary = "链路质量一般，建议观察抖动和SNR变化。"
    else:
        overall = "bad"
        summary = "链路质量较差，建议检查天线姿态、遮挡和干扰。"

    return {
        "overall_level": overall,
        "summary": summary,
        "metrics": metrics,
    }


def get_quality_rules_table() -> List[Dict]:
    rows = []
    for key, cfg in _RULES.items():
        direction = "高为好" if cfg["higher_better"] else "低为好"
        rows.append(
            {
                "metric": key,
                "display": cfg["display"],
                "good_threshold": cfg["good"],
                "warn_threshold": cfg["warn"],
                "direction": direction,
                "tip": cfg["tip"],
            }
        )
    return rows
