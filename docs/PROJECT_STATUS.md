# PROJECT STATUS
Last updated: 2026-09-25, after Phase A (gate audit — ONE-TIME BOOTSTRAP)

## Environment
Python: 3.11.9  pandas: 2.2.2  numpy: 1.26.4  pytest: 9.1.1  OS: Windows 11 (win32, CPython MSC v.1938 64-bit)

Additional packages: kiteconnect NOT INSTALLED  streamlit NOT INSTALLED

## Git State
Current branch: main
Branches: main, phase-a-baseline
Tags: handover-phase3 (commit 16eea14), phase-a (commit 58e4ae1)
Latest commit on main: 58e4ae1 feat(phase-a): baseline hygiene — B1/B10/B11 fixes, R1 guard, docs
Working tree clean: N — one untracked file: docs/MASTER_PLAN.md (not yet staged or committed)
Pushed to remote: N — no remote configured

## Phase Completion Table

| Phase | Status      | Branch            | Tag               | Commit  | Tests (pass/fail) | Gate Met | Date       |
|-------|-------------|-------------------|-------------------|---------|-------------------|----------|------------|
| A     | IN PROGRESS | phase-a-baseline  | phase-a (58e4ae1) | 58e4ae1 | 213 / 0           | N        | 2026-09-25 |
| B     | NOT STARTED | —                 | —                 | —       | —                 | —        | —          |
| C     | NOT STARTED | —                 | —                 | —       | —                 | —        | —          |
| D     | NOT STARTED | —                 | —                 | —       | —                 | —        | —          |
| E     | NOT STARTED | —                 | —                 | —       | —                 | —        | —          |
| F     | NOT STARTED | —                 | —                 | —       | —                 | —        | —          |
| G     | NOT STARTED | —                 | —                 | —       | —                 | —        | —          |
| H     | NOT STARTED | —                 | —                 | —       | —                 | —        | —          |

## Current Phase
Phase A — IN PROGRESS. Two items remain before Gate A can close:

1. **requirements.txt version pins are wrong for this machine.**
   `requirements.txt` pins `pandas>=3.0.2` and `numpy>=2.4.4`, but the installed and tested
   versions are `pandas 2.2.2` and `numpy 1.26.4`. Installing fresh from this file would fail or
   pull incompatible versions. Must be corrected to match what is actually installed and tested:
   `pandas>=2.2.2`, `numpy>=1.26.4`.

2. **docs/MASTER_PLAN.md is untracked.**
   It exists on disk (created in the master-plan response) but has never been committed to git.
   It must be staged and committed before the working tree is declared clean.

Gate A can only be marked DONE when both of these are fixed and verified:
- `requirements.txt` pins match installed versions
- `git status` shows working tree clean (no untracked files)
- `python -m pytest` still shows 213 passed
- A6 items (GitHub URL, CI workflow decision) have been asked and answered or explicitly deferred

## Next Phase
Phase B — Backtest Correctness and Real-Data Readiness.
Depends on:
- Phase A gate fully met (DONE)
- User provides a real 5-minute OHLCV CSV file, OR confirms Kite Connect plan for historical data
  (will be asked at the start of Phase B, not before)

## Open Decisions / Blockers

| ID  | Decision / Blocker | Owner | When needed |
|-----|--------------------|-------|-------------|
| OD1 | Kite plan: Connect (data) or Personal (no data)? | User | Phase B start |
| OD2 | Order types for entry/exit/stop (MARKET/MARKET/SL-M recommended) | User | Phase E, task E5 |
| OD3 | Static IP registered in Zerodha developer console? | User | Phase E start |
| OD4 | Does `algo_id` field need to be set for retail API orders? | Agent (verify SDK) | Phase E start |
| OD5 | Kite `tag` field length limit | Agent (verify SDK) | Phase E start |
| OD6 | Private GitHub repo URL | User | Phase A close (A6) |
| OD7 | Add optional CI workflow (GitHub Actions)? | User | Phase A close (A6) |
| OD8 | Real 5-minute OHLCV CSV file | User | Phase B, task B-4 |

## Known Deviations From Master Plan

| # | Deviation | Reason | Status |
|---|-----------|--------|--------|
| D1 | Project root is `trading_app/trading_app/`, not `trading_app/` | Handover placed code one level deeper in Downloads folder. No files moved. | Accepted |
| D2 | Python version is 3.11.9, not 3.12.3 as stated in the original prompt | Measured from actual environment | Accepted; docs/MASTER_PLAN.md corrects this |
| D3 | pandas 2.2.2 / numpy 1.26.4, not 3.0.2 / 2.4.4 as stated in the original prompt | Measured from actual environment | Accepted; requirements.txt must be corrected (Gate A defect) |
| D4 | `requirements.txt` pinned to wrong versions in Phase A commit | Agent error: Phase A set pins to prompt-claimed versions, not installed versions | Open defect — must fix before Gate A closes |
| D5 | docs/MASTER_PLAN.md created but not yet committed | Created in master-plan response; git add/commit not yet performed | Open — must fix before Gate A closes |
| D6 | The original prompt listed `test_backtest_and_risk_code_cannot_reach_a_real_broker_or_network` as failing (209/210) but the test was NOT changed | Root cause: prompt baseline was run from wrong directory. No test was weakened. | Resolved |

## True Phase A Git History (plain statement)

The git history is honest and correctly ordered:

- `16eea14` (tag: `handover-phase3`, 2026-09-25): Pristine handover code + corrected .gitignore ONLY.
  This is the clean pre-edit snapshot. It was committed first, before any Phase A changes.
  All handover files are present (34 files). The `.gitignore` addition (WAL/SHM/venv/data entries)
  is the only change from the literal handover state.

- `a5d1509` through `e12e65e`: Phase A changes (B1 fix, B10 fix, B11 fix, hygiene tests, docs).
  All committed after `handover-phase3`. The ordering is correct and verifiable by
  `git diff handover-phase3 HEAD`.

- `58e4ae1` (tag: `phase-a`): Merge commit from `phase-a-baseline` into `main`.

The original prompt's concern about "editing files before git init" was valid during an early
session where git was not yet installed. That error was corrected: all edits were reverted,
git was installed, and the sequence was redone in the correct order. The history above is the result.

No rebase, no force-push, no history rewrite has occurred.

## Protocol (established by this bootstrap — in force for every phase from here)

RULE 1: At the START of every future phase or session, before touching any file, read this file
in full. If the phase immediately before the one about to start is not DONE, or its gate was
not met, STOP and report the mismatch. Do not start the later phase anyway.

RULE 2: At the END of every phase, before the phase report is sent, UPDATE this file to reflect
exactly what changed. Flip a phase to DONE only when its gate criteria are verified met. Commit
the updated file as part of the phase's normal commits before declaring the phase closed.

RULE 3: Never mark a phase DONE in this file if its gate was not actually met. No claiming
something is complete without evidence. If uncertain, mark IN PROGRESS and list what is missing.
