# Fixed Channel Matrix

| Channel | Product | Strategy | State |
| --- | --- | --- | --- |
| `INVERSE_BTC_SHORT_VOL` | Inverse BTC | two-sided premium sale | implemented |
| `INVERSE_BTC_LONG_GAMMA` | Inverse BTC | Long Gamma | reserved |
| `INVERSE_ETH_SHORT_VOL` | Inverse ETH | two-sided premium sale | reserved |
| `INVERSE_ETH_LONG_GAMMA` | Inverse ETH | Long Gamma | reserved |

Reserved means an explicit identity and nothing else. A future implementation must supply its own
Policy, strategy owner, Case semantics, business simulation, and live validation.
