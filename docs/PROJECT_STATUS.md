# PROJECT STATUS
Last updated: 2026-09-25, after Phase B closeout

## Environment
Python: 3.11.9  pandas: 2.2.2  numpy: 1.26.4  pytest: 9.1.1  OS: Windows 11 (win32, CPython MSC v.1938 64-bit)

Additional packages: kiteconnect NOT INSTALLED  streamlit NOT INSTALLED

## Git State
Current branch: main
Branches: main, phase-a-baseline, phase-b-backtest
Tags: handover-phase3 (commit 16eea14), phase-a (commit 58e4ae1), phase-b (commit pending merge)
Latest commit on main: 0f434b5 docs: record pushed status in PROJECT_STATUS.md
Working tree clean: Y
Pushed to remote: Y (origin/main and tags up to phase-a pushed; phase-b to be pushed upon gate)
Remote (origin): https://github.com/jumailtaj/trading_app.git

## Phase Completion Table

| Phase | Status      | Branch            | Tag               | Commit  | Tests (pass/fail) | Gate Met | Date       |
|-------|-------------|-------------------|-------------------|---------|-------------------|----------|------------|
| A     | DONE        | phase-a-baseline  | phase-a (58e4ae1) | 58e4ae1 | 213 / 0           | Y        | 2026-09-25 |
| B     | DONE        | phase-b-backtest  | phase-b           | 59f048c | 224 / 0           | Y        | 2026-09-25 |
| C     | IN PROGRESS | phase-c-hardening | —                 | —       | —                 | —        | —          |
| D     | NOT STARTED | —                 | —                 | —       | —                 | —        | —          |
| E     | NOT STARTED | —                 | —                 | —       | —                 | —        | —          |
| F     | NOT STARTED | —                 | —                 | —       | —                 | —        | —          |
| G     | NOT STARTED | —                 | —                 | —       | —                 | —        | —          |
| H     | NOT STARTED | —                 | —                 | —       | —                 | —        | —          |

## Current Phase
Phase C — Domain Hardening (IN PROGRESS on `phase-c-hardening`).
Tasks:
1. `models.py`: Add `LAPSED`, `PENDING`, `TRIGGER_PENDING` to `OrderStatus`. Update `TERMINAL_STATUSES` and `NON_TERMINAL_STATUSES`. Add `PositionProtection` enum and `Position.protection` property. Implement `Order.transition_to(...)`.
2. `utils/signal_id.py`: Deterministic SHA256 `signal_id` generator.
3. `db.py`: Update CHECK constraints. Add `UNIQUE (mode, signal_id, purpose)` on `orders`. Add `schema_version` table (v1). Add `count_entries_today()`, `get_unresolved_orders()`, `get_unprotected_live_positions()`. Support persistent kill switch and daily loss latch in settings.
4. `trading/risk_manager.py`: Accept `db: Optional[Database] = None`. Enforce check priority: kill switch -> trading window -> daily loss latch -> max trades -> quantity.
5. `tests/test_safety.py` & unit tests in `tests/test_db.py`, `tests/test_risk_manager.py`.
6. Mutation testing on 4 safety guards.

## Next Phase
Phase D — Broker Layer, Market Data, Engine, Paper Trading.
Depends on Phase C gate closure.

## Open Decisions / Blockers

| ID  | Decision / Blocker | Owner | When needed |
|-----|--------------------|-------|-------------|
| OD1 | Kite plan: Connect (data) or Personal (no data)? | User | Phase D start |
| OD2 | Order types for entry/exit/stop (MARKET/MARKET/SL-M recommended) | User | Phase E, task E5 |
| OD3 | Static IP registered in Zerodha developer console? | User | Phase E start |
| OD4 | Does `algo_id` field need to be set for retail API orders? | Agent (verify SDK) | Phase E start |
| OD5 | Kite `tag` field length limit | Agent (verify SDK) | Phase E start |
| OD8 | Real 5-minute OHLCV CSV file | User | Phase B spot-check (deferred to Phase D/E) |

## Known Deviations From Master Plan

| # | Deviation | Reason | Status |
|---|-----------|--------|--------|
| D1 | Project root is `trading_app/trading_app/`, not `trading_app/` | Handover placed code one level deeper in Downloads folder. No files moved. | Accepted |
| D2 | Python version is 3.11.9, not 3.12.3 as stated in the original prompt | Measured from actual environment | Accepted; docs/MASTER_PLAN.md corrects this |
| D3 | pandas 2.2.2 / numpy 1.26.4, not 3.0.2 / 2.4.4 as stated in the original prompt | Measured from actual environment | Accepted; requirements.txt updated in Phase B |
| D4 | `requirements.txt` pinned to wrong versions in Phase A commit | Corrected in Phase B commit `59f048c` to `pandas>=2.2.2`, `numpy>=1.26.4` | Resolved |
| D5 | docs/MASTER_PLAN.md created but not yet committed | Committed in `44c9a9a` | Resolved |
| D6 | The original prompt listed `test_backtest_and_risk_code_cannot_reach_a_real_broker_or_network` as failing (209/210) | Root cause: prompt baseline was run from wrong directory. No test was weakened. | Resolved |
| D7 | Task B-4 (manual spot-check against real CSV) deferred | User explicitly instructed to proceed without stopping for B-4; will be performed when CSV is provided | Accepted |

## Protocol (established by bootstrap — in force for every phase)

RULE 1: At the START of every future phase or session, before touching any file, read this file
in full. If the phase immediately before the one about to start is not DONE, or its gate was
not met, STOP and report the mismatch. Do not start the later phase anyway.

RULE 2: At the END of every phase, before the phase report is sent, UPDATE this file to reflect
exactly what changed. Flip a phase to DONE only when its gate criteria are verified met. Commit
the updated file as part of the phase's normal commits before declaring the phase closed.

RULE 3: Never mark a phase DONE in this file if its gate was not actually met. No claiming
something is complete without evidence. If uncertain, mark IN PROGRESS and list what is missing.
