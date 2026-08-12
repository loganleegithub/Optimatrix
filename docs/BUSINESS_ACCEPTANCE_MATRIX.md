# Business acceptance matrix

The deterministic simulation suite must exercise the following materially different paths:

| Scenario | Business assertion |
| --- | --- |
| calm high VRP | full Iron Condor enters and captures premium |
| Gamma explosion | high premium cannot override path/jump/breakout risk |
| event phase | pre-event and post-event states do not collapse into one rule |
| short-only risk exit | dangerous short can be bought back without a wing bid |
| double-side whipsaw | both sides can realize loss in one Session |
| partial entry | one-side residue remains durable, recovers its remediation duty, and flattens short risk |
| process recovery | restart preserves the same Position and risk duty |
| expiry settlement | remaining contracts settle from delivery price |
| roll/reprice | early Session is review-only under the launch prior |
| low VRP | fast Theta alone does not create a trade |
| late Theta | late entry requires richer VRP |
| wings-only | wings-only safety fallback remains an explicit Position |
| source skew | incoherent entry facts create partial/remediation, not fabricated full entry |
| public combo | combo absence is diagnostic, not a blocker |
| failed entry | durable Decision Case ends as `NO_ENTRY` |
| Friday settlement | non-daily delivery fees are reserved and capped |
| failed exit recovery | exit intent survives unavailable quotes and restart |
| live shock after entry | existing short risk is actively flattened |

The matrix proves state reachability, exact arithmetic and responsibility. It does not establish
market frequency, expected return, optimal sweet zones or Policy qualification.
