"""
usage_source Tests
==================

Unit tests for the data-source dispatcher: routing per ``settings.DATA_SOURCE``
and the ``auto`` fallback, which keys on token presence alone.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from usage_monitor_for_claude import usage_source

USAGE_API = {'source': 'api'}
USAGE_LOCAL = {'source': 'local'}
PROFILE_API = {'account': {'uuid': 'api'}}
PREPAID_API = {'amount': 5597, 'currency': 'EUR'}
ORG_UUID = '00000000-0000-0000-0000-000000000000'


@patch('usage_monitor_for_claude.usage_source.local_source')
@patch('usage_monitor_for_claude.usage_source.api')
class TestFetchUsageRouting(unittest.TestCase):
    """fetch_usage() routes to the source named by DATA_SOURCE."""

    @patch('usage_monitor_for_claude.settings.DATA_SOURCE', 'api')
    def test_api_mode_calls_api(self, mock_api, mock_local):
        mock_api.fetch_usage.return_value = USAGE_API
        self.assertEqual(usage_source.fetch_usage(), USAGE_API)
        mock_local.fetch_usage.assert_not_called()
        mock_api.read_access_token.assert_not_called()

    @patch('usage_monitor_for_claude.settings.DATA_SOURCE', 'local')
    def test_local_mode_calls_local(self, mock_api, mock_local):
        mock_local.fetch_usage.return_value = USAGE_LOCAL
        self.assertEqual(usage_source.fetch_usage(), USAGE_LOCAL)
        mock_api.fetch_usage.assert_not_called()

    @patch('usage_monitor_for_claude.settings.DATA_SOURCE', 'auto')
    def test_auto_without_token_falls_back_to_local(self, mock_api, mock_local):
        mock_api.read_access_token.return_value = None
        mock_local.fetch_usage.return_value = USAGE_LOCAL
        self.assertEqual(usage_source.fetch_usage(), USAGE_LOCAL)
        mock_api.fetch_usage.assert_not_called()

    @patch('usage_monitor_for_claude.settings.DATA_SOURCE', 'auto')
    def test_auto_with_token_uses_api(self, mock_api, mock_local):
        mock_api.read_access_token.return_value = 'token'
        mock_api.fetch_usage.return_value = USAGE_API
        self.assertEqual(usage_source.fetch_usage(), USAGE_API)
        mock_local.fetch_usage.assert_not_called()

    @patch('usage_monitor_for_claude.settings.DATA_SOURCE', 'auto')
    def test_auto_with_token_passes_api_errors_through(self, mock_api, mock_local):
        """A present token means API errors (auth_error, rate_limited) are returned unchanged."""
        mock_api.read_access_token.return_value = 'token'
        for err in ({'error': 'x', 'auth_error': True}, {'error': 'y', 'rate_limited': True}):
            with self.subTest(err=err):
                mock_api.fetch_usage.return_value = err
                self.assertEqual(usage_source.fetch_usage(), err)
                mock_local.fetch_usage.assert_not_called()


@patch('usage_monitor_for_claude.usage_source.local_source')
@patch('usage_monitor_for_claude.usage_source.api')
class TestFetchProfileRouting(unittest.TestCase):
    """fetch_profile() follows the same routing as fetch_usage()."""

    @patch('usage_monitor_for_claude.settings.DATA_SOURCE', 'api')
    def test_api_mode_calls_api(self, mock_api, mock_local):
        mock_api.fetch_profile.return_value = PROFILE_API
        self.assertEqual(usage_source.fetch_profile(), PROFILE_API)
        mock_local.fetch_profile.assert_not_called()

    @patch('usage_monitor_for_claude.settings.DATA_SOURCE', 'local')
    def test_local_mode_calls_local(self, mock_api, mock_local):
        mock_local.fetch_profile.return_value = None
        self.assertIsNone(usage_source.fetch_profile())
        mock_api.fetch_profile.assert_not_called()

    @patch('usage_monitor_for_claude.settings.DATA_SOURCE', 'auto')
    def test_auto_without_token_calls_local(self, mock_api, mock_local):
        mock_api.read_access_token.return_value = None
        mock_local.fetch_profile.return_value = None
        self.assertIsNone(usage_source.fetch_profile())
        mock_api.fetch_profile.assert_not_called()

    @patch('usage_monitor_for_claude.settings.DATA_SOURCE', 'auto')
    def test_auto_with_token_calls_api(self, mock_api, mock_local):
        mock_api.read_access_token.return_value = 'token'
        mock_api.fetch_profile.return_value = PROFILE_API
        self.assertEqual(usage_source.fetch_profile(), PROFILE_API)
        mock_local.fetch_profile.assert_not_called()


@patch('usage_monitor_for_claude.usage_source.local_source')
@patch('usage_monitor_for_claude.usage_source.api')
class TestFetchPrepaidCreditsRouting(unittest.TestCase):
    """fetch_prepaid_credits() follows the same routing as fetch_usage()."""

    @patch('usage_monitor_for_claude.settings.DATA_SOURCE', 'api')
    def test_api_mode_calls_api(self, mock_api, mock_local):
        mock_api.fetch_prepaid_credits.return_value = PREPAID_API
        self.assertEqual(usage_source.fetch_prepaid_credits(ORG_UUID), PREPAID_API)
        mock_api.fetch_prepaid_credits.assert_called_once_with(ORG_UUID)
        mock_local.fetch_prepaid_credits.assert_not_called()
        mock_api.read_access_token.assert_not_called()

    @patch('usage_monitor_for_claude.settings.DATA_SOURCE', 'local')
    def test_local_mode_calls_local(self, mock_api, mock_local):
        mock_local.fetch_prepaid_credits.return_value = None
        self.assertIsNone(usage_source.fetch_prepaid_credits(ORG_UUID))
        mock_local.fetch_prepaid_credits.assert_called_once_with(ORG_UUID)
        mock_api.fetch_prepaid_credits.assert_not_called()

    @patch('usage_monitor_for_claude.settings.DATA_SOURCE', 'auto')
    def test_auto_without_token_calls_local(self, mock_api, mock_local):
        mock_api.read_access_token.return_value = None
        mock_local.fetch_prepaid_credits.return_value = None
        self.assertIsNone(usage_source.fetch_prepaid_credits(ORG_UUID))
        mock_api.fetch_prepaid_credits.assert_not_called()

    @patch('usage_monitor_for_claude.settings.DATA_SOURCE', 'auto')
    def test_auto_with_token_calls_api(self, mock_api, mock_local):
        mock_api.read_access_token.return_value = 'token'
        mock_api.fetch_prepaid_credits.return_value = PREPAID_API
        self.assertEqual(usage_source.fetch_prepaid_credits(ORG_UUID), PREPAID_API)
        mock_local.fetch_prepaid_credits.assert_not_called()

    @patch('usage_monitor_for_claude.settings.DATA_SOURCE', 'auto')
    def test_auto_with_token_passes_unavailable_through(self, mock_api, mock_local):
        """An unavailable API balance stays None - auto never substitutes the local side for it."""
        mock_api.read_access_token.return_value = 'token'
        mock_api.fetch_prepaid_credits.return_value = None
        self.assertIsNone(usage_source.fetch_prepaid_credits(ORG_UUID))
        mock_local.fetch_prepaid_credits.assert_not_called()


class TestLocalPrepaidCredits(unittest.TestCase):
    """The real local side (unmocked) yields no balance and sends no request."""

    @patch('usage_monitor_for_claude.settings.DATA_SOURCE', 'local')
    def test_local_mode_returns_none_without_network(self):
        with patch('usage_monitor_for_claude.api.fetch_prepaid_credits') as mock_fetch,                 patch('usage_monitor_for_claude.api.read_access_token') as mock_token:
            self.assertIsNone(usage_source.fetch_prepaid_credits(ORG_UUID))
        mock_fetch.assert_not_called()
        mock_token.assert_not_called()


if __name__ == '__main__':
    unittest.main()
