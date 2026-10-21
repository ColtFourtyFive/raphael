# Agent Trading Platform: Backend & Infrastructure Plan

*For das and Aryan · October 20, 2026*

*Prices are public list prices as of October 2026 and change often. Anything marked "est." is our own estimate. Verify before committing to any vendor.*

---

## Summary

| Question | Answer |
|---|---|
| How does it run cheaply? | Agents are data plus timers, not servers. A shared watch engine monitors the market for every agent and wakes an agent only when its conditions fire. |
| What do we actually have to pay third parties for? | Market data, AI models, card payments, and (for less common brokers) a broker aggregator. Everything else runs on AWS building blocks, open-source software we host, or our own code. |
| What does it cost at launch? | About $750–1,700/month in fixed costs (est.), much of it coverable by startup credits. |
| What does each user cost? | About $0.50–1 (light), $4–6 (typical), $25–40 (heavy) per month (est.). |
| Biggest savings found | Databento's $199/month plan includes a live US stock feed we can show users without exchange license fees. A self-hosted model gateway avoids OpenRouter's 5.5% fee. AWS Lambda makes user-code sandboxes cost cents. |
| Biggest risk | Not infrastructure. It's builder quality, real-money correctness, broker approvals, and how many users pay. |

---

## 1. How the system works

### Agents don't run as servers

- An agent is a database row (its definition and state) plus a timer. A durable workflow sleeps until a trigger fires, a shared worker runs one decision, and the agent goes back to sleep. Sleeping costs nothing.
- Running a 24/7 sandbox per agent would cost about $49 per agent per month at E2B's rates (1 vCPU, 1 GiB). The shared design costs cents per agent.
- Reliability comes from durable execution, a unique key per order, and checking positions against the broker every cycle. It doesn't depend on machines staying on.

### Watching vs thinking

| | Watching | Thinking |
|---|---|---|
| What | Checking every agent's conditions against each price update, news item, or schedule | Running the agent's rules or AI judgment, then the risk check and the order |
| Who does it | One shared watch engine (two or more copies for redundancy) | The agent, woken by the engine |
| When | Continuously | Only when a condition fires or a scheduled scan is due |
| Cost | A few containers for the whole platform | Per decision (AI credits where AI is used) |

- **Shared indicators:** each indicator (e.g. RSI on AAPL) is computed once per symbol and shared by every agent that uses it.
- **Judgment-based agents still watch continuously** in three ways:
  - Event triggers, such as news on a watched ticker or unusual volume.
  - Scheduled scans by a cheap model.
  - Escalation to a stronger model when the scan flags something.
- **Simple exits run at the broker:** stop-losses and take-profits are sent to the broker as native stop and limit orders, so they fire even if our platform is down.

### One engine, three modes

| Mode | Data | Clock | Fills |
|---|---|---|---|
| Backtest | Historical | Simulated | Simulated |
| Paper | Live | Real | Our own paper broker (simulated) |
| Live | Live | Real | Real broker |

The same agent code runs in all three modes, so results stay comparable.

### Order path

```
market data → watch engine → agent wakes (rules or AI) → risk engine → broker adapter → broker or paper broker
                                                                                              │
ledger, decision log, portfolio view, leaderboards  ←──────────────── fills ←─────────────────┘
(positions reconciled against the broker every cycle)
```

### Layers

| Layer | What's in it |
|---|---|
| Experience | Web app, real-time updates |
| Product services | API, login, social features, competitions, billing, notifications |
| Agent engine | Watch engine, shared signals, durable runtime, decision workers, code sandbox, model gateway, builder agent |
| Trading core | Risk engine, order management, ledger, paper broker, broker adapters, backtest engine |
| Data | Postgres, ClickHouse, Valkey, NATS, S3/R2 |
| Foundation | AWS, containers, secrets, monitoring, CI/CD |
| External | Brokers, market data, news, AI model providers, Stripe |

---

## 2. Full stack: what we need, best pick, cheapest alternative, cost

Each layer has its own table. **Build ourselves?** means writing it as our own code; running open-source software counts as "No".

### 2.1 Foundation and operations

| Component (what it does) | Best pick (cost) | Cheapest solid alternative (cost) | Build ourselves? | Risk | Best case → worst case | Call |
|---|---|---|---|---|---|---|
| Cloud (runs everything) | AWS. Self-funded founders get $1,000 in credits (some reach $5,000); up to $200,000 needs a provider ID from a VC or accelerator | GCP: up to $350,000 for AI-first startups, but only with equity funding, and it doesn't cover third-party models like Claude | No | Low | Credits cover year one → full list prices | AWS now; apply for GCP credits after raising |
| Containers (API, workers, engines) | ECS Fargate on Graviton (Arm): $0.03238/vCPU-hour, $0.00356/GB-hour; Spot about 70% cheaper | EC2 servers with ECS (cheaper for steady load, more ops work) | No | Low | ~$150/mo → ~$1,500/mo at 10k users (est.) | Fargate; Spot for backtests |
| Infrastructure as code and deploys | Terraform/OpenTofu + GitHub Actions | Pulumi | Config only | Low | ~$0 → ~$50/mo | Terraform |
| CDN, DNS, firewall | Cloudflare | CloudFront + AWS WAF | No | Low | ~$0 → ~$200/mo | Cloudflare |
| Broker tokens and secrets | AWS KMS envelope encryption; encrypted tokens stored in Postgres (cents) | HashiCorp Vault, Infisical | Thin wrapper | Very high impact if leaked | Cents → about $0.40 per user per month if each token is a separate Secrets Manager entry | Build the wrapper; never one stored secret per user |
| Monitoring | Grafana Cloud + OpenTelemetry. Free tier covers 10k metrics plus 50 GB of logs and 50 GB of traces a month; paid is a $19 platform fee plus usage | SigNoz, self-hosted (free) | No | Low | $0 → a few hundred dollars a month | Grafana Cloud |
| Error tracking | Sentry: free tier; Team $26/month | GlitchTip, self-hosted | No | Low | $0 → $26+/mo | Sentry |

### 2.2 Data

| Component (what it does) | Best pick (cost) | Cheapest solid alternative (cost) | Build ourselves? | Risk | Best case → worst case | Call |
|---|---|---|---|---|---|---|
| Main database (users, agents, orders, ledger) | Aurora PostgreSQL: about $0.12 per capacity-unit-hour on Serverless v2; can't scale to zero | Supabase or Neon for development and early stages (Neon doesn't support TimescaleDB) | No | High (money data) | ~$90/mo → $1–2k/mo with standby replicas at scale (est.) | Aurora or RDS Multi-AZ in production; Neon for development |
| Analytics and time-series (decision logs, metrics, price bars) | ClickHouse, self-hosted (~$50–100/mo, est.) | TimescaleDB | No | Medium | $50 → ~$1k/mo | ClickHouse |
| Cache, leaderboards, rate limits | ElastiCache for Valkey: serverless minimum about $6/month; smallest node about $9/month | Upstash: 1M commands under 1 GB costs about $2 | No | Low | $6 → ~$300/mo | Valkey |
| Event bus (prices, signals, orders, fills) | NATS JetStream, self-hosted (about 1M durable messages/second) | Redpanda (Kafka-compatible, single binary, no JVM) | No | Medium | ~$60 → ~$500/mo | NATS |
| Files, historical data, archives | S3 (Object Lock for tamper-proof records) | Cloudflare R2 (no data-out fees) | No | Low | $10 → ~$300/mo | S3 for records, R2 for heavy reads |
| Semantic search (news, agent memory) | pgvector inside Postgres | Pinecone | No | Low | $0 extra | pgvector |
| Text search (agents, people, clans) | Postgres full-text search | Typesense | No | Low | $0 extra | Postgres |

### 2.3 Agent engine

| Component (what it does) | Best pick (cost) | Cheapest solid alternative (cost) | Build ourselves? | Risk | Best case → worst case | Call |
|---|---|---|---|---|---|---|
| Durable runtime (keeps each agent's loop alive through crashes and deploys) | Temporal Cloud: $50 per million actions, no base fee; commitments cut that by more than half; $6,000 startup credits | DBOS (library that saves workflow progress in our own Postgres); self-hosted Temporal; Hatchet (MIT) | Rent the engine, build the workflows | Medium | $0 on credits → ~$3–5k/mo at 10k agents at list price (est.) | Temporal Cloud; self-host at ~$3–5k/mo |
| Watch engine (checks every agent's conditions on each update) | Build: Python service on NATS, conditions grouped by symbol, two or more copies | RisingWave or Flink (streaming SQL) | Yes, core IP | Medium–high | ~$100 → ~$1k/mo compute | Build |
| Shared indicators and signals | Build with polars + TA-Lib | NautilusTrader indicators | Yes | Low–medium | Included in compute | Build |
| Decision workers (run rules or AI when an agent wakes) | Python containers on Fargate | Lambda | Yes | Medium | Included in compute | Fargate |
| Sandbox for user SDK code | AWS Lambda on Arm: $0.20 per million requests + $0.0000133334 per GB-second; 1M requests and 400,000 GB-seconds free monthly | E2B for interactive sessions: ~$0.05/vCPU-hour + ~$0.018/GiB-hour, free Pro tier for startups; Northflank ~$0.017/vCPU-hour | No | High if self-built | ~$0 → ~$500/mo (est.) | Lambda for decision runs; E2B for SDK development sessions |
| Model gateway (routes calls to model providers, enforces budgets) | LiteLLM (open source, self-hosted), no fee | Vercel AI Gateway (no markup); OpenRouter (5.5% on credit purchases; own keys free to 1M requests/month, then 5%) | No | Low | 0% → 5.5% of all model spend | LiteLLM |
| AI models | Haiku 5.5: $0.10 in / $0.50 out per million tokens for prompts under 100k tokens; cached input $0.01; batch half price. Sonnet 5.5: $2/$10, or $1/$5 through batch | DeepSeek V4 ($0.14/$0.28), GPT and Gemini through the same gateway | No | Medium (prices change) | ~$2 per AI agent per month → $10+ with checks every minute (est.) | Haiku for scans; Sonnet for builder and escalations |
| AI tracing and evaluations | Langfuse: free Hobby tier, Core $29/month, Pro $199/month; MIT core can be self-hosted | Arize Phoenix | No | Low | $0 → $199/mo | Langfuse |
| Builder agent (turns conversations and past trades into agents) | Build on provider SDKs with structured outputs | LangGraph | Yes, core IP | High (quality) | Model costs only | Build |

### 2.4 Trading core

| Component (what it does) | Best pick (cost) | Cheapest solid alternative (cost) | Build ourselves? | Risk | Best case → worst case | Call |
|---|---|---|---|---|---|---|
| Broker connections | Direct, $0 per user: Robinhood's agent connection; IBKR Web API (third parties must register and pass IBKR compliance approval); Alpaca later | SnapTrade: $2 per connected user per month, unlimited requests at up to 250/minute; one person counts once across all their brokers. Plaid Investments is read-only (no trading) | Build adapters | High (approvals) | $0 per user → $2 per user if direct routes are refused | Direct first; SnapTrade for other brokers and history import |
| Order management (order states, no duplicates) | Build on Postgres | NautilusTrader execution components | Yes | High | — | Build carefully |
| Risk engine (limits, approvals, kill switch) | Build as plain code outside the agents | — | Yes | High | — | Build |
| Ledger and reconciliation | Build: double-entry in Postgres | Formance (open-source ledger) | Yes | High | — | Build |
| Paper broker (simulated fills on live prices) | Build | Alpaca paper accounts (free, Alpaca only) | Yes | Medium | — | Build, so paper works with every broker |
| Backtest engine | NautilusTrader: LGPL-3.0, Rust core, same strategy code in backtest and live | LEAN (Apache 2.0) | No | Medium (still maturing) | $0 license | NautilusTrader |
| Live market data | Databento Standard: $199/month, live data with no exchange license fees. Its US Equities Mini feed allows display and redistribution without licensing restrictions | Massive: individual plans $29–199/month, but redistribution needs a Business contract. Alpaca's free real-time IEX feed for prototyping | No | Medium (licensing) | $199/mo → Plus about $1,500/mo or Unlimited about $4,000/mo | Databento Standard; confirm terms in writing |
| Historical data | Included: Standard covers the full history of 1-second and 1-minute bars for US equities. Store as Parquet, query with DuckDB | Massive bulk files | No | Low | $0 extra → pay-as-you-go for deep tick data | Databento |
| News and sentiment | Stock News API ($19.99–49.99/month) plus our own AI tagging | Benzinga (custom quote). Reddit commercial access about $0.24 per 1,000 calls with a $12,000/year minimum | Build tagging | Medium | $20/mo → $1k+/mo with social data | News first, social later |
| Reference data (symbols, splits, calendars) | Databento | Massive | No | Medium (missed splits break backtests) | Included | Databento |

### 2.5 Product services

| Component (what it does) | Best pick (cost) | Cheapest solid alternative (cost) | Build ourselves? | Risk | Best case → worst case | Call |
|---|---|---|---|---|---|---|
| Login | WorkOS AuthKit: free up to 1M monthly active users | Clerk (free to 50,000 retained users); Better Auth (free, open source) | No | Low | $0 → $0 at our scale | WorkOS |
| API layer | FastAPI (Python) behind Next.js | — | Yes | Low | Included in compute | Build |
| Real-time push (prices, agent activity, feeds) | Centrifugo (open source, self-hosted) | Ably: free tier of 6M messages/month and 200 concurrent connections | No | Low–medium | ~$30 → ~$500/mo | Centrifugo |
| Clan chat | Build on Centrifugo + Postgres | Stream, about $399/month | Yes | Medium (moderation) | ~$0 → $399+/mo | Build simple |
| Feeds and follows | Postgres + Valkey | Stream Feeds | Yes | Medium | Included | Build |
| Leaderboards | Valkey sorted sets, fed by broker-verified fills | — | Yes | Low | Included | Build |
| Competitions engine | Build | — | Yes | High | — | Build |
| Email and push notifications | Amazon SES or Resend; web push | Postmark | No | Low | ~$0 → ~$100/mo | SES |
| Billing and credits | Stripe plus our own credit ledger; Stripe Billing takes 0.7% of billed volume | Lago (open source, used by Mistral AI); Orb (now part of Adyen) | Build credit ledger | Medium | 0.7% + card fees | Stripe + our own ledger |
| Product analytics and feature flags | PostHog | Amplitude | No | Low | Free tier → paid at scale | PostHog |
| Admin tools | Internal admin screens | Retool | Yes | Low | — | Build basic |

### 2.6 Compliance and money (later stages)

| Component (what it does) | Best pick (cost) | Cheapest solid alternative (cost) | Build ourselves? | Risk | Best case → worst case | Call |
|---|---|---|---|---|---|---|
| Tamper-proof records | S3 Object Lock + append-only audit log | — | Build | Medium | ~$10/mo | Build from day one |
| ID checks (paid competitions) | Sumsub: $1.35–1.85 per check, $149–299/month minimums | Persona (custom quote), Plaid Identity Verification | No | Medium | Only when paid contests launch | Sumsub |
| Location checks (state rules) | Radar (bills per user; claims 50–90% savings over per-check pricing) | GeoComply (reportedly $0.01–0.05 per check) | No | High (state law) | Only when paid contests launch | Choose with our lawyer |
| Holding and paying out pots | Licensed payments or escrow partner | — | Never | Very high | Partner fees | Partner |
| Security certification (SOC 2) | Vanta or Drata | — | No | Medium | Later | When partners ask |

---

## 3. Can we build it ourselves directly on AWS or GCP?

Mostly yes, and the recommended plan already does. Most of the stack is AWS building blocks (Fargate, Lambda, Aurora, S3, KMS, SES) plus open-source software we host plus our own code. The table covers every component where a third party is an option, with the "go to the core provider and build the rest ourselves" route next to it.

| Component | Third-party option | Do-it-ourselves route (core provider + our code) | Cost vs third party | Effort | Risk | Verdict |
|---|---|---|---|---|---|---|
| Durable runtime | Temporal Cloud ($50/M actions) | Self-host open-source Temporal on our containers with Postgres, or use DBOS (a library on our own Postgres) | Servers only (~$100–300/mo, est.) vs per-action billing | Medium (Temporal ops) / Low (DBOS) | Medium | **DIY later** when Cloud passes ~$3–5k/mo; DBOS works from day one |
| Code sandbox | E2B | AWS Lambda (Firecracker microVMs underneath) *is* the do-it-ourselves route. Going further means running Firecracker on bare-metal EC2, or GKE Sandbox (gVisor) on GCP | Lambda costs cents; bare metal pays off only at very high, steady volume | High for bare metal | High (security) | **Lambda now**; never hand-roll Firecracker early |
| Model gateway | OpenRouter (5.5%) | LiteLLM on our containers | Saves 5.5% of model spend | Low | Low | **DIY now** |
| AI models | Anthropic / OpenAI APIs | Same models through AWS Bedrock or Google Vertex (one bill; check which cloud credits apply, since Google's don't cover third-party models), or self-host open-weight models on GPUs | Self-hosting GPUs costs more than Haiku 5.5's $0.10/$0.50 at our volume | High | Medium | **Use APIs**; Bedrock if credits apply |
| AI tracing | Langfuse Cloud ($29–199/mo paid) | Self-host Langfuse (MIT) on our containers + ClickHouse | Servers only | Low–medium | Low | Cloud free tier now; **self-host** when we outgrow it |
| Monitoring | Grafana Cloud | Self-host Prometheus, Loki, Tempo, and Grafana; or AWS Managed Prometheus/Grafana + CloudWatch (CloudWatch logs get expensive) | Self-host saves at scale but costs engineer time | Medium | Low | Free tier now; **self-host** past ~$500/mo |
| Error tracking | Sentry ($0–26/mo) | GlitchTip, self-hosted | Servers vs $26 | Low | Low | Keep Sentry (cheap) |
| Login | WorkOS (free to 1M MAU) | AWS Cognito: 10,000 MAU free, then $0.0055/MAU (Lite) or $0.015/MAU (Essentials); or Better Auth (open source) on our Postgres | WorkOS free is cheaper than Cognito | Low–medium | Medium (security) | **Stay on WorkOS**; Better Auth if we want zero vendors |
| Real-time push | Ably / Pusher | Centrifugo on our containers, or AWS API Gateway WebSockets ($1.00 per million messages + $0.25 per million connection-minutes) | Centrifugo is cheapest at scale | Low–medium | Low | **DIY (Centrifugo)** |
| Chat | Stream (~$399/mo) | Build on Centrifugo + Postgres | Saves $399+/mo | Medium | Medium (moderation) | **DIY** |
| Feeds | Stream Feeds | Postgres + Valkey | Saves vendor fees | Medium | Low | **DIY** |
| Main database | Aurora (managed) | Self-managed Postgres on EC2 | Maybe about half the cost (est.), but we own backups, failover, upgrades | Medium–high | High (money data) | **Don't DIY** the system of record |
| Cache | ElastiCache Valkey (~$6–9/mo to start) | Valkey on our containers | Small savings | Low | Low | Either; managed is cheap |
| Event bus | Synadia, Confluent, MSK | NATS on our containers | Servers only | Medium | Medium | **DIY** |
| Analytics database | ClickHouse Cloud | Self-hosted ClickHouse | Servers only | Medium | Medium | **DIY** to start |
| Product analytics | PostHog | Events into our ClickHouse + Grafana or Metabase | Saves fees later | Low | Low | PostHog free tier now; DIY later |
| Containers | Fargate | EC2 servers with ECS or k3s on savings plans | Cheaper for steady load (est. 30–50%), but we manage servers | Medium | Low–medium | Fargate first; move steady services to EC2 later |
| CI/CD | GitHub Actions hosted runners | Self-hosted runners on EC2 Spot | Cheaper at volume | Low | Low | Later |
| Billing | Stripe Billing (0.7%) + Stripe Payments | Our own subscription and credit logic, with Stripe only for card processing | Saves 0.7% of billed volume | Medium | Medium | **Build the credit ledger now**; move subscriptions off Stripe Billing when volume justifies it |
| Broker connections | SnapTrade ($2/user/month) | Direct adapters to Robinhood, IBKR, Alpaca | $0 per user | Medium–high | High (approvals) | **DIY for the main brokers** |
| Backtest engine | QuantConnect (hosted) | NautilusTrader, self-hosted | License-free | Medium | Medium | **DIY** |
| News | Benzinga and other paid APIs | Our own feed from SEC EDGAR filings (free public data: 8-Ks, insider Form 4s) plus company press-release feeds, tagged by our models | Data is free; wire news still needs a license | Medium | Medium (content licensing) | **DIY for filings**; buy wire news |
| Market data | Databento | Direct exchange feeds | Far more expensive (license fees, connectivity), so DIY isn't cheaper | Very high | High | **Don't**; Databento is the cheap path |
| ID and location checks | Sumsub, Radar | Free IP-geolocation databases for basic gating only | Not compliance-grade | — | High | **Buy** for real-money contests |
| Pot custody | Licensed partner | — | — | — | Very high | **Never build** |
| Secrets | HashiCorp Vault | AWS KMS + our wrapper | Cents | Low–medium | Very high impact | **DIY** |

### What we actually have to pay third parties for

| Must pay | Why it can't be built | Cost |
|---|---|---|
| Market data (Databento) | Exchange licensing; building our own feed costs far more | $199/mo to start |
| AI models (Anthropic, others) | Matching their quality requires frontier models | Usage-based (see costs) |
| Card payments (Stripe) | Payment processing is regulated | Card fees (+0.7% if we use Stripe Billing) |
| Cloud (AWS) | Building blocks for everything else | Usage-based, mostly covered by credits early |
| Broker aggregator (SnapTrade), for less common brokers only | Each broker's integration and approval | $2 per connected user per month, only for users who need it |
| Later: ID checks, location checks, escrow partner | Regulated and liability-heavy | Per check or partner fees |

Free or near-free vendors we keep because they're cheaper than doing it ourselves: WorkOS, Sentry, and the Grafana Cloud and Langfuse free tiers.

### Three ways to run it (est.)

| Approach | What it means | Fixed cost at launch | Fixed cost at 10k users | Extra engineering load | Verdict |
|---|---|---|---|---|---|
| Managed-heavy | Temporal Cloud, paid Grafana Cloud, Ably, Stream, Langfuse Pro, OpenRouter, SnapTrade for every broker, Aurora | ~$1.7–2.5k/mo | ~$30–40k/mo (SnapTrade alone ~$20k at $2/user) | Lowest | Fast to build, expensive at scale |
| **Recommended hybrid** | Managed database and login; open source we host for the event bus, real-time, and gateway; direct broker connections; monitoring free tiers | ~$750–1,700/mo | ~$8k/mo | Moderate | **Best balance** |
| Do-it-ourselves max | Self-host everything including Postgres, Temporal, monitoring; reserved EC2 servers | ~$500–1,000/mo | ~$5–6k/mo | High (about a part-time ops person) | Only cheaper if engineering time is free |

---

## 4. Costs

### Cost per active user per month (est.)

| User type | What they run | Cost |
|---|---|---|
| Light | 2 rule-based agents | $0.50–1 |
| Typical | 1 rule-based agent, 1 AI agent (checks every 5 minutes, ~5 escalations a day), ~3 builder sessions | $4–6 |
| Heavy | 5 AI agents checking every minute, SnapTrade connection | $25–40 |

Where the typical number comes from:
- A Haiku check costs about $0.0002–0.0005.
- An escalation to Sonnet costs about $0.015.
- A builder session costs about $0.50.
- The runtime costs about $0.33 per agent per month at Temporal's list price.

Newer Claude models count about 30% more tokens for the same text, so these numbers include headroom.

### Fixed costs at launch per month (est.)

| Line | Best case | Expected | Worst case |
|---|---|---|---|
| Containers | $150 | $300–500 | $800 |
| Postgres | $50 | $150–350 | $700 |
| ClickHouse, Valkey, S3 | $25 | $75–200 | $400 |
| Temporal | $0 | $0–150 | $300 |
| Market data | $199 | $199 | $1,500 |
| News | $20 | $20–50 | $50 |
| Monitoring, errors, AI tracing | $0 | $0–75 | $250 |
| Login | $0 | $0 | $0 |
| E2B | $0 | $0–150 | $150 + usage |
| **Total** | **~$450** | **~$750–1,700** | **~$4,150** |

### At 10,000 active users (est., Pro $27, Premium $79)

| | Best case | Expected | Worst case |
|---|---|---|---|
| Free / Pro / Premium mix | 70 / 25 / 5% | 85 / 12 / 3% | 95 / 4 / 1% |
| Variable cost | ~$34k | ~$22k | ~$16k |
| Fixed cost | ~$8k | ~$8k | ~$12k |
| Total cost | ~$42k | ~$30k | ~$28k |
| Revenue | ~$107k | ~$56k | ~$19k |
| Gross margin | ~61% | ~47% | Loss of ~$9k/mo |

The risk is how many users pay, not infrastructure. Break-even is about 6% of active users paying (est.).

### What we charge (proposed)

Comparable products: Composer's Trading Pass is $32/month billed annually ($40 monthly), TradersPost is $49.99/month, and QuantConnect Researcher is $84/month.

| Plan | Price | Includes | Gross margin (est.) |
|---|---|---|---|
| Free | $0 | Paper trading, backtests, 1 live rule-based agent, small AI allowance | About -$1 per active user |
| Pro | $25–29/mo | Unlimited rule-based agents, 2 AI agents, builder allowance, competitions | ~65–75% |
| Premium | $79/mo | More AI agents, checks every minute, larger models, priority | ~50–70% |
| Credits | Top-ups | Priced at about 2× model cost | ~50% |

Hard caps on free AI usage. Every agent has a compute budget.

### Startup credits to apply for

| Program | Amount | Requirement |
|---|---|---|
| AWS Activate | $1,000 (some get $5,000); up to $200,000 | Self-funded tier is open; the large tier needs a provider ID from a VC or accelerator |
| Google for Startups | Up to $350,000 (AI-first) | Equity funding; doesn't cover third-party models on Vertex |
| Microsoft for Startups | Up to $150,000 in Azure plus OpenAI credits | Application |
| Temporal | $6,000 | Under $30M raised |
| E2B | Free Pro tier | Startup program application |
| Cloudflare | $10,000 tier | Open to unfunded founders |

---

## 5. Workarounds that change the math

| Workaround | What it saves | How |
|---|---|---|
| Databento's license-free feed | Thousands per month in business data licenses | Use the US Equities Mini feed on the $199 Standard plan for both agents and display. Databento says it adds no redistribution restrictions of its own; confirm our exact use in writing |
| Shared watch engine | ~$49 per agent per month → cents | One engine checks every agent's conditions; agents sleep between triggers |
| Stops and limits held at the broker | Reliability, plus compute | Exits fire even if our platform is down |
| Shared prompt prefix across agents | Most model input cost | All agents share one system prompt, so the prompt cache stays warm |
| Batch API for backtests and nightly reviews | 50% of those model costs | They aren't time-sensitive |
| Store AI decisions per agent version and data snapshot | Re-run backtests for free | Replay stored outputs instead of calling the model again |
| LiteLLM instead of OpenRouter | 5.5% of model spend | Self-hosted gateway with our own provider keys |
| KMS envelope encryption | ~$0.40 per user per month | Encrypted tokens live in Postgres instead of one stored secret per user |
| Direct broker connections | $2 per user per month | SnapTrade only for less common brokers. For history import: connect, import, disconnect (check billing terms); avoid manual syncs ($0.05 each) |
| Event-driven wakes, commitments, self-hosting | Most of the Temporal bill | Agents wake on events, not fixed polling; self-hosting is the fallback |
| Fargate Spot and Graviton | ~70% on batch jobs, ~20% everywhere | Backtests on Spot; Arm processors for everything |
| Our own paper broker | Per-broker paper limits | One simulator for every broker, consistent across competitions |
| Staggered wakes at the 9:30am open | Broker rate-limit failures | Spread wake-ups out; queue orders per broker |
| Free tiers | Hundreds per month early | WorkOS, Grafana Cloud, Langfuse, Sentry, PostHog |
| SEC EDGAR filings | Part of the news bill | Free official filings (8-Ks, insider trades), tagged by our models |

---

## 6. Build vs rent

| Category | Components | Why |
|---|---|---|
| Build (ours, core) | Builder agent, watch engine, shared signals, order management, risk engine, ledger, paper broker, broker adapters, credit ledger, competitions, social features, leaderboards | This is the product, and where correctness matters |
| Run open source ourselves | NATS, Centrifugo, LiteLLM, NautilusTrader, ClickHouse, Langfuse (later) | No license fees; we pay only for servers |
| Rent from core cloud | Containers, Lambda, Aurora/RDS, S3, KMS, SES, Valkey | Building blocks; managed where failure is expensive |
| Rent from specialists | Market data, AI models, payments, login (free), monitoring (free tier) | Cheaper and better than building |
| Never build | Sandbox isolation technology, exchange data feeds, pot custody, ID and location checks | Security-critical or regulated |

### Hardest parts, ranked

| Rank | Part | Why it's hard |
|---|---|---|
| 1 | Builder agent quality | Turning conversations and past trades into correct strategies; this is the core IP |
| 2 | Real-money correctness | Order management, risk engine, ledger, reconciliation |
| 3 | Watch engine and runtime at scale | Thousands of agents waking at the market open |
| 4 | Broker approvals and quirks | Depends on the brokers, not on us |
| 5 | Realistic simulation | Fills, slippage, and backtests of AI-judged decisions |
| 6 | Competition integrity | Cheating detection; later, the legal work around pots |
| Easy | Login, notifications, leaderboards, feeds, dashboards | Well-trodden ground |

---

## 7. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Builder produces wrong strategies | High | High | Replay and backtest before deploying; plain-English review; guardrails |
| Duplicate or missed orders | Medium | Very high | Unique key per order; reconciliation against the broker; stops and limits held at the broker |
| A broker refuses access for hosted agents | Medium | High | Fall back to SnapTrade and Alpaca; add more brokers |
| Overload at the 9:30am open | High | Medium | Stagger wakes; queue orders per broker |
| Misusing market data licenses | Low–medium | High | Databento's terms in writing |
| AI model price changes | Medium | Medium | Gateway with multiple providers; per-agent budgets |
| Too few paying users | Medium | High | Free-tier caps; clear reasons to upgrade to Pro |
| Broker credential leak | Low | Very high | KMS encryption; models and user code never see tokens |
| Competition cheating | Medium | High | Score only broker-verified fills; collusion checks |

---

## 8. Build stages mapped to the stack

| Stage | What gets built |
|---|---|
| 1. Foundation | AWS, Fargate, Aurora, Valkey, NATS, Temporal Cloud, Databento, NautilusTrader, agent definition, watch engine v1, paper broker, LiteLLM, WorkOS |
| 2. Builder and Lab | Builder agent, backtests, instant replay, past-trade import (SnapTrade read-only), Langfuse |
| 3. Live trading | Robinhood and IBKR adapters, order management, risk engine, ledger and reconciliation, Lambda sandbox, Centrifugo, notifications |
| 4. Social and Arena | Profiles, follows, feeds, chat, leaderboards, competitions, Stripe billing and credit ledger |
| Later | ID and location checks, pot partner, SOC 2, crypto |

### Suggested ownership

| Owner | Areas |
|---|---|
| Platform and trading core | Cloud, data stores, event bus, watch engine, runtime, broker connections, order management, risk engine, ledger, paper broker, market data |
| AI and product | Builder agent, model gateway, prompts and evaluations, Lab experience, frontend, social features, billing |

---

## 9. Decisions to make

| Decision | Options | Recommendation | When |
|---|---|---|---|
| Primary cloud | AWS / GCP | AWS | Now |
| Durable runtime | Temporal Cloud / DBOS | Temporal Cloud | Stage 1 |
| Watch engine language | Python / Rust | Python first; Rust for hot paths later | Stage 1 |
| Backtest engine | NautilusTrader / LEAN | NautilusTrader | Stage 1 |
| Market data | Databento Standard / Massive Business | Databento, once terms are confirmed | Now |
| Broker routes | Direct / SnapTrade | Direct plus SnapTrade; apply to IBKR and Robinhood now | Apply now, build in Stage 3 |
| Login | WorkOS / Clerk | WorkOS | Stage 1 |

## 10. Changes vs the current PRD & Technical doc

| Area | Was | Now |
|---|---|---|
| Sandbox | E2B | Lambda, with E2B for SDK development sessions |
| Model routing | OpenRouter | LiteLLM |
| Backtesting | LEAN | NautilusTrader (LEAN as fallback) |
| Market data | Undecided | Databento Standard |
| New components | — | Watch engine, NATS, ClickHouse, Centrifugo, WorkOS, Langfuse |

---

## Sources

Most of these came from search results and weren't all read in full; confirm figures before relying on them.

- Sandboxes: https://e2b.dev/pricing · https://www.beam.cloud/blog/e2b-pricing-explained · https://northflank.com/blog/ai-sandbox-pricing
- AWS Lambda: https://www.eon.io/blog/aws-lambda-pricing · https://cloudburn.io/blog/aws-lambda-pricing
- AWS Fargate: https://www.factualminds.com/tools/aws-fargate-pricing-calculator/
- Temporal: https://temporal.io/blog/paygo-developer-support · https://temporal.io/pricing
- DBOS, Hatchet: https://dbos.dev/compare/dbos-vs-temporal · https://aicoolies.com/comparisons/hatchet-vs-temporal
- Model gateways: https://hackernoon.com/openrouter-alternatives-in-2026-three-ai-gateways-compared-for-production-scale · https://www.betterclaw.io/blog/openrouter-alternatives-ai-agents · https://api7.ai/openrouter-vs-litellm
- Claude pricing: https://techenclave.com/news/items/claude-haiku-5-5-launches-with-0-10-input-pricing-for-shorter-prompts · https://apidog.com/blog/claude-sonnet-5-5-pricing/ · https://emergent.sh/learn/claude-haiku-5-5-pricing · https://www.eesel.ai/blog/claude-haiku-5-5-pricing
- Other model pricing: https://techsy.io/en/blog/llm-api-pricing-comparison
- Databento: https://databento.com/blog/introducing-databento-us-equities · https://databento.com/blog/databento-us-equities-mini-now-available · https://databento.com/blog/upcoming-changes-to-pricing-plans-in-january-2025 · https://databento.com/pricing · https://us.fitgap.com/products/033314/databento
- Massive, Alpaca data: https://multiples.vc/compare/api-pricing · https://providers.apievangelist.com/providers/polygon/ · https://qveris.ai/guides/stock-api-free-comparison/?lang=en
- SnapTrade, Plaid: https://us.fitgap.com/products/snaptrade · https://snaptrade.com/blogs/plaid-vs-yodlee · https://snaptrade.com/brokerage-api · https://snaptrade.com/comparison-plaid
- IBKR third-party access: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/o-auth-1-0-a/third-party-o-auth/third-party-o-auth-workflow · https://www.ibkr.com/download/03-IB17-1071-API.pdf
- NautilusTrader: https://docs.ccxt.com/docs/comparisons/ccxt-vs-nautilustrader · https://docs.nautilustrader.io/concepts/overview.html
- Login: https://workos.com/blog/workos-vs-betterauth-vs-clerk · https://devtoollab.com/blog/best-authentication-providers · https://clerk.com/articles/clerk-vs-aws-cognito-developer-experience-vs-scale-economics-3 · https://us.fitgap.com/products/020158/amazon-cognito
- Real-time: https://ably.com/compare/ably-vs-centrifugo · https://sliplane.io/de-de/blog/5-awesome-soketi-alternatives · https://talkjs.com/resources/ably-alternatives/ · https://wring.co/blog/aws-api-gateway-pricing-guide
- Billing: https://flexprice.io/questions/best-alternative-to-stripe-billing-for-usage-based-pricing · https://www.solvimon.com/blog/best-billing-systems-for-ai-startups-in-2026-what-actually-matters-beyond-metering · https://www.landbase.com/blog/usage-based-billing-software
- Monitoring, tracing: https://betterstack.com/community/comparisons/datadog-vs-grafana-cloud.md · https://www.guance.com/learn/articles/datadog-vs-grafana-cloud · https://dupple.com/learn/best-observability-platforms · https://futureagi.com/blog/best-grafana-alternatives-2026
- Databases: https://guptadeepak.com/tools/top-5-database-as-a-service-platforms-2026/ · https://neon.tech/blog/postgres-autoscaling-aurora-serverless-v2-vs-neon · https://www.techplained.com/best-managed-postgres
- Cache: https://upstash.com/blog/upstash-vs-aws-elasticache-serverless-redis-pricing-and-performance-2026 · https://upstash.com/blog/aws-elasticache-pricing-explained-2026-full-cost-breakdown
- Event bus: https://www.index.dev/skill-vs-skill/nats-vs-redis-vs-kafka · https://www.pkgpulse.com/guides/redpanda-vs-nats-vs-apache-kafka-event-streaming-2026
- News and social data: https://us.fitgap.com/products/stock-news-api · https://www.xpoz.ai/blog/guides/reddit-api-pricing-tiers-and-alternatives/
- ID and location checks: https://www.signzy.com/blogs/persona-alternatives · https://tech-insider.org/?p=8820
- Startup credits: https://hub.causo.ai/startup-cloud-credits-compared-2026 · https://fin.ai/learn/startup-credit-programs · https://echai.ventures/startingup/from/guptadeepak-com
- Comparable pricing: https://tooliverse.ai/tools/composer · https://www.quantconnect.com/pricing.md · https://traderspost.io/compare/traderspost-vs-composer
