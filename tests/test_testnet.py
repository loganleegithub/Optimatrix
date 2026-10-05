"""Offline boundary and reconciliation tests. No network or real credentials."""
import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from testnet import AUTH_SCOPE, DeribitTestnetClient, MarketDataProvider, TestnetError, fee_rate


NOW = 1801699200.0


def instrument(**updates):
    value = {"instrument_name": "BTC-TEST-C", "kind": "option", "option_type": "call",
             "instrument_type": "reversed", "base_currency": "BTC", "quote_currency": "BTC",
             "settlement_currency": "BTC", "counter_currency": "USD", "price_index": "btc_usd",
             "state": "open", "is_active": True, "contract_size": 1,
             "expiration_timestamp": (NOW + 30 * 86400) * 1000,
             "min_trade_amount": 0.1, "tick_size": 0.0001,
             "tick_size_steps": [{"above_price": 0.005, "tick_size": 0.0005}],
             "maker_commission": 0.0003, "taker_commission": 0.0003}
    value.update(updates)
    return value


def summary(**updates):
    value = {"id": 42, "currency": "BTC", "equity": 2, "available_funds": 1.5,
             "cross_collateral_enabled": False}
    value.update(updates)
    return value


class ConnectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "local").mkdir()
        self.path = self.root / ".env"
        self.path.write_text("DERIBIT_TESTNET_CLIENT_ID=fixture-id\nDERIBIT_TESTNET_CLIENT_SECRET=fixture-secret\n")
        self.path.chmod(0o600)
        self.clock = patch("testnet.time.time", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.session = Mock()
        self.session.headers = {}
        self.session_patch = patch("testnet.requests.Session", return_value=self.session)
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)
        self.client = DeribitTestnetClient(self.root)
        self.client._token = "fixture-token"
        self.client._token_until = NOW + 3600
        self.client._account_auth_generation = self.client._auth_generation
        self.client._instruments = {"BTC-TEST-C": instrument()}
        self.client._instruments_at = NOW

    def reply(self, result=None, *, testnet=True, status=200, error=None, age=0):
        def handle(url, **kwargs):
            payload = {"jsonrpc": "2.0", "id": kwargs.get("json", {}).get("id"),
                       "testnet": testnet, "usOut": (NOW - age) * 1e6, "result": result}
            if error is not None:
                payload["error"] = error
            return Mock(status_code=status, json=Mock(return_value=payload))
        return handle

    def test_fixed_hosts_no_proxy_no_redirect_and_zero_retries(self):
        self.session.post.side_effect = self.reply([])
        self.client.get_instruments()
        args, kwargs = self.session.post.call_args
        self.assertEqual(args[0], "https://test.deribit.com/api/v2/public/get_instruments")
        self.assertFalse(kwargs["allow_redirects"])
        self.assertFalse(self.session.trust_env)
        adapter = self.session.mount.call_args.args[1]
        self.assertEqual(adapter.max_retries.total, 0)
        with self.assertRaises(TestnetError):
            self.client._rpc("private/withdraw", {})
        with self.assertRaises(TestnetError):
            self.client._rpc("https://www.deribit.com/api/v2/private/buy", {})
        provider = MarketDataProvider()
        with self.assertRaises(TestnetError):
            provider._get("private/buy")
        self.session.get.assert_not_called()

    def test_credentials_require_private_regular_owned_file(self):
        self.assertTrue(self.client.configured)
        self.path.chmod(0o644)
        self.assertFalse(self.client.configured)
        with self.assertRaises(TestnetError):
            self.client.authenticate()
        self.path.chmod(0o600)
        other = self.path.with_name("elsewhere.json")
        self.path.rename(other)
        self.path.symlink_to(other)
        self.assertFalse(self.client.configured)
        with self.assertRaises(TestnetError):
            self.client.authenticate()
        self.session.post.assert_not_called()

    def test_configuration_uses_only_complete_dotenv_without_json_or_environment_fallback(self):
        self.path.unlink()
        (self.root / "local" / "testnet.credentials.json").write_text(
            json.dumps({"client_id": "legacy-id", "client_secret": "legacy-secret"}))
        with patch.dict(os.environ, {"DERIBIT_TESTNET_CLIENT_ID": "environment-id",
                                     "DERIBIT_TESTNET_CLIENT_SECRET": "environment-secret"}):
            self.assertFalse(self.client.configured)
            with self.assertRaises(TestnetError) as caught:
                self.client.authenticate()
            self.assertEqual(caught.exception.status, "credentials_missing")
        self.path.write_text("DERIBIT_TESTNET_CLIENT_ID=partial-id\n")
        self.path.chmod(0o600)
        self.assertFalse(self.client.configured)
        self.session.post.assert_not_called()

    def test_configuration_does_not_return_other_business_credentials(self):
        with self.path.open("a") as handle:
            handle.write("GREEKS_LIVE_AUTH_TOKEN=fixture-other-business-secret\n")
        self.assertEqual(self.client._credentials(), {"client_id": "fixture-id", "client_secret": "fixture-secret"})
        self.assertTrue(self.client.configured)
        self.session.post.assert_not_called()

    def test_auth_scope_narrowing_and_safe_metadata(self):
        self.session.post.side_effect = self.reply({"access_token": "fixture-secret-token",
            "refresh_token": "fixture-refresh", "token_type": "bearer", "expires_in": 3600,
            "scope": "trade:read_write account:read wallet:none expires:3600"})
        result = self.client.authenticate()
        self.assertTrue(result["authenticated"])
        self.assertNotIn("fixture", json.dumps(result))
        params = self.session.post.call_args.kwargs["json"]["params"]
        self.assertEqual(params["scope"], AUTH_SCOPE)
        self.assertNotIn("client_secret", self.session.post.call_args.args[0])
        self.assertNotIn("Authorization", self.session.headers)

    def test_auth_missing_or_elevated_permissions_fail_closed(self):
        for scope in ("trade:read account:read wallet:none", "trade:read_write account:read_write wallet:none",
                      "trade:read_write account:read wallet:read_write", "trade:read_write account:read block_trade:read_write",
                      "trade:read_write account:read custody:read", "trade:read_write account:read block_rfq:read_write",
                      "trade:read_write account:read mystery:read_write"):
            with self.subTest(scope=scope):
                self.session.post.side_effect = self.reply({"access_token": "fixture-secret-token",
                    "token_type": "bearer", "expires_in": 3600, "scope": scope})
                with self.assertRaises(TestnetError):
                    self.client.authenticate()
                self.assertIsNone(self.client._token)

    def test_explicit_none_scopes_may_be_omitted_without_granting_access(self):
        self.session.post.side_effect = self.reply({"access_token": "fixture-secret-token",
            "token_type": "bearer", "expires_in": 3600,
            "scope": "name:optimatrix session:rest-example trade:read_write expires:3600 account:read mainaccount"})
        result = self.client.authenticate()
        self.assertEqual(result["denied_scopes"], ["block_rfq", "block_trade", "custody", "wallet"])
        with self.assertRaises(TestnetError):
            self.client._rpc("private/get_deposit_address", {})

    def test_expired_quote_after_auth_is_not_sent(self):
        self.client._token = None
        def authenticate():
            self.client._token = "fixture-token"
            self.clock.stop()
            self.clock = patch("testnet.time.time", return_value=NOW + 16)
            self.clock.start()
        with patch.object(self.client, "authenticate", side_effect=authenticate):
            with self.assertRaises(TestnetError) as caught:
                self.client.buy("BTC-TEST-C", 0.1, 0.01, "opx-fixture", validity_deadline=NOW + 15)
        self.assertFalse(caught.exception.uncertain)
        self.session.post.assert_not_called()
        self.clock.stop()

    def test_preflight_checks_immediately_before_write(self):
        def preflight():
            raise TestnetError("工程身份变化", "blocked")
        with self.assertRaises(TestnetError):
            self.client.sell("BTC-TEST-C", 0.1, 0.01, "opx-fixture", preflight=preflight)
        self.session.post.assert_not_called()

    def test_refreshing_auth_invalidates_prior_account_snapshot(self):
        self.session.post.side_effect = self.reply({"access_token": "fixture-secret-token",
            "token_type": "bearer", "expires_in": 3600, "scope": "trade:read_write account:read"})
        self.client.authenticate()
        self.assertIsNone(self.client._account_auth_generation)
        self.session.post.reset_mock()
        with self.assertRaises(TestnetError) as caught:
            self.client.buy("BTC-TEST-C", 0.1, 0.01, "opx-fixture")
        self.assertEqual(caught.exception.status, "account_reconciliation_required")
        self.assertFalse(caught.exception.uncertain)
        self.session.post.assert_not_called()

    def test_error_redaction_and_no_write_retry(self):
        self.session.post.side_effect = requests.Timeout("fixture-secret https://secret")
        with self.assertRaises(TestnetError) as caught:
            self.client.buy("BTC-TEST-C", 0.1, 0.01, "opx-fixture")
        self.assertTrue(caught.exception.uncertain)
        self.assertNotIn("fixture-secret", str(caught.exception))
        self.assertEqual(self.session.post.call_count, 1)
        self.session.post.side_effect = self.reply(error={"code": 10009, "message": "fixture-secret"})
        with self.assertRaises(TestnetError) as caught:
            self.client.buy("BTC-TEST-C", 0.1, 0.01, "opx-fixture")
        self.assertFalse(caught.exception.uncertain)
        self.assertNotIn("fixture-secret", str(caught.exception))

    def test_rpc_timeout_is_uncertain_and_wrong_environment_blocks(self):
        for kwargs in ({"error": {"code": 10050}}, {"testnet": False}, {"testnet": None}, {"status": 302}, {"age": 31}):
            with self.subTest(kwargs=kwargs):
                self.session.post.side_effect = self.reply(**kwargs)
                with self.assertRaises(TestnetError) as caught:
                    self.client.cancel("fixture-order")
                self.assertTrue(caught.exception.uncertain)

    def test_stop_blocks_write_before_auth_and_network(self):
        (self.root / "STOP").touch()
        self.client._token = None
        with self.assertRaises(TestnetError) as caught:
            self.client.cancel("fixture-order")
        self.assertEqual(caught.exception.status, "stopped")
        self.session.post.assert_not_called()

    def test_stop_created_during_auth_prevents_write(self):
        self.client._token = None
        def authenticate():
            self.client._token = "fixture-token"
            (self.root / "STOP").touch()
        with patch.object(self.client, "authenticate", side_effect=authenticate):
            with self.assertRaises(TestnetError):
                self.client.cancel("fixture-order")
        self.session.post.assert_not_called()

    def test_only_verified_btc_call_and_exact_units_can_trade(self):
        for updates in ({"option_type": "put"}, {"base_currency": "ETH"}, {"quote_currency": "USD"},
                        {"contract_size": 10}, {"min_trade_amount": None}, {"state": "closed"},
                        {"instrument_type": "linear"}, {"tick_size_steps": None}):
            with self.subTest(updates=updates):
                self.client._instruments["BTC-TEST-C"] = instrument(**updates)
                with self.assertRaises(TestnetError):
                    self.client.buy("BTC-TEST-C", 0.1, 0.01, "opx-fixture")
        self.client._instruments["BTC-TEST-C"] = instrument()
        for amount, price in [(0.11, 0.01), (0.1, 0.0101), (0.1, float("nan")), (-0.1, 0.01)]:
            with self.assertRaises(TestnetError):
                self.client.buy("BTC-TEST-C", amount, price, "opx-fixture")
        with self.assertRaises(TestnetError):
            self.client.sell("BTC-TEST-C", 0.1, 0.01, "opx-fixture", reduce_only=False)
        self.session.post.assert_not_called()
        self.session.post.side_effect = self.reply({"order": {"order_id": "fixture"}})
        self.client.sell("BTC-TEST-C", Decimal("0.1"), Decimal("0.01"), "opx-fixture")
        params = self.session.post.call_args.kwargs["json"]["params"]
        self.assertTrue(params["reduce_only"])
        self.assertEqual(params["amount"], 0.1)
        self.assertEqual(params["type"], "limit")

    def test_book_uses_book_timestamp_not_rpc_time_and_checks_identity(self):
        for book in ({"instrument_name": "BTC-OTHER-C", "timestamp": NOW * 1000},
                     {"instrument_name": "BTC-TEST-C", "timestamp": (NOW - 31) * 1000}):
            self.session.post.side_effect = self.reply(book)
            with self.assertRaises(TestnetError):
                self.client.get_order_book("BTC-TEST-C")
        self.session.post.side_effect = self.reply({"instrument_name": "BTC-TEST-C", "timestamp": (NOW - 5) * 1000})
        self.assertEqual(self.client.get_order_book("BTC-TEST-C")["source_at"], NOW - 5)

    def test_mainnet_daily_query_includes_only_completed_days(self):
        midnight = int(NOW // 86400) * 86400
        ticks = list(range((midnight - 63 * 86400) * 1000, midnight * 1000, 3600000))
        raw = {"status": "ok", "ticks": ticks, "open": [100] * len(ticks), "close": [102] * len(ticks),
               "high": [105] * len(ticks), "low": [99] * len(ticks), "volume": [1] * len(ticks), "cost": [100] * len(ticks)}
        self.session.get.side_effect = self.reply(raw, testnet=False)
        provider = MarketDataProvider()
        envelope = provider.candles(midnight + 8 * 3600)
        args, kwargs = self.session.get.call_args
        self.assertEqual(args[0], "https://www.deribit.com/api/v2/public/get_tradingview_chart_data")
        params = kwargs["params"]
        self.assertEqual(params["end_timestamp"], int((NOW // 86400) * 86400 * 1000 - 1))
        self.assertEqual(params["resolution"], "60")
        self.assertEqual(params["instrument_name"], "BTC-PERPETUAL")
        self.assertEqual(len(envelope["result"]["ticks"]), 63)
        self.assertTrue(all(tick % 86400000 == 0 for tick in envelope["result"]["ticks"]))
        self.assertEqual(envelope["result"]["volume"], [24] * 63)
        self.assertEqual(envelope["source_result"], raw)

    def test_utc_daily_aggregation_rejects_missing_or_duplicate_hour(self):
        midnight = int(NOW // 86400) * 86400
        ticks = list(range((midnight - 63 * 86400) * 1000, midnight * 1000, 3600000))
        for bad_ticks in (ticks[1:], ticks[:-1] + [ticks[-2]]):
            raw = {"status": "ok", "ticks": bad_ticks, "open": [100] * len(bad_ticks), "close": [102] * len(bad_ticks),
                   "high": [105] * len(bad_ticks), "low": [99] * len(bad_ticks), "volume": [1] * len(bad_ticks), "cost": [100] * len(bad_ticks)}
            self.session.get.side_effect = self.reply(raw, testnet=False)
            with self.assertRaises(TestnetError):
                MarketDataProvider().candles(midnight + 8 * 3600)

    def test_candle_window_is_explicit_and_bounded(self):
        provider = MarketDataProvider()
        for days in (0, 124, True, 61.5):
            with self.assertRaises(TestnetError):
                provider.candles(NOW, days=days)
        self.session.get.assert_not_called()
        midnight = int(NOW // 86400) * 86400
        ticks = list(range((midnight - 2 * 86400) * 1000, midnight * 1000, 3600000))
        raw = {"status": "ok", "ticks": ticks, **{key: [100] * len(ticks) for key in ("open", "close", "high", "low", "volume", "cost")}}
        self.session.get.side_effect = self.reply(raw, testnet=False)
        self.assertEqual(len(provider.candles(NOW, days=2)["result"]["ticks"]), 2)

    def test_trades_overlap_millisecond_boundary_without_losing_same_time_fills(self):
        def row(identity, ts):
            return {"trade_id": identity, "timestamp": ts}
        pages = [{"trades": [row("a", 1), row("b", 2)], "has_more": True},
                 {"trades": [row("b", 2), row("c", 2)], "has_more": False}]
        with patch.object(self.client, "_rpc", side_effect=[{"result": page} for page in pages]) as rpc:
            rows = self.client._trades(0, 10, True)
        self.assertEqual([row["trade_id"] for row in rows], ["a", "b", "c"])
        self.assertEqual(rpc.call_args_list[1].args[1]["start_timestamp"], 2)

    def test_saturated_trade_timestamp_and_page_limit_fail_closed(self):
        page = {"result": {"trades": [{"trade_id": "a", "timestamp": 0}], "has_more": True}}
        with patch.object(self.client, "_rpc", return_value=page):
            with self.assertRaises(TestnetError):
                self.client._trades(0, 10, False)
        page = {"result": {"trades": [{"trade_id": "a", "timestamp": 1}], "has_more": True}}
        with patch.object(self.client, "_rpc", return_value=page), patch("testnet.MAX_PAGES", 1):
            with self.assertRaises(TestnetError):
                self.client._trades(0, 10, False)

    def test_order_history_paginates_unfilled_and_old_records(self):
        pages = [{"result": [{"order_id": "a"}, {"order_id": "b"}]}, {"result": [{"order_id": "c"}]}]
        with patch("testnet.PAGE_SIZE", 2), patch.object(self.client, "_rpc", side_effect=pages) as rpc:
            rows = self.client._orders(True)
        self.assertEqual(len(rows), 3)
        params = rpc.call_args_list[1].args[1]
        self.assertEqual(params["offset"], 2)
        self.assertTrue(params["historical"])
        self.assertTrue(params["include_old"])
        self.assertFalse(params["include_unfilled"])

    def test_recent_unfilled_orders_and_historical_are_separate_compatible_queries(self):
        with patch.object(self.client, "_rpc", return_value={"result": []}) as rpc:
            self.client._orders(False)
            self.client._orders(True)
        recent, old = [call.args[1] for call in rpc.call_args_list]
        self.assertTrue(recent["include_unfilled"])
        self.assertFalse(recent["historical"])
        self.assertFalse(old["include_unfilled"])
        self.assertTrue(old["historical"])
        self.assertTrue(recent["include_old"])
        self.assertTrue(old["include_old"])

    def test_snapshot_joins_recent_and_historical_and_retains_external_activity(self):
        def handler(method, params):
            if method == "private/get_account_summary":
                return {"result": summary(email="private@example.invalid", username="secret-profile"), "source_at": NOW}
            if method == "private/get_positions":
                return {"result": [{"instrument_name": "BTC-PERPETUAL", "size": 10}]}
            if method == "private/get_open_orders_by_currency":
                return {"result": [{"order_id": "outside", "label": "manual"}]}
            if method == "private/get_user_trades_by_currency_and_time":
                suffix = "old" if params["historical"] else "new"
                return {"result": {"trades": [{"trade_id": suffix, "timestamp": int(NOW * 1000)}], "has_more": False}}
            if method == "private/get_order_history_by_currency":
                return {"result": [{"order_id": "history-" + str(params["historical"])}]}
            self.fail("unexpected method")
        with patch.object(self.client, "_rpc", side_effect=handler) as rpc:
            snapshot = self.client.account_snapshot(int((NOW - 86400 * 3) * 1000))
        self.assertTrue(snapshot["complete"])
        self.assertTrue(snapshot["historical_indexing_may_lag"])
        self.assertFalse(snapshot["historical_unfilled_orders_available"])
        self.assertEqual(snapshot["account_id"], "42")
        self.assertEqual(len(snapshot["trades"]), 2)
        self.assertEqual(len(snapshot["orders"]), 2)
        self.assertEqual(snapshot["open_orders"][0]["label"], "manual")
        self.assertNotIn("private@example", json.dumps(snapshot))
        self.assertNotIn("secret-profile", json.dumps(snapshot))
        self.assertEqual(rpc.call_count, 7)

    def test_snapshot_account_identity_and_currency_required(self):
        for invalid in (summary(id=None), summary(currency="USDC"), summary(equity=float("nan"))):
            with patch.object(self.client, "_rpc", return_value={"result": invalid, "source_at": NOW}):
                with self.assertRaises(TestnetError):
                    self.client.account_snapshot()
                self.assertIsNone(self.client._account_auth_generation)


class FeesTests(unittest.TestCase):
    def test_base_and_relative_discount_cannot_expand_budget(self):
        self.assertEqual(fee_rate(instrument(), summary()), Decimal("0.0003"))
        for multiplier, expected in [(0.625, "0.0003"), (2, "0.0006")]:
            fees = {"btc_usd": {"option": {"default": {"type": "relative", "maker": multiplier, "taker": multiplier}}}}
            self.assertEqual(fee_rate(instrument(), summary(fees=fees)), Decimal(expected))

    def test_fixed_surcharge_reserved_and_rebate_ignored(self):
        fees = {"btc_usd": {"option": {"default": {"type": "fixed", "maker": -0.001, "taker": 0.001}}}}
        self.assertEqual(fee_rate(instrument(), summary(fees=fees)), Decimal("0.001"))

    def test_unknown_fee_or_cross_currency_basis_blocks(self):
        for item in (summary(fees={"other": {}}), summary(cross_collateral_enabled=True),
                     summary(affiliate_promotion_fee=0.1), summary(currency="ETH")):
            with self.assertRaises(TestnetError):
                fee_rate(instrument(), item)
        with self.assertRaises(TestnetError):
            fee_rate(instrument(maker_commission=None), summary())


if __name__ == "__main__":
    unittest.main()
