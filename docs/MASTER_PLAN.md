# MASTER PLAN — Simple Algo Trading System
# Generated: 2026-09-25 after Phase A completion
# This document replaces and supersedes docs/IMPLEMENTATION_PLAN.md.

---

## STEP 1 — RE-BASELINE (actual state as of 2026-09-25)

### 1.1 Environment

| Item | Value |
|---|---|
| Python | 3.11.9 (**prompt said 3.12.3 — confirmed wrong**) |
| pandas | **2.2.2** (**prompt said 3.0.2 — WRONG; that number was the test environment at the time of plan writing, not this machine**) |
| numpy | **1.26.4** (**prompt said 2.4.4 — WRONG for the same reason**) |
| pytest | 9.1.1 |
| Git | 2.55.0.windows.5 |

> **Critical correction**: The requirements.txt change in Phase A pinned `pandas>=3.0.2` and `numpy>=2.4.4`,
> but the installed versions are 2.2.2 and 1.26.4 respectively. These pins are WRONG for this machine.
> Phase A left a broken requirements.txt — tests pass only because pytest does not re-install on each run.
> This must be corrected at the start of Phase A's close-out (see section 2.1 below).

### 1.2 Test results

**213 passed, 0 failed** running `python -m pytest` from `trading_app/trading_app/`.

Breakdown by file:
- test_backtest_engine.py: 53
- test_charges.py: 14
- test_config.py: 51 (includes 12 new from conftest)
- test_db.py: 24
- test_ema_strategy.py: 31
- test_hygiene.py: 3 (new in Phase A)
- test_logger.py: 7
- test_metrics.py: 9
- test_risk_manager.py: 21

### 1.3 Git state

| Item | Value |
|---|---|
| Repo | Initialized, local only |
| Current branch | `main` |
| Branches | `main`, `phase-a-baseline` |
| Tags | `handover-phase3` (16eea14), `phase-a` (58e4ae1) |
| Working tree | Clean |
| Remote | None configured |
| Pushed | Nothing |

### 1.4 Files changed since handover-phase3

| File | Change |
|---|---|
| `config.py` | Removed unused `IST` re-export and `DEFAULT_DB_PATH` |
| `db.py` | `get_logs`: `_LEVELS[key]` → `_LEVELS.get(key, 0)` to fix KeyError (B1) |
| `requirements.txt` | Pins changed (but to WRONG versions — see 1.1) |
| `tests/test_backtest_engine.py` | Removed unused `Signal`, `NO_FEES` imports |
| `tests/test_db.py` | Removed unused `Database` import |
| `tests/test_risk_manager.py` | Removed unused `timedelta` import |
| `tests/test_hygiene.py` | **New file**: R1 guard, kiteconnect isolation, repo hygiene |
| `docs/IMPLEMENTATION_PLAN.md` | **New file**: original plan |
| `docs/PROJECT_STATUS.md` | **New file**: status snapshot |

### 1.5 Outstanding Gate A items — final resolution

**Item 1 (git-first ordering):** RESOLVED. The `handover-phase3` tag on commit `16eea14` captures the
pristine handover code with only the corrected `.gitignore`. All Phase A changes are in subsequent
commits on `phase-a-baseline`, merged to `main` as `phase-a`. The ordering is now correct and verifiable
by `git diff handover-phase3 HEAD`.

**Item 2 (disputed test evidence):** RESOLVED. The test `test_backtest_and_risk_code_cannot_reach_a_real_broker_or_network`
was NOT changed. Its original assertion `len(files) >= 5` remains in the code. The test passes today
(213/213). My earlier "fix" was reverted in full after it was confirmed the failure was caused by running
pytest from the wrong directory (`trading_app/` instead of `trading_app/trading_app/`).

**New item discovered (Phase A close-out bug):** The `requirements.txt` pins are wrong for this machine.
Must fix before Phase A can truly close.

---

## STEP 2 — FULL PLAN: PHASES A (close-out) THROUGH H

---

## WHAT "PRODUCTION LEVEL" MEANS FOR THIS PROJECT

This project targets **personal use by one developer, not enterprise deployment**. "Production level" means:

1. **Safety**: no real order can be placed without explicit multi-step confirmation; no position can
   exist without a verified stop; a daily-loss halt survives a process restart; an emergency stop leaves
   protective stops in place.
2. **Correctness**: strategy generates the same signals regardless of whether it sees data one candle at
   a time or as a full series; the backtest engine never fills a signal across a data gap or outside market
   hours; all money arithmetic is checked against hand-calculated reference values.
3. **Reliability**: network failures and API errors are detected, logged at CRITICAL, and halt new orders
   rather than producing phantom state; a crashed process restarts to a known, reconciled state.
4. **Auditability**: every order traces back to a signal_id; every trade is in the DB; logs are redacted;
   nothing secret is ever committed or displayed.
5. **Testability**: every safety-critical guard has at least one test that demonstrates it has teeth (the
   guard is deliberately broken, the test fails, the guard is restored, the test passes again — this
   "mutation" step is documented per guard in each phase below).

This does NOT mean: multiple strategies, ML, Postgres, Redis, Kafka, Docker, cloud deployment, portfolio
optimisation, or anything else in rule R8. If any phase plan below drifts toward those, it is a deviation
and will be flagged as one.

The Phase H final audit (section 9 of the prompt) checks: architecture isolation, no bare excepts outside
the DBLogHandler intentional catch, no secrets in code/DB/git, all safety guards tested with teeth, live-
readiness checklist honestly ticked only for what tests actually prove.

---

## RUNNING TOTALS

| Item | Value |
|---|---|
| Phases completed | A (partially — requirements.txt bug outstanding) |
| Phases remaining | A close-out + B + C + D + E + F + G + H = **8 work sessions minimum** |
| Riskiest phase | **Phase D** (broker layer + market data + signal engine + paper parity test — most new code, most interaction points, most opportunity for design misfits discovered only at integration) |
| Second riskiest | **Phase E** (Kite adapter — cannot be tested against a real API at all; relies entirely on mock fidelity) |
| Session estimate | **10–14 "continue" cycles total** (2 for A close-out + B, 1–2 for C, 3–4 for D, 2–3 for E, 1–2 for F, 1 for G, 1 for H) — round up if Kite plan or CSV are not ready when needed |

---

## PHASE A — CLOSE-OUT (current branch: main / no new branch needed)

**Status:** Gate A criteria were reported as met, but one defect was subsequently found.

### Goal
Fix the requirements.txt version pins to match the actual installed environment, re-run tests, close Gate A properly.

### Exact files to modify
- `requirements.txt` — correct pins to versions that actually exist in this environment

### Fix
The pins must be either:
- (a) Minimum bounds matching what is actually installed: `pandas>=2.2.2`, `numpy>=1.26.4`, `pytest>=9.1.1`, `python-dotenv>=1.0.0`
- (b) Exact pins with `==` if we want a reproducible lockfile

Recommended: option (a) with `>=` at the installed floor. Exact pinning is better done with `pip freeze > requirements-lock.txt` which is out of scope for this phase. The original lower bounds (`pandas>=2.0`, `numpy>=1.24`) were technically correct as minimums but undertested; the Phase A change raised them to numbers not installed here. Correct to installed floors.

### Tests to add
None new — `python -m pytest` must still show 213 passed.

### Safety-critical guards with teeth verification in this phase
None (this is a dependency metadata fix only).

### What I need from you and when
- **Now (before this close-out commit):** Confirm whether you want exact pins (`==`) or minimum bounds (`>=`). Default: `>=` at installed floor, which I will apply unless you say otherwise.

### Main risk
None — one-line change to a metadata file.

### Gate criteria
- `requirements.txt` pins match installed versions (verifiable with `pip check`)
- 213 tests pass
- `git status` clean
- New commit on `main` directly (no new branch needed for a one-line hotfix)
- No push

### Git
- Branch: `main` (direct hotfix commit)
- Tag: `phase-a-closed` after this commit

### Effort: 0.5 sessions (fold into start of Phase B session)

---

## PHASE B — BACKTEST CORRECTNESS AND REAL-DATA READINESS

### Goal
Fix the two known engine bugs (B3: stale fills across data gaps; B4: timeframe and market-hours not
validated). Add a CSV data loader. Run one backtest on real data and manually spot-check ≥3 trades.

### Exact files to create or modify

| Path | Action |
|---|---|
| `backtest/engine.py` | Modify: validate candle spacing; filter outside 09:15–15:30; expire signals across gaps |
| `market/__init__.py` | Already exists (empty) |
| `market/historical_data.py` | **Create**: CSV loader → tz-aware IST DataFrame; Kite fetch placeholder (disabled until Kite plan confirmed) |
| `tests/test_backtest_engine.py` | Modify: add gap/timeframe/hours tests |
| `tests/test_historical_data.py` | **Create**: CSV loader tests |
| `docs/PROJECT_STATUS.md` | Modify: record spot-check results |

### Detailed task order

**B-1: Fix B3 — stale fills across data gaps**

Current bug: a BUY signal at candle i executes at candle i+1 regardless of the time gap between them.
Fix: when queuing a pending signal, also record the timestamp of candle i. When executing it at candle i+1,
first check: `(times[i+1] - times[i]).total_seconds() == timeframe_minutes * 60`. If not, expire the signal
into `skipped["GAP_SIGNAL_EXPIRED"]` rather than executing it.

**B-2: Fix B4 — timeframe and market hours not validated**

Two sub-bugs:
- Sub-bug 1 (timeframe): `_prepare()` never checks that consecutive candle timestamps are `timeframe_minutes` apart. Add a check: if the modal spacing is not `timeframe_minutes * 60` seconds, raise `BacktestDataError`.
- Sub-bug 2 (market hours): candles outside 09:15–15:30 IST are accepted. Add a filter in `_prepare()` that drops outside-hours rows and logs a count, or raises if ALL rows are out of hours. Configurable: `filter_hours=True` (default) vs raise.

**B-3: market/historical_data.py — CSV loader**

```
load_csv(path: str | Path) -> pd.DataFrame
```
- Reads CSV; detects common column aliases (Date/date, Open/open, etc.)
- Requires: open, high, low, close; volume optional
- Parses timestamps; requires or infers IST timezone; raises `DataLoadError` with a clear message if ambiguous
- Returns DataFrame with tz-aware IST DatetimeIndex, lower-case column names
- Validates with `Backtester._prepare()` — if that raises, re-raises with the CSV path in the message

Kite fetch: stub only in Phase B. `load_kite(kite_client, symbol, from_date, to_date, interval)` raises
`NotImplementedError("Kite fetch is not available until Phase D")`.

**B-4: Spot-check**

Once you supply a CSV: run one backtest, manually verify ≥3 trades against raw candles:
- Confirm entry was at the next candle's open after the signal candle
- Confirm stop price = fill * (1 - stop_loss_pct/100)
- Confirm charges are plausible (not zero, not 10x the trade value)
Document results in `docs/PROJECT_STATUS.md`. No profitability interpretation; no parameter tuning.

### Tests to add (test_backtest_engine.py additions)

```python
test_signal_expires_if_next_candle_is_not_exactly_one_timeframe_later()
# Pass: 60-min gap between candles; BUY signal at candle before gap; assert skipped["GAP_SIGNAL_EXPIRED"] == 1 and no trade
# Mutation: comment out the gap check; confirm this test fails; restore

test_candles_outside_market_hours_are_filtered()
# Pass: candles at 03:00 IST are removed from data; engine processes only market-hours candles
# Mutation: remove the hours filter; assert test fails on an 03:00 candle being processed

test_wrong_timeframe_raises_backtest_data_error()
# Pass: 15-min candles submitted to a 5-minute config; assert BacktestDataError raised
# Mutation: remove the spacing check; assert this test would wrongly pass 15-min data

test_gap_count_reported_in_result()
# Pass: data with 3 gaps; result.skipped_signals["GAP_SIGNAL_EXPIRED"] == (up to 3 pending signals that expired)
```

`tests/test_historical_data.py`:
```python
test_csv_load_roundtrip_produces_engine_schema()
test_csv_with_missing_required_column_raises_data_load_error()
test_csv_timezone_naive_gets_localized_to_ist()
test_csv_with_invalid_ohlc_raises()
test_kite_stub_raises_not_implemented()
```

### Safety-critical guards with teeth — Phase B

| Guard | Teeth test |
|---|---|
| Signal expiry across gaps (B3) | Break: comment out gap check; `test_signal_expires_if_next_candle_is_not_exactly_one_timeframe_later` must fail; restore |
| Market-hours filter (B4) | Break: remove hours filter; `test_candles_outside_market_hours_are_filtered` must fail |

### What I need from you and when
- **At B-4**: a real 5-minute OHLCV CSV (or Kite Connect plan confirmation for historical fetch). I will ask for this explicitly when B-1 through B-3 are committed and passing. I will not ask before that.

### Main risk
CSV column naming and timezone detection edge cases. Real data often has surprises (duplicate timestamps,
weekends, bad OHLC relationships) — the loader must report these clearly rather than silently producing
wrong results.

### Gate criteria
- All existing 213 tests pass + new B tests pass (target: ~225 total)
- Gap, timeframe, and hours tests each have a documented mutation result in the commit message
- `market/historical_data.py` added and tested
- Real-data spot-check documented in `docs/PROJECT_STATUS.md`
- No profitability claims anywhere in docs or code
- Working tree clean, branch merged, tag `phase-b`

### Git
- Branch: `phase-b-backtest`
- Tag: `phase-b`

### Effort: 1–2 sessions (1 for B-1 to B-3; 1 more once CSV is supplied)

---

## PHASE C — DOMAIN HARDENING

### Goal
Fix all safety defects that must exist before broker code is written: B5 (missing OrderStatus values),
B6 (COMPLETE without evidence), B7 (unprotected live position), B8 (daily-loss latch not persisted),
B9 (no signal_id), plus add schema_version, kill switch, and DB queries needed by risk and reconciliation.

### Exact files to create or modify

| Path | Action |
|---|---|
| `models.py` | Modify: add `LAPSED`, `TRIGGER_PENDING`, `PENDING` to OrderStatus; update `TERMINAL_STATUSES`; add `NON_TERMINAL_STATUSES` set |
| `db.py` | Modify: update all CHECK constraints to include new statuses; add `schema_version` table; add migration/recreate path; add `get_open_positions`, `get_unresolved_orders`, `realized_pnl_today`, `count_entries_today`; add kill-switch and daily-loss-latch rows to settings |
| `trading/risk_manager.py` | Modify: `check_entry` reads persisted latch from DB; persists latch when triggered; checks kill switch from DB |
| `tests/test_db.py` | Modify: add tests for new statuses, new queries, latch persistence, kill switch |
| `tests/test_risk_manager.py` | Modify: add tests for persisted latch, kill switch |
| `tests/test_safety.py` | **Create**: restart-recovery and cross-session latch tests |

### Detailed task order

**C1: OrderStatus additions**

Add to `OrderStatus`:
- `LAPSED = "LAPSED"` — terminal (broker auto-cancels an order that was never triggered)
- `PENDING = "PENDING"` — non-terminal (interim: order received by exchange, not yet open)
- `TRIGGER_PENDING = "TRIGGER_PENDING"` — non-terminal (resting stop order)

Update:
- `TERMINAL_STATUSES = frozenset({COMPLETE, REJECTED, CANCELLED, LAPSED})`
- `NON_TERMINAL_STATUSES = frozenset({CREATED, SUBMITTED, PENDING, OPEN, TRIGGER_PENDING, UNKNOWN})`

Update DB CHECK constraint to include all 9 values.

**C2: Legal order-state transitions**

Add `Order.transition_to(new_status, *, broker_order_id=None, fill_price=None)` method that enforces:
- `CREATED` → `SUBMITTED` | `REJECTED` (immediate rejection before submission)
- `SUBMITTED` → `PENDING` | `OPEN` | `TRIGGER_PENDING` | `REJECTED` | `CANCELLED` | `LAPSED`
- `PENDING` → `OPEN` | `TRIGGER_PENDING` | `REJECTED` | `CANCELLED` | `LAPSED`
- `OPEN` → `COMPLETE` | `CANCELLED` | `REJECTED` | `LAPSED`
- `TRIGGER_PENDING` → `OPEN` | `COMPLETE` | `CANCELLED` | `LAPSED`
- `UNKNOWN` → any (because we are resolving an unknown state; do not block recovery)
- Terminal → terminal same-state: allowed (idempotent); terminal → different state: forbidden

In LIVE mode, `COMPLETE` requires `broker_order_id is not None` and `fill_price is not None`.
In PAPER/BACKTEST mode, those are not required (simulated fills).

**C3: Position protection state**

Add a `PositionProtection` enum: `PROTECTED`, `UNPROTECTED`.
A `Position` with `mode == LIVE` and `stop_order_id is None` is `UNPROTECTED`.
Add `Position.protection` property. Add a DB helper `get_unprotected_live_positions()`.
`save_position` for LIVE must set a flag in the DB if `stop_order_id is None`.

**C4: signal_id — deterministic generation and DB deduplication**

`signal_id = sha256(f"{mode.value}:{symbol}:{timeframe}:{closed_candle_iso}:{signal.value}").hexdigest()[:16]`

Add `generate_signal_id(mode, symbol, timeframe, candle_time, signal)` to a new `utils/signal_id.py`.

Add DB UNIQUE constraint on `(mode, signal_id, purpose)` for the orders table, so a duplicate ENTRY or EXIT
order for the same signal_id is rejected at the DB level, not just in application logic.
Stop-loss retries must use a separate `attempt` counter and NOT create a new signal_id.

**C5: DB queries, persisted latch, kill switch**

New DB methods:
```python
realized_pnl_today(mode, day) -> float  # already exists — verify used
count_entries_today(mode, symbol, day) -> int  # new
get_unresolved_orders(mode) -> list[Order]  # non-terminal orders
get_open_positions(mode) -> list[Position]  # already exists — verify
```

Settings keys:
```
"daily_loss_halt:{mode}:{day_iso}"  -> bool
"kill_switch:{mode}"                -> bool (cleared only by explicit user action)
```

`RiskManager.__init__` now requires a `db: Database` parameter. `check_entry` reads the latch and kill
switch from the DB; persists the latch when triggered; checks the kill switch first (before window check).

Order of checks: kill switch → trading window → daily loss → max trades → quantity.

**C6: Schema version and migration**

Add `schema_version` table with a single row. Current version = 1. On `Database.__init__`, if the table
exists but the version is old, raise `DatabaseError("Schema is version X; expected Y. Delete the DB to start fresh.")`.
Since there is no production data yet, recreate is acceptable. Document this in the README.

### Tests to add

`tests/test_db.py` additions:
```python
test_lapsed_is_terminal_and_round_trips_through_db()
test_trigger_pending_is_non_terminal()
test_complete_in_live_mode_requires_broker_order_id_and_fill_price()
test_complete_in_paper_mode_does_not_require_broker_order_id()
test_order_transition_rejects_illegal_state_changes()
test_signal_id_unique_constraint_blocks_duplicate_entry_orders()
test_kill_switch_persists_across_db_instantiation()
test_daily_loss_latch_persists_across_db_instantiation()
test_unprotected_live_position_flagged_correctly()
test_schema_version_mismatch_raises()
```

`tests/test_risk_manager.py` additions:
```python
test_kill_switch_blocks_entry_before_all_other_checks()
test_kill_switch_survives_risk_manager_restart()
test_daily_loss_latch_survives_risk_manager_restart()
```

`tests/test_safety.py` (new):
```python
test_restart_cannot_clear_daily_loss_halt()
# Simulate: create DB, trigger latch, close DB, create new DB instance, check latch still active
test_restart_cannot_clear_kill_switch()
test_kill_switch_requires_explicit_user_clear()
test_position_with_no_stop_order_is_unprotected_in_live()
test_position_with_stop_order_is_protected_in_live()
test_paper_position_does_not_require_stop_order_id()
```

### Safety-critical guards with teeth — Phase C

| Guard | Teeth test |
|---|---|
| `COMPLETE` in LIVE requires broker_order_id+fill | Break: remove the LIVE check in `transition_to`; `test_complete_in_live_mode_requires_broker_order_id_and_fill_price` must fail |
| Latch persists across restart | Break: make latch in-memory only (comment out DB write); `test_daily_loss_latch_survives_risk_manager_restart` must fail |
| Kill switch persists | Break: comment out DB kill-switch check; `test_kill_switch_survives_risk_manager_restart` must fail |
| signal_id DB unique | Break: remove UNIQUE constraint from schema; `test_signal_id_unique_constraint_blocks_duplicate_entry_orders` must fail |

### What I need from you and when
Nothing for Phase C. All pure Python + SQLite.

### Main risk
`RiskManager` now requires a `db` argument. The existing 213 tests (especially the 21 risk manager tests
and 24 DB tests) will need updating since the risk manager's interface changes. I must not break existing
tests. Strategy for this: make `db` optional (default `None`) in `__init__`; when `None`, the in-memory
behaviour is preserved for existing tests; when a real `db` is passed, persistence is used. Document
the distinction.

### Gate criteria
- All tests pass (target ~250 total after additions)
- Each safety guard in Phase C has a documented mutation result
- `git diff` shows no change to `TERMINAL_STATUSES` that removes any existing terminal state
- A fresh `RiskManager(config, db=db)` after a latch event correctly refuses entry (demonstrated by test)
- Working tree clean, branch merged, tag `phase-c`

### Git
- Branch: `phase-c-hardening`
- Tag: `phase-c`

### Effort: 1–2 sessions

---

## PHASE D — BROKER LAYER, MARKET DATA, ENGINE, PAPER TRADING

**This is the riskiest phase.** It creates the most new code, wires all existing components into a
single pipeline for the first time, and must prove parity between the Backtester and the paper engine.

### Goal
Broker interface + MockBroker + PaperBroker; tick→candle builder; signal engine (one shared pipeline for
paper and live); paper trading end-to-end on replayed data; parity test.

### Exact files to create or modify

| Path | Action |
|---|---|
| `trading/broker.py` | **Create**: abstract `Broker` interface |
| `trading/mock_broker.py` | **Create**: scriptable `MockBroker` |
| `trading/paper_broker.py` | **Create**: `PaperBroker` (simulated fills, no kiteconnect) |
| `market/instruments.py` | **Create**: stub (full in Phase E) |
| `market/live_data.py` | **Create**: `ReplayFeed`, `FakeFeed`; tick→closed-candle builder; feed health |
| `market/historical_data.py` | Modify: add `load_kite()` stub (raises `NotImplementedError`) |
| `trading/signal_engine.py` | **Create**: one pipeline for paper and live |
| `app.py` | **Create**: entry point (no UI yet); wires `setup_logging()` |
| `utils/logger.py` | Modify: ensure `setup_logging()` is called from `app.py` |
| `utils/signal_id.py` | **Create**: `generate_signal_id()` (may move here from C) |
| `tests/test_broker.py` | **Create**: MockBroker + PaperBroker tests |
| `tests/test_signal_engine.py` | **Create**: signal engine + parity test |
| `tests/test_live_data.py` | **Create**: ReplayFeed / FakeFeed / candle builder tests |

### Broker interface (`trading/broker.py`)

```python
class Broker(ABC):
    @abstractmethod
    def place_order(self, order: Order) -> str:          # returns broker_order_id
        ...
    @abstractmethod
    def get_order_status(self, broker_order_id: str) -> OrderStatus:
        ...
    @abstractmethod
    def get_positions(self) -> list[Position]:
        ...
    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> None:
        ...
```

### MockBroker

Scriptable responses for each method. Scenarios it must support (each has a test):
- Immediate success fill
- Delayed fill (returns PENDING, then COMPLETE on next poll)
- Immediate rejection
- Cancellation
- Partial fill (returns filled_quantity < requested_quantity)
- Timeout (stays in interim state past the polling deadline)
- Disconnect (raises NetworkException on call)
- Stop-loss placement failure
- Stop fills during cancel (H1 race: cancel returns OK but stop was already COMPLETE)

### PaperBroker

- Uses `SimulatedBroker` logic from `backtest/broker.py` but wrapped in the `Broker` interface
- Takes a `ReplayFeed` as its price source
- Can never import or reference `kiteconnect` — enforced by an AST test (extend the existing architecture guard)
- Fills at the next available feed price (next candle's open), consistent with the backtest assumption

### Signal engine (`trading/signal_engine.py`)

One pipeline, mode-agnostic:
```
closed candle → strategy → dedupe(signal_id, DB) → risk check → broker.place_order()
→ verify fill (poll) → DB write → position update → stop/target placement
→ end-of-day square-off at square_off_time
```

The broker object determines mode behaviour. The engine has no `if live:` branches.

Key behaviours:
- Deduplication: if `signal_id` already exists in DB for this mode, skip without error
- Entry: place → poll until COMPLETE or timeout → if COMPLETE, record position → place stop
- Stop placement: after verified fill, compute stop from FILL price, place stop order, verify TRIGGER_PENDING or OPEN → store stop_order_id. If stop fails: retry once; if still fails: CRITICAL + halt + position = UNPROTECTED
- Exit sequence (H1): cancel stop → verify cancel terminal → if stop was COMPLETE, position is already closed → else place exit → verify → reconcile
- Ambiguous failure (H2): any NetworkException on place_order → look up by signal_id/tag in orders() → if unresolved → UNKNOWN → halt new orders
- Partial fill (H3): stop is sized to filled_quantity; remainder cancelled
- End-of-day: at square_off_time, cancel pending entries, exit open positions (stop-cancel-then-exit sequence)

### ReplayFeed and FakeFeed

`ReplayFeed`: takes a DataFrame of candles; yields one closed candle per tick; used for paper trading on historical data and for tests.
`FakeFeed`: generates synthetic price data; used only in unit tests where real candle data is not needed.

Feed health: tracks time of last tick; if `now - last_tick > stale_threshold` (configurable, default 30s for paper), raises `StaleFeedError`.

### Parity test (D4)

The same sequence of candles run through:
1. `Backtester` with zero slippage and `ChargesConfig.none()`
2. `SignalEngine` with `PaperBroker` with zero slippage and no charges, fed by `ReplayFeed`

Must produce **identical entry/exit timestamps, symbols, and quantities**. If there is a documented,
deliberate difference (e.g., the signal engine never executes on the last candle because it waits for the
next open), that difference must be listed explicitly in `docs/PROJECT_STATUS.md`. The parity test is a
regression guard, not a proof of profitability.

### Tests to add

`tests/test_broker.py`:
```python
test_mock_broker_immediate_success()
test_mock_broker_delayed_fill_returns_pending_then_complete()
test_mock_broker_rejection()
test_mock_broker_timeout_returns_unknown()
test_mock_broker_partial_fill_sized_to_filled_quantity()
test_mock_broker_disconnect_raises()
test_mock_broker_stop_fills_during_cancel_h1_race()
test_paper_broker_never_imports_kiteconnect()   # AST check
test_paper_broker_fills_at_next_candle_open()
```

`tests/test_live_data.py`:
```python
test_replay_feed_yields_closed_candles_in_order()
test_replay_feed_stale_raises_stale_feed_error()
test_fake_feed_produces_valid_ohlcv()
test_candle_builder_emits_only_closed_candles()
```

`tests/test_signal_engine.py`:
```python
test_parity_backtest_vs_paper_engine()
test_duplicate_signal_id_skipped()
test_entry_with_failed_stop_halts_engine_and_marks_unprotected()
test_stop_fills_during_exit_cancel_does_not_double_sell()  # H1
test_ambiguous_place_order_failure_halts_new_orders()      # H2
test_partial_fill_stop_sized_to_filled_qty()               # H3
test_end_of_day_square_off_at_configured_time()
test_engine_is_process_singleton()                          # H4 (early version — full guard in F)
```

### Safety-critical guards with teeth — Phase D

| Guard | Teeth test |
|---|---|
| PaperBroker cannot import kiteconnect | Break: add `import kiteconnect` to paper_broker.py; AST test must fail |
| Duplicate signal_id skipped | Break: remove dedup check; `test_duplicate_signal_id_skipped` must fail |
| Stop failure → UNPROTECTED + halt | Break: comment out halt on stop failure; `test_entry_with_failed_stop_halts_engine_and_marks_unprotected` must fail |
| H1 exit race | Break: remove stop-cancel-before-exit step; `test_stop_fills_during_exit_cancel_does_not_double_sell` must fail |

### What I need from you and when
- **At D-start**: Kite plan confirmation (Connect vs Personal) — only affects whether `load_kite()` is implemented in Phase D or deferred to Phase E. If Personal plan, CSV is the only data source through all phases.
- I will ask for this at the start of Phase D, not before.

### Main risk
Parity test may reveal a genuine design difference between the Backtester and the signal engine (e.g.,
the engine can't execute on the final candle because there is no "next open" until the next tick arrives).
These differences must be documented, not silently hidden. If they are material, Phase D may need a
second session to reconcile.

### Gate criteria
- Paper mode runs end-to-end on replayed data with ≥1 trade
- Parity test passes OR differences explicitly documented
- No `kiteconnect` import reachable from `trading/paper_broker.py` (AST test)
- All safety guards have documented mutation results
- Target: ~290 tests passing
- Working tree clean, branch merged, tag `phase-d`

### Git
- Branch: `phase-d-paper`
- Tag: `phase-d`

### Effort: 3–4 sessions (most complex phase)

---

## PHASE E — KITE BROKER (MOCK-TESTED ONLY)

### Goal
Implement `KiteBroker` — the only module that may import `kiteconnect`. All testing is via MockBroker and
a mocked `kiteconnect` object. Zero real API calls.

### Exact files to create or modify

| Path | Action |
|---|---|
| `trading/kite_broker.py` | **Create**: `KiteBroker(Broker)` |
| `market/instruments.py` | Modify: implement instrument dump + symbol→token lookup |
| `market/historical_data.py` | Modify: implement `load_kite()` if Connect plan confirmed |
| `tests/test_kite_broker.py` | **Create**: all Kite broker tests |
| `README.md` | Modify: add order-type decisions section |

### KiteBroker design

**E1: Live gate**
First line of every order method:
```python
if not self._runtime_mode.is_live_allowed():
    raise RuntimeError("CRITICAL: live order attempted while live is not enabled")
```
Test: live disabled → mocked `kiteconnect.place_order` is never called (assert call count == 0).

**E2: Order lifecycle**
```
place_order()
  → kite.place_order(..., tag=signal_id[:20])   # tag length limit TBD — see OD5
  → capture broker_order_id
  → poll kite.orders() or kite.order_history() with timeout (configurable, default 30s, interval 1s)
  → map status string via _map_status(raw) → OrderStatus
  → if interim after timeout → UNKNOWN → halt + CRITICAL
  → only COMPLETE → create/update position
```

Status mapping (covers all strings from K6 of the prompt, verified against SDK source before coding):
```python
_STATUS_MAP = {
    "OPEN": OrderStatus.OPEN,
    "COMPLETE": OrderStatus.COMPLETE,
    "CANCELLED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "LAPSED": OrderStatus.LAPSED,
    "PUT ORDER REQUEST RECEIVED": OrderStatus.PENDING,
    "VALIDATION PENDING": OrderStatus.PENDING,
    "OPEN PENDING": OrderStatus.PENDING,
    "MODIFY VALIDATION PENDING": OrderStatus.PENDING,
    "MODIFY PENDING": OrderStatus.PENDING,
    "TRIGGER PENDING": OrderStatus.TRIGGER_PENDING,
    "CANCEL PENDING": OrderStatus.PENDING,
    "AMO REQ RECEIVED": OrderStatus.PENDING,
}
# Anything not in this map → OrderStatus.UNKNOWN
```
This map will be **re-verified against the installed kiteconnect SDK source and the official orders page before coding**. If a new status string is found, it is added; no string is silently dropped.

**E3: Stop-loss order**
- Placed immediately after verified entry fill
- Stop price = fill_price * (1 - stop_loss_pct/100), rounded to nearest tick (0.05 by default)
- Order type: `SL-M` (stop-market) — see OD2/E5
- Verify: poll until `TRIGGER_PENDING` or `OPEN` (both healthy for a resting stop)
- If fails: retry once with a 2s delay
- If second failure: CRITICAL log, halt all new trading, mark position UNPROTECTED
- Never pretend a stop is placed when it isn't

**E4: Exit sequence (H1 race)**
```
1. cancel(stop_order_id)
2. poll stop until terminal; if COMPLETE → position already closed → no exit needed → reconcile
3. if CANCELLED/LAPSED → place exit order → poll until COMPLETE
4. reconcile with broker positions after any close
```

**E5: Order typing decision**
This decision will be documented in `README.md` after verification and a recommendation in the E5 commit.
Current recommendation:
- Entry: `MARKET` with `market_protection=-1` (automatic protection)
- Exit: `MARKET` with `market_protection=-1`
- Stop: `SL-M` (stop-market, no limit leg) — simplest, fills in gaps, but can gap through stop price

Trade-off documented: `SL-M` can fill significantly below stop in a gap; `SL` (stop-limit) might not fill in a gap. For intraday NSE equity, SL-M is the safer choice against adverse gap risk. You will confirm this decision before E3 is coded.

**E6: Error mapping**
```python
TokenException       → disconnect halt: block entries, keep resting stops, alert
PermissionException  → clear message: "Check Kite plan or permissions"
IPException (input)  → CRITICAL, non-retried, halting halt: "Unregistered IP — register in Kite developer console"
InputException       → rejection handling: log + record as REJECTED
OrderException       → rejection handling
NetworkException     → H2 flow: look up by tag before any retry
RateLimitException   → backoff (2^n seconds, max 60s), never spam
GeneralException     → log + UNKNOWN if order state unknown
```

### Tests to add (`tests/test_kite_broker.py`)

```python
test_live_disabled_place_order_never_calls_kite()
test_live_enabled_place_order_calls_kite()
test_status_map_covers_all_known_kite_strings()
test_status_map_unknown_string_returns_unknown()
test_interim_status_after_timeout_halts_and_marks_unknown()
test_stop_placement_verify_trigger_pending()
test_stop_fails_twice_marks_unprotected_and_halts()
test_exit_sequence_cancels_stop_before_exit()         # H1
test_stop_fills_during_cancel_skips_exit()            # H1 race
test_ambiguous_network_failure_looks_up_by_tag()      # H2
test_partial_fill_stop_sized_to_filled_qty()          # H3
test_token_exception_triggers_disconnect_halt()
test_ip_rejection_is_critical_and_non_retried()
test_rate_limit_triggers_backoff()
test_tag_carries_signal_id()
```

### Safety-critical guards with teeth — Phase E

| Guard | Teeth test |
|---|---|
| Live gate: disabled → no kite.place_order call | Break: remove is_live_allowed() check; `test_live_disabled_place_order_never_calls_kite` must fail |
| IP rejection non-retried | Break: add retry on IPException; `test_ip_rejection_is_critical_and_non_retried` must fail |
| Stop fail → UNPROTECTED + halt | Break: comment out second-failure halt; `test_stop_fails_twice_marks_unprotected_and_halts` must fail |
| H1: stop-cancel-before-exit | Break: remove cancel step; `test_exit_sequence_cancels_stop_before_exit` must fail |

### What I need from you and when
- **Before E3**: confirm order type choices (MARKET entry/exit, SL-M stop) — I will present these in an E5 recommendation commit and stop for your confirmation before coding E3
- **Before E-start**: Kite plan (if not already confirmed in Phase D)
- I will ask for these at the right moment, not before

### Main risk
The mocked kiteconnect may not faithfully replicate real API edge cases. The status strings may have changed.
I will re-verify the full status string list from the installed SDK source before coding the status map.

### Gate criteria
- Zero real kiteconnect calls (verified by mock call counts)
- All E tests pass with documented mutation results for each safety guard
- Order-type decision documented in README
- Status map verified against SDK source (commit cites where it was checked)
- Target: ~330 tests passing
- Working tree clean, branch merged, tag `phase-e`

### Git
- Branch: `phase-e-kite-broker`
- Tag: `phase-e`

### Effort: 2–3 sessions (2 if plan decisions (OD2, OD5) are confirmed quickly; 3 if rework needed)

---

## PHASE F — RECONCILIATION, RECOVERY, NETWORK FAILURE, EMERGENCY STOP

### Goal
Startup reconciliation; periodic reconciliation; network/feed failure handling; emergency stop (H5);
single-instance guard (H4); persisted kill switch.

### Exact files to create or modify

| Path | Action |
|---|---|
| `trading/reconciliation.py` | **Create**: startup + periodic reconcile |
| `trading/signal_engine.py` | Modify: startup reconcile hook; feed-health check; reconnect flow |
| `trading/emergency_stop.py` | **Create**: emergency stop + kill switch management |
| `utils/instance_guard.py` | **Create**: single-instance guard (lock file + DB heartbeat) |
| `tests/test_reconciliation.py` | **Create** |
| `tests/test_emergency_stop.py` | **Create** |
| `tests/test_instance_guard.py` | **Create** |

### Detailed designs

**F1: Startup reconciliation**
```
1. connect to Kite (profile() call — works on both plans)
2. fetch broker positions → compare with DB open positions
3. fetch today's broker orders → compare with DB orders for today
4. any mismatch (quantity, symbol, unknown order, unprotected position) → SAFE MODE
5. SAFE MODE: no new live orders; show "RECONCILIATION ERROR" in UI; no guessing
6. only after clean reconcile → allow trading
```

Periodic: every N minutes (configurable, default 5) repeat steps 2–4 during live trading.

**F2: Network/feed failure**
- On `NetworkException`: block new orders, log CRITICAL, do NOT cancel protective stops
- Wait for reconnect (exponential backoff, configurable max)
- On reconnect: re-run reconciliation (F1 steps 2–4) before allowing any new orders
- Stale feed (last tick too old): block entries, log WARNING, do not block stop monitoring

**F3: Emergency stop (H5)**
```
EMERGENCY STOP:
  1. Set kill switch in DB (persisted)
  2. Block all new strategy signals
  3. Cancel pending ENTRY orders only (not stops, not exits)
  4. Leave open positions and their protective stops untouched
  5. Log CRITICAL "Emergency stop activated"
  6. UI shows EMERGENCY STOP ACTIVE banner
```

Flattening (closing open positions) is a separate, explicit, confirmed user action. The emergency stop
does NOT flatten. The UI will have a separate "FLATTEN ALL POSITIONS" button requiring confirmation.

Kill switch: stored in `settings` table as `kill_switch:{mode}`. Cleared only by an explicit
`clear_kill_switch(mode)` call that requires a confirmation token (a short string the user must type).

**F4: Single-instance guard (H4)**
- On startup: write a lock row to the settings table: `instance_lock:{mode}` with a process ID and timestamp
- Refresh the timestamp via a heartbeat every 30s
- On startup, if a lock row exists and its timestamp is < 60s old, refuse to start: "Another instance of the live engine is running (PID X)"
- If the lock is stale (>60s), assume the previous process crashed and take over
- On clean shutdown: remove the lock row

### Tests to add

`tests/test_reconciliation.py`:
```python
test_clean_reconcile_allows_trading()
test_position_mismatch_triggers_safe_mode()
test_unknown_broker_order_triggers_safe_mode()
test_unprotected_position_triggers_safe_mode()
test_restart_mid_position_reconciles_correctly()
test_stale_feed_blocks_new_entries_but_not_stop_monitoring()
```

`tests/test_emergency_stop.py`:
```python
test_emergency_stop_sets_kill_switch()
test_emergency_stop_cancels_pending_entries_only()
test_emergency_stop_does_not_cancel_protective_stops()   # H5
test_emergency_stop_does_not_close_positions()
test_kill_switch_requires_confirmation_token_to_clear()
test_flatten_is_separate_explicit_action()
```

`tests/test_instance_guard.py`:
```python
test_second_live_engine_refuses_start()          # H4
test_stale_lock_is_overrideable()
test_clean_shutdown_releases_lock()
```

### Safety-critical guards with teeth — Phase F

| Guard | Teeth test |
|---|---|
| Emergency stop does NOT cancel protective stops | Break: make emergency stop cancel all open orders; `test_emergency_stop_does_not_cancel_protective_stops` must fail |
| Second live engine refuses | Break: remove lock check; `test_second_live_engine_refuses_start` must fail |
| Kill switch requires confirmation | Break: remove confirmation check; `test_kill_switch_requires_confirmation_token_to_clear` must fail |
| Mismatch → SAFE MODE (no new orders) | Break: remove safe-mode gate; `test_position_mismatch_triggers_safe_mode` must fail |

### What I need from you and when
Nothing for Phase F — all testable with MockBroker.

### Main risk
Windows lock-file behaviour differs from POSIX. The DB-heartbeat approach is more portable than file locks
on Windows. I will use the DB approach by default. File-lock approach is a fallback if DB approach proves
unreliable.

### Gate criteria
- All F tests pass with documented mutation results
- Emergency stop leaves protective stops intact (proven by test with deliberate break)
- Second instance refuses to start (proven by test)
- Startup reconciliation tested with mismatch scenarios
- Target: ~370 tests passing
- Working tree clean, branch merged, tag `phase-f`

### Git
- Branch: `phase-f-safety`
- Tag: `phase-f`

### Effort: 1–2 sessions

---

## PHASE G — STREAMLIT UI

### Goal
Six pages; process-wide engine singleton; live page with 4-step confirmation; all safety banners from
persisted state; STOP ALL TRADING always visible.

### Exact files to create or modify

| Path | Action |
|---|---|
| `app.py` | Modify: wire Streamlit; mount engine singleton |
| `ui/engine_singleton.py` | **Create**: process-wide singleton (survives Streamlit reruns) |
| `ui/dashboard.py` | **Create**: current position, today's P&L, status banners |
| `ui/backtest_page.py` | **Create**: CSV upload, config form, results display |
| `ui/paper_page.py` | **Create**: paper trading controls |
| `ui/live_page.py` | **Create**: 4-step live confirmation; visually distinct; always shows STOP |
| `ui/settings_page.py` | **Create**: config form (validates via TradingConfig; cannot persist live flag) |
| `ui/logs_page.py` | **Create**: filtered log viewer from DB |
| `requirements.txt` | Modify: add `streamlit>=1.35` |
| `tests/test_ui.py` | **Create**: AppTest-based tests |

### Live page — 4-step confirmation (non-negotiable UI flow)

```
Step 1: Select "LIVE" from mode dropdown
Step 2: Checkbox "I understand this will place real orders with real money"
Step 3: Type the exact trading symbol to confirm (e.g., "HDFCBANK")
Step 4: Click "ENABLE LIVE TRADING"
```

After step 4: shows current strategy, symbol, capital, risk %, max daily loss, max trades, current position.
"STOP ALL TRADING" button is always visible on every page, in a fixed sidebar location.

CRITICAL/SAFE MODE/DAILY LOSS LIMIT REACHED/MAXIMUM DAILY TRADES REACHED banners come from the DB
settings table — they are not in-memory-only. A page reload or a new tab will show the correct banner.

### Engine singleton (H4 partial)

```python
# ui/engine_singleton.py
import threading
_engine_lock = threading.Lock()
_engine = None

def get_engine(config, mode, db) -> SignalEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = SignalEngine(config, mode, db)
    return _engine
```

A Streamlit rerun calls `get_engine()` again but gets the same instance. The process-level instance guard
(Phase F) still operates — a second `streamlit run` process on the same DB will be rejected at startup.

### Tests to add (`tests/test_ui.py`)

AppTest limitations are real: it cannot test JavaScript interactions, file uploads, or multi-process
scenarios. The following are what AppTest can cover:
```python
test_stop_all_trading_always_visible()
test_live_page_step1_requires_live_mode_selection()
test_live_page_step3_rejects_wrong_symbol()
test_critical_banner_shows_from_db_state()
test_settings_cannot_set_live_flag_to_true()
test_settings_validates_through_trading_config()
```

The following must be tested manually and documented in `docs/PROJECT_STATUS.md`:
- Second browser tab does not create a second engine
- Page reload preserves live confirmation state correctly

### What I need from you and when
Nothing for Phase G.

### Main risk
Streamlit session state + threading + the singleton pattern can produce subtle race conditions. The
engine must run in a background thread, not the Streamlit main thread. I will use `threading.Thread`
with a daemon flag and a queue for UI→engine communication. If this proves unreliable, the fallback
is a subprocess model (engine runs as a separate process; UI polls DB for state).

### Gate criteria
- All 6 pages render without error
- Live page requires all 4 steps (AppTest verifies steps 1 and 3; manual verification documents 2 and 4)
- All banners come from DB (verified by writing a DB row and checking the banner appears on fresh load)
- Settings cannot enable live flag (AppTest)
- Target: ~390 tests passing (AppTest adds ~6)
- Working tree clean, branch merged, tag `phase-g`

### Git
- Branch: `phase-g-ui`
- Tag: `phase-g`

### Effort: 1 session (UI is presentation only; core logic already tested)

---

## PHASE H — INTEGRATION, DOCUMENTATION, CLEAN-UP, FINAL AUDIT

### Goal
End-to-end failure-scenario integration tests; full README; clean-up; final audit; live-readiness checklist.

### Exact files to create or modify

| Path | Action |
|---|---|
| `tests/test_integration.py` | **Create**: end-to-end scenarios |
| `README.md` | Rewrite: full documentation |
| `docs/LIVE_RUNBOOK.md` | **Create**: step-by-step supervised first-order procedure |
| `docs/PROJECT_STATUS.md` | Update: final |
| `docs/MASTER_PLAN.md` | Update: mark complete |
| Misc source | Clean-up: remove any dead code vulture flags |

### Integration tests (`tests/test_integration.py`)

```python
test_full_paper_session_from_csv_to_trade_record()
test_stop_loss_failure_halts_new_trading()
test_network_drop_mid_trade_blocks_new_entries()
test_restart_mid_position_reconciles_and_resumes_correctly()
test_reconciliation_mismatch_triggers_safe_mode()
test_emergency_stop_leaves_protective_stops()
test_end_of_day_square_off_verified_flat()
```

### Final audit checklist (H4)

The audit checks each item, marks PASS/FAIL, and records the test that proves it:

| Item | Proven by |
|---|---|
| Strategy cannot import broker/DB/engine | AST test (existing) |
| No bare `except:` outside DBLogHandler | AST scan |
| No secrets in code, DB, or git | test_hygiene + `git log -S KEY` scan |
| All safety guards tested with deliberate break | Per-phase mutation records in commit messages |
| LIVE gate checked inside broker methods | E1 test |
| Kill switch survives restart | C+F tests |
| Emergency stop does not cancel protective stops | F test |
| Reconciliation mismatch → SAFE MODE | F test |
| Parity: paper engine == backtest | D test |
| Live-readiness checklist honestly ticked | Manual review |

### Live-readiness checklist (in README, honestly ticked)

```
[ ] Backtest on real data spot-checked (Phase B)
[ ] Strategy behaviour verified (Phases 1-3, existing)
[ ] Paper trading completed (Phase D)
[ ] Paper/live signal parity checked (Phase D)
[ ] Risk limits tested (Phase C)
[ ] Order-status verification tested (Phase E)
[ ] Stop-loss failure tested (Phase E)
[ ] Network failure tested (Phase F)
[ ] Restart recovery tested (Phase F)
[ ] Reconciliation tested (Phase F)
[ ] Emergency stop tested (Phase F)
[ ] Credentials secured (.env, never committed)
[ ] Static IP registered (your action)
[ ] Data plan confirmed (your action)
[ ] LIVE explicitly enabled by the user (your action, each session)
```

Items marked `your action` cannot be ticked by any test — they require manual steps the developer performs.

### What I need from you and when
Nothing for H — but the live runbook includes steps only you can execute (registering IP, running the first supervised order).

### Gate criteria
- All integration tests pass
- Audit document in `docs/PROJECT_STATUS.md` shows no FAIL items
- No bare `except:` in any file except the intentional `DBLogHandler.emit` one
- README covers: install, env vars, Kite setup, daily token, CSV backtest, paper, live confirmation, risk controls, emergency stop, limitations, testing, Git workflow
- Live-readiness checklist in README is honest — items not tested by the suite are not ticked
- Working tree clean, branch merged, tag `phase-h`

### Git
- Branch: `phase-h-final`
- Tag: `phase-h`

### Effort: 1 session

---

## CORRECTIONS TO THE ORIGINAL PROMPT (section 0-11)

The following items in the original prompt are now known to be wrong or need revision:

| Section | Item | Correction |
|---|---|---|
| §2 | "Python 3.12.3" | Actual: **3.11.9** on this machine |
| §2 | "pandas 3.0.2, numpy 2.4.4" | Actual on this machine: **pandas 2.2.2, numpy 1.26.4** — the prompt numbers appear to be from a different machine or a future test run. The requirements.txt pinned in Phase A must be corrected. |
| §2 | "210 passed (also with -W error)" | Actual baseline was **209 passed, 1 failed** at the root directory the prompt was tested from, for the reason documented in Gate A Item 2. The 210-passed figure appears to be correct when run from the project root — it just was not run from there in my initial check. |
| §4 B2 | ".gitignore lists '*.db' only" | At handover, `.gitignore` had 6 entries: `.env`, `*.db`, `logs/`, `__pycache__/`, `.pytest_cache/`. No `*.db-wal`, `*.db-shm` etc. This is correctly described in the prompt. |
| §3 K8 | "Historical data has per-request date-range and rate limits (verify for interval '5minute')" | Not yet re-verified. Will verify from installed SDK source at Phase E start. |
| §3 K5 | "Access token expires around 06:00 IST" | Not yet re-verified. Will verify at Phase E start. |
| §3 K7 | "tag length limit" | Not yet determined. Will check installed SDK source at Phase E start (OD5). |
| §6 Phase A A6 | "Ask me for the private GitHub repo URL and whether to add the optional CI workflow" | These questions are still open. They belong at Gate A close, not during Phase B. |
