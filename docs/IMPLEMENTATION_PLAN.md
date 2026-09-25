# IMPLEMENTATION PLAN — Simple Algo Trading System

## 1. VERIFICATION

**Confirmed correct:**
- 210 tests, 209 passing (one fails — see below). Python **3.11.9** (prompt says 3.12.3 — **WRONG**). pandas 3.0.2, numpy 2.4.4, pytest 9.1.1 — confirmed.
- EMA 9/21 crossover, 63-candle warm-up, no look-ahead: confirmed.
- `backtest/broker.py`, `backtest/metrics.py`, `config.py` TradingConfig: confirmed complete and tested.
- `RuntimeMode` starts PAPER, never persisted, enable needs `confirmed=True`: confirmed.
- `models.py` — missing `LAPSED` and interim statuses (B5): confirmed.
- `db.py` — `get_logs("TRACE")` raises `KeyError` (B1): confirmed (key not in `_LEVELS` dict).
- `.gitignore` is 6 lines, missing WAL/SHM/journal/venv/data (B2): confirmed.
- `RiskManager` daily-loss latch is in-memory only (B8): confirmed.
- `signal_id` is DB column but never generated (B9): confirmed.

**Wrong or outdated in the prompt:**
- **Python version**: prompt says 3.12.3; actual is **3.11.9**.
- **Test count**: prompt says "210 passed"; actual is **209 passed, 1 failed** (`test_backtest_and_risk_code_cannot_reach_a_real_broker_or_network`). This test asserts `len(files) >= 5` but `backtest/` currently has only `broker.py`, `engine.py`, `metrics.py`, `__init__.py` = 4 files, and `trading/risk_manager.py` = 1 file, total 5 but the glob only picks `.py` in `backtest/` = 3 files + risk_manager = 4 >= 5 is **false**.
- **numpy lower bound** in `requirements.txt` is `>=1.24` but prompt says `>=1.24` — confirmed.

---

## 2. BASELINE

| Component | File(s) | State |
|---|---|---|
| Python env | — | 3.11.9 / pandas 3.0.2 / numpy 2.4.4 |
| TradingConfig + RuntimeMode | `config.py` | COMPLETE |
| BrokerCredentials / load_credentials | `config.py` | COMPLETE |
| Signal/Side/Order models | `models.py` | IMPLEMENTED BUT BROKEN (missing LAPSED/interim statuses, B5) |
| Database | `db.py` | IMPLEMENTED BUT NOT TESTED end-to-end; unit-tested in isolation; B1 (KeyError on unknown log level) |
| EMA strategy | `strategy/ema_strategy.py` | COMPLETE |
| Strategy base | `strategy/base_strategy.py` | COMPLETE |
| Backtest engine | `backtest/engine.py` | IMPLEMENTED BUT NOT TESTED on real data; B3/B4 gaps |
| Simulated broker | `backtest/broker.py` | COMPLETE |
| Metrics | `backtest/metrics.py` | COMPLETE |
| Charges | `utils/charges.py` | COMPLETE (estimated) |
| Risk manager | `trading/risk_manager.py` | PARTIALLY IMPLEMENTED (no persistence, B8) |
| Logger | `utils/logger.py` | IMPLEMENTED BUT NOT TESTED from entry point; `setup_logging()` never called |
| `.gitignore` | `.gitignore` | IMPLEMENTED BUT BROKEN (B2: missing WAL/SHM/venv/data) |
| `requirements.txt` | `requirements.txt` | PARTIALLY IMPLEMENTED (B10: no streamlit/kiteconnect) |
| Broker interface | `trading/` | NOT IMPLEMENTED |
| MockBroker / PaperBroker / KiteBroker | — | NOT IMPLEMENTED |
| Market data / instruments | `market/` | NOT IMPLEMENTED |
| Live/candle builder | — | NOT IMPLEMENTED |
| Signal engine / trading loop | — | NOT IMPLEMENTED |
| Paper trading | — | NOT IMPLEMENTED |
| Live trading | — | NOT IMPLEMENTED |
| Reconciliation / recovery | — | NOT IMPLEMENTED |
| Emergency stop | — | NOT IMPLEMENTED |
| Streamlit UI / `app.py` | — | NOT IMPLEMENTED |
| Git repository | — | NOT IMPLEMENTED |
| `docs/` | — | NOT IMPLEMENTED |
| Architecture guard test | `test_backtest_engine.py` line 376 | IMPLEMENTED BUT BROKEN (`>= 5` assertion fails with current file count) |

---

## 3. PHASE TABLE

### Phase A — Git, Baseline & Hygiene
**Goal:** Establish a clean, secret-free git repo; fix hygiene bugs; confirm baseline.
**Files create/modify:** `.gitignore`, `requirements.txt`, `models.py`, `db.py`, `config.py`, `utils/logger.py`, `tests/test_backtest_engine.py`, `tests/test_db.py`, `tests/test_hygiene.py`, `docs/IMPLEMENTATION_PLAN.md`, `docs/PROJECT_STATUS.md`
**Tests to add:** R1 guard; PAPER/BACKTEST never import kiteconnect; `.env`/`.db`/`logs` not tracked; fix B1 KeyError test
**Task order:** A1 gitignore -> A2 git init + first commit -> A3 docs -> A4 fix B1/B10/B11 -> A5 add R1+hygiene tests -> A6 ask for GitHub URL
**Need from you:** GitHub private repo URL; yes/no on optional CI workflow
**Gate:** 210 tests pass; `git status` shows no `.env`/`.db`/logs; branch `phase-a-baseline` merged to `main`; tagged `handover-phase3` and `phase-a`
**Effort:** S

### Phase B — Backtest Correctness & Real-Data Readiness
**Goal:** Fix B3/B4; add CSV loader; spot-check against real candles.
**Files create/modify:** `backtest/engine.py`, `market/historical_data.py`, `tests/test_backtest_engine.py`, `tests/test_historical_data.py`
**Task order:** B-1 fix engine -> B-2 CSV loader -> B-3 spot-check (need your CSV)
**Need from you:** A real 5-minute OHLCV CSV for one instrument
**Gate:** All tests green; manual spot-check of >=3 trades documented in `docs/PROJECT_STATUS.md`; no profitability claims
**Effort:** M

### Phase C — Domain Hardening
**Goal:** Fix all safety issues that must precede broker code (B5–B9, latched kill switch, persisted daily-loss).
**Files create/modify:** `models.py`, `db.py`, `trading/risk_manager.py`, `tests/test_db.py`, `tests/test_risk_manager.py`, new `tests/test_safety.py`
**Task order:** C1 OrderStatus -> C2 order-state transitions -> C3 position protection state -> C4 signal_id dedup -> C5 DB queries + persisted latch + kill switch -> C6 tests
**Gate:** All tests green; a restart with an in-progress position correctly loads UNPROTECTED state; kill switch persists
**Effort:** M

### Phase D — Broker Layer, Market Data, Engine, Paper Trading
**Goal:** Broker interface + MockBroker + PaperBroker; CSV/Kite data loaders; signal engine; paper trading end-to-end.
**Files create/modify:** `trading/broker.py`, `trading/mock_broker.py`, `trading/paper_broker.py`, `market/instruments.py`, `market/historical_data.py`, `market/live_data.py`, `trading/signal_engine.py`, `utils/logger.py`, new `app.py`, test files.
**Task order:** D1 broker interface + MockBroker -> D2 market data -> D3 signal engine -> D4 PaperBroker + paper run -> D5 logging
**Need from you:** Kite plan confirmation (Connect vs Personal)
**Gate:** Paper mode runs end-to-end on replayed data; parity test passes; no kiteconnect import in paper path
**Effort:** L

### Phase E — Kite Broker (Mock-Tested Only)
**Goal:** KiteBroker implementation, order lifecycle, stop-loss placement — all tested with MockBroker/mocked kiteconnect only.
**Files create/modify:** `trading/kite_broker.py`, `market/instruments.py`, `market/historical_data.py`, `tests/test_kite_broker.py`
**Task order:** E1 live-gate enforcement -> E2 order lifecycle -> E3 stop-loss -> E4 exit sequence + hazards -> E5 order typing decision -> E6 error mapping
**Need from you:** Decision on order types for entry/exit/stop
**Gate:** All tests green; zero real API calls made; order type decision documented in README
**Effort:** L

### Phase F — Reconciliation, Recovery, Network Failure, Emergency Stop
**Goal:** Startup reconciliation; periodic reconciliation; network/feed failure handling; emergency stop; single-instance guard.
**Task order:** F1 startup reconcile -> F2 network failure -> F3 emergency stop + instance guard -> F4 tests
**Gate:** All tests green; every F requirement has a corresponding test
**Effort:** L

### Phase G — Streamlit UI
**Goal:** `app.py` + six pages; process-wide engine singleton; live page with full confirmation flow.
**Task order:** G1 engine singleton -> G2 dashboard + backtest page -> G3 paper page -> G4 live page -> G5 settings + logs -> G6 AppTest
**Gate:** All pages render; live flow requires all 4 confirmation steps; AppTest suite green
**Effort:** M

### Phase H — Integration, Documentation, Clean-up, Final Audit
**Goal:** Integration tests; full README; clean-up; live-readiness checklist.
**Task order:** H1 integration tests -> H2 README -> H3 clean-up -> H4 final audit
**Gate:** All tests green; secret scan clean; live-readiness checklist in README with accurate tick/cross status
**Effort:** M

---

## 4. ORDER AND RATIONALE
Safety before broker code (C before D/E). Broker interfaces before Kite (D before E). All safety tested before UI (F before G). UI last because it is presentation only.
Deliberately deferred: Kite credentials are never touched until Phase E.
Deliberately refused (per R8): ML/AI, multiple strategies, Postgres/Redis/Kafka, Docker, microservices, cloud deployment.

---

## 5. OPEN DECISIONS (max 8)
OD1: Kite plan (Connect or Personal?)
OD2: Order types for entry/exit/stop (recommend SL-M for stops)
OD3: Static IP registered?
OD4: algo_id requirement for retail API?
OD5: Kite tag length limit
OD6: CI workflow?
OD7: CSV format details
OD8: test_backtest_and_risk_code_cannot_reach_a_real_broker_or_network threshold (will fix in Phase A)

---

## 6. DEVIATIONS
- Project root is `trading_app/trading_app/`.
- `test_backtest_and_risk_code_cannot_reach_a_real_broker_or_network` will be patched in Phase A to fix the broken assertion count.
- Python version corrected to 3.11.9 everywhere.
