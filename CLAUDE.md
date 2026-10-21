# CLAUDE.md: Agent Trading Platform (working name)

## What this is
A web platform where anyone builds, tests, and runs AI trading agents on their own brokerage accounts, and competes, copies, and connects with others. Full vision: `docs/vision.md`. Full requirements: `docs/prd-and-technical.md`.

**Current phase: v0.** Prove the core backend loop on the real architecture: one hand-defined agent, our paper broker plus Alpaca (paper → small live), deterministic replay of historical days, deployed on AWS. **Build only what's in `docs/v0/SPEC.md`.** Work through `docs/v0/PLAN.md` in order and tick boxes as tasks land.

## Docs: read on demand, not all at once
| Doc | Use it for |
|---|---|
| `docs/v0/SPEC.md` | **Source of truth for v0**: architecture, schemas, tables, components, acceptance tests |
| `docs/v0/PLAN.md` | Milestones and task checklist |
| `docs/v0/SETUP.md` | Accounts, tools, environment, costs |
| `docs/big-ticket-costs.md` | Current infrastructure choices and costs (supersedes older stack choices) |
| `docs/infrastructure-decisions.md` | Short infrastructure decisions and cost model |
| `docs/infrastructure-full.md` | Full provider research (reference) |
| `docs/prd-and-technical.md` | Full product requirements (beyond v0) |
| `docs/status-and-decisions.md` | Locked decisions, open questions |
| `docs/archive/` | Superseded docs; don't follow |

**Precedence when docs conflict:** `v0/SPEC.md` > `big-ticket-costs.md` > `infrastructure-decisions.md` > `infrastructure-full.md` > `prd-and-technical.md` > `vision.md`. The PRD's original stack (Temporal, E2B, OpenRouter, LEAN) is superseded.

## Architecture rules (non-negotiable)
1. **Agents are data, not servers.** An agent is a versioned JSON definition plus state in Postgres. No process or sandbox per agent.
2. **Watching vs thinking.** One shared watch engine computes indicators once per symbol and publishes `jobs.wake`; stateless decision workers do the thinking.
3. **One engine, three modes.** Only `Clock`, `MarketDataSource`, and `Broker` differ between replay, paper, and live. Never fork logic by mode elsewhere.
4. **Guardrails live outside the agent.** Every order passes the risk engine. Agents can't modify guardrails.
5. **Idempotency everywhere.** NATS delivery is at-least-once. Message IDs `{instance_id}:{bar_ts}`; `client_order_id` unique in Postgres; acks only after commit; DLQ after max deliveries.
6. **Every decision is logged and replayable.** Inputs, rule result, model output (cached by request hash), reasoning, action.
7. **Reconcile with the broker every cycle**; any mismatch pauses the instance and alerts.
8. **No Temporal.** Durable loop = NATS JetStream work queue + Postgres state. Add DBOS only if a genuinely multi-step flow needs it, and ask first.

## Stack
Python 3.12 · uv · ruff · mypy · pytest · asyncio · FastAPI · Pydantic v2 · SQLAlchemy 2 + Alembic · Postgres 16 · NATS JetStream (`nats-py`) · `alpaca-py` · LiteLLM proxy → `claude-haiku-5-5` · our own SMA/EMA/RSI (no native TA-Lib) · Docker Compose (local only) · Terraform → AWS ECS on EC2 Arm, RDS, KMS, CloudWatch · Grafana Cloud + Sentry.

## Target repo layout (create as you go)
```
src/atp/
  schema/        # Pydantic models: agent definition, messages
  clock/         # RealClock, SimClock
  marketdata/    # MarketDataSource, AlpacaDataSource, ReplayDataSource
  indicators/
  watch/         # watch engine
  worker/        # decision worker, AI filter, llm cache
  risk/          # risk engine (pure functions)
  orders/        # order manager, state machine
  brokers/       # Broker interface, PaperBroker, AlpacaBroker
  ledger/        # positions, ledger entries
  reconcile/
  control/       # FastAPI control panel (Jinja/HTMX)
  cli/           # typer CLI `atp`
  db/            # models, session, alembic
  bus/           # NATS streams, publish/consume helpers
tests/           # unit + integration (docker compose services)
agents/examples/ # example agent definitions
infra/terraform/
docker/
```

## Commands
(Fill in as they're created.)
- Install: `uv sync`
- Local services: `docker compose up -d`
- Migrate: `uv run alembic upgrade head`
- Tests: `uv run pytest`
- Lint/type-check: `uv run ruff check . && uv run mypy src`
- CLI: `uv run atp --help`

## Conventions
- Typed Python everywhere; Pydantic at boundaries; no untyped dicts crossing modules.
- Money in `Decimal`; timestamps timezone-aware UTC; market sessions in America/New_York.
- Every new component gets unit tests. The loop gets integration tests against Compose services.
- Small, focused commits with clear messages. Update `docs/v0/PLAN.md` checkboxes in the same commit.
- If the spec is ambiguous or a decision changes architecture, stop and ask; don't guess.

## Safety rules
- **Paper by default.** Live orders require `ALLOW_LIVE_TRADING=true` and a live account row. Never enable live trading on your own initiative.
- Never commit secrets. `.env` is gitignored; only `.env.example` is tracked.
- Never log, print, or send broker credentials or API keys to an LLM.
- Ask before running `terraform apply`/`destroy` or anything that costs money or touches real accounts.
- The kill switch must always work. Test it whenever order flow changes.
