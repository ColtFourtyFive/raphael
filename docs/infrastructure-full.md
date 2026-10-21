# Agent Trading Platform: Complete Backend & Infrastructure Plan

> **Note:** this predates the big-ticket research. `docs/big-ticket-costs.md` has the current choices and numbers: the agent loop runs on a NATS job queue instead of Temporal (~$0), servers on ECS on EC2 (~$180–200/mo at launch), RDS Multi-AZ (~$230/mo), direct broker APIs, and a recommended-setup total of ~$0.9k / $1.2k / $8.2k per month at 500 / 1k / 10k users.


*For das and Aryan · October 20, 2026 · Replaces the earlier infrastructure file*

*Prices are public list prices as of October 2026 and change often. "est." = our own estimate. Anything marked "confirm" must be verified directly with the vendor before we commit.*

---

## 0. Research coverage

What has been checked, what is estimated, and what is still open.

| Area | Providers and options compared | Status |
|---|---|---|
| Hosting and compute | AWS Fargate, AWS EC2, Google Cloud Run, Cloudflare Workers and Containers, Hetzner | Verified pricing |
| Durable runtime (keeps agent loops alive) | Temporal Cloud, self-hosted Temporal, DBOS, Hatchet, AWS Step Functions, Cloudflare Workflows and Durable Objects | Verified; exact Step Functions per-transition rate not captured |
| Code sandboxes | E2B, Daytona, Modal, Northflank, AWS Lambda, Lambda MicroVMs, Cloudflare Workers for Platforms, GKE Sandbox | Verified pricing |
| AI models and routing | Anthropic direct, AWS Bedrock, Google Vertex, OpenRouter, Vercel AI Gateway, LiteLLM, DeepSeek, GPT, Gemini | Verified (Anthropic prices from reputable summaries; confirm on Anthropic's page) |
| Market data | Databento, Massive (formerly Polygon), Alpaca | Verified; Massive Business price is quote-only; **confirm** Databento redistribution terms in writing |
| News and filings | SEC EDGAR, Stock News API, Benzinga, sec-api.io, Reddit | Verified except Benzinga (quote-only) |
| Brokers | Robinhood agent connection, IBKR Web API, SnapTrade, Plaid, Alpaca | Access models verified; Robinhood rate limits unpublished (**confirm**) |
| Databases | Aurora, RDS, Neon, Supabase, Cloud SQL, AlloyDB, ClickHouse (self-hosted and Cloud) | Verified |
| Cache and event bus | ElastiCache Valkey, Upstash, NATS, Redpanda, Kafka | Verified; managed NATS/Redpanda prices not captured (self-hosting assumed) |
| Login | WorkOS, Clerk, Auth0, Better Auth, AWS Cognito, Supabase Auth | Verified |
| Real-time and chat | Centrifugo, Ably, Pusher, Stream, API Gateway WebSockets, Supabase Realtime, Cloudflare Durable Objects | Verified |
| Billing | Stripe Billing, Metronome, Orb, Lago, OpenMeter | Verified; Stripe card fees not captured |
| Monitoring and analytics | Grafana Cloud, Datadog, SigNoz, Sentry, Langfuse, PostHog | Verified |
| Compliance | Sumsub, Persona, GeoComply, Radar, Vanta, Drata, SOC 2 audits | Verified ranges |
| Startup credits | AWS, Google, Microsoft, Temporal, E2B, Cloudflare | Verified |
| **Not researched** | X (Twitter) API, escrow partners for pots (legal-led), Webull direct API terms, Alpaca Broker API (embedded brokerage), legal fees | Next round |
| **Our estimates** | Per-user costs, container sizing, scale scenarios, approach comparisons | Estimates; check against real usage |

---

## 1. Summary

| Question | Answer |
|---|---|
| How does it run cheaply? | Agents are data plus timers, not servers. A shared watch engine monitors markets for every agent and wakes an agent only when its conditions fire. |
| What must we pay third parties for? | Market data, AI models, card payments, cloud, and (for less common brokers) a broker aggregator. Later: ID checks, location checks, an escrow partner, SOC 2. |
| Recommended setup | AWS-based hybrid: managed database and login, plus open-source software we host for the event bus, real-time push, and model gateway, plus our own code for the core. |
| Launch cost | ~$750–1,700/month fixed (est.), much of it coverable by credits. |
| Cost per user | ~$0.50–1 light, $4–6 typical, $25–40 heavy per month (est.). |
| Biggest savings found | Databento's $199/month feed can be shown to users without license fees. AWS credits reportedly pay for Claude via Bedrock at the same price as Anthropic direct. A self-hosted model gateway avoids OpenRouter's 5.5%. Lambda makes sandboxes cost cents. Cloudflare charges nothing while workflows sleep. |
| Biggest risk | Not infrastructure: builder quality, real-money correctness, broker approvals, and how many users pay. |

---

## 2. How the system works

### Agents don't run as servers
- An agent is a database row plus a timer. A durable workflow sleeps until a trigger fires, a shared worker runs one decision, and the agent sleeps again. Sleeping costs nothing.
- An always-on sandbox per agent would cost ~$49 per agent per month at E2B's rates (1 vCPU, 1 GiB). The shared design costs cents.
- Reliability comes from durable execution, unique order keys, and reconciling with the broker every cycle.

### Watching vs thinking

| | Watching | Thinking |
|---|---|---|
| What | Checking every agent's conditions against each price update, news item, or schedule | Running the agent's rules or AI judgment, then the risk check and order |
| Who | One shared watch engine (two or more copies) | The agent, woken by the engine |
| When | Continuously | Only when a condition fires or a scheduled scan is due |
| Cost | A few containers for the whole platform | Per decision (AI credits where used) |

- Indicators are computed once per symbol and shared by every agent that uses them.
- Judgment-based agents still watch continuously, through event triggers, scheduled cheap-model scans, and escalation to a stronger model.
- Stop-losses and take-profits are sent to the broker as native orders, so they fire even if we're down.

### One engine, three modes

| Mode | Data | Clock | Fills |
|---|---|---|---|
| Backtest | Historical | Simulated | Simulated |
| Paper | Live | Real | Our paper broker |
| Live | Live | Real | Real broker |

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
| Agent engine | Watch engine, shared signals, durable runtime, decision workers, sandbox, model gateway, builder agent |
| Trading core | Risk engine, order management, ledger, paper broker, broker adapters, backtest engine |
| Data | Postgres, ClickHouse, Valkey, NATS, S3/R2 |
| Foundation | Cloud, containers, secrets, monitoring, CI/CD |
| External | Brokers, market data, news and filings, AI models, Stripe |

---

## 3. Full stack: every component, best pick, alternatives, cost

Each layer has its own table. Columns:
- **Best pick:** our recommendation, with cost.
- **Cheapest solid alternative:** the lowest-cost option that still meets our quality bar.
- **Cloud-native option:** what AWS, Google Cloud, or Cloudflare offer themselves.
- **Build ourselves?:** whether we write it as our own code; running open-source software counts as "No".

### 3.1 Foundation and operations

| Component (what it does) | Best pick (cost) | Cheapest solid alternative (cost) | Cloud-native option (cost) | Build ourselves? | Risk | Best → worst case | Call |
|---|---|---|---|---|---|---|---|
| Cloud (runs everything) | AWS. Credits: $1,000 self-funded (some $5,000); up to $200,000 via VC/accelerator provider ID; reportedly covers Claude via Bedrock | Hetzner for dev and batch boxes (several times cheaper; no managed services) | GCP: up to $350,000 (AI-first, equity-funded), excludes Claude | No | Low | Credits cover year one → list prices | AWS |
| Containers (API, workers, engines) | ECS Fargate on Graviton: $0.03238/vCPU-hour, $0.00356/GB-hour; Spot ~70% off | EC2 servers on savings plans (cheaper for steady load, more ops work) | Google Cloud Run: ~$0.000018/vCPU-second (~$0.065/vCPU-hour), roughly 2× Fargate Arm | No | Low | ~$150 → ~$1,500/mo at 10k users (est.) | Fargate |
| Infrastructure as code, deploys | Terraform/OpenTofu + GitHub Actions | Pulumi | AWS CodePipeline, Google Cloud Build | Config | Low | ~$0 → $50/mo | Terraform |
| CDN, DNS, firewall | Cloudflare | — | CloudFront + AWS WAF (~$5/web ACL/month + $1/rule + $0.60/M requests) | No | Low | ~$0 → $200/mo | Cloudflare |
| Broker tokens, secrets | AWS KMS envelope encryption; encrypted tokens in Postgres (cents) | Infisical, HashiCorp Vault | AWS Secrets Manager (~$0.40 per secret per month; too costly per user) | Thin wrapper | Very high impact | Cents → ~$0.40/user/month if done wrong | KMS + wrapper |
| Monitoring | Grafana Cloud: free tier 10k metrics, 50 GB logs, 50 GB traces/month; Pro $19 + usage | SigNoz, self-hosted | CloudWatch, Managed Prometheus/Grafana (CloudWatch logs costly at volume) | No | Low | $0 → hundreds/mo | Grafana Cloud |
| Error tracking | Sentry: free; Team $26/month | GlitchTip, self-hosted | — | No | Low | $0 → $26+/mo | Sentry |
| Product analytics, feature flags | PostHog: 1M events free/month, then from $0.00005/event, falling with volume | Our own events into ClickHouse + Metabase | — | No | Low | $0 → ~$200/mo at 2M events | PostHog |

### 3.2 Data

| Component (what it does) | Best pick (cost) | Cheapest solid alternative (cost) | Cloud-native option (cost) | Build ourselves? | Risk | Best → worst case | Call |
|---|---|---|---|---|---|---|---|
| Main database (users, agents, orders, ledger) | Aurora PostgreSQL (~$0.12/capacity-unit-hour on Serverless v2; can't scale to zero) or RDS Multi-AZ | Supabase Pro ($25/month + compute; bundles database, login, storage, real-time); Neon for development | Google Cloud SQL (2 vCPU/16 GB with high availability ~$315/month); AlloyDB from ~$227/month per instance | No | High (money data) | ~$90 → $1–2k/mo (est.) | Aurora/RDS in production |
| Analytics, time-series (decision logs, metrics, bars) | ClickHouse, self-hosted (~$50–100/mo, est.) | ClickHouse Cloud Basic: $66.52 (6 h/day) to $186.27 (24/7)/month; Scale from ~$499; no free tier | BigQuery, Redshift | No | Medium | $50 → ~$1k/mo | Self-host first |
| Cache, leaderboards, rate limits | ElastiCache Valkey: serverless minimum ~$6/month; small node ~$9/month | Upstash: ~$2 per 1M commands under 1 GB | GCP Memorystore | No | Low | $6 → ~$300/mo | Valkey |
| Event bus (prices, signals, orders, fills) | NATS JetStream, self-hosted (~1M durable messages/second) | Redpanda (Kafka-compatible single binary) | Amazon SQS/SNS/Kinesis; Google Pub/Sub | No | Medium | ~$60 → ~$500/mo | NATS |
| Files, historical data, archives | S3 (Object Lock for tamper-proof records) | Cloudflare R2 (no data-out fees) | Google Cloud Storage | No | Low | $10 → ~$300/mo | S3 + R2 |
| Semantic search (news, agent memory) | pgvector in Postgres | Pinecone | OpenSearch, Vertex Vector Search | No | Low | $0 extra | pgvector |
| Text search (agents, people, clans) | Postgres full-text search | Typesense | OpenSearch | No | Low | $0 extra | Postgres |

### 3.3 Agent engine

| Component (what it does) | Best pick (cost) | Cheapest solid alternative (cost) | Cloud-native option (cost) | Build ourselves? | Risk | Best → worst case | Call |
|---|---|---|---|---|---|---|---|
| Durable runtime (keeps agent loops alive) | Temporal Cloud: $50/M actions, no base fee; commitments cut >50%; $6,000 startup credits | DBOS (library on our Postgres); self-hosted Temporal; Hatchet (MIT) | Cloudflare Workflows: no charge while sleeping; $0.30/M requests + $0.02/M CPU-ms. AWS Step Functions: per state transition, 4,000 free/month | Rent the engine, build the workflows | Medium | $0 → ~$3–5k/mo at 10k agents on Temporal list price (est.); ~$10–50/mo on Cloudflare (est.) | Temporal Cloud now; **prototype Cloudflare** (see section 4) |
| Watch engine (checks all agents' conditions) | Build: Python on NATS, conditions grouped by symbol, two or more copies | RisingWave or Flink (streaming SQL) | Managed stream processing (Kinesis Analytics, Dataflow): heavier | Yes, core IP | Medium–high | ~$100 → ~$1k/mo | Build |
| Shared indicators and signals | Build with polars + TA-Lib | NautilusTrader indicators | — | Yes | Low–medium | Included | Build |
| Decision workers | Python on Fargate | Lambda | Google Cloud Run | Yes | Medium | Included | Fargate |
| Sandbox for user SDK code | AWS Lambda on Arm: $0.20/M requests + $0.0000133334/GB-second; 1M requests + 400k GB-s free monthly | E2B (~$0.05/vCPU-hour + $0.018/GiB-hour; free Pro tier for startups); Northflank (~$0.017/vCPU-hour) | GKE Sandbox (gVisor); Cloudflare Workers for Platforms ($25/month; best suited to JavaScript) | No | High if self-built | ~$0 → ~$500/mo (est.) | Lambda for runs; E2B for development sessions |
| Model gateway | LiteLLM, self-hosted: 0% fee | Vercel AI Gateway (no markup); OpenRouter (5.5% on credit purchases; own keys free to 1M requests/month, then 5%) | Bedrock as a single endpoint for Claude and other models | No | Low | 0% → 5.5% of model spend | LiteLLM |
| AI models | Haiku 5.5: $0.10 in / $0.50 out per M tokens (prompts under 100k tokens); cache reads $0.01; batch half price. Sonnet 5.5: $2/$10; batch $1/$5 | DeepSeek V4 ($0.14/$0.28); GPT and Gemini through the same gateway | Bedrock: Claude at the same price as direct, credits reportedly apply, new versions arrive 1–4 weeks later. Vertex: Google credits cover Gemini, not Claude | No | Medium (prices change) | ~$2/AI agent/month → $10+ with every-minute checks (est.) | Direct API for newest models; Bedrock to spend AWS credits |
| AI tracing and evaluations | Langfuse: free Hobby tier; Core $29, Pro $199/month; MIT core self-hostable | Arize Phoenix | Bedrock/CloudWatch logging (basic) | No | Low | $0 → $199/mo | Langfuse |
| Builder agent | Build on provider SDKs with structured outputs | LangGraph | Bedrock AgentCore, Vertex Agent Engine (managed, lock-in) | Yes, core IP | High (quality) | Model costs | Build |

### 3.4 Trading core

| Component (what it does) | Best pick (cost) | Cheapest solid alternative (cost) | Cloud-native option (cost) | Build ourselves? | Risk | Best → worst case | Call |
|---|---|---|---|---|---|---|---|
| Broker connections | Direct, $0 per user. Robinhood's official agent connection (OAuth; ~100,000 agent accounts by late June; rate limits unpublished). IBKR Web API third-party OAuth (registration + compliance approval). Alpaca later | SnapTrade: $2/connected user/month (one per person; 250 requests/min; $0.05 per manual sync; daily plans reportedly from $1). Plaid Investments is read-only | — | Build adapters | High (approvals) | $0 → $2/user if direct routes are refused | Direct + SnapTrade |
| Order management | Build on Postgres (unique keys, order states) | NautilusTrader execution components | — | Yes | High | — | Build carefully |
| Risk engine | Build (plain code, outside agents) | — | — | Yes | High | — | Build |
| Ledger and reconciliation | Build (double-entry Postgres) | Formance (open-source ledger) | — | Yes | High | — | Build |
| Paper broker | Build on live quotes | Alpaca paper (free, Alpaca only) | — | Yes | Medium | — | Build |
| Backtest engine | NautilusTrader (LGPL-3.0, Rust core, same code backtest and live) | LEAN (Apache 2.0) | Run on AWS Batch or Cloud Run Jobs with Spot | No | Medium | $0 license | NautilusTrader |
| Live market data | Databento Standard: $199/month; US Equities Mini feed allows display and redistribution without license fees | Massive ($29–199 individual; Business contract to redistribute); Alpaca free IEX feed (prototype) | — | No | Medium (licensing) | $199 → Plus ~$1,500 or Unlimited ~$4,000/mo | Databento (**confirm** terms) |
| Historical data | Included: Standard covers the full history of 1-second and 1-minute bars; store as Parquet | Massive flat files | Query on S3 with Athena or DuckDB | No | Low | $0 extra | Databento |
| News and filings | SEC EDGAR (free, keyless, 10 requests/sec, ~4,700 filings/day) + Stock News API ($19.99–49.99/month) + our AI tagging | Benzinga (quote); sec-api.io (paid real-time filings); Reddit commercial (~$0.24/1k calls, $12k/year minimum) | — | Build ingest and tagging | Medium | $20 → $1k+/mo with social data | EDGAR + news API |
| Reference data (symbols, splits, calendars) | Databento | Massive | — | No | Medium | Included | Databento |

### 3.5 Product services

| Component (what it does) | Best pick (cost) | Cheapest solid alternative (cost) | Cloud-native option (cost) | Build ourselves? | Risk | Best → worst case | Call |
|---|---|---|---|---|---|---|---|
| Login | WorkOS: free to 1M monthly active users | Clerk (free to 50,000 retained users); Better Auth (free, open source); Supabase Auth (100,000 MAU on Pro) | AWS Cognito: 10,000 MAU free, then $0.0055/MAU (Lite) or $0.015 (Essentials) | No | Low | $0 → $0 | WorkOS |
| API layer | FastAPI + Next.js | — | API Gateway HTTP ($1.00/M calls) | Yes | Low | Included | Build |
| Real-time push | Centrifugo, self-hosted (free) | Ably (free: 6M messages/month, 200 connections); Supabase Realtime (5M messages included, $2.50/M after; 500 concurrent on Pro) | API Gateway WebSockets ($1.00/M messages + $0.25/M connection-minutes); Cloudflare Durable Objects with WebSocket hibernation | No | Low–medium | ~$30 → ~$500/mo | Centrifugo |
| Clan chat | Build on Centrifugo + Postgres | Stream (~$399/month) | — | Yes | Medium (moderation) | $0 → $399+/mo | Build |
| Feeds and follows | Postgres + Valkey | Stream Feeds | — | Yes | Medium | Included | Build |
| Leaderboards | Valkey sorted sets, fed by verified fills | — | — | Yes | Low | Included | Build |
| Competitions engine | Build | — | — | Yes | High | — | Build |
| Email and push | Amazon SES or Resend; web push | Postmark | Amazon SNS, Firebase Cloud Messaging | No | Low | ~$0 → $100/mo | SES |
| Billing and credits | Stripe + our own credit ledger (Stripe Billing takes 0.7% of billed volume) | Lago, OpenMeter (open source); Orb (now Adyen) | — | Build credit ledger | Medium | 0.7% + card fees | Stripe + own ledger |
| Admin tools | Internal admin screens | Retool | — | Yes | Low | — | Build basic |

### 3.6 Compliance and money (later stages)

| Component (what it does) | Best pick (cost) | Cheapest solid alternative (cost) | Cloud-native option (cost) | Build ourselves? | Risk | Best → worst case | Call |
|---|---|---|---|---|---|---|---|
| Tamper-proof records | S3 Object Lock + append-only audit log | — | — | Build | Medium | ~$10/mo | From day one |
| ID checks (paid contests) | Sumsub: $1.35–1.85/check; $149–299/month minimums | Persona (quote), Plaid Identity Verification | — | No | Medium | Only at launch of paid contests | Sumsub |
| Location checks | Radar (per-user billing; claims 50–90% savings) | GeoComply (~$0.01–0.05/check reported) | — | No | High (state law) | Only at launch of paid contests | Choose with our lawyer |
| Pot custody and payouts | Licensed payments/escrow partner | — | — | Never | Very high | Partner fees | Partner |
| SOC 2 | Vanta or Drata (~$7,500–15,000/year entry) + audit (Type I $5–15k; Type II $15–40k) | Startup-focused auditors; bundled audit offers | — | No | Medium | ~$13k → ~$60k first year | Type I first, when partners ask |

---

## 4. Six ways to set up the whole platform

| Option | What it is | Fixed cost at launch (est.) | Fixed cost at 10k users (est.) | Strengths | Weaknesses | Verdict |
|---|---|---|---|---|---|---|
| **A. Recommended hybrid on AWS** | Fargate, Aurora, NATS, Temporal Cloud, LiteLLM, Centrifugo, WorkOS, Databento, Lambda sandboxes | ~$750–1,700/mo | ~$8k/mo | AWS credits can cover Claude via Bedrock; managed database for money data; Lambda sandboxes | More pieces to wire together | **Pick** |
| B. Google Cloud-native | Cloud Run, Cloud SQL, Pub/Sub, Vertex | ~$900–2,000/mo | ~$9–11k/mo | Larger credits (up to $350k) once equity-funded | Credits exclude Claude; Cloud Run compute ~2× Fargate Arm; high-availability Cloud SQL ~$315/mo minimum | Only if we land AI-first credits and lean on Gemini |
| C. Cloudflare-native agent layer | Each agent as a Durable Object or Workflow that hibernates; Workers run watch logic; R2 for storage | ~$5–100/mo for the agent layer | Low: pay per request and CPU-millisecond, nothing while sleeping (est. ~$10–50/mo orchestration at 10k agents) | Idle agents cost nothing; built-in timers and per-object storage | Best suited to JavaScript; quant libraries (NautilusTrader, polars) need Cloudflare Containers or a separate backend; lock-in | **Prototype in Stage 1** as a Temporal replacement for the agent loop; keep the trading core on AWS |
| D. Supabase-centric MVP | Supabase Pro for database, login, real-time, storage; Fargate/Lambda for engines | ~$400–800/mo | ~$6–9k/mo | Fastest MVP; one bill; easy exit (standard Postgres) | Real-time limits (500 concurrent on Pro); database never scales to zero; less control for money data | Good for the prototype phase; move to RDS before real money |
| E. Managed-heavy | Temporal Cloud, Ably, Stream, Langfuse Pro, OpenRouter, SnapTrade for every broker | ~$1.7–2.5k/mo | ~$30–40k/mo | Least engineering | SnapTrade alone ~$20k/mo at 10k users | No |
| F. Do-it-ourselves max (incl. Hetzner) | Self-host everything on reserved EC2 or Hetzner | ~$300–1,000/mo | ~$4–6k/mo | Cheapest raw compute | Ops load of roughly a part-time engineer; no managed key service or database; Hetzner raised prices in 2026 and some lines are unavailable; weak optics for a US fintech holding broker credentials | Only for backtests and dev boxes |

---

## 5. Can we build it ourselves on AWS, GCP, or something else?

Mostly yes, and the recommended plan already does: AWS building blocks, plus open-source software we host, plus our own code.

| Component | Third-party option | Do-it-ourselves route | Cost vs third party | Effort | Risk | Verdict |
|---|---|---|---|---|---|---|
| Durable runtime | Temporal Cloud | Self-host Temporal, use DBOS on our Postgres, or Cloudflare Workflows | Servers only (~$100–300/mo est.), or near-zero on Cloudflare | Medium / Low | Medium | DIY later at ~$3–5k/mo; prototype Cloudflare now |
| Code sandbox | E2B | Lambda *is* the DIY route; further = Firecracker on bare-metal EC2 or GKE Sandbox | Lambda: cents | High for bare metal | High (security) | Lambda now; never hand-roll Firecracker early |
| Model gateway | OpenRouter | LiteLLM on our containers | Saves 5.5% | Low | Low | **DIY now** |
| AI models | Anthropic/OpenAI APIs | Same models on Bedrock (credits), or self-hosted open-weight models on GPUs | GPUs cost more than Haiku 5.5 at our volume | High | Medium | APIs; Bedrock to use credits |
| AI tracing | Langfuse Cloud | Self-host Langfuse (MIT) | Servers only | Low–medium | Low | Free tier now; self-host later |
| Monitoring | Grafana Cloud | Self-host Prometheus, Loki, Tempo, Grafana | Saves at scale, costs engineer time | Medium | Low | Free tier now; self-host past ~$500/mo |
| Error tracking | Sentry | GlitchTip | ~$26/mo saved | Low | Low | Keep Sentry |
| Login | WorkOS (free) | Cognito (charges after 10k MAU) or Better Auth | WorkOS is cheaper | Low–medium | Medium | Stay on WorkOS |
| Real-time | Ably/Pusher | Centrifugo, or API Gateway WebSockets | Centrifugo cheapest at scale | Low–medium | Low | **DIY (Centrifugo)** |
| Chat | Stream | Build on Centrifugo + Postgres | Saves $399+/mo | Medium | Medium | **DIY** |
| Feeds | Stream Feeds | Postgres + Valkey | Saves fees | Medium | Low | **DIY** |
| Main database | Aurora | Self-managed Postgres on EC2 | ~half the cost (est.), but we own backups and failover | Medium–high | High | **Don't DIY** |
| Cache | ElastiCache | Valkey on our containers | Small savings | Low | Low | Either |
| Event bus | Managed Kafka/NATS | NATS on our containers | Servers only | Medium | Medium | **DIY** |
| Analytics database | ClickHouse Cloud (from ~$67/mo) | Self-hosted ClickHouse | Servers only | Medium | Medium | **DIY** to start |
| Product analytics | PostHog | Our events into ClickHouse + Metabase | Saves fees later | Low | Low | PostHog free now |
| Containers | Fargate | EC2 servers on savings plans | Est. 30–50% cheaper for steady load | Medium | Low–medium | Fargate first; move steady services later |
| CI/CD | GitHub hosted runners | Self-hosted runners on Spot | Cheaper at volume | Low | Low | Later |
| Billing | Stripe Billing (0.7%) | Our own subscription and credit logic; Stripe only for card processing | Saves 0.7% | Medium | Medium | Build credit ledger now |
| Broker connections | SnapTrade | Direct adapters to Robinhood, IBKR, Alpaca | $0/user | Medium–high | High (approvals) | **DIY for main brokers** |
| Backtest engine | QuantConnect (hosted) | NautilusTrader self-hosted | License-free | Medium | Medium | **DIY** |
| News | Paid news APIs | SEC EDGAR filings (free) + company press releases, tagged by our models | Free data; wire news still licensed | Medium | Medium | **DIY for filings**; buy wire news |
| Market data | Databento | Direct exchange feeds | Far more expensive | Very high | High | **Don't** |
| ID and location checks | Sumsub, Radar | Free IP geolocation for basic gating only | Not compliance-grade | — | High | **Buy** |
| Pot custody | Licensed partner | — | — | — | Very high | **Never build** |
| Secrets | Vault | KMS + our wrapper | Cents | Low–medium | Very high impact | **DIY** |

### What we actually have to pay for

| Must pay | Why it can't be built | Cost |
|---|---|---|
| Market data (Databento) | Exchange licensing | $199/mo to start |
| AI models | Frontier models can't be matched cheaply | Usage-based (see costs) |
| Card payments (Stripe) | Regulated payment processing | Card fees (+0.7% with Stripe Billing) |
| Cloud (AWS) | Building blocks for everything | Usage-based; credits early |
| Broker aggregator (less common brokers only) | Each broker's integration and approval | $2/connected user/month, only for users who need it |
| Later: ID checks, location checks, escrow, SOC 2 | Regulated, liability-heavy, or audited | Per check, partner fees, ~$13k+ first year for SOC 2 |

---

## 6. Costs

### Cost per active user per month (est.)

| User type | What they run | Cost |
|---|---|---|
| Light | 2 rule-based agents | $0.50–1 |
| Typical | 1 rule-based agent, 1 AI agent (checks every 5 min, ~5 escalations/day), ~3 builder sessions | $4–6 |
| Heavy | 5 AI agents checking every minute, SnapTrade connection | $25–40 |

Building blocks of the typical cost:
- A Haiku check costs ~$0.0002–0.0005.
- A Sonnet escalation costs ~$0.015.
- A builder session costs ~$0.50.
- The runtime costs ~$0.33 per agent per month at Temporal list price, and near-zero on Cloudflare (est.).

Newer Claude models count ~30% more tokens for the same text; these figures include headroom for that.

### Fixed costs at launch per month (est.)

| Line | Best case | Expected | Worst case |
|---|---|---|---|
| Containers | $150 | $300–500 | $800 |
| Postgres | $50 | $150–350 | $700 |
| ClickHouse, Valkey, S3 | $25 | $75–200 | $400 |
| Durable runtime | $0 | $0–150 | $300 |
| Market data | $199 | $199 | $1,500 |
| News | $20 | $20–50 | $50 |
| Monitoring, errors, AI tracing, analytics | $0 | $0–75 | $250 |
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
| Gross margin | ~61% | ~47% | Loss ~$9k/mo |

The risk is conversion, not infrastructure. Break-even is ~6% of active users paying (est.).

### Later-stage costs (only when those features launch)

| Item | Cost |
|---|---|
| SOC 2 Type I | Platform ~$7,500–15,000/year + audit $5–15k |
| SOC 2 Type II | Platform + audit $15–40k |
| ID checks | $1.35–1.85 per check; $149–299/month minimum |
| Location checks | ~$0.01–0.05 per check (per-check model) or per-user pricing |
| Databento Plus, if broader rights are needed | ~$1,500/month |

### What we charge (proposed)

Comparable products: Composer's Trading Pass is $32/month billed annually ($40 monthly), TradersPost is $49.99/month, and QuantConnect Researcher is $84/month.

| Plan | Price | Includes | Gross margin (est.) |
|---|---|---|---|
| Free | $0 | Paper trading, backtests, 1 live rule-based agent, small AI allowance | ~-$1/active user |
| Pro | $25–29/mo | Unlimited rule-based agents, 2 AI agents, builder allowance, competitions | ~65–75% |
| Premium | $79/mo | More AI agents, checks every minute, larger models, priority | ~50–70% |
| Credits | Top-ups | ~2× model cost | ~50% |

### Startup credits

| Program | Amount | Requirement / note |
|---|---|---|
| AWS Activate | $1,000 (some $5,000); up to $200,000 | Large tier needs a VC/accelerator provider ID. Users report credits cover Claude on Bedrock (**confirm** with AWS billing) |
| Google for Startups | Up to $350,000 (AI-first) | Equity funding; doesn't cover third-party models like Claude |
| Microsoft for Startups | Up to $150,000 Azure + OpenAI credits | Application |
| Temporal | $6,000 | Under $30M raised |
| E2B | Free Pro tier | Startup program |
| Cloudflare | $10,000 tier | Open to unfunded founders |

---

## 7. Workarounds that change the math

| Workaround | What it saves | How |
|---|---|---|
| Databento's license-free feed | Thousands/month in business data licenses | US Equities Mini on the $199 Standard plan for agents and display (**confirm** terms in writing) |
| AWS credits for Claude via Bedrock | Most early AI spend | Bedrock charges the same as Anthropic direct; users report Activate credits apply. New versions arrive 1–4 weeks later, so use direct API for the newest models |
| Shared watch engine | ~$49/agent/month → cents | Agents sleep between triggers |
| Cloudflare hibernation for agent loops | Most of a Temporal bill | Sleeping workflows and inactive Durable Objects aren't billed (prototype first) |
| Stops and limits held at the broker | Reliability and compute | Exits fire even if we're down |
| Shared prompt prefix | Most model input cost | All agents share one system prompt, so the cache stays warm |
| Batch API for backtests and reviews | 50% of those model costs | Not time-sensitive |
| Store AI decisions per agent version and data snapshot | Free backtest re-runs | Replay stored outputs |
| LiteLLM instead of OpenRouter | 5.5% of model spend | Self-hosted gateway, our own keys |
| KMS envelope encryption | ~$0.40/user/month | Encrypted tokens in Postgres |
| Direct broker connections | $2/user/month | SnapTrade only for less common brokers; import history, then disconnect (check terms); avoid $0.05 manual syncs |
| SEC EDGAR | Part of the news bill | Free official filings (8-Ks, insider trades), 10 requests/sec |
| Self-hosted ClickHouse | ~$67–500/mo | Run on our containers |
| Fargate Spot and Graviton | ~70% on batch, ~20% everywhere | Backtests on Spot; Arm everywhere |
| Our own paper broker | Per-broker paper limits | One simulator for all brokers |
| Staggered wakes at 9:30am | Rate-limit failures | Spread wake-ups; queue per broker |
| Free tiers | Hundreds/month early | WorkOS, Grafana Cloud, Langfuse, Sentry, PostHog (1M events) |

---

## 8. Build vs rent

| Category | Components | Why |
|---|---|---|
| Build (ours, core) | Builder agent, watch engine, signals, order management, risk engine, ledger, paper broker, broker adapters, credit ledger, competitions, social features, leaderboards, EDGAR ingest | The product, and where correctness matters |
| Run open source ourselves | NATS, Centrifugo, LiteLLM, NautilusTrader, ClickHouse, Langfuse (later) | No license fees |
| Rent from core cloud | Containers, Lambda, Aurora/RDS, S3, KMS, SES, Valkey, Bedrock | Building blocks; managed where failure is expensive |
| Rent from specialists | Market data, AI models, payments, login (free), monitoring (free tier) | Cheaper and better than building |
| Never build | Sandbox isolation technology, exchange feeds, pot custody, ID and location checks | Security-critical or regulated |

### Hardest parts, ranked

| Rank | Part | Why |
|---|---|---|
| 1 | Builder agent quality | Correct strategies from conversations and past trades; core IP |
| 2 | Real-money correctness | Order management, risk engine, ledger, reconciliation |
| 3 | Watch engine and runtime at scale | Thousands of agents waking at the market open |
| 4 | Broker approvals and quirks | Depends on brokers, not us |
| 5 | Realistic simulation | Fills, slippage, AI-judged backtests |
| 6 | Competition integrity | Cheating detection; later, pots |
| Easy | Login, notifications, leaderboards, feeds, dashboards | Well-trodden ground |

---

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Builder produces wrong strategies | High | High | Replay and backtest before deploy; plain-English review; guardrails |
| Duplicate or missed orders | Medium | Very high | Unique keys; reconciliation; broker-held exits |
| A broker refuses hosted-agent access | Medium | High | SnapTrade, Alpaca, more brokers |
| Overload at the 9:30am open | High | Medium | Stagger wakes; per-broker queues |
| Market data license misuse | Low–medium | High | Databento terms in writing |
| Model price changes | Medium | Medium | Multi-provider gateway; per-agent budgets |
| Too few paying users | Medium | High | Free-tier caps; strong Pro value |
| Credential leak | Low | Very high | KMS; models and user code never see tokens |
| Competition cheating | Medium | High | Broker-verified fills; collusion checks |
| Vendor lock-in (Cloudflare, Bedrock) | Medium | Medium | Keep the agent definition portable; gateway abstracts models |

---

## 10. Build stages and ownership

| Stage | What gets built |
|---|---|
| 1. Foundation | AWS, Fargate, Aurora, Valkey, NATS, Temporal Cloud (plus Cloudflare prototype), Databento, NautilusTrader, agent definition, watch engine v1, paper broker, LiteLLM, WorkOS |
| 2. Builder and Lab | Builder agent, backtests, instant replay, past-trade import (SnapTrade read-only), Langfuse, EDGAR ingest |
| 3. Live trading | Robinhood and IBKR adapters, order management, risk engine, ledger and reconciliation, Lambda sandbox, Centrifugo, notifications |
| 4. Social and Arena | Profiles, follows, feeds, chat, leaderboards, competitions, Stripe billing, credit ledger |
| Later | ID and location checks, pot partner, SOC 2, crypto |

| Owner | Areas |
|---|---|
| Platform and trading core | Cloud, data stores, event bus, watch engine, runtime, broker connections, order management, risk engine, ledger, paper broker, market data |
| AI and product | Builder agent, model gateway, prompts and evaluations, Lab experience, frontend, social features, billing |

---

## 11. Decisions to make

| Decision | Options | Recommendation | When |
|---|---|---|---|
| Primary cloud | AWS / GCP | AWS | Now |
| Durable runtime | Temporal Cloud / DBOS / Cloudflare | Temporal Cloud, with a Cloudflare prototype in Stage 1 | Stage 1 |
| AI model access | Anthropic direct / Bedrock | Both: Bedrock to spend credits, direct for the newest models | Stage 1 |
| Watch engine language | Python / Rust | Python first; Rust hot paths later | Stage 1 |
| Backtest engine | NautilusTrader / LEAN | NautilusTrader | Stage 1 |
| Market data | Databento / Massive Business | Databento, once terms are confirmed | Now |
| Broker routes | Direct / SnapTrade | Direct plus SnapTrade; apply now | Apply now, build Stage 3 |
| Login | WorkOS / Clerk | WorkOS | Stage 1 |
| MVP database | Aurora / Supabase | Aurora (or Supabase for a throwaway prototype only) | Stage 1 |

## 12. To confirm directly with vendors

| Vendor | Question |
|---|---|
| Databento | Can we display US Equities Mini to users and feed it to user-owned agents on Standard? |
| Robinhood | Developer-app registration, OAuth scopes, rate limits, session lifetime; is a multi-user hosted platform allowed? |
| Interactive Brokers | Third-party OAuth approval process and timeline |
| SnapTrade | Production approval; can Robinhood or IBKR trading be enabled; daily-plan pricing |
| AWS | Do Activate credits cover Claude on Bedrock for our account? |
| Temporal, E2B | Startup program eligibility |
| News vendor | Rights to display headlines to users |

## 13. Changes vs the current PRD & Technical doc

| Area | Was | Now |
|---|---|---|
| Sandbox | E2B | Lambda, with E2B for SDK development sessions |
| Model routing | OpenRouter | LiteLLM, plus Bedrock for credit-funded Claude usage |
| Backtesting | LEAN | NautilusTrader (LEAN fallback) |
| Market data | Undecided | Databento Standard |
| Durable runtime | Temporal | Temporal, with a Cloudflare prototype |
| New components | — | Watch engine, NATS, ClickHouse, Centrifugo, WorkOS, Langfuse, EDGAR ingest |

---

## Sources

Mostly search results, not all read in full; confirm figures before relying on them.

- Sandboxes: https://e2b.dev/pricing · https://www.beam.cloud/blog/e2b-pricing-explained · https://northflank.com/blog/ai-sandbox-pricing
- AWS Lambda, Fargate: https://www.eon.io/blog/aws-lambda-pricing · https://cloudburn.io/blog/aws-lambda-pricing · https://www.factualminds.com/tools/aws-fargate-pricing-calculator/
- Cloudflare: https://developers.cloudflare.com/workflows/reference/pricing · https://developers.cloudflare.com/durable-objects/platform/pricing · https://developers.cloudflare.com/containers/pricing/ · https://makerkit.dev/pricing-calculator/cloudflare
- Google Cloud: https://tech-insider.org/how-to-set-up-google-cloud-run-2026/ · https://bytebase.com/blog/understanding-google-alloydb-pricing/ · https://www.bytebase.com/dbcost/alloydb-pricing/
- Temporal, DBOS, Hatchet, Step Functions: https://temporal.io/blog/paygo-developer-support · https://temporal.io/pricing · https://dbos.dev/compare/dbos-vs-temporal · https://aicoolies.com/comparisons/hatchet-vs-temporal · https://aws.amazon.com/step-functions/pricing
- Model gateways: https://hackernoon.com/openrouter-alternatives-in-2026-three-ai-gateways-compared-for-production-scale · https://www.betterclaw.io/blog/openrouter-alternatives-ai-agents · https://api7.ai/openrouter-vs-litellm
- Claude pricing: https://techenclave.com/news/items/claude-haiku-5-5-launches-with-0-10-input-pricing-for-shorter-prompts · https://apidog.com/blog/claude-sonnet-5-5-pricing/ · https://emergent.sh/learn/claude-haiku-5-5-pricing · https://www.eesel.ai/blog/claude-haiku-5-5-pricing
- Bedrock: https://www.manageengine.com/cloudspend/articles/amazon-bedrock-pricing.html · https://www.spheron.network/blog/aws-bedrock-pricing-2026-managed-api-cost/ · https://yomotherboard.com/question/can-i-use-aws-activate-credits-for-anthropic-claude-models-on-aws-bedrock/
- Other models: https://techsy.io/en/blog/llm-api-pricing-comparison
- Databento: https://databento.com/blog/introducing-databento-us-equities · https://databento.com/blog/databento-us-equities-mini-now-available · https://databento.com/blog/upcoming-changes-to-pricing-plans-in-january-2025 · https://databento.com/pricing · https://us.fitgap.com/products/033314/databento
- Massive, Alpaca data: https://multiples.vc/compare/api-pricing · https://providers.apievangelist.com/providers/polygon/ · https://qveris.ai/guides/stock-api-free-comparison/?lang=en
- SEC EDGAR: https://www.sec.gov/os/accessing-edgar-data · https://arkolith.com/blog/sec-edgar-api-guide · https://sec-api.io/pricing
- News and social: https://us.fitgap.com/products/stock-news-api · https://www.xpoz.ai/blog/guides/reddit-api-pricing-tiers-and-alternatives/
- Brokers: https://vorplabs.com/agent-tools/robinhood-cli · https://runtimewire.com/article/virtuals-says-robinhood-completed-agentic-trading-rollout · https://magica.com/news/robinhood-agentic-trading-mcp · https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/o-auth-1-0-a/third-party-o-auth/third-party-o-auth-workflow · https://www.ibkr.com/download/03-IB17-1071-API.pdf · https://us.fitgap.com/products/snaptrade · https://snaptrade.com/blogs/plaid-vs-yodlee · https://snaptrade.com/brokerage-api
- NautilusTrader: https://docs.ccxt.com/docs/comparisons/ccxt-vs-nautilustrader · https://docs.nautilustrader.io/concepts/overview.html
- Databases: https://guptadeepak.com/tools/top-5-database-as-a-service-platforms-2026/ · https://neon.tech/blog/postgres-autoscaling-aurora-serverless-v2-vs-neon · https://www.techplained.com/best-managed-postgres · https://selfhost.dev/blog/clickhouse-pricing-real-cost-of-running-it/
- Supabase: https://www.activepieces.com/blog/supabase-pricing-free-tier-limits-pro-costs-egress · https://makerkit.dev/blog/saas/supabase-pricing · https://metacto.com/blogs/the-true-cost-of-supabase-a-comprehensive-guide-to-pricing-integration-and-maintenance
- Cache, event bus: https://upstash.com/blog/upstash-vs-aws-elasticache-serverless-redis-pricing-and-performance-2026 · https://www.index.dev/skill-vs-skill/nats-vs-redis-vs-kafka · https://www.pkgpulse.com/guides/redpanda-vs-nats-vs-apache-kafka-event-streaming-2026
- Hetzner: https://privatedevops.com/news/hetzner-june-2026-cloud-price-increase-what-to-do · https://northflank.com/blog/hetzner-cloud-server-price-increases
- Login: https://workos.com/blog/workos-vs-betterauth-vs-clerk · https://devtoollab.com/blog/best-authentication-providers · https://clerk.com/articles/clerk-vs-aws-cognito-developer-experience-vs-scale-economics-3 · https://us.fitgap.com/products/020158/amazon-cognito
- Real-time, API Gateway: https://ably.com/compare/ably-vs-centrifugo · https://sliplane.io/de-de/blog/5-awesome-soketi-alternatives · https://talkjs.com/resources/ably-alternatives/ · https://wring.co/blog/aws-api-gateway-pricing-guide
- Billing: https://flexprice.io/questions/best-alternative-to-stripe-billing-for-usage-based-pricing · https://www.solvimon.com/blog/best-billing-systems-for-ai-startups-in-2026-what-actually-matters-beyond-metering · https://www.landbase.com/blog/usage-based-billing-software
- Monitoring, analytics: https://betterstack.com/community/comparisons/datadog-vs-grafana-cloud.md · https://dupple.com/learn/best-observability-platforms · https://futureagi.com/blog/best-grafana-alternatives-2026 · https://posthog.com/product-analytics/pricing
- Compliance: https://www.signzy.com/blogs/persona-alternatives · https://tech-insider.org/?p=8820 · https://www.costbench.com/compare/drata-vs-vanta/ · https://tracelayer.it.com/blog/soc2-compliance-cost-2026
- Startup credits: https://hub.causo.ai/startup-cloud-credits-compared-2026 · https://fin.ai/learn/startup-credit-programs · https://echai.ventures/startingup/from/guptadeepak-com
- Comparable pricing: https://tooliverse.ai/tools/composer · https://www.quantconnect.com/pricing.md · https://traderspost.io/compare/traderspost-vs-composer
