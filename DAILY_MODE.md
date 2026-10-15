# Daily paper mode 2.0-daily

Approved effective date: 2026-10-15 (Asia/Shanghai). Activate with
`invest_daily.activate(db)` only during authorized maintenance, before any
research or settlement that day. Activation appends `rules:2.0-daily`; it never
replaces the original rules, starting capital, fills, valuations or evidence.
Without that event the previous mode remains active, including for legacy tests.

## Schedule and execution

- 16:00: collect complete current-session bars and settle orders frozen by the
  previous trading session's daily-mode research. One attempt; unavailable or
  unverified data rejects the order. No later fill or rollover of that order.
- 16:30–16:55: research the current completed session and freeze direction and
  quantity. Server adds `research_day`, next trading `execution_day` and
  `rules_version`. Each agent run retains its eight-minute maximum and bounded
  market-call budget. Empty orders with a truthful data limitation are valid.
- 20:00–21:00: review, without new orders. No missed research is backfilled.
- First day: no pending daily-mode orders. Old intraday reports are never used
  as daily-mode orders. Existing calendar refuses unsupported years; 2027 must
  be verified separately before cross-year execution can be scheduled.

Execution is the next session's unadjusted close, a deterministic paper model,
not a claim that an actual closing-auction order would fill. Final quantities
cannot be revised after seeing the execution day's price. Existing cash, T+1,
lot size, zero fees/slippage and limit-price rejection rules remain in force.

## Data and eligibility

Use Tencent `web.ifzq.gtimg.cn/.../fqkline/get` and Sina
`finance.sina.com.cn/realstock/company/{symbol}/hisdata_klc2/klc_kl.js`.
Never call the denied Sina realtime endpoint. The trusted bundled decoder is
from AKShare 1.18.64's MIT-licensed stock/cons.py; its license is embedded in
`sina_daily_decode.mjs`. Provider JavaScript is not executed: only its named,
quoted compressed payload is supplied to the decoder in a bounded Node process.

Use the current trading day only after 16:00 and require the previous trading
day as well. Ignore future bars and historical data outside the requested
window. Tencent's embedded closing timestamp must match the date and be at or
after 15:00. A daily session label is not a provider publication timestamp.
Original responses and acquisition timestamps remain in immutable evidence.

Unadjusted close and previous close agree exactly after conversion to fen
(0.01 point for CSI300); other OHLC differ by at most 0.01. For this tested
Tencent endpoint, volume is multiplied by 100 and compared with Sina shares,
allowing 100 shares of rounding difference. Only jointly verified historical
rows are returned for research. Sina amount is in yuan and explicitly marked
single-source; it is not claimed to be independently verified. Daily quotes
used in reports must have been acquired within one hour.

Trading eligibility additionally requires Tencent's embedded same-day closing
identity, previous close and positive activity, ordinary-mainboard name,
at least five prior verified daily bars, and upper/lower limits equal to the
ordinary 10% formula using the dual-source previous close. Special limit
regimes, ST/retirement/new-listing names, missing status, suspension, ambiguous
corporate actions and other mismatches fail closed. Closing at either limit
rejects both buys and sells. This intentionally rejects uncertain candidates.

Intraday turnover discovery is disabled in daily mode. The agent chooses
candidates through public research within the existing universe and verifies
each through the market API; no new fixed stock pool or strategy is imposed.

## Validation and rollback

`test_invest_daily.py` uses synthetic responses and a temporary database, never
an actual agent. Run existing investment, market-budget, source and audit tests
alongside it. Public responses fetched on 2026-10-15 at 10:27 verified the
2026-10-14 closes for CSI300, sh600519 and sz000001; they do not prove today's
closing-publication timing or the agent's ability to submit a report tonight.

Pre-change deployment: 0.1.12, commit
`78227368355834b34d8f8e0f7b1813ec6dc75fad`. To roll code back, first pause investment
execution through the existing maintenance control, then deploy that clean
revision using the existing deployment script. Preserve all runtime records
including the activation event. Do not restart old intraday trading merely
because old code was restored; resumption needs a compatible mode decision.
Never reset or rewrite the journal to roll back code. Missing original benchmark
base remains missing; this mode change does not invent or repair past returns.
