# Agent Trading Platform: Infrastructure Decisions (Short Version)

> **Note:** this predates the big-ticket research. `docs/big-ticket-costs.md` has the current choices and numbers: the agent loop runs on a NATS job queue instead of Temporal (~$0), servers on ECS on EC2 (~$180–200/mo at launch), RDS Multi-AZ (~$230/mo), direct broker APIs, and a recommended-setup total of ~$0.9k / $1.2k / $8.2k per month at 500 / 1k / 10k users.


*For das and Aryan · October 20, 2026*

This covers only what matters: the expensive items, what we could build ourselves, what we need to decide, and what needs more research. Everything low-cost or no-choice is in the full doc (agent-platform-infrastructure-full.md). That includes login, monitoring, error tracking, analytics, email, CDN, cache, and file storage.

*"est." = our estimate. Prices are October 2026 list prices.*

---

## 1. Where the money goes

| Item | Cost now → at 10k users | Best pick | Main alternative | Action |
|---|---|---|---|---|
| **AI models** (billed to users) | ~$2 per AI agent/month → $10+ with checks every minute (est.); passed through to users via credits at ~2× cost, so not in our cost totals | Claude Haiku 5.5 for scans, Sonnet 5.5 for the builder and escalations | Same models via AWS Bedrock (same price, can use AWS credits) | Price credits above cost; cap the free-tier AI allowance (the part we absorb); use batch and prompt caching |
| **Durable runtime** (keeps agent loops alive) | $0 on credits → ~$3–5k/mo (est.) | Temporal Cloud | Cloudflare Workflows (~$10–50/mo at 10k agents, est.), DBOS, or self-hosted Temporal | Prototype Cloudflare in Stage 1 |
| **Broker connections** | $0 → ~$20k/mo if every user goes through SnapTrade | Direct connections to Robinhood and IBKR ($0 per user) | SnapTrade ($2 per connected user per month) | Apply to IBKR and Robinhood now; use SnapTrade only for less common brokers |
| **Market data** | $199/mo → $1,500–4,000/mo if broader rights are needed | Databento Standard (feed can be shown to users) | Massive Business contract (quote only) | Confirm Databento display and redistribution terms in writing |
| **Main database** | ~$90 → $1–2k/mo (est.) | AWS Aurora/RDS (managed) | Supabase for a throwaway prototype | Decide the MVP database |
| **Servers** | ~$150 → ~$1,500/mo (est.) | AWS Fargate on Arm processors | EC2 savings plans for steady load; Hetzner for backtest boxes | Revisit at scale |
| **Model routing fee** | 0% vs 5.5% of all model spend | LiteLLM, self-hosted (0%) | OpenRouter (5.5%) | Build LiteLLM in Stage 1 |
| **SOC 2** (later) | ~$13k → ~$60k first year | Vanta or Drata, plus Type I audit | Startup-focused auditors | Only when partners ask |
| **ID and location checks** (later) | Per check | Sumsub, plus Radar or GeoComply | Persona | Only for paid competitions; decide with our lawyer |

---

## 2. What we can build ourselves

| Build | Instead of (cost avoided) | Effort | Risk | When |
|---|---|---|---|---|
| Watch engine (checks every agent's conditions) | An always-on sandbox per agent (~$49 per agent per month) | Medium–high | Medium | Stage 1 |
| Model gateway (LiteLLM) | OpenRouter's 5.5% fee | Low | Low | Stage 1 |
| Paper broker | Alpaca-only paper accounts | Medium | Medium | Stage 1 |
| Builder agent | Nothing to buy; this is the core product | High | High | Stage 2 |
| SEC filings feed (EDGAR, free) | Part of a paid news feed | Medium | Low | Stage 2 |
| Direct broker connections | SnapTrade's $2 per user per month | Medium–high | High (approvals) | Stage 3 |
| Order management, risk engine, ledger | Nothing safe to buy | High | Very high (real money) | Stage 3 |
| Real-time push (Centrifugo, open source) | Ably/Pusher fees | Low–medium | Low | Stage 3 |
| Chat and feeds | Stream (~$399+/mo) | Medium | Medium (moderation) | Stage 4 |
| Credit ledger | Stripe Billing's limits and fees | Medium | Medium | Stage 4 |
| Self-hosted analytics database (ClickHouse) | ClickHouse Cloud ($67–500/mo) | Medium | Medium | Stage 1 |
| Later: self-hosted Temporal, monitoring, AI tracing | Their cloud bills once they pass ~$500–5k/mo | Medium | Low–medium | When bills justify it |

**Don't build:** market data feeds, sandbox isolation technology, running our own main database, ID and location checks, or holding pot money.

---

## 3. Decisions to make

| Decision | Options | Recommendation | When |
|---|---|---|---|
| Primary cloud | AWS / Google Cloud | AWS (credits likely cover Claude; Google's don't) | Now |
| Durable runtime | Temporal Cloud / Cloudflare / DBOS | Temporal Cloud, with a Cloudflare prototype | Stage 1 |
| AI model access | Anthropic direct / AWS Bedrock | Both: Bedrock to spend credits, direct for the newest models | Stage 1 |
| Market data | Databento / Massive | Databento, once terms are confirmed | Now |
| Broker routes | Direct / SnapTrade | Direct first, SnapTrade for the rest | Apply now |
| MVP database | Aurora / Supabase | Aurora (Supabase only for a throwaway prototype) | Stage 1 |
| Watch engine language | Python / Rust | Python first | Stage 1 |
| Backtest engine | NautilusTrader / LEAN | NautilusTrader | Stage 1 |
| Pricing | Pro $25–29, Premium $79, credits at ~2× model cost | Start there and adjust with real usage | Before launch |

---

## 4. Confirm or research further

| Item | Why it matters | Next step |
|---|---|---|
| Databento display and redistribution terms | Drives market data cost: $199 vs $1,500+/mo | Ask Databento in writing |
| Robinhood rules for hosted platforms (registration, rate limits, sessions) | Determines whether direct Robinhood access works | Review developer docs; contact Robinhood |
| IBKR third-party OAuth approval | Timeline for the IBKR connection | Apply now |
| AWS credits for Claude on Bedrock | Could cover most early AI spend | Ask AWS billing |
| Cloudflare as the agent runtime | Could cut the runtime bill by ~99% | Stage 1 prototype |
| SnapTrade production approval, Robinhood/IBKR trading, daily-plan price | Fallback broker costs | Contact SnapTrade |
| News display rights | Showing headlines to users | Ask the news vendor |
| Not yet researched: X API, escrow partners, Webull direct, Alpaca Broker API, legal fees | Gaps in the plan | Next research round |

---

## 5. Cost snapshot (est.)

AI usage is billed to users through credits, so it's excluded here. Full detail is in section 6.

| | Best case (build what we can) | Recommended (Middle A) | Worst case (all providers) |
|---|---|---|---|
| Fixed cost at launch | ~$450/mo | ~$750–1,700/mo | ~$4,150/mo |
| Platform cost at 1k users | ~$1.3k/mo | ~$2.5k/mo | ~$6.0k/mo |
| Platform cost at 10k users | ~$8.5k/mo | ~$12.0k/mo | ~$37.3k/mo |
| Subscription revenue at 10k users (12% Pro, 3% Premium) | ~$56.1k/mo | ~$56.1k/mo | ~$56.1k/mo |

Infrastructure stays cheap if we build the right pieces ourselves. The real risk is how many users pay. On the recommended setup, break-even is about 7% of active users paying at 1k users and about 3% at 10k (est.).

---

## 6. Cost model: four scenarios at 500, 1k, 10k, and 100k users

This model includes every cost line from the full doc. All figures are monthly estimates at list prices. **AI model usage is billed to users through credits, so it appears as a reference line but is not in any total, margin, or per-user figure.** Revenue counts subscriptions only; the margin on AI credits comes on top. They exclude salaries, legal fees, and startup credits, and they don't include ID or location checks, which only apply once paid competitions launch.

### Assumptions

| Assumption | Value |
|---|---|
| User mix | 85% free (light use), 12% Pro ($27), 3% Premium ($79) |
| Light user | 2 rule-based agents, occasional builder use: ~$0.25/month in AI |
| Typical (Pro) user | 1 rule-based + 1 AI agent (5-min checks, ~5 escalations/day), 3 builder sessions: ~$3.65/month in AI |
| Heavy (Premium) user | 5 AI agents checking every minute, 6 builder sessions: ~$25/month in AI |
| Users who link a brokerage | 60% |
| Durable runtime | ~4 actions per agent wake. Temporal Cloud at $50/M actions, falling to $35/M at 10k users and $25/M at 100k with volume discounts. Cloudflare costs near zero while agents sleep |
| Card processing | Standard US card rate (2.9% + $0.30 per charge; verify with Stripe) |
| AI models | Billed to users via credits (~2× model cost), so excluded from totals. Shown as reference lines. The free-tier allowance (~$0.25 per free user) is the part we absorb unless capped |

### What each scenario means

| Scenario | Runtime | Brokers | Model gateway | Real-time, chat, feeds | Data and analytics | Monitoring | Billing, secrets, login |
|---|---|---|---|---|---|---|---|
| **Best: build everything we can** | Cloudflare Workflows (or self-hosted) | Direct; SnapTrade for 15% of linked users | LiteLLM (0%) | Centrifugo; own chat and feeds | Self-hosted ClickHouse and NATS; Databento Standard, Plus at 100k | Free tiers, then self-hosted | Own subscription logic; KMS; WorkOS |
| **Middle A: recommended hybrid** | Temporal Cloud, self-hosted from 10k | Direct; SnapTrade for 25% | LiteLLM (0%) | Centrifugo; own chat and feeds | Self-hosted ClickHouse and NATS; Databento | Grafana Cloud, Sentry, Langfuse, PostHog | Stripe Billing; KMS; WorkOS |
| **Middle B: managed-leaning** | Temporal Cloud throughout | Direct; SnapTrade for 50% | Vercel AI Gateway (0%) | Ably; Stream for chat and feeds | ClickHouse Cloud; managed Kafka; Databento Plus from 10k | Grafana Cloud, Sentry, Langfuse, PostHog | Stripe Billing; KMS; WorkOS |
| **Worst: build nothing optional** | Temporal Cloud throughout | SnapTrade for every linked user | OpenRouter (5.5%) | Ably; Stream for chat and feeds | ClickHouse Cloud; managed Kafka; Databento Plus, then Unlimited; premium news | Datadog, Sentry, Langfuse, PostHog | Stripe Billing; one Secrets Manager secret per user; Clerk |

The core product (watch engine, order management, risk engine, ledger, builder agent) gets built in every scenario. "Worst" means buying every optional piece rather than building it, not a broken architecture.

### Totals per month (est., excluding AI usage billed to users)

| Scenario | 500 users | 1k users | 10k users | 100k users |
|---|---|---|---|---|
| Best case: build everything we can | $860 | $1.3k | $8.5k | $62.4k |
| Middle A: recommended hybrid | $1.5k | $2.5k | $12.0k | $90.7k |
| Middle B: managed-leaning | $2.7k | $4.0k | $25.7k | $185k |
| Worst case: build nothing optional, all providers | $4.3k | $6.0k | $37.3k | $295k |
| Subscription revenue at the assumed mix | $2.8k | $5.6k | $56.1k | $561k |
| *Memo: AI usage billed to users via credits (not in totals)* | *$703* | *$1.4k* | *$14.1k* | *$141k* |
| *Memo: free-tier AI allowance we absorb unless capped (not in totals)* | *$106* | *$212* | *$2.1k* | *$21.2k* |

| Gross margin on subscriptions | 500 users | 1k users | 10k users | 100k users |
|---|---|---|---|---|
| Best | 69% | 77% | 85% | 89% |
| Middle A | 48% | 56% | 79% | 84% |
| Middle B | 2% | 29% | 54% | 67% |
| Worst | -53% | -7% | 34% | 47% |

| Platform cost per active user | 500 users | 1k users | 10k users | 100k users |
|---|---|---|---|---|
| Best | $1.72 | $1.30 | $0.85 | $0.62 |
| Middle A | $2.91 | $2.48 | $1.20 | $0.91 |
| Middle B | $5.49 | $4.01 | $2.57 | $1.85 |
| Worst | $8.57 | $6.03 | $3.73 | $2.95 |

### Line items: Best case: build everything we can

| Cost line | 500 users | 1k users | 10k users | 100k users |
|---|---|---|---|---|
| Servers / containers | $150 | $250 | $1.2k | $8.0k |
| Main database (Aurora/RDS) | $150 | $250 | $1.0k | $5.0k |
| Analytics DB (ClickHouse) | $50 | $75 | $300 | $1.5k |
| Cache (Valkey) | $10 | $15 | $100 | $500 |
| Event bus | $60 | $60 | $200 | $800 |
| File storage (S3/R2) | $10 | $15 | $100 | $800 |
| Durable runtime (fixed) | $5 | $5 | $20 | $100 |
| Sandboxes (E2B dev) | $0 | $0 | $0 | $150 |
| Market data (Databento) | $199 | $199 | $199 | $1.5k |
| News and filings | $20 | $20 | $50 | $500 |
| Monitoring, errors, AI tracing, analytics | $0 | $0 | $200 | $1.0k |
| Chat and feeds (vendor) | $0 | $0 | $0 | $0 |
| Login | $0 | $0 | $0 | $0 |
| CDN, email, secrets, CI/CD | $10 | $15 | $140 | $750 |
| SOC 2 (amortized) | $0 | $0 | $1.1k | $2.5k |
| Durable runtime (usage) | $2 | $5 | $50 | $500 |
| Model gateway fee | $0 | $0 | $0 | $0 |
| Broker aggregator (SnapTrade) | $90 | $180 | $1.8k | $18.0k |
| Card processing | $104 | $208 | $2.1k | $20.8k |
| Stripe Billing (0.7%) | $0 | $0 | $0 | $0 |
| Real-time vendor (Ably) | $0 | $0 | $0 | $0 |
| Per-user secrets (Secrets Manager) | $0 | $0 | $0 | $0 |
| **Total** | **$860** | **$1.3k** | **$8.5k** | **$62.4k** |
| *AI usage, billed to users (not in total)* | *$703* | *$1.4k* | *$14.1k* | *$141k* |

### Line items: Middle A: recommended hybrid

| Cost line | 500 users | 1k users | 10k users | 100k users |
|---|---|---|---|---|
| Servers / containers | $200 | $300 | $1.5k | $10.0k |
| Main database (Aurora/RDS) | $150 | $250 | $1.0k | $5.0k |
| Analytics DB (ClickHouse) | $50 | $75 | $300 | $1.5k |
| Cache (Valkey) | $10 | $15 | $100 | $500 |
| Event bus | $60 | $60 | $200 | $800 |
| File storage (S3/R2) | $10 | $15 | $100 | $800 |
| Durable runtime (fixed) | $0 | $0 | $600 | $3.0k |
| Sandboxes (E2B dev) | $0 | $0 | $150 | $150 |
| Market data (Databento) | $199 | $199 | $199 | $1.5k |
| News and filings | $50 | $50 | $500 | $1.0k |
| Monitoring, errors, AI tracing, analytics | $0 | $55 | $678 | $6.0k |
| Chat and feeds (vendor) | $0 | $0 | $0 | $0 |
| Login | $0 | $0 | $0 | $0 |
| CDN, email, secrets, CI/CD | $10 | $35 | $140 | $750 |
| SOC 2 (amortized) | $0 | $0 | $1.1k | $5.0k |
| Durable runtime (usage) | $441 | $881 | $0 | $0 |
| Model gateway fee | $0 | $0 | $0 | $0 |
| Broker aggregator (SnapTrade) | $150 | $300 | $3.0k | $30.0k |
| Card processing | $104 | $208 | $2.1k | $20.8k |
| Stripe Billing (0.7%) | $20 | $39 | $393 | $3.9k |
| Real-time vendor (Ably) | $0 | $0 | $0 | $0 |
| Per-user secrets (Secrets Manager) | $0 | $0 | $0 | $0 |
| **Total** | **$1.5k** | **$2.5k** | **$12.0k** | **$90.7k** |
| *AI usage, billed to users (not in total)* | *$703* | *$1.4k* | *$14.1k* | *$141k* |

### Line items: Middle B: managed-leaning

| Cost line | 500 users | 1k users | 10k users | 100k users |
|---|---|---|---|---|
| Servers / containers | $250 | $400 | $2.0k | $14.0k |
| Main database (Aurora/RDS) | $150 | $250 | $1.0k | $5.0k |
| Analytics DB (ClickHouse) | $186 | $186 | $500 | $2.5k |
| Cache (Valkey) | $30 | $50 | $300 | $1.5k |
| Event bus | $300 | $300 | $1.0k | $4.0k |
| File storage (S3/R2) | $10 | $15 | $100 | $800 |
| Durable runtime (fixed) | $0 | $0 | $0 | $0 |
| Sandboxes (E2B dev) | $150 | $150 | $150 | $150 |
| Market data (Databento) | $199 | $199 | $1.5k | $1.5k |
| News and filings | $50 | $50 | $500 | $1.5k |
| Monitoring, errors, AI tracing, analytics | $0 | $55 | $678 | $6.0k |
| Chat and feeds (vendor) | $499 | $499 | $1.5k | $8.0k |
| Login | $0 | $0 | $0 | $0 |
| CDN, email, secrets, CI/CD | $30 | $75 | $190 | $950 |
| SOC 2 (amortized) | $0 | $0 | $1.1k | $5.0k |
| Durable runtime (usage) | $441 | $881 | $6.2k | $44.1k |
| Model gateway fee | $0 | $0 | $0 | $0 |
| Broker aggregator (SnapTrade) | $300 | $600 | $6.0k | $60.0k |
| Card processing | $104 | $208 | $2.1k | $20.8k |
| Stripe Billing (0.7%) | $20 | $39 | $393 | $3.9k |
| Real-time vendor (Ably) | $25 | $50 | $500 | $5.0k |
| Per-user secrets (Secrets Manager) | $0 | $0 | $0 | $0 |
| **Total** | **$2.7k** | **$4.0k** | **$25.7k** | **$185k** |
| *AI usage, billed to users (not in total)* | *$703* | *$1.4k* | *$14.1k* | *$141k* |

### Line items: Worst case: build nothing optional, all providers

| Cost line | 500 users | 1k users | 10k users | 100k users |
|---|---|---|---|---|
| Servers / containers | $250 | $400 | $2.0k | $14.0k |
| Main database (Aurora/RDS) | $150 | $250 | $1.0k | $5.0k |
| Analytics DB (ClickHouse) | $186 | $186 | $500 | $2.5k |
| Cache (Valkey) | $30 | $50 | $300 | $1.5k |
| Event bus | $300 | $300 | $1.0k | $4.0k |
| File storage (S3/R2) | $10 | $15 | $100 | $800 |
| Durable runtime (fixed) | $0 | $0 | $0 | $0 |
| Sandboxes (E2B dev) | $150 | $150 | $150 | $150 |
| Market data (Databento) | $199 | $199 | $1.5k | $4.0k |
| News and filings | $500 | $500 | $1.5k | $3.0k |
| Monitoring, errors, AI tracing, analytics | $640 | $703 | $2.1k | $19.8k |
| Chat and feeds (vendor) | $499 | $499 | $1.5k | $8.0k |
| Login | $0 | $0 | $25 | $1.0k |
| CDN, email, secrets, CI/CD | $25 | $80 | $170 | $900 |
| SOC 2 (amortized) | $0 | $0 | $1.1k | $5.0k |
| Durable runtime (usage) | $441 | $881 | $6.2k | $44.1k |
| Model gateway fee | $39 | $77 | $774 | $7.7k |
| Broker aggregator (SnapTrade) | $600 | $1.2k | $12.0k | $120k |
| Card processing | $104 | $208 | $2.1k | $20.8k |
| Stripe Billing (0.7%) | $20 | $39 | $393 | $3.9k |
| Real-time vendor (Ably) | $25 | $50 | $500 | $5.0k |
| Per-user secrets (Secrets Manager) | $120 | $240 | $2.4k | $24.0k |
| **Total** | **$4.3k** | **$6.0k** | **$37.3k** | **$295k** |
| *AI usage, billed to users (not in total)* | *$703* | *$1.4k* | *$14.1k* | *$141k* |

### What to use at each size

| Component | 500–1k users | 10k users | 100k users |
|---|---|---|---|
| Durable runtime | Temporal Cloud on credits, or Cloudflare | Self-hosted Temporal or Cloudflare (Temporal Cloud ≈ $6k/mo) | Cloudflare or self-hosted only (Temporal Cloud ≈ $44k/mo) |
| Broker connections | SnapTrade for everyone is affordable (~$600–1,200/mo) | Direct required (SnapTrade for all ≈ $12k/mo) | Direct required (SnapTrade for all ≈ $120k/mo) |
| Model gateway | OpenRouter's fee is small (~$40–80/mo) | LiteLLM (fee ≈ $800/mo) | LiteLLM (fee ≈ $7.7k/mo) |
| Real-time, chat, feeds | Ably free tier and Stream (~$400–500/mo) are fine | Centrifugo plus our own chat and feeds | Our own (Ably + Stream ≈ $13k/mo) |
| Market data | Databento Standard ($199) | Standard if display terms allow; otherwise Plus ($1,500) | Plus ($1,500), or Unlimited ($4,000) if needed |
| Monitoring | Free tiers | Grafana Cloud (Datadog ≈ $2k/mo) | Self-hosted or negotiated Grafana (Datadog ≈ $20k/mo) |
| Analytics database | Self-hosted, or ClickHouse Cloud Basic ($186) | Self-hosted | Self-hosted cluster |
| Main database | Small Aurora/RDS (Supabase acceptable for a prototype) | Aurora Multi-AZ | Aurora with read replicas |
| Servers | Fargate | Fargate plus EC2 savings plans | Mostly reserved EC2 |
| Secrets | KMS | KMS (Secrets Manager ≈ $2.4k/mo) | KMS (Secrets Manager ≈ $24k/mo) |
| Login | WorkOS (free) | WorkOS (free) | WorkOS (free to 1M users; Clerk ≈ $1k/mo) |

### Warning: the architecture mistake that dwarfs every scenario

Running each AI agent in its own always-on sandbox (~$49 per agent per month) instead of using the shared watch engine would add about **$6.6k/mo at 500 users, $131k/mo at 10k, and $1.3M/mo at 100k** on top of any scenario above.

### Takeaways

| | |
|---|---|
| AI is pass-through, not our cost | ~$14k/mo of AI usage at 10k users and ~$141k/mo at 100k, billed to users through credits at ~2× cost. Our exposure is the free-tier allowance (~$2k/mo at 10k, ~$21k/mo at 100k) unless capped |
| Building ourselves cuts platform costs by ~75–80% | Best vs worst: ~$0.9k vs ~$4.3k at 500 users; ~$8.5k vs ~$37.3k at 10k; ~$62k vs ~$295k at 100k |
| The three costliest lines to avoid buying | Broker aggregator for everyone, Temporal Cloud at scale, and a Datadog-based monitoring stack. Together they're ~$184k/mo of the ~$295k worst case at 100k |
| Small scale is the tight phase | At 500 users, subscription margin is ~69% (best), ~48% (recommended), ~2% (managed-leaning), and a loss (worst). Fixed costs dominate until ~1–2k users; startup credits cover this phase |
| Middle A is the practical path | ~79–84% margin at 10k–100k users with less to build up front. Switch the runtime and monitoring to self-hosted as the 10k column shows |
