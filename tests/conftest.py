import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.nasa import DailySeries

def synth_series(start=date(1981, 11, 1), end=date(2026, 11, 14), const=None, trend_per_year=0.0, seed=1,
                 as_of=None) -> DailySeries:
    n = (end - start).days + 1
    days = np.arange(n)
    if const is not None:
        vals = np.full(n, float(const))
    else:
        doy = np.array([(start + timedelta(days=int(i))).timetuple().tm_yday for i in days])
        rng = np.random.default_rng(seed)
        vals = 5.0 - 16.0 * np.cos(2 * np.pi * (doy - 20) / 365.25) + trend_per_year * days / 365.25 + rng.normal(0, 2.0, n)
    if as_of is not None:
        vals[(as_of - start).days + 1:] = np.nan
    return DailySeries(start, vals, {})

@pytest.fixture
def synth():
    return synth_series
