from __future__ import annotations


def ms_to_hhmm(ms: int | None) -> str:
    """Convert milliseconds since midnight to HH:MM string."""
    if ms is None:
        return "--:--"
    total_sec = ms // 1000
    h = (total_sec // 3600) % 24
    m = (total_sec % 3600) // 60
    return f"{h:02d}:{m:02d}"


def delay_str(minutes: int) -> str:
    """Human-readable delay string, empty if on time."""
    if minutes <= 0:
        return ""
    return f"+{minutes} Min"
