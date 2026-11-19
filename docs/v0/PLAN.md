# v0 Build Plan

Work top to bottom. Tick boxes as tasks land. Every milestone ends with its tests passing. Estimates assume one full-time engineer; part-time takes longer.

Status key: `[x]` done and tested here · `[~]` built, but needs an account or approval to verify (see **Blocked on** below) · `[ ]` not started.

## M0: Repo foundation (days 1–2)
- [x] `pyproject.toml` with uv, ruff, mypy, pytest; package layout per CLAUDE.md
- [x] `docker-compose.yml` for local dev: Postgres 16, NATS (JetStream on), LiteLLM proxy
- [x] Alembic setup and first migration with all tables from SPEC §6
- [x] Pydantic models: agent definition (SPEC §4), bar, job, decision, order
- [x] Load and validate `agents/examples/*.json` (CLI `atp agent load`)
- [~] CI: GitHub Actions running lint, type-check, and tests (`.github/workflows/ci.yml`; the same steps pass locally, first GitHub run pending)
- **Done when:** `docker compose up` plus `uv run pytest` pass on a fresh clone. ✅ (62 tests)

## M1: Data and replay (weeks 1–2)
- [x] `Clock` interface: `RealClock`, `SimClock` (speed control)
- [~] `MarketDataSource` interface; `AlpacaDataSource` (historical REST + live websocket, IEX feed). Built and unit-tested (1-min → 5-min aggregation); not yet run against Alpaca (needs keys)
- [x] Historical bar cache into the `bars` table (`atp bars fetch`; `atp bars synth` for keyless synthetic data)
- [x] `ReplayDataSource` publishing to `md.bars.<symbol>` on the `SimClock`
- [x] NATS streams `MD`, `JOBS`, `JOBS_DLQ`, `EVENTS` created idempotently at startup
- **Done when:** `atp replay --date <day>` streams a full day of bars into NATS at 20x. ✅ (on synthetic bars; real bars need Alpaca keys)

## M2: The loop on paper (weeks 2–4)
- [x] Indicators (SMA, EMA, RSI) with unit tests against known values
- [x] Watch engine: shared indicator windows, condition evaluation, `jobs.wake` with message IDs, advisory-lock leadership
- [x] Decision worker: pull consumer, rules, explicit ack/NAK, DLQ after max deliveries
- [x] LiteLLM integration for the AI filter, with an `llm_cache` for deterministic replay
- [x] Risk engine (all SPEC §7 checks) with unit tests per rule
- [x] Order manager with state machine, `order_events`, unique `client_order_id`
- [x] `PaperBroker` (fill model, slippage, limit/stop handling)
- [x] Ledger, positions, and decision log writes in single transactions
- [x] Simple reference backtest (plain pandas) for the parity test
- **Done when:** acceptance tests 1, 3, 4, and 6 pass in replay. ✅

## M3: Real broker, paper account (weeks 4–5)
- [~] `AlpacaBroker` (paper): submit/cancel/get/list/positions/account. Built; error mapping, live-trading refusal and timeouts unit-tested; not yet run against Alpaca (needs keys). Trade updates by polling (no stream yet)
- [x] Broker-native stop and limit exits where supported (protective stop-loss rests at the broker after each entry; take-profit stays rule-based, see `src/atp/orders/protect.py`)
- [x] Reconciliation loop: diffs, events, auto-pause
- [x] Credential encryption (local key in dev, KMS in AWS)
- [x] Control panel (FastAPI + HTMX) and CLI commands from SPEC §7
- [x] Alerts (log-based with `alert=true` + CloudWatch metric/alarm; optional webhook)
- **Done when:** the agent trades the Alpaca paper account during market hours end to end, and test 5 passes. Test 5 ✅ (injected failures); Alpaca paper run blocked on keys.

## M4: AWS deployment (week 5)
- [~] Terraform: VPC (public subnets, no NAT gateway), ECS cluster on EC2 Arm, task definitions for each service, RDS t4g.micro, KMS key, CloudWatch logs, secrets wiring. `terraform validate` passes; not applied
- [~] Container images built in CI and pushed to ECR (`.github/workflows/deploy.yml`, manual; image builds locally)
- [~] Grafana Cloud and Sentry wired in (Sentry via `SENTRY_DSN`; structured JSON logs; Grafana Cloud/OTel not yet)
- [ ] `terraform destroy` works cleanly (needs an apply first)
- **Done when:** test 10 passes and the paper agent runs from AWS. **Start the 2-week paper soak (test 2).** Blocked on an AWS account and approval to apply.

## M5: Hardening and live (weeks 5–6+)
- [x] Market-open burst test with 1,000 instances in replay (test 7): 10,000 orders, 0 duplicates, 1,000/1,000 reconciliations clean, worst per-bar drain 33 s
- [x] AI cost metering per decision and per instance (test 9)
- [~] `AlpacaBroker(live)` behind the `ALLOW_LIVE_TRADING` flag (refuses unless the flag is on and the account row is live; untested against Alpaca)
- [ ] Go live with $100–500 for 1 week (test 8): your decision, needs live keys
- [ ] Stretch: connect a Robinhood agentic account via its agent connection (MCP) to confirm a hosted platform can trade through it
- **Done when:** all 10 acceptance tests in SPEC §9 pass.

## Acceptance tests (SPEC §9)

| # | Test | Status | Where |
|---|---|---|---|
| 1 | Replay parity | ✅ matches the pandas reference exactly; re-runs identical | `tests/integration/test_acceptance_replay.py` |
| 2 | Paper soak (2 weeks, Alpaca paper) | ⏳ needs Alpaca keys + AWS | |
| 3 | Worker crash | ✅ crashes after commit, after submit, and a hard kill mid-job | `test_acceptance_replay.py` |
| 4 | Watch engine restart | ✅ two restarts plus a crash before ack: identical trades | `test_acceptance_replay.py` |
| 5 | Broker failures | ✅ 5xx/timeouts retry; outage leaves the order safe; expired keys pause | `test_acceptance_ops.py` |
| 6 | Kill switch | ✅ cancels open orders (ours and the broker's) well under 5 s; blocks new ones | `test_acceptance_ops.py` |
| 7 | Market-open burst | ✅ 1,000 copies (CI runs 100–200) | `test_acceptance_replay.py`, `scripts/burst.py` |
| 8 | Live (1 week, $100–500) | ⏳ your decision | |
| 9 | AI cost | ✅ cost per decision; cached re-runs cost $0 | `test_acceptance_replay.py` |
| 10 | Infra apply/destroy | ⏳ needs AWS account + approval | `infra/terraform` |

## Blocked on
1. **Alpaca paper API keys**: run `AlpacaDataSource` and `AlpacaBroker` for real; fetch real historical bars; start test 2.
2. **Anthropic API key** (into LiteLLM): real Haiku 5.5 calls. Tests use the `mock-take` gateway model.
3. **AWS account + approval to `terraform apply`** (~$25–40/month): tests 10 and 2.
4. **Live trading decision** for test 8.

## After v0
Databento adapter, NATS three-node cluster (R3), RDS Multi-AZ before outside users, conversational builder, more brokers.
