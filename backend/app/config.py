from __future__ import annotations

import os


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


SIMULATOR_BASE_URL = os.getenv("SIMULATOR_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
SIMULATOR_TIMEOUT_SECONDS = _float("SIMULATOR_TIMEOUT_SECONDS", 4.0)
SNAPSHOT_POLL_SECONDS = _float("SNAPSHOT_POLL_SECONDS", 3.0)
SSE_RECONNECT_SECONDS = _float("SSE_RECONNECT_SECONDS", 1.0)
DEMAND_HISTORY_LIMIT = max(1, min(2000, _int("DEMAND_HISTORY_LIMIT", 200)))
FORECAST_HORIZON_TICKS = max(1, min(96, _int("FORECAST_HORIZON_TICKS", 16)))
CORS_ORIGINS = [
    x.strip()
    for x in os.getenv(
        "CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if x.strip()
]
