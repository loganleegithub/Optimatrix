"""Offline checks only: all prices/contracts below are synthetic test fixtures.

No live Deribit request, account, credential file, or Codex CLI is used here.
"""
import copy
import unittest
from unittest.mock import Mock, patch

import requests

from app import create_app
from market import (
    BASE_URL,
    MarketError,
    MarketService,
    PublicClient,
    empty_option,
    iso,
    parse_book,
    retry_delay,
    select_instruments,
    valid_instrument,
)


NOW = 1_800_000_000.0


def instrument(name="fixture-call", option_type="call", strike=100_000, days=1):
    return {
        "instrument_name": name,
        "kind": "option",
        "instrument_type": "reversed",
        "base_currency": "BTC",
        "quote_currency": "BTC",
        "settlement_currency": "BTC",
        "counter_currency": "USD",
        "price_index": "btc_usd",
        "state": "open",
        "is_active": True,
        "option_type": option_type,
        "contract_size": 1,
        "strike": strike,
        "expiration_timestamp": (NOW + days * 86400) * 1000,
    }


def envelope(result, source=NOW, received=NOW):
    return {
        "payload": {
            "jsonrpc": "2.0", "result": result,
            "testnet": False, "usOut": source * 1_000_000,
        },
        "source_at": iso(source), "received_at": iso(received),
    }


def book(item, bids=None, asks=None, stamp=NOW):
    return envelope({
        "instrument_name": item["instrument_name"], "state": "open",
        "timestamp": stamp * 1000,
        "bids": [[0.012, 2.0]] if bids is None else bids,
        "asks": [[0.013, 3.0]] if asks is None else asks,
    })


def fixture_service():
    call = instrument()
    put = instrument("fixture-put", "put")
    client = Mock()
    client.get.side_effect = [
        envelope({"index_price": 100_000}), envelope([call, put]),
        book(call), book(put),
    ]
    return MarketService(client=client), client


class ProductAndBookTests(unittest.TestCase):
    def test_metadata_is_required_and_does_not_depend_on_name(self):
        item = instrument("an-arbitrary-name")
        self.assertTrue(valid_instrument(item, NOW))
        invalid = {
            "kind": "future", "instrument_type": "linear",
            "base_currency": "ETH", "quote_currency": "USDC",
            "settlement_currency": "USDC", "counter_currency": "BTC",
            "price_index": "btc_usdc", "state": "closed", "is_active": False,
            "option_type": "other", "contract_size": 0.1,
            "strike": float("nan"), "expiration_timestamp": NOW * 1000,
            "instrument_name": "",
        }
        for field, value in invalid.items():
            with self.subTest(field=field, value=value):
                self.assertFalse(valid_instrument({**item, field: value}, NOW))
                missing = dict(item)
                del missing[field]
                self.assertFalse(valid_instrument(missing, NOW))
        self.assertFalse(valid_instrument({**item, "contract_size": True}, NOW))

    def test_selection_uses_live_expiry_common_strike_and_both_option_types(self):
        items = []
        for days in (3, 1, 2):
            for strike in (90_000, 101_000):
                for side in ("call", "put"):
                    items.append(instrument(f"fixture-{days}-{strike}-{side}", side, strike, days))
        items += [instrument("expired", days=-1), instrument("near-expiry", days=0.01)]
        chosen = select_instruments(items, 100_000, NOW)
        self.assertEqual([i["option_type"] for i in chosen], ["call", "put", "call", "put"])
        self.assertEqual([i["strike"] for i in chosen], [101_000] * 4)
        self.assertEqual([i["expiration_timestamp"] for i in chosen],
                         [(NOW + 86400) * 1000] * 2 + [(NOW + 2 * 86400) * 1000] * 2)
        with self.assertRaises(MarketError):
            select_instruments([instrument()], 100_000, NOW)

    def test_book_empty_side_is_absent_not_zero(self):
        item = instrument()
        parsed = parse_book(book(item, bids=[]), item)
        self.assertIsNone(parsed["bid"])
        self.assertIsNone(parsed["bid_amount"])
        self.assertEqual((parsed["ask"], parsed["ask_amount"]), (0.013, 3.0))
        self.assertEqual(parsed["source_at"], iso(NOW))

    def test_book_identity_time_and_levels_are_validated(self):
        item = instrument()
        bad_results = [
            {"instrument_name": "another-contract"}, {"state": "closed"},
            {"timestamp": (NOW + 10) * 1000}, {"timestamp": None},
            {"bids": None}, {"bids": [[0.01, -1]]}, {"asks": [[True, 2]]},
            {"bids": [[0.02, 1]], "asks": [[0.01, 1]]},
        ]
        for mutation in bad_results:
            with self.subTest(mutation=mutation):
                response = book(item)
                response["payload"]["result"].update(mutation)
                with self.assertRaises(MarketError):
                    parse_book(response, item)


class StateTests(unittest.TestCase):
    @patch("market.time.time", return_value=NOW)
    def test_initial_and_first_failure_do_not_create_data(self, _clock):
        client = Mock()
        client.get.side_effect = MarketError("fixture unavailable")
        service = MarketService(client=client)
        initial = service.snapshot(NOW)
        self.assertIsNone(initial["index"])
        self.assertEqual(initial["options"], [])
        self.assertEqual(initial["catalog"]["status"], "missing")
        with self.assertRaises(MarketError):
            service.refresh_once()
        failed = service.snapshot(NOW)
        self.assertIsNone(failed["index"])
        self.assertEqual(failed["collector"]["error"], "fixture unavailable")
        self.assertIsNone(failed["collector"]["last_success_at"])

    @patch("market.time.time", return_value=NOW)
    def test_failure_preserves_last_value_and_both_timestamps(self, _clock):
        service, client = fixture_service()
        service.refresh_once()
        previous = service.snapshot(NOW)
        client.get.side_effect = MarketError("fixture timeout")
        with self.assertRaises(MarketError):
            service.refresh_once()
        failed = service.snapshot(NOW + 20)
        for key in ("price", "source_at", "received_at"):
            self.assertEqual(failed["index"][key], previous["index"][key])
        self.assertEqual(failed["index"]["status"], "error")
        self.assertEqual(failed["index"]["source_age_seconds"], 20)
        self.assertEqual(failed["sequence"], previous["sequence"])
        self.assertEqual(failed["collector"]["last_success_at"], previous["collector"]["last_success_at"])

    @patch("market.time.time", return_value=NOW)
    def test_book_failure_preserves_quotes_and_recovery_clears_error(self, _clock):
        service, client = fixture_service()
        service.refresh_once()
        original = copy.deepcopy(service.state["options"])
        client.get.side_effect = [envelope({"index_price": 100_001}), MarketError("fixture book failure")]
        with self.assertRaises(MarketError):
            service.refresh_once()
        failed = service.snapshot(NOW)
        for old, current in zip(original, failed["options"]):
            for key in ("bid", "ask", "bid_amount", "ask_amount", "source_at", "received_at"):
                self.assertEqual(old[key], current[key])
            self.assertEqual(current["status"], "error")
        client.get.side_effect = [envelope({"index_price": 100_002}), *[book(i) for i in original]]
        service.refresh_once()
        self.assertIsNone(service.snapshot(NOW)["collector"]["error"])
        self.assertTrue(all(o["status"] == "live" for o in service.snapshot(NOW)["options"]))

    def test_source_age_receipt_age_future_and_expiry_are_independent(self):
        service = MarketService(client=Mock())
        for source, received, expected in (
            (NOW, NOW, "live"), (NOW - 61, NOW, "stale"),
            (NOW, NOW - 61, "stale"), (NOW + 6, NOW, "stale"),
        ):
            with self.subTest(source=source, received=received):
                service.state["index"] = {"price": 100_000, "source_at": iso(source),
                                          "received_at": iso(received), "error": None}
                self.assertEqual(service.snapshot(NOW)["index"]["status"], expected)
        item = instrument(days=-1)
        row = empty_option(item)
        row.update(parse_book(book(item), item))
        service.state["options"] = [row]
        self.assertEqual(service.snapshot(NOW)["options"][0]["status"], "expired")
        returned = service.snapshot(NOW)
        returned["index"]["price"] = -123
        self.assertEqual(service.state["index"]["price"], 100_000)


class PublicTransportTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.session.headers = {}
        self.session_patch = patch("market.requests.Session", return_value=self.session)
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)
        self.client = PublicClient()
        self.addCleanup(self.client.close)
        self.response = Mock(status_code=200, headers={})
        self.response.json.return_value = envelope({"index_price": 100_000})["payload"]
        self.session.get.return_value = self.response

    @patch("market.time.time", return_value=NOW)
    def test_public_request_has_timeout_no_environment_credentials_and_no_redirects(self, _clock):
        result = self.client.get("get_index_price", index_name="btc_usd")
        self.assertFalse(self.session.trust_env)
        self.session.get.assert_called_once_with(
            BASE_URL + "public/get_index_price", params={"index_name": "btc_usd"},
            timeout=(3.05, 7), allow_redirects=False,
        )
        self.assertEqual(result["source_at"], iso(NOW))
        self.session.get.reset_mock()
        with self.assertRaises(MarketError):
            self.client.get("buy")
        self.session.get.assert_not_called()

    def test_http_429_honors_retry_after_and_backoff_is_bounded(self):
        self.response.status_code = 429
        self.response.headers = {"Retry-After": "120"}
        with self.assertRaises(MarketError) as caught:
            self.client.get("get_index_price")
        self.assertEqual(caught.exception.retry_after, 120)
        self.assertEqual([retry_delay(i) for i in (1, 2, 3, 4, 5, 1000)], [30, 60, 120, 240, 300, 300])
        self.assertEqual(retry_delay(1, caught.exception.retry_after), 120)

    @patch("market.time.time", return_value=NOW)
    def test_rpc_rate_limit_timeout_bad_json_and_http_errors(self, _clock):
        self.response.json.return_value = {"error": {"code": 10028, "message": "untrusted text"}}
        with self.assertRaises(MarketError) as caught:
            self.client.get("get_index_price")
        self.assertEqual(caught.exception.retry_after, 60)
        self.assertNotIn("untrusted text", str(caught.exception))
        self.response.json.side_effect = ValueError("fixture malformed JSON")
        with self.assertRaisesRegex(MarketError, "非 JSON"):
            self.client.get("get_index_price")
        self.session.get.side_effect = requests.Timeout("fixture timeout")
        with self.assertRaisesRegex(MarketError, "超时"):
            self.client.get("get_index_price")
        self.session.get.side_effect = None
        self.response.status_code = 503
        with self.assertRaisesRegex(MarketError, "HTTP 503"):
            self.client.get("get_index_price")

    @patch("market.time.time", return_value=NOW)
    def test_unknown_production_and_invalid_source_time_are_rejected(self, _clock):
        original = envelope({"index_price": 100_000})["payload"]
        for update in ({"testnet": True}, {"testnet": None}, {"usOut": None}, {"usOut": (NOW + 10) * 1e6}):
            with self.subTest(update=update):
                self.response.json.return_value = {**original, **update}
                with self.assertRaises(MarketError):
                    self.client.get("get_index_price")

    def test_collector_waits_after_rate_limit_and_closes_client(self):
        service = MarketService(client=Mock())
        service.refresh_once = Mock(side_effect=MarketError("fixture rate limit", 120))
        service.stop_event = Mock()
        service.stop_event.is_set.side_effect = [False, True]
        with self.assertLogs(level="WARNING"):
            service._run()
        service.stop_event.wait.assert_called_once_with(120)
        service.client.close.assert_called_once_with()
        self.assertFalse(service.state["collector"]["running"])


class LocalWebTests(unittest.TestCase):
    def test_web_reads_cached_state_without_starting_collector_or_cli(self):
        service = Mock(spec=MarketService)
        service.snapshot.return_value = {"index": None, "options": [], "sequence": 0}
        with patch("app.codex_status", side_effect=AssertionError("CLI must not run")):
            client = create_app(service).test_client()
            for _ in range(3):
                response = client.get("/api/state")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["sequence"], 0)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            with client.get("/") as home_response:
                self.assertEqual(home_response.status_code, 200)
        self.assertEqual(service.snapshot.call_count, 3)
        service.start.assert_not_called()
        service.refresh_once.assert_not_called()
        self.assertEqual(client.get("/api/state", headers={"Host": "external.example"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
