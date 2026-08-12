# Primary sources consulted

Exchange mechanics:

- Deribit Contract Introduction Policy: daily BTC/ETH option expiries and 08:00 UTC schedule.
  https://support.deribit.com/hc/en-us/articles/25944688876957-Contract-Introduction-Policy
- Deribit Settlement: 08:00–08:00 sessions and 07:30–08:00 delivery-price context.
  https://support.deribit.com/hc/en-us/articles/29734325712413-Settlement
- Deribit Inverse Options: inverse premium, payoff, minimum quantity, tick and settlement semantics.
  https://support.deribit.com/hc/en-us/articles/31424939096093-Inverse-Options
- Deribit Fees: standard option and delivery fees and premium/payoff caps.
  https://support.deribit.com/hc/en-us/articles/25944746248989-Fees
- Deribit Option Combo Order: atomic multi-leg limit-order and RFQ behavior.
  https://support.deribit.com/hc/en-us/articles/25944794271261-Option-Combo-Order

Public API contracts used by the bounded adapter:

- `public/get_index_price`
  https://docs.deribit.com/api-reference/market-data/public-get_index_price
- `public/get_instruments`
  https://docs.deribit.com/api-reference/market-data/public-get_instruments
- `public/get_order_book`
  https://docs.deribit.com/api-reference/market-data/public-get_order_book
- `public/get_index_chart_data`
  https://docs.deribit.com/api-reference/market-data/public-get_index_chart_data
- `public/get_combos`
  https://docs.deribit.com/api-reference/combo-books/public-get_combos
- `public/get_delivery_prices`
  https://docs.deribit.com/api-reference/market-data/public-get_delivery_prices

These sources support exchange mechanics and payload contracts. They do not validate the
launch-prior score, thresholds, session sweet zones or market Edge.
