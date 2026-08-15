# Primary sources

This file is an evidence index, not Authority or permission. Each source supports only the stated
mechanism or exchange fact; none validates Optimatrix thresholds, BTC 0DTE transferability, Edge,
or profitability.

**Last checked:** 2026-08-15

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
- [Combo Books](https://support.deribit.com/hc/en-us/articles/31424954956061-Combo-Books)
  — Combo-book lifecycle and the distinction between a created Combo instrument and resting
  counterparty liquidity.

## Strategy-mechanism research

- [Cboe S&P 500 Iron Condor Index methodology v4.1](https://cdn.cboe.com/api/global/us_indices/governance/CNDR_Methodology.pdf)
  — a mature monthly SPX benchmark sells approximately 20-delta Call/Put legs, buys approximately
  5-delta wings, and defines worst option payoff from the wider wing. It supports the bounded
  four-leg mechanism, not BTC 0DTE or the current Optimatrix delta, sigma, width, or timing values.
- [Bakshi and Kapadia, *Review of Financial Studies* 2003](https://doi.org/10.1093/rfs/16.2.527)
  — supports a negative volatility-risk-premium mechanism in S&P 500 options; it does not establish
  a BTC 0DTE entry threshold.
- [Carr and Wu, *Review of Financial Studies* 2009](https://doi.org/10.1093/rfs/hhn038)
  — estimates variance risk premia from model-free variance-swap replication. This bounds the
  current nearest-ATM mark-IV versus trailing-RV measure to the name `VRP proxy`.
- [Todorov, *Review of Financial Studies* 2010](https://doi.org/10.1093/rfs/hhp035)
  — supports separating jump risk from diffusive variance risk; it does not establish the current
  jump-share or exit thresholds.
- [Hoang and Baur, *Journal of Futures Markets* 2020](https://doi.org/10.1002/fut.22144)
  — Deribit BTC implied volatility was less accurate than ARMA/HAR at a one-day forecast horizon
  but added information at longer horizons and in combined forecasts. It is direct evidence that
  the current 0DTE `VRP proxy` levels remain hypotheses.
- [Cboe 0DTE market study](https://www.cboe.com/insights/posts/0-dt-es-decoded-positioning-trends-and-market-impact)
  — documents extensive use of limited-risk spreads in SPX 0DTE. It supports defined-risk structure
  as a mechanism, not the transfer of SPX parameters or observed performance to BTC.
- [Cboe practitioner note on an SPX 0DTE iron condor](https://www.cboe.com/insights/posts/henry-schwartzs-zero-day-spx-iron-condor-strategy-a-deep-dive/)
  — expert practice favors avoiding scheduled event windows and managing late-expiry Gamma; this is
  practitioner evidence, not a controlled study or authority for a numeric gate.

## Public market-data API

- [Market-data collection best practices](https://docs.deribit.com/articles/market-data-collection-best-practices)
  — cross-instrument feeds are asynchronous; REST is for infrequent snapshots/resynchronization,
  while WebSocket aggregated subscriptions are preferred for continuously time-sensitive updates.
- [Book subscription](https://docs.deribit.com/subscriptions/orderbook/bookinstrument_nameinterval)
  — the initial full book, incremental `new`/`change`/`delete` actions, per-instrument `change_id`
  and `prev_change_id`, and public `100ms` interval.
- [Ticker subscription](https://docs.deribit.com/subscriptions/market-data/tickerinstrument_nameinterval)
  — push-based option mark IV, Greeks, open interest, underlying, and index-related fields.
- [Notifications and subscriptions](https://docs.deribit.com/articles/notifications)
  — `public/subscribe`, asynchronous channels, initial book snapshots, and resubscription after a
  connection loss.
- [`public/set_heartbeat`](https://docs.deribit.com/api-reference/upcoming/session-management/public-set_heartbeat)
  — WebSocket liveness interval and `test_request` response requirement.
- [Connection-management best practices](https://docs.deribit.com/articles/connection-management-best-practices)
  — persistent subscription preference and public unauthenticated connection capability.
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
- [`public/get_instrument`](https://docs.deribit.com/api-reference/market-data/public-get_instrument)
  — instrument kind, active/open state, expiry, minimum trade amount, and tick metadata.

## Private facts for later stages

These sources describe capability but grant no permission:

- [Creating an API key](https://docs.deribit.com/articles/creating-api-key)
  — API-key maximum account/trade/wallet permissions and read-only versus read-write selection;
  token effective scope remains a separate `public/auth` response fact.
- [`public/auth`](https://docs.deribit.com/api-reference/authentication/public-auth)
  — client-credentials authentication, requested/effective scope, bearer-token result, and response
  timing envelope; a token may request scope below the API key maximum. C1 always requests exactly
  `account:read trade:read`. The mainnet credential is user-declared read-only, while the fixed
  application contains no write method. C1 does not normalize, gate on, output, persist, or project
  the response scope text and therefore labels token-scope normalization `UNAVAILABLE` rather than
  claiming an exact effective permission set.
- [`private/get_account_summary`](https://docs.deribit.com/api-reference/account-management/private-get_account_summary)
  — authenticated BTC equity, funds, and margin facts; C1 fixes `extended=false` and does not request
  account-specific fee expansion. This method requires `account:read`.
- [`private/get_positions`](https://docs.deribit.com/api-reference/account-management/private-get_positions)
  — authenticated BTC option, future, and Combo Position facts; this method requires `trade:read`.
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
- [`private/cancel`](https://docs.deribit.com/api-reference/trading/private-cancel)
  — cancellation of one exact open order and the resulting order state; requires
  `trade:read_write`.
