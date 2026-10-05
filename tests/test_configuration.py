"""Local credential parsing and least-field access; fixtures only, no network."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backtest import BacktestError, BacktestService, load_config
from configuration import ConfigurationError, GREEKS_FIELDS, MAX_CONFIG_BYTES, TESTNET_FIELDS, read_secrets


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / ".env"

    def write(self, content):
        self.path.write_text(content, encoding="utf-8")
        self.path.chmod(0o600)

    def test_literal_quotes_comments_bearer_and_field_isolation(self):
        self.write("# Shared file, separately consumed\n"
                   "GREEKS_LIVE_AUTH_TOKEN=Bearer fixture-token # trailing comment\n"
                   "GREEKS_LIVE_DATA_API_KEY='fixture#data=key'\n"
                   'DERIBIT_TESTNET_CLIENT_ID="fixture-id" # comment\n'
                   "DERIBIT_TESTNET_CLIENT_SECRET=fixture-secret\n"
                   "UNRELATED_FIELD=fixture-private-other\n")
        self.assertEqual(load_config(self.root), {"GREEKS_LIVE_AUTH_TOKEN": "Bearer fixture-token",
                                                  "GREEKS_LIVE_DATA_API_KEY": "fixture#data=key"})
        self.assertEqual(read_secrets(self.root, TESTNET_FIELDS),
                         {"DERIBIT_TESTNET_CLIENT_ID": "fixture-id", "DERIBIT_TESTNET_CLIENT_SECRET": "fixture-secret"})
        with self.assertRaises(ConfigurationError):
            read_secrets(self.root, {"UNRELATED_FIELD"})

    def test_values_never_expand_or_mutate_process_environment(self):
        self.write('GREEKS_LIVE_AUTH_TOKEN="${HOME} $(touch marker) `whoami`"\n')
        before = dict(os.environ)
        with patch("os.system", side_effect=AssertionError("must not evaluate")):
            self.assertEqual(load_config(self.root), {"GREEKS_LIVE_AUTH_TOKEN": "${HOME} $(touch marker) `whoami`"})
        self.assertEqual(dict(os.environ), before)
        self.assertFalse((self.root / "marker").exists())

    def test_missing_and_empty_fields_preserve_unconfigured_backtest(self):
        with patch.dict(os.environ, {"GREEKS_LIVE_AUTH_TOKEN": "environment-only-secret"}):
            self.assertEqual(load_config(self.root), {})
            service = BacktestService(self.root)
            self.assertFalse(service.configuration()["configured"])
        self.write('GREEKS_LIVE_AUTH_TOKEN=""\nGREEKS_LIVE_DATA_API_KEY= # empty\n')
        self.assertEqual(load_config(self.root), {})
        self.write("GREEKS_LIVE_DATA_API_KEY=fixture-data-only\n")
        self.assertFalse(service.configuration()["configured"])
        self.assertIn("CSV Data API Key", service.configuration()["reason"])

    def test_rejects_duplicate_or_nonstandard_lines_without_echoing_secrets(self):
        cases = (
            "GREEKS_LIVE_AUTH_TOKEN=fixture-secret\nGREEKS_LIVE_AUTH_TOKEN=other-secret\n",
            "UNRELATED=fixture-secret\nUNRELATED=other-secret\n",
            "Client Secret: fixture-secret\n",
            "export GREEKS_LIVE_AUTH_TOKEN=fixture-secret\n",
            'GREEKS_LIVE_AUTH_TOKEN="fixture-secret\n',
            'GREEKS_LIVE_AUTH_TOKEN="fixture-secret"junk\n',
            "GREEKS_LIVE_AUTH_TOKEN=fixture-secret\x00\n",
        )
        messages = set()
        for content in cases:
            with self.subTest(case=cases.index(content)):
                self.write(content)
                with self.assertRaises(ConfigurationError) as caught:
                    load_config(self.root)
                messages.add(str(caught.exception))
                self.assertNotIn("fixture-secret", str(caught.exception))
                self.assertNotIn("other-secret", str(caught.exception))
                service = BacktestService(self.root)
                self.assertFalse(service.configuration()["configured"])
                with self.assertRaises(BacktestError):
                    service._client()
        self.assertEqual(len(messages), 1)

    def test_requires_0600_owner_regular_file_without_links(self):
        self.write("GREEKS_LIVE_AUTH_TOKEN=fixture-secret\n")
        for mode in (0o644, 0o400, 0o660):
            self.path.chmod(mode)
            with self.assertRaises(ConfigurationError):
                load_config(self.root)
        self.path.chmod(0o600)
        with patch("configuration.os.getuid", return_value=os.getuid() + 1):
            with self.assertRaises(ConfigurationError):
                load_config(self.root)
        other = self.root / "other-config"
        os.link(self.path, other)
        with self.assertRaises(ConfigurationError):
            load_config(self.root)
        self.path.unlink()
        self.path.symlink_to(other)
        with self.assertRaises(ConfigurationError):
            load_config(self.root)
        self.path.unlink()
        self.path.mkdir(mode=0o700)
        with self.assertRaises(ConfigurationError):
            load_config(self.root)

    def test_size_encoding_and_fifo_fail_closed(self):
        self.write("#" + "x" * MAX_CONFIG_BYTES)
        with self.assertRaises(ConfigurationError):
            load_config(self.root)
        self.path.write_bytes(b"GREEKS_LIVE_AUTH_TOKEN=\xff\n")
        with self.assertRaises(ConfigurationError):
            load_config(self.root)
        self.path.unlink()
        os.mkfifo(self.path, 0o600)
        with self.assertRaises(ConfigurationError):
            load_config(self.root)


if __name__ == "__main__":
    unittest.main()
