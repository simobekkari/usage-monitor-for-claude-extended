"""
Local Source Location Tests
===========================

Unit tests for the Claude-Data file location and the legacy fallback in
local_source.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from usage_monitor_for_claude.i18n import T
from usage_monitor_for_claude.local_source import fetch_usage

MINUTE_MS = 60 * 1000
BASE_MS = 1_790_000_000_000
NEW_PATH = ('Claude-Data', 'claude_pzs8sxrjxfjjc')
OLD_PATH = ('Packages', 'Claude_pzs8sxrjxfjjc', 'LocalCache', 'Roaming', 'Claude')


def _write(root: Path, parts: tuple[str, ...], samples: list[dict]) -> None:
    """Write a usage file under *root* / *parts*."""
    folder = root.joinpath(*parts)
    folder.mkdir(parents=True)
    (folder / 'plan-usage-history.json').write_text(json.dumps({'version': 2, 'samples': samples}), encoding='utf-8')


def _sample(minutes: float, **usage: int) -> dict:
    """Build a sample *minutes* after BASE_MS."""
    return {'t': BASE_MS + int(minutes * MINUTE_MS), 'org': 'org', 'u': usage}


class TestFileLocation(unittest.TestCase):
    """Tests for resolving the usage file."""

    def _fetch(self, root: Path) -> dict:
        with patch.dict('os.environ', {'LOCALAPPDATA': str(root)}):
            return fetch_usage()

    def test_claude_data_location_is_read(self):
        """A file under Claude-Data is found."""
        with TemporaryDirectory() as tmp:
            _write(Path(tmp), NEW_PATH, [_sample(0, fh=40, oa=0, cw=13)])
            self.assertEqual(self._fetch(Path(tmp))['seven_day_cowork']['utilization'], 13.0)

    def test_legacy_location_is_fallback(self):
        """The MSIX package location is used when Claude-Data has no file."""
        with TemporaryDirectory() as tmp:
            _write(Path(tmp), OLD_PATH, [_sample(0, fh=40, oa=0, cw=7)])
            self.assertEqual(self._fetch(Path(tmp))['seven_day_cowork']['utilization'], 7.0)

    def test_claude_data_wins_over_legacy(self):
        """Claude-Data takes precedence when both files exist."""
        with TemporaryDirectory() as tmp:
            _write(Path(tmp), NEW_PATH, [_sample(0, fh=40, oa=0, cw=13)])
            _write(Path(tmp), OLD_PATH, [_sample(0, fh=40, oa=0, cw=99)])
            self.assertEqual(self._fetch(Path(tmp))['seven_day_cowork']['utilization'], 13.0)

    def test_no_file_returns_error(self):
        """No file at either location returns the unavailable error."""
        with TemporaryDirectory() as tmp:
            self.assertEqual(self._fetch(Path(tmp)), {'error': T['local_data_unavailable']})

    def test_unknown_usage_key_is_ignored(self):
        """An unmapped key such as ``xu`` does not break parsing or leak into the result."""
        with TemporaryDirectory() as tmp:
            _write(Path(tmp), NEW_PATH, [_sample(0, fh=67, oa=0, cw=13, xu=100)])
            result = self._fetch(Path(tmp))
            self.assertEqual(result['five_hour']['utilization'], 67.0)
            self.assertNotIn('xu', result)


if __name__ == '__main__':
    unittest.main()
