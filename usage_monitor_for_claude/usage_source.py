"""
Usage Source
============

Thin dispatcher that routes usage, profile and prepaid-credit fetches to a
data source based on ``settings.DATA_SOURCE``:

- ``api``   - the Anthropic OAuth usage API (default; unchanged behavior).
- ``local`` - Claude Desktop's local ``plan-usage-history.json`` file.
- ``auto``  - the API when a token is present, otherwise the local file.

For ``auto`` the fallback is decided on token presence alone
(``api.read_access_token() is None``).  When a token exists the API result is
returned unchanged - including ``auth_error``/``rate_limited``/transient
errors - so the cache's token-refresh and 429-backoff paths keep working.

Keeping this routing here (rather than in the cache) leaves the cache a single,
source-agnostic caller.
"""
from __future__ import annotations

from typing import Any

from . import api
from . import local_source
from . import settings


def fetch_usage() -> dict[str, Any]:
    """Fetch usage data from the configured data source."""
    if _use_local():
        return local_source.fetch_usage()

    return api.fetch_usage()


def fetch_profile() -> dict[str, Any] | None:
    """Fetch the account profile from the configured data source."""
    if _use_local():
        return local_source.fetch_profile()

    return api.fetch_profile()


def fetch_prepaid_credits(org_uuid: Any) -> dict[str, Any] | None:
    """Fetch the prepaid credit balance from the configured data source.

    The local file carries no balance, so the local side returns None and
    local mode sends no request at all.

    Parameters
    ----------
    org_uuid : Any
        Organization uuid from the profile, validated by ``api`` before use.
    """
    if _use_local():
        return local_source.fetch_prepaid_credits(org_uuid)

    return api.fetch_prepaid_credits(org_uuid)


def _use_local() -> bool:
    """Return True when the local source should serve this request."""
    if settings.DATA_SOURCE == 'local':
        return True

    return settings.DATA_SOURCE == 'auto' and api.read_access_token() is None
