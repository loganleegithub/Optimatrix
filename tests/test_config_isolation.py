"""Credential migration boundaries, using fixture values and mocked I/O only."""
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch

from app import codex_status
from market import MarketError, PublicClient
from researcher_cli import clean_environment, cli_overrides
from testnet import MarketDataProvider, TestnetError


NOW = 1801699200.0
SENSITIVE_ENV = {
    "DERIBIT_TESTNET_CLIENT_ID": "fixture-testnet-id",
    "DERIBIT_TESTNET_CLIENT_SECRET": "fixture-testnet-secret",
    "GREEKS_LIVE_AUTH_TOKEN": "fixture-greeks-token",
    "GREEKS_LIVE_DATA_API_KEY": "fixture-greeks-key",
    "OPENAI_API_KEY": "fixture-unapproved-api-key",
    "HTTP_PROXY": "https://fixture-proxy.invalid",
    "DERIBIT_BASE_URL": "https://fixture-unapproved-host.invalid",
}


class ConfigIsolationTests(unittest.TestCase):
    def test_codex_status_checks_do_not_inherit_business_credentials(self):
        responses = [Mock(stdout="codex-cli 0.159.2\n", stderr="", returncode=0),
                     Mock(stdout="Logged in using ChatGPT\n", stderr="", returncode=0)]
        with patch.dict(os.environ, {**SENSITIVE_ENV, "PATH": "/usr/bin:/bin"}, clear=True), \
                patch("app.shutil.which", return_value="/fixture/codex"), \
                patch("app.subprocess.run", side_effect=responses) as run:
            status = codex_status()
        self.assertEqual(status["version"], "0.159.2")
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertFalse(set(SENSITIVE_ENV).intersection(call.kwargs["env"]))
            self.assertEqual(call.kwargs["env"]["PATH"], "/usr/bin:/bin")

    def test_research_process_environment_excludes_business_credentials(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
                os.environ, {**SENSITIVE_ENV, "PATH": "/usr/bin:/bin",
                             "HOME": temporary, "LANG": "en_US.UTF-8"}, clear=True):
            before = dict(os.environ)
            environment = clean_environment(Path(temporary))
            self.assertEqual(environment["HOME"], temporary)
            self.assertEqual(environment["PATH"], "/usr/bin:/bin")
            self.assertFalse(set(SENSITIVE_ENV).intersection(environment))
            self.assertEqual(dict(os.environ), before)

    def test_research_sandbox_cannot_read_project_env_or_inherit_shell_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "input"
            workspace.mkdir()
            config = {"reasoning_effort": "high", "service_tier": "default"}
            settings = tomllib.loads("\n".join(cli_overrides(workspace, workspace / "prompt.md", config)))
            permissions = settings["permissions"]["researcher"]
            self.assertEqual(permissions["filesystem"][":root"], "deny")
            self.assertEqual(permissions["filesystem"][str(workspace.resolve())], "read")
            self.assertFalse(permissions["network"]["enabled"])
            self.assertEqual(settings["shell_environment_policy"]["inherit"], "none")
            self.assertEqual(set(settings["shell_environment_policy"]["set"]), {"PATH"})
            self.assertFalse(settings["allow_login_shell"])

    def test_public_clients_never_open_configuration_or_use_environment_credentials(self):
        for client_class, method in ((PublicClient, "get"), (MarketDataProvider, "index")):
            with self.subTest(client=client_class.__name__):
                session = Mock()
                session.headers = {}
                session.get.return_value = Mock(status_code=200, headers={}, json=Mock(return_value={
                    "testnet": False, "usOut": NOW * 1e6, "result": {"index_price": 100000},
                }))
                # Any filesystem read would fail this check, including .env or old JSON.
                with patch.dict(os.environ, SENSITIVE_ENV), \
                        patch("requests.Session", return_value=session), \
                        patch("time.time", return_value=NOW), \
                        patch.object(Path, "open", side_effect=AssertionError("configuration read")), \
                        patch("builtins.open", side_effect=AssertionError("configuration read")), \
                        patch("os.open", side_effect=AssertionError("configuration read")):
                    client = client_class()
                    self.addCleanup(client.close)
                    if method == "get":
                        client.get("get_index_price", index_name="btc_usd")
                        private_call = lambda: client.get("private/buy")
                    else:
                        client.index()
                        private_call = lambda: client._get("private/buy")
                    self.assertFalse(session.trust_env)
                    arguments, keywords = session.get.call_args
                    self.assertEqual(arguments[0], "https://www.deribit.com/api/v2/public/get_index_price")
                    self.assertEqual(keywords["params"], {"index_name": "btc_usd"})
                    self.assertFalse(keywords["allow_redirects"])
                    self.assertNotIn("Authorization", session.headers)
                    self.assertNotIn("auth", keywords)
                    session.get.reset_mock()
                    with self.assertRaises((MarketError, TestnetError)):
                        private_call()
                    session.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
