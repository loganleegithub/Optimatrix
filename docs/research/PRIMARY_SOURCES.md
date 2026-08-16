# Primary sources

This file is an evidence index, not Authority or permission. Each source supports only the stated
mechanism or exchange fact; none validates Optimatrix thresholds, BTC 0DTE transferability, Edge,
or profitability.

**Last checked:** 2026-08-16

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
  — historical average index values for a named relative range; useful only when the returned
  timestamps and cadence cover the exact hindsight interval.
- [`public/get_historical_volatility`](https://docs.deribit.com/api-reference/market-data/public-get_historical_volatility)
  — official realized-volatility time series by currency; a diagnostic series, not the product's
  decision-time matched-horizon RV method by itself.
- [`public/get_volatility_index_data`](https://docs.deribit.com/api-reference/market-data/public-get_volatility_index_data)
  — historical DVOL OHLC with exact start/end, supported resolution, and pagination; forward-vol
  context, not a 0DTE structure's decision-time IV or executable price.
- [`public/get_mark_price_history`](https://docs.deribit.com/api-reference/market-data/public-get_mark_price_history)
  — historical mark-price points for one instrument; mark valuation cannot replace a full-amount
  historical component book.
- [`public/get_last_trades_by_instrument_and_time`](https://docs.deribit.com/api-reference/market-data/public-get_last_trades_by_instrument_and_time)
  — timestamp-bounded historical public trades, including option trade IV when present; sparse
  trades cannot prove continuous liquidity or reconstruct an absent book.
- [Options Data Collection](https://docs.deribit.com/articles/options-data-collection-best-practices)
  — official separation of live order books/tickers from REST historical volatility, trades,
  candles, and settlement backfill, including pagination limits.
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
