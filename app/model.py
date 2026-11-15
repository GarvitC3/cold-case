from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

@dataclass(frozen=True)
class IceParams:
    alpha: float = 2.7
    alpha_low: float = 2.2
    alpha_high: float = 3.2
    snow_lambda_cm: float = 12.0
    snow_floor: float = 0.5

    @classmethod
    def from_config(cls, cfg: Dict[str, Dict]) -> "IceParams":
        c = cfg.get("ice", {})
        return cls(
            alpha=float(c.get("alpha_bare", 2.7)),
            alpha_low=float(c.get("alpha_low", 2.2)),
            alpha_high=float(c.get("alpha_high", 3.2)),
            snow_lambda_cm=float(c.get("snow_lambda_cm", 12.0)),
            snow_floor=float(c.get("snow_floor", 0.5)),
        )

DEFAULT_PARAMS = IceParams()

def snow_factor(snow_cm: Optional[float], p: IceParams = DEFAULT_PARAMS) -> float:
    if snow_cm is None or not math.isfinite(snow_cm) or snow_cm <= 0:
        return 1.0
    return p.snow_floor + (1.0 - p.snow_floor) * math.exp(-snow_cm / p.snow_lambda_cm)

def ice_cm(fdd, snow_cm: Optional[float] = 0.0, alpha: Optional[float] = None, p: IceParams = DEFAULT_PARAMS):
    a = p.alpha if alpha is None else alpha
    f = snow_factor(snow_cm, p)
    if isinstance(fdd, np.ndarray):
        return a * f * np.sqrt(np.maximum(fdd, 0.0))
    if fdd is None or not math.isfinite(fdd):
        return float("nan")
    return a * f * math.sqrt(max(fdd, 0.0))

def ice_estimate(fdd: Optional[float], snow_cm: Optional[float] = 0.0, p: IceParams = DEFAULT_PARAMS) -> Dict[str, float]:
    f = snow_factor(snow_cm, p)
    if fdd is None or not math.isfinite(fdd):
        return {"cm": float("nan"), "lo": float("nan"), "hi": float("nan"), "factor": f}
    return {
        "cm": ice_cm(fdd, snow_cm, p.alpha, p),
        "lo": ice_cm(fdd, snow_cm, p.alpha_low, p),
        "hi": ice_cm(fdd, snow_cm, p.alpha_high, p),
        "factor": f,
    }

def fdd_for_ice(cm: float, snow_cm: Optional[float] = 0.0, p: IceParams = DEFAULT_PARAMS) -> float:
    a = p.alpha * snow_factor(snow_cm, p)
    return (cm / a) ** 2 if a > 0 else float("inf")
