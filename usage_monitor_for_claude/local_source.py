"""
Local Data Source
=================

Reads Claude usage from the ``plan-usage-history.json`` file written by the
Claude Desktop app and returns the same dict shape as ``api.fetch_usage()``,
so the rest of the tool works unchanged.

Read-only and network-free: this module never writes a file and never reads
or uses an OAuth token or any credentials.  There is no profile endpoint
locally, so ``fetch_profile()`` always returns ``None``.

Reset times are derived only when the sample history provides a real anchor
and are otherwise omitted - never fabricated (see the project spec, section
7).  Utilization percentages are exact; reset countdowns are approximate.
"""
from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from .i18n import T

__all__ = ['fetch_prepaid_credits', 'fetch_profile', 'fetch_usage']

# Locations of Claude Desktop's usage file, relative to %LOCALAPPDATA%, tried
# in this order.  The MSIX package family name (observed: Claude_pzs8sxrjxfjjc)
# is wildcarded so a different build still resolves.  Desktop 3.x writes to
# Claude-Data; earlier builds wrote under the MSIX package (kept as fallback).
USAGE_FILE_GLOB_DATA = 'Claude-Data/claude_*/plan-usage-history.json'
USAGE_FILE_GLOB = 'Packages/Claude_*/LocalCache/Roaming/Claude/plan-usage-history.json'

# Schema version this parser understands; anything else is treated as drift.
SCHEMA_VERSION = 2

# Added to a session start to estimate the 5-hour reset.
FIVE_HOUR_RESET_SECONDS = 5 * 60 * 60

# Added to an observed weekly drop to estimate its reset.  A named constant,
# not a hardcoded weekday: the true period is per-user and only ever an
# estimate from this file (see the project spec, section 7).
WEEKLY_RESET_SECONDS = 7 * 24 * 60 * 60

# Weekly-drop detection: a downward step of at least WEEKLY_DROP_DELTA landing
# at or below WEEKLY_DROP_CEILING marks a reset.  Catches both a clean drop to
# zero and a reopen at a small post-reset value.
WEEKLY_DROP_DELTA = 25
WEEKLY_DROP_CEILING = 10


def fetch_usage() -> dict[str, Any]:
    """Read the latest usage sample from Claude Desktop's local file."""
    path = _find_usage_file()
    if not path:
        return {'error': T['local_data_unavailable']}

    return _usage_from_file(path)


def fetch_profile() -> None:
    """No account profile is available from the local file."""
    return None


def fetch_prepaid_credits(org_uuid: Any) -> None:
    """No prepaid credit balance is available from the local file."""
    return None


# Helpers


def _find_usage_file() -> str | None:
    """Return the first matching usage file path, or ``None`` if none exists."""
    local_appdata = os.environ.get('LOCALAPPDATA')
    if not local_appdata:
        return None

    for pattern in (USAGE_FILE_GLOB_DATA, USAGE_FILE_GLOB):
        matches = glob.glob(os.path.join(local_appdata, pattern))
        if matches:
            # Deterministic pick if a pattern ever matches more than one package.
            return sorted(matches)[-1]

    return None


def _usage_from_file(path: str) -> dict[str, Any]:
    """Parse the usage file at *path* into the API usage-dict shape.

    Parameters
    ----------
    path : str
        Absolute path to a ``plan-usage-history.json`` file.

    Returns
    -------
    dict
        ``{field: {'utilization': float[, 'resets_at': str]}}`` on success,
        where ``five_hour`` is ``None`` when no session is active, or
        ``{'error': ...}`` when the file is unreadable, malformed, of an
        unknown schema version, or has no usable samples.
    """
    try:
        with open(path, encoding='utf-8-sig') as handle:
            raw = json.loads(handle.read())
    except (OSError, ValueError):
        return {'error': T['local_data_unavailable']}

    if not isinstance(raw, dict) or raw.get('version') != SCHEMA_VERSION:
        return {'error': T['local_data_unavailable']}

    samples = raw.get('samples')
    if not isinstance(samples, list) or not samples:
        return {'error': T['local_data_unavailable']}

    latest = samples[-1]
    usage = latest.get('u') if isinstance(latest, dict) else None
    if not isinstance(usage, dict):
        return {'error': T['local_data_unavailable']}

    return {
        'five_hour': _five_hour_field(samples, usage),
        'seven_day_cowork': _weekly_field(samples, usage, 'cw'),
        'seven_day_oauth_apps': _weekly_field(samples, usage, 'oa'),
    }


def _five_hour_field(samples: list, usage: dict) -> dict[str, Any] | None:
    """Build the ``five_hour`` quota field, or ``None`` when no session is active."""
    pct = usage.get('fh')
    if not isinstance(pct, (int, float)) or isinstance(pct, bool) or pct == 0:
        return None

    field: dict[str, Any] = {'utilization': float(pct)}
    start = _last_session_start(samples)
    if start is not None:
        field['resets_at'] = _reset_iso(start, FIVE_HOUR_RESET_SECONDS)

    return field


def _weekly_field(samples: list, usage: dict, key: str) -> dict[str, Any] | None:
    """Build a weekly quota field from short key *key*, or ``None`` when absent."""
    pct = usage.get(key)
    if not isinstance(pct, (int, float)) or isinstance(pct, bool):
        return None

    field: dict[str, Any] = {'utilization': float(pct)}
    drop = _last_weekly_drop(samples, key)
    if drop is not None:
        field['resets_at'] = _reset_iso(drop, WEEKLY_RESET_SECONDS)

    return field


def _last_session_start(samples: list) -> int | None:
    """Return the timestamp of the most recent ``fh`` 0 -> non-zero transition."""
    start = None
    prev = None
    for sample in samples:
        cur = _metric(sample, 'fh')
        if prev == 0 and cur is not None and cur > 0:
            start = sample.get('t')
        prev = cur

    return start


def _last_weekly_drop(samples: list, key: str) -> int | None:
    """Return the timestamp of the most recent downward step marking a reset."""
    drop = None
    prev = None
    for sample in samples:
        cur = _metric(sample, key)
        if prev is not None and cur is not None and prev - cur >= WEEKLY_DROP_DELTA and cur <= WEEKLY_DROP_CEILING:
            drop = sample.get('t')
        prev = cur

    return drop


def _metric(sample: Any, key: str) -> float | None:
    """Return a numeric usage metric from a sample, or ``None`` if unavailable."""
    if not isinstance(sample, dict):
        return None

    usage = sample.get('u')
    if not isinstance(usage, dict):
        return None

    value = usage.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None

    return value


def _reset_iso(anchor_ms: float, seconds: int) -> str:
    """Return *anchor_ms* (epoch ms) plus *seconds* as a UTC ISO-8601 string."""
    reset = datetime.fromtimestamp(anchor_ms / 1000, tz=timezone.utc) + timedelta(seconds=seconds)
    return reset.replace(microsecond=0).isoformat()
