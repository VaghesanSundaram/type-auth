import numpy as np
from scipy.stats import pearsonr
from typing import Tuple, List

CORRELATION_THRESHOLD = 0.8
MSE_THRESHOLD = 0.01
KEYPHRASE = "the quick brown fox jumped over the lazy dog"


def validate_timings(profile: np.ndarray, attempt: np.ndarray) -> Tuple[bool, float, float]:
    """returns (success, correlation, mse)."""
    if len(profile) != len(attempt):
        return False, 0.0, float('inf')

    try:
        correlation, _ = pearsonr(profile, attempt)
    except Exception:
        correlation = 0.0

    mse = float(np.mean((profile - attempt) ** 2))
    success = bool(correlation > CORRELATION_THRESHOLD and mse < MSE_THRESHOLD)
    return success, float(correlation), float(mse)


def compute_mean_profile(timing_samples: List[List[float]]) -> np.ndarray:
    return np.mean(timing_samples, axis=0)


def get_expected_timing_length() -> int:
    return len(KEYPHRASE) - 1
