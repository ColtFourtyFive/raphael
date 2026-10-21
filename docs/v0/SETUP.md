# v0 Setup: What It Takes

## Accounts

| Account | Why | Cost |
|---|---|---|
| GitHub (private repo) | Code and CI | Free |
| AWS | Hosting (apply for Activate credits) | ~$20–60/mo for v0 |
| Alpaca | Paper trading (free), then live with $100–500; free IEX market data | $0 + test funds |
| Anthropic API (or AWS Bedrock) | Haiku for the AI-filter variant | Cents to a few dollars a month |
| Grafana Cloud, Sentry | Monitoring (free tiers) | $0 |
| Robinhood agentic account (stretch) | Test the hosted agent connection | Optional |

## Local tools
- Docker (with Compose), Python 3.12, `uv`
- Terraform or OpenTofu, AWS CLI (configured with a deploy role, not root)
- Claude Code, run from the repo root

## Environment variables
Copy `.env.example` to `.env` and fill it in. **Never commit `.env`.**

## People and time (est.)
- About 5–6 weeks for one full-time engineer to reach all v0 acceptance tests, plus a 2-week paper soak.
- Longer part-time.

## Costs (est.)

| Item | Monthly |
|---|---|
| EC2 Arm instance (ECS) | ~$15–30 |
| RDS t4g.micro | $0–12 (free tier for 12 months) |
| KMS, logs, storage | ~$2–5 |
| Load balancer (optional) | $0–16 |
| AI calls (Haiku) | <$5 |
| Data and broker (Alpaca) | $0 |
| **Total** | **~$20–60** + $100–500 live test funds |

## Starting the build with Claude Code
1. Clone the repo, `cd` into it, and run `claude`. It reads `CLAUDE.md` automatically.
2. Run `/context` to confirm `CLAUDE.md` loaded.
3. First prompt: *"Read docs/v0/SPEC.md and docs/v0/PLAN.md, then start M0. Propose the package layout and docker-compose first, then implement."*
4. Work milestone by milestone. Have Claude tick off `PLAN.md` as tasks land.
