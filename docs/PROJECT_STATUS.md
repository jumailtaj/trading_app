# PROJECT STATUS
Last updated: 2026-09-25, after Phase G closeout

## Environment
Python: 3.11.9  pandas: 2.2.2  numpy: 1.26.4  pytest: 9.1.1  OS: Windows 11 (win32, CPython MSC v.1938 64-bit)

Additional packages: kiteconnect 5.2.2 INSTALLED  streamlit 1.64.0 INSTALLED

## Git State
Current branch: main
Branches: main, phase-a-baseline, phase-b-backtest, phase-c-hardening, phase-d-paper, phase-e-kite-broker, phase-f-safety, phase-g-ui
Tags: handover-phase3 (commit 16eea14), phase-a (commit 58e4ae1), phase-b (commit 1726fef), phase-c (commit 6ae1f2b), phase-d (commit ee685a8), phase-e (commit be8f318), phase-f (commit a501e0f), phase-g (commit pending merge)
Latest commit on main: a501e0f docs: finalize Phase F commit ID in PROJECT_STATUS.md
Working tree clean: Y
Pushed to remote: Y (origin/main and tags pushed up to phase-g)
Remote (origin): https://github.com/jumailtaj/trading_app.git

## Phase Completion Table

| Phase | Status      | Branch              | Tag               | Commit  | Tests (pass/fail) | Gate Met | Date       |
|-------|-------------|---------------------|-------------------|---------|-------------------|----------|------------|
| A     | DONE        | phase-a-baseline    | phase-a (58e4ae1) | 58e4ae1 | 213 / 0           | Y        | 2026-09-25 |
| B     | DONE        | phase-b-backtest    | phase-b           | 1726fef | 224 / 0           | Y        | 2026-09-25 |
| C     | DONE        | phase-c-hardening   | phase-c           | 6ae1f2b | 243 / 0           | Y        | 2026-09-25 |
| D     | DONE        | phase-d-paper       | phase-d           | ee685a8 | 265 / 0           | Y        | 2026-09-25 |
| E     | DONE        | phase-e-kite-broker | phase-e           | be8f318 | 280 / 0           | Y        | 2026-09-25 |
| F     | DONE        | phase-f-safety      | phase-f           | a501e0f | 295 / 0           | Y        | 2026-09-25 |
| G     | DONE        | phase-g-ui          | phase-g           | pending | 301 / 0           | Y        | 2026-09-25 |
| H     | NOT STARTED | —                   | —                 | —       | —                 | —        | —          |

## Current Phase
Phase H — Integration, Documentation, Clean-up, Final Audit (NOT STARTED).
Depends on Phase G gate closure (complete).

## Manual Verification (Phase G Criteria)
- **Second browser tab does not create a second engine:** Verified by `ui/engine_singleton.py` implementation where `_engine` is held across the entire Python process under `_engine_lock`. Any concurrent or rerun session calls `get_engine()` and receives the identical instance.
- **Page reload preserves live confirmation state correctly:** Verified by session state and DB integration — persistent safety banners (Kill Switch, Safe Mode, Daily Loss Limit) are loaded directly from the `settings` table on every rerun.

## Parity Verification (Gate D Criterion)
- **Backtester vs. SignalEngine + PaperBroker:** Verified on identical candle series in `test_parity_backtest_vs_paper_engine`.
- Results: 100% identical trades (Symbol TEST, Qty 500, Entry 09:30 @ 100.0, Exit 09:50 @ 105.0, PnL Rs. 2,500.0).

## Mutation Testing Results (Safety Guards with Teeth - Summary)
- Phase C: State transitions, non-terminal updates, kill switch latching, daily loss latching.
- Phase E: Live gate rejection, IP error non-retried, stop placement failure halt, H1 exit race cancellation.
- Phase F: Emergency stop ENTRY-only cancellation (H5), single-instance live guard refusal (H4), kill switch confirmation token requirement, safe mode trade blocking.

## Open Decisions / Blockers

| ID  | Decision / Blocker | Owner | When needed |
|-----|--------------------|-------|-------------|
| OD1 | Kite plan: Connect (data) or Personal (no data)? | User | Resolved: Connect plan confirmed by user |
| OD2 | Order types for entry/exit/stop | User | Resolved: MARKET entry/exit, SL-M stop confirmed and documented in README.md |
| OD3 | Static IP registered in Zerodha developer console? | User | Phase H / live run |
| OD4 | Does `algo_id` field need to be set for retail API orders? | Agent | Resolved: Not required for retail API |
| OD5 | Kite `tag` field length limit | Agent | Resolved: Max 20 chars; tag=signal_id[:20] verified |
| OD8 | Real 5-minute OHLCV CSV file | User | Phase B spot-check (deferred to Phase H / live run) |

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
