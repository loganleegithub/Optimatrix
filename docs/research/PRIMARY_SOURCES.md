# Primary exchange sources

This file is an evidence index, not Authority or permission. Each source supports only the stated
exchange fact; none validates Optimatrix thresholds, proxies, Edge, or profitability.

**Last checked:** 2026-08-13

## Public mechanics

- [Contract Introduction Policy](https://support.deribit.com/hc/en-us/articles/25944688876957-Contract-Introduction-Policy)
  — daily BTC option expiries and expiry schedule.
- [Settlement](https://support.deribit.com/hc/en-us/articles/29734325712413-Settlement)
  — `08:00–08:00 UTC` Session, expiry, delivery, and final delivery-price window.
- [Inverse Options](https://support.deribit.com/hc/en-us/articles/31424939096093-Inverse-Options)
  — inverse BTC premium/payoff units, BTC cash settlement, quantity, and tick semantics.
- [Fees](https://support.deribit.com/hc/en-us/articles/25944746248989-Fees)
  — option, delivery, account-specific, and buy-versus-sell Combo fee rules.
- [Option Combo Order](https://support.deribit.com/hc/en-us/articles/25944794271261-Option-Combo-Order)
  — one simultaneous multi-instrument limit order, RFQ non-execution meaning, TIF, and reduce-only.

## Public market-data API

- [JSON-RPC overview](https://docs.deribit.com/articles/json-rpc-overview)
  — production endpoint, request envelope, response timing fields, and `testnet` environment fact.
- [`public/get_time`](https://docs.deribit.com/api-reference/supporting/public-get_time)
  — public server-clock result used by the bounded runtime preflight.
- [`public/get_instruments`](https://docs.deribit.com/api-reference/market-data/public-get_instruments)
  — available instrument payload.
- [`public/get_order_book`](https://docs.deribit.com/api-reference/market-data/public-get_order_book)
  — one instrument book and public Greeks/OI payload.
- [`public/get_index_price`](https://docs.deribit.com/api-reference/market-data/public-get_index_price)
  — index-price payload.
- [`public/get_index_chart_data`](https://docs.deribit.com/api-reference/market-data/public-get_index_chart_data)
  — bounded historical index payload.
- [`public/get_delivery_prices`](https://docs.deribit.com/api-reference/market-data/public-get_delivery_prices)
  — official delivery-price payload.
- [`public/get_combos`](https://docs.deribit.com/api-reference/combo-books/public-get_combos)
  — currently active Combo descriptors; absence does not prove on-demand impossibility.

## Private facts for later stages

These sources describe capability but grant no permission:

- [`private/get_account_summary`](https://docs.deribit.com/api-reference/account-management/private-get_account_summary)
  — authenticated equity, funds, margin, and account-specific fee facts.
- [`private/get_positions`](https://docs.deribit.com/api-reference/account-management/private-get_positions)
  — authenticated option and Combo Position facts.
- [`private/get_order_state`](https://docs.deribit.com/api-reference/trading/private-get_order_state)
  — authenticated order-state facts.
- [`private/get_user_trades_by_order`](https://docs.deribit.com/api-reference/trading/private-get_user_trades_by_order)
  — authenticated trades and actual fee facts for an order.
- [`private/create_combo`](https://docs.deribit.com/api-reference/combo-books/private-create_combo)
  — returns a matching Combo or creates one; requires `trade:read_write` and is not read-only.
- [`private/buy`](https://docs.deribit.com/api-reference/trading/private-buy) and
  [`private/sell`](https://docs.deribit.com/api-reference/trading/private-sell)
  — order placement, TIF, reduce-only, and returned order/trade facts; both require
  `trade:read_write`.
