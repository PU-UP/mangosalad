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


## 2.1-ready scheduled from 2026-10-16

An appended `rules:2.1-ready` event schedules this version; selection uses the
Beijing date. It does not modify 2.0-daily, report #28 or today's terminal work.
Required prices and eligibility are unchanged. Execution dates already stored
in reports are never recalculated by readiness or new calendar selection.

Persisted transitions in `invest_readiness` are:
`waiting -> checking -> waiting | finalizing -> settled`.
Each of the 16:30, 17:00, 17:30, 18:00 and 18:30 slots can be claimed once,
with an atomic owner claim and a five-minute lease/window. An interrupted slot
is marked interrupted, never retried. Later slots can continue. Late arrivals
skip expired slots; no new readiness requests start at or after 18:35.
Each symbol is checked at most once per slot; 401/403 stops retries for that
symbol that day. Every response checkpoints raw public data, its original
acquisition time and diagnostics, without writing quote/evidence journal rows
or invoking a model while waiting. No waiting sleep is added to the worker.

Required symbols are CSI300, current holdings and frozen orders whose stored
execution_day is today. Unqueried research candidates are not presumed ready.
When all required quotes verify, or after the last slot, current-day cache no
older than one hour is persisted idempotently and settlement runs once.
Unverified/missing individual orders are rejected under the existing rules.
A restart after quote persistence cannot duplicate evidence or a fill; an
existing settled event is always terminal, even if the state update was lost.
No late prices can reopen a completed settlement or research report.

Research starts at least five minutes after settlement, once, no later than
18:50, with an absolute 19:00 submission cutoff. Its existing eight-minute
model budget and six-minute collection limit begin only when the model starts.
If the worker misses that window it records missed research and never backfills.
Review remains 20:00-21:00. A delayed/missing price does not move execution_day
or permit another same-day investment decision.

Rollback code to 0.1.14 / 15c01ae342f35bc9e174576ba458f1a388805fbe only after
pausing investment execution; preserve all runtime tables and rules events.
Older code does not understand the future mode, so do not resume it silently.
