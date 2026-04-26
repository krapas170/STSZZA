from __future__ import annotations

from typing import Optional


def ms_to_hhmm(ms: int | None) -> str:
    """Convert milliseconds since midnight to HH:MM string."""
    if ms is None:
        return "--:--"
    total_sec = ms // 1000
    h = (total_sec // 3600) % 24
    m = (total_sec % 3600) // 60
    return f"{h:02d}:{m:02d}"


def hhmm_to_ms(time_str: str | None) -> Optional[int]:
    """
    Convert a HH:MM string (as sent by STS in zugfahrplan) to
    milliseconds since midnight.  Returns None for empty / invalid input.
    """
    if not time_str:
        return None
    try:
        h, m = time_str.split(":")
        return (int(h) * 3600 + int(m) * 60) * 1000
    except (ValueError, AttributeError):
        return None


def delay_str(minutes: int) -> str:
    """Human-readable delay string, empty if on time."""
    if minutes <= 0:
        return ""
    return f"+{minutes} Min"
