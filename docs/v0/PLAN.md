# v0 Build Plan

Work top to bottom. Tick boxes as tasks land. Every milestone ends with its tests passing. Estimates assume one full-time engineer; part-time takes longer.

## M0: Repo foundation (days 1–2)
- [ ] `pyproject.toml` with uv, ruff, mypy, pytest; package layout per CLAUDE.md
- [ ] `docker-compose.yml` for local dev: Postgres 16, NATS (JetStream on), LiteLLM proxy
- [ ] Alembic setup and first migration with all tables from SPEC §6
- [ ] Pydantic models: agent definition (SPEC §4), bar, job, decision, order
- [ ] Load and validate `agents/examples/*.json` (CLI `atp agent load`)
- [ ] CI: GitHub Actions running lint, type-check, and tests
- **Done when:** `docker compose up` plus `uv run pytest` pass on a fresh clone.

## M1: Data and replay (weeks 1–2)
- [ ] `Clock` interface: `RealClock`, `SimClock` (speed control)
- [ ] `MarketDataSource` interface; `AlpacaDataSource` (historical REST + live websocket, IEX feed)
- [ ] Historical bar cache into the `bars` table (and/or Parquet)
- [ ] `ReplayDataSource` publishing to `md.bars.<symbol>` on the `SimClock`
- [ ] NATS streams `MD`, `JOBS`, `JOBS_DLQ`, `EVENTS` created idempotently at startup
- **Done when:** `atp replay --date <day>` streams a full day of bars into NATS at 20x.

## M2: The loop on paper (weeks 2–4)
- [ ] Indicators (SMA, EMA, RSI) with unit tests against known values
- [ ] Watch engine: shared indicator windows, condition evaluation, `jobs.wake` with message IDs, advisory-lock leadership
- [ ] Decision worker: pull consumer, rules, explicit ack/NAK, DLQ after max deliveries
- [ ] LiteLLM integration for the AI filter, with an `llm_cache` for deterministic replay
- [ ] Risk engine (all SPEC §7 checks) with unit tests per rule
- [ ] Order manager with state machine, `order_events`, unique `client_order_id`
- [ ] `PaperBroker` (fill model, slippage, limit/stop handling)
- [ ] Ledger, positions, and decision log writes in single transactions
- [ ] Simple reference backtest (plain pandas) for the parity test
- **Done when:** acceptance tests 1, 3, 4, and 6 pass in replay.

## M3: Real broker, paper account (weeks 4–5)
- [ ] `AlpacaBroker` (paper): submit/cancel/get/list/positions/account, trade-update stream
- [ ] Broker-native stop and limit exits where supported
- [ ] Reconciliation loop: diffs, events, auto-pause
- [ ] Credential encryption (local key in dev, KMS in AWS)
- [ ] Control panel (FastAPI + HTMX) and CLI commands from SPEC §7
- [ ] Alerts (log-based to start; Slack or email webhook optional)
- **Done when:** the agent trades the Alpaca paper account during market hours end to end, and test 5 passes.

## M4: AWS deployment (week 5)
- [ ] Terraform: VPC (public subnets, no NAT gateway), ECS cluster on EC2 Arm, task definitions for each service, RDS t4g.micro, KMS key, CloudWatch logs, secrets wiring
- [ ] Container images built in CI and pushed to ECR
- [ ] Grafana Cloud and Sentry wired in
- [ ] `terraform destroy` works cleanly
- **Done when:** test 10 passes and the paper agent runs from AWS. **Start the 2-week paper soak (test 2).**

## M5: Hardening and live (weeks 5–6+)
- [ ] Market-open burst test with 1,000 instances in replay (test 7)
- [ ] AI cost metering per decision and per instance (test 9)
- [ ] `AlpacaBroker(live)` behind the `ALLOW_LIVE_TRADING` flag
- [ ] Go live with $100–500 for 1 week (test 8)
- [ ] Stretch: connect a Robinhood agentic account via its agent connection (MCP) to confirm a hosted platform can trade through it
- **Done when:** all 10 acceptance tests in SPEC §9 pass.

## After v0
Databento adapter, NATS three-node cluster (R3), RDS Multi-AZ before outside users, conversational builder, more brokers.
