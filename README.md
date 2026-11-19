# Agent Trading Platform (working name)

Build, test, and run AI trading agents on your own brokerage accounts, and compete, copy, and connect with others.

**Status:** v0 backend built and tested locally (62 tests, 7 of 10 SPEC acceptance tests passing); the remaining 3 need Alpaca keys, an AWS account, and a live-trading decision. Building **v0**: one agent on the real backend, paper plus Alpaca, deterministic replay, deployed on AWS.

- Vision: `docs/vision.md`
- Requirements: `docs/prd-and-technical.md`
- Infrastructure and costs: `docs/big-ticket-costs.md`, `docs/infrastructure-decisions.md`, `docs/infrastructure-full.md`
- Decisions and open questions: `docs/status-and-decisions.md`
- **v0:** `docs/v0/SPEC.md`, `docs/v0/PLAN.md`, `docs/v0/SETUP.md`
- Instructions for Claude Code: `CLAUDE.md`

## Getting started
Needs Docker, Python 3.12 and `uv`.

```bash
cp .env.example .env                 # set ADMIN_TOKEN; keys optional for local work
docker compose up -d                 # Postgres, NATS, LiteLLM
uv sync
uv run alembic upgrade head
uv run atp init-bus
uv run atp agent load agents/examples/*.json
uv run atp bars synth --start 2026-10-01 --end 2026-10-16   # synthetic bars (no keys needed)
uv run atp replay --agent rsi-ma-basic --date 2026-10-14 --speed 0 --inline
uv run atp run panel                 # http://127.0.0.1:8000, sign in with ADMIN_TOKEN
uv run pytest                        # unit + acceptance tests
```

With Alpaca keys in `.env`: `uv run atp bars fetch --start ... --end ...` caches real IEX bars, and
`atp account add-alpaca` plus `atp instance create --mode alpaca_paper` trades the paper account.

Status per milestone and acceptance test: `docs/v0/PLAN.md`. AWS: `infra/terraform/README.md`.
