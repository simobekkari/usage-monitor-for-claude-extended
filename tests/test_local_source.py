"""
local_source Tests
==================

Unit tests for the local ``plan-usage-history.json`` reader: field mapping,
reset estimation, the schema-version guard, and the missing/empty/malformed
paths.

Reset estimation is deterministic - it derives times from sample timestamps,
not the wall clock - so these tests assert exact ISO-8601 strings without
patching ``datetime``.
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from usage_monitor_for_claude import local_source

ORG = '00000000-0000-0000-0000-000000000000'

# Two fixed anchors and their expected derived resets (see _reset_iso).
SESSION_START_MS = 1785000000000        # 2026-07-25T17:20:00+00:00
SESSION_RESET_ISO = '2026-07-25T22:20:00+00:00'   # + 5 hours
WEEKLY_DROP_MS = 1785100000000          # 2026-07-26T21:06:40+00:00
WEEKLY_RESET_ISO = '2026-08-02T21:06:40+00:00'    # + 7 days


def _sample(t: int, fh: float, cw: float, oa: float) -> dict:
    """Build one history sample in the file's schema."""
    return {'t': t, 'org': ORG, 'u': {'fh': fh, 'cw': cw, 'oa': oa}}


def _doc(samples: list, version: int = 2) -> dict:
    """Wrap samples in the top-level document shape."""
    return {'version': version, 'samples': samples}


def _parse(doc) -> dict:
    """Write *doc* (dict -> JSON, or raw str) to a temp file and parse it."""
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / 'plan-usage-history.json'
        path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding='utf-8')
        return local_source._usage_from_file(str(path))


@patch('usage_monitor_for_claude.local_source.T', {'local_data_unavailable': 'ERR'})
class TestFieldMapping(unittest.TestCase):
    """Field mapping and reset derivation from a healthy history."""

    def test_maps_all_three_fields_with_resets(self):
        """fh/cw/oa map to the API field names; session and weekly resets derive."""
        samples = [
            _sample(SESSION_START_MS - 300000, 0, 55, 0),
            _sample(SESSION_START_MS, 5, 55, 0),               # fh 0 -> non-zero (session start)
            _sample(SESSION_START_MS + 300000, 12, 55, 0),
            _sample(WEEKLY_DROP_MS - 300000, 20, 55, 0),
            _sample(WEEKLY_DROP_MS, 30, 0, 0),                 # cw 55 -> 0 (weekly reset)
            _sample(WEEKLY_DROP_MS + 300000, 42, 3, 0),        # latest
        ]
        result = _parse(_doc(samples))
        self.assertEqual(result['five_hour'], {'utilization': 42.0, 'resets_at': SESSION_RESET_ISO})
        self.assertEqual(result['seven_day_cowork'], {'utilization': 3.0, 'resets_at': WEEKLY_RESET_ISO})
        self.assertEqual(result['seven_day_oauth_apps'], {'utilization': 0.0})

    def test_utilization_is_float(self):
        """Whole-number percentages are emitted as floats (API parity)."""
        result = _parse(_doc([_sample(SESSION_START_MS, 62, 100, 0)]))
        self.assertIsInstance(result['seven_day_cowork']['utilization'], float)
        self.assertEqual(result['seven_day_cowork']['utilization'], 100.0)


@patch('usage_monitor_for_claude.local_source.T', {'local_data_unavailable': 'ERR'})
class TestFiveHour(unittest.TestCase):
    """five_hour rules: inactive session, and mid-session start."""

    def test_zero_session_is_none(self):
        """fh == 0 emits the field as None (no active session)."""
        result = _parse(_doc([_sample(SESSION_START_MS, 0, 20, 0)]))
        self.assertIsNone(result['five_hour'])

    def test_boolean_fh_is_not_treated_as_number(self):
        """A boolean fh is rejected, not coerced to 1."""
        doc = _doc([{'t': SESSION_START_MS, 'org': ORG, 'u': {'fh': True, 'cw': 20, 'oa': 0}}])
        self.assertIsNone(_parse(doc)['five_hour'])

    def test_active_session_without_start_has_no_reset(self):
        """fh > 0 with no 0 -> non-zero transition emits utilization, no resets_at."""
        samples = [_sample(SESSION_START_MS, 5, 20, 0), _sample(SESSION_START_MS + 300000, 10, 20, 0)]
        five_hour = _parse(_doc(samples))['five_hour']
        self.assertEqual(five_hour['utilization'], 10.0)
        self.assertNotIn('resets_at', five_hour)


@patch('usage_monitor_for_claude.local_source.T', {'local_data_unavailable': 'ERR'})
class TestWeeklyReset(unittest.TestCase):
    """Weekly drop detection."""

    def test_no_drop_has_no_reset(self):
        """A monotonically rising weekly metric yields utilization without resets_at."""
        samples = [_sample(SESSION_START_MS, 0, 10, 0), _sample(SESSION_START_MS + 300000, 0, 30, 0)]
        cowork = _parse(_doc(samples))['seven_day_cowork']
        self.assertEqual(cowork['utilization'], 30.0)
        self.assertNotIn('resets_at', cowork)

    def test_reopen_at_small_value_counts_as_drop(self):
        """A step down of >= delta landing <= ceiling (e.g. 60 -> 5) is a reset."""
        samples = [_sample(SESSION_START_MS, 0, 60, 0), _sample(WEEKLY_DROP_MS, 0, 5, 0)]
        cowork = _parse(_doc(samples))['seven_day_cowork']
        self.assertEqual(cowork['resets_at'], WEEKLY_RESET_ISO)

    def test_small_dip_is_not_a_drop(self):
        """A small decrease (40 -> 30) below the delta threshold is ignored."""
        samples = [_sample(SESSION_START_MS, 0, 40, 0), _sample(SESSION_START_MS + 300000, 0, 30, 0)]
        self.assertNotIn('resets_at', _parse(_doc(samples))['seven_day_cowork'])

    def test_oauth_apps_uses_same_logic(self):
        """oa maps to seven_day_oauth_apps and derives a reset from its own drop."""
        samples = [_sample(SESSION_START_MS, 0, 0, 50), _sample(WEEKLY_DROP_MS, 0, 0, 0)]
        oauth = _parse(_doc(samples))['seven_day_oauth_apps']
        self.assertEqual(oauth['utilization'], 0.0)
        self.assertEqual(oauth['resets_at'], WEEKLY_RESET_ISO)


@patch('usage_monitor_for_claude.local_source.T', {'local_data_unavailable': 'ERR'})
class TestGuards(unittest.TestCase):
    """Schema-version guard and malformed / empty inputs."""

    def test_wrong_version_is_error(self):
        for version in (1, 3):
            with self.subTest(version=version):
                self.assertEqual(_parse(_doc([_sample(SESSION_START_MS, 5, 5, 0)], version=version)), {'error': 'ERR'})

    def test_missing_version_is_error(self):
        self.assertEqual(_parse({'samples': [_sample(SESSION_START_MS, 5, 5, 0)]}), {'error': 'ERR'})

    def test_non_dict_top_level_is_error(self):
        self.assertEqual(_parse([1, 2, 3]), {'error': 'ERR'})

    def test_empty_samples_is_error(self):
        self.assertEqual(_parse(_doc([])), {'error': 'ERR'})

    def test_samples_missing_is_error(self):
        self.assertEqual(_parse({'version': 2}), {'error': 'ERR'})

    def test_samples_not_a_list_is_error(self):
        self.assertEqual(_parse({'version': 2, 'samples': {}}), {'error': 'ERR'})

    def test_malformed_json_is_error(self):
        self.assertEqual(_parse('{ not valid json'), {'error': 'ERR'})

    def test_latest_missing_usage_is_error(self):
        self.assertEqual(_parse({'version': 2, 'samples': [{'t': SESSION_START_MS, 'org': ORG}]}), {'error': 'ERR'})

    def test_latest_usage_not_dict_is_error(self):
        self.assertEqual(_parse({'version': 2, 'samples': [{'t': SESSION_START_MS, 'org': ORG, 'u': 5}]}), {'error': 'ERR'})


@patch('usage_monitor_for_claude.local_source.T', {'local_data_unavailable': 'ERR'})
class TestFileDiscovery(unittest.TestCase):
    """_find_usage_file() glob and fetch_usage() end-to-end."""

    def test_no_localappdata_returns_none(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(local_source._find_usage_file())

    def test_glob_finds_file_under_localappdata(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / 'Packages' / 'Claude_pzs8sxrjxfjjc' / 'LocalCache' / 'Roaming' / 'Claude'
            target.mkdir(parents=True)
            usage_file = target / 'plan-usage-history.json'
            usage_file.write_text('{}', encoding='utf-8')
            with patch.dict(os.environ, {'LOCALAPPDATA': tmp}, clear=True):
                self.assertEqual(local_source._find_usage_file(), str(usage_file))

    def test_no_match_returns_none(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {'LOCALAPPDATA': tmp}, clear=True):
            self.assertIsNone(local_source._find_usage_file())

    def test_fetch_usage_no_file_is_error(self):
        with patch.object(local_source, '_find_usage_file', return_value=None):
            self.assertEqual(local_source.fetch_usage(), {'error': 'ERR'})

    def test_fetch_usage_reads_found_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'plan-usage-history.json'
            path.write_text(json.dumps(_doc([_sample(SESSION_START_MS, 0, 25, 0)])), encoding='utf-8')
            with patch.object(local_source, '_find_usage_file', return_value=str(path)):
                self.assertEqual(local_source.fetch_usage()['seven_day_cowork'], {'utilization': 25.0})


class TestProfile(unittest.TestCase):
    """No profile is available locally."""

    def test_fetch_profile_is_none(self):
        self.assertIsNone(local_source.fetch_profile())


if __name__ == '__main__':
    unittest.main()
