# Agent Trading Platform: Big-Ticket Monthly Costs and Alternatives

*For das and Aryan · October 2026*

*Estimates at list prices; "est." = our estimate. AI model usage is billed to users through credits, so it's excluded. Confirm vendor terms before committing.*

---

## 1. Summary

| Line | Before (500 / 1k / 10k users) | After (500 / 1k / 10k users) | Recommended |
|---|---|---|---|
| Durable runtime (agent loop) | $441 / $881 / $600 | ~$0 / $0 / $0 | Job queue on NATS + idempotent workers; DBOS for multi-step flows |
| Servers (incl. NATS cluster and networking) | $260 / $360 / $1.7k | ~$180 / $200 / $800 | ECS on EC2 Arm instances across 2+ availability zones |
| Main database | $150 / $250 / $1.0k | ~$230 / $230 / $600 (~$25 while paper-only) | RDS Postgres Multi-AZ, non-burstable |
| Broker connections | $150 / $300 / $3.0k | ~$75 / $150 / $1.5k | Direct broker APIs + SnapTrade Daily/Real-time only where needed |
| Card processing | $104 / $208 / $2.1k | ~$80 / $165 / $1.65k | Stripe + ACH + annual plans; Helcim or interchange-plus at volume |
| Market data | $199 / $199 / $199 | $199 (~$30–100 if EODHD confirms) | Databento Standard |
| **Total platform cost, recommended setup** | **$1.5k / $2.5k / $12.0k** | **~$0.9k / $1.2k / $8.2k** | |

---

## 2. Market data

### Options

| Provider | Cost | Can we show it to users? | Notes |
|---|---|---|---|
| **Databento Standard** | $199/mo | Yes: its US Equities Mini feed allows display and redistribution without license fees | Live data with no exchange license fees; full history of 1-second and 1-minute bars included |
| Databento Plus / Unlimited | ~$1,500 / ~$4,000/mo | Yes, broader rights | Only if we outgrow Standard |
| EODHD | From ~$18–20/mo; real-time from $29; all-in-one ~$80–100 | Reportedly free redistribution on real-time US stocks | Cheapest display option **if confirmed in writing** (the source looked EODHD-friendly) |
| Twelve Data | Grow $29/mo (individual, internal only); Venture $149/mo (business, external display) | Display on Venture; redistribution is a paid add-on | Default real-time US feed covers only ~5% of US trading volume |
| Tiingo | Power $30/mo (individuals); Commercial $50/mo or $499/yr | Unclear | Clean data for research; FMP's US prices are licensed from Tiingo |
| Financial Modeling Prep | From $22/mo | Business tiers | Strongest on fundamentals |
| Finnhub | $49.99/mo | Business tiers | Real-time US, fundamentals, alternative data |
| Massive (formerly Polygon) | Basic $0, Starter $29, Developer $79, Advanced $199 (individual) | Business contract needed to redistribute | Fast; redistribution is the expensive part |
| Intrinio | Individual $150 (personal); Startup $333 → $666 → $1,499; Enterprise from $1,250 | Business tiers | Enterprise-grade licensing |
| Marketstack | From $9.99/mo | Check terms | Simple REST, end-of-day focus |
| Nasdaq Basic (direct) | $1,600/firm + $13.50/user; distribution $2,080 + $0.50 per personal user | Yes | Too expensive now |
| UTP intraday (delayed) display | $250/mo + $250/yr admin, no per-user fees | Yes, delayed | Cheap way to show intraday charts |
| Alpaca IEX feed | Free | No | Prototype only |
| IEX Cloud | Shut down | — | Not an option |

### Levers
- **Real-time for agents, delayed for screens.** Agents use real-time data internally. Public and social screens show delayed or historical prices, which are much cheaper or free to display. Real-time consolidated redistribution routinely costs five figures a month.
- **Prototype on free or cheap feeds** (Alpaca, Tiingo) before showing prices to users.

### Recommendation
Market data isn't a big lever; the most we'd save is ~$100–170/month. Stay with Databento Standard unless EODHD confirms free redistribution in writing.

---

## 3. Card processing

### Options

| Provider | Cost | Notes |
|---|---|---|
| **Stripe** | 2.9% + 30¢ online; 3.4% + 30¢ keyed; ACH 0.8% capped at $5; disputes $15. Add-ons: Billing +0.7%, Tax +0.5% | Easiest; interchange-plus pricing available at high volume (typically saves 0.5–1%) |
| Helcim | Interchange + 0.15–0.5% + 15–25¢ online (~2.27% + 25¢ effective); ACH 0.5% + 25¢; no monthly fee | ~20% cheaper than Stripe's standard rate |
| Adyen | $0.13 per transaction + interchange + markup; ACH ~40¢ | €500/month minimum; complex integration |
| Paddle | 5% + 50¢ | Merchant of Record: handles sales tax and invoicing |
| Lemon Squeezy | 5% | Merchant of Record |
| Braintree / PayPal, Square | ~Stripe-level card rates | No advantage for us |

### Levers (per $27 Pro charge)

| Method | Fee |
|---|---|
| Card on Stripe | ~$1.08 |
| Card on Helcim | ~$0.86 |
| ACH on Stripe | ~$0.22 |
| Annual plan on card | One $0.30 fixed fee instead of 12 (saves $3.30/year per subscriber) |

- Sell credits in larger bundles so there are fewer charges.
- Build our own credit ledger, and only use Stripe Billing (+0.7%) for subscriptions.

### Recommendation
Stripe now, with ACH and annual plans from day one. Move to Helcim or Stripe interchange-plus once card volume passes ~$25–50k/month.

---

## 4. Main database

### Options

| Option | Cost | Notes |
|---|---|---|
| RDS t4g.micro (single-AZ) | ~$11.68/mo on-demand; ~$8.47 reserved 1 year; free 12 months for new accounts | Burstable, no standby: paper-only and development |
| **RDS m6g.large Multi-AZ** | ~$99/mo per instance × 2 + storage ≈ **$230/mo** (~$170 reserved) | What we need before real money |
| RDS full high availability (standby + read replica + 200 GB) | ~$475/mo | Around 10k users |
| Aurora t4g.medium / Serverless v2 | $59.86/mo / $0.12 per capacity-unit-hour (minimum 0.5, never zero) | Faster failover, read scaling; for ~50–100k users |
| Supabase Pro | $25/mo + compute (includes login, storage, real-time) | Fast prototype; database never scales to zero |
| Neon | Free tier; scale-to-zero | Development branches; no TimescaleDB |
| PlanetScale Postgres | From $5/mo single node | Prototype |
| Selfhost.dev | Same Graviton hardware as RDS at 40–50% less | Price-check at 10k; younger vendor |
| Google Cloud SQL / AlloyDB | ~$315/mo (2 vCPU/16 GB, high availability) / from ~$227 per instance | Only if we're on Google Cloud |
| Self-hosted Postgres on EC2 | Lowest infrastructure cost; high availability doubles it plus setup | We'd own backups and failover; **not with real money yet** |

### Stages

| Stage | Setup | Monthly |
|---|---|---|
| Paper-only prototype | RDS t4g.micro, single-AZ | $0–25 |
| Live trading (launch) | RDS m6g.large, Multi-AZ | ~$230 (~$170 reserved) |
| ~10k users | Multi-AZ + read replica | ~$475–700 |
| ~50–100k users | Aurora with read replicas | Scale with load |

### Required for safe deployment
- Multi-AZ with a standby, on a non-burstable instance (m6g/m7g).
- Automated backups, point-in-time restore, deletion protection, encryption, connection pooling.
- If DBOS load grows, a separate database for workflow state.

---

## 5. Broker connections

### SnapTrade plans

| Plan | Cost | What you get |
|---|---|---|
| Free | $0 | Up to 5 brokerage connections (development) |
| Daily | From ~$1 per connected user/month; $0.05 per manual sync | Data cached daily: enough for history import |
| Real-time | $2 per connected user/month | Live data and trading; 250 requests/min |
| Custom | From $500/month minimum | Volume discounts, higher limits, priority support |

One person with several brokers counts as one connected user.

### Alternatives

| Option | Cost | Notes |
|---|---|---|
| Robinhood agent connection (MCP) | $0/user | Official; hosted third-party apps already use it; rate limits unpublished |
| IBKR Web API (third-party OAuth) | $0/user | Requires registration and compliance approval |
| Schwab Trader API (commercial) | $0/user | Approved case by case |
| Tradier partner API | $0/user | Approval in ~2 weeks |
| Alpaca Connect / OAuth | $0/user | App review for live trading |
| Webull | $0/user | OAuth for outside agents |
| Plaid, Yodlee, MX | Varies | Read-only, no trading |

No other aggregator lets apps place trades across many brokers, so SnapTrade's real competition is direct broker APIs.

### Recommendation
1. Connect directly to Robinhood, IBKR, Schwab, Alpaca, and Tradier, which covers most US retail accounts.
2. Use SnapTrade Daily for history imports (connect, import, disconnect; check billing terms).
3. Use Real-time only for trading at less common brokers.
4. Negotiate a custom plan around 5k users.

---

## 6. Servers

### Options

| Option | Cost | Notes |
|---|---|---|
| **EC2 Arm (Graviton)** | t4g.medium (2 vCPU, 4 GB) $30.37/mo on-demand; up to 72% off reserved | Cheapest on AWS for always-on services |
| Fargate on Arm | $0.03238/vCPU-hour + $0.00356/GB-hour (~$29/mo per 1 vCPU + 2 GB); Spot ~70% off | No server management; pricier for always-on |
| Google Cloud Run | ~$0.065/vCPU-hour | ~2× Fargate Arm |
| Fly.io | From ~$1.94/mo small VMs; $0.02/GB data out | Cheap; another vendor |
| Railway | $20/vCPU/month + $10/GB RAM/month | Simple; pricier always-on |
| Render | $7 / $25 / $85 per month | Fixed, predictable |
| DigitalOcean | Predictable pricing | Cheaper than Render at scale |
| Hetzner | Several times cheaper than AWS | 2026 price rises and some unavailable lines; no managed services; backtest boxes only |
| Kubernetes on AWS (EKS) | +$73/mo control plane | Not needed early; ECS has no control-plane fee |

### Hidden networking costs

| Item | Cost |
|---|---|
| NAT gateway | ~$32/mo + $0.045/GB (use VPC endpoints to cut) |
| Load balancer | ~$16/mo + usage |
| Public IPv4 | $3.60/mo each |
| Cross-availability-zone traffic | $0.01/GB each way |

### Launch layout (~$180–200/month)
- 2 app/worker instances across availability zones.
- 3 small NATS nodes.
- A load balancer and a NAT gateway.

At ~10k users, the same layout with larger instances is ~$800/month reserved.

### Required for safe deployment
- ECS on EC2 across 2+ availability zones, **never Docker Compose on one machine**.
- Don't rely on burstable CPU for the watch engine and workers.
- Spot for backtests only.
- Arm builds confirmed for NautilusTrader; check TA-Lib and other dependencies.

---

## 7. Durable runtime (agent loop)

### Options

| Option | Cost | Notes |
|---|---|---|
| Temporal Cloud | $50 per million actions (down to ~$25 with volume or commitments); $6k startup credits | Our model: $441 / $881 at 500 / 1k users; ~$6k at 10k; ~$44k at 100k at list price |
| Self-hosted Temporal | Reportedly ~$2.5–4.5k/month including operations | Heavy to run |
| Inngest | 50,000 step runs/month free; $20/mo for 200K | Per-step billing gets expensive at millions of wakes |
| Trigger.dev | $0 + usage | Waits over 5 seconds checkpointed free on its cloud |
| Cloudflare Workflows / Durable Objects | No CPU charge while sleeping; $0.30/M requests + $0.02/M CPU-ms | ~$20/mo at 10k users (est.); best suited to JavaScript |
| Upstash Workflow | Pay per message | No workers to run |
| Restate | Free self-hosted (single binary) | Newer |
| AWS Step Functions | Per state transition; 4,000 free/month | Pricey for long-running loops |
| DBOS | Free library on our Postgres | Good for multi-step flows; younger, with limited independent production reviews |
| **Job queue on NATS + our own workers** | ~$0 extra (runs on existing servers) | Standard when each job is short |

### Why we can drop Temporal
An agent decision is a short job, and our watch engine already decides when agents wake. The engine publishes "wake agent X" jobs to NATS (already in the stack). Workers process them with unique keys, and state lives in Postgres. DBOS handles the few multi-step flows, such as an order's lifecycle and builder sessions.

### Required for safe deployment
- NATS: 3 nodes, replicated streams (R3), message IDs for duplicate protection.
- Delivery is at-least-once, so every order needs a unique key enforced by a Postgres unique constraint.
- Build our own dead-letter queue; NATS has no built-in one.
- One active scheduler per partition (a lock), so no agent is woken twice.
- Order state machine in Postgres plus reconciliation against the broker every cycle.
- Keep workflow code behind an interface, so we can move to Temporal if complexity grows.
- Load-test the 9:30am wake-up burst before launch.

---

## 8. Other lines over $50/month

| Line | 500 / 1k / 10k users | Cheaper option |
|---|---|---|
| ClickHouse (analytics) | $50 / $75 / $300 | Keep decision logs in Postgres until volume justifies it; ClickHouse Cloud starts at ~$67/mo |
| Monitoring, tracing, analytics | $0 / $55 / $680 | Free tiers early (Grafana Cloud, Sentry, Langfuse, PostHog 1M events); self-host past 10k |
| News | $50 / $50 / $500 | Free SEC EDGAR filings first (10 requests/sec); paid news API later |
| SOC 2 (at 10k+) | — / — / ~$1.1k | Type I first (~$13k first year), only when partners ask |

---

## 9. To confirm

| Item | With |
|---|---|
| Free redistribution of real-time US data | EODHD (in writing) |
| Display rights on the US Equities Mini feed | Databento (in writing) |
| Commercial API approval | Robinhood, IBKR, Schwab, Tradier, Alpaca |
| Custom plan pricing at ~5k users | SnapTrade |
| Arm builds for all dependencies | Our build pipeline |
| Whether AWS credits cover Claude on Bedrock | AWS billing |

---

## Sources (main)

- Market data: https://databento.com/blog/introducing-databento-us-equities · https://databento.com/blog/databento-us-equities-mini-now-available · https://us.fitgap.com/products/033314/databento · https://twelvedata.com/pricing.md · https://support.twelvedata.com/en/articles/9935903-us-equities-market-data · https://www.lambdafin.com/articles/financial-data-api-2026 · https://geekflare.com/guides/best-stock-market-api/ · https://multiples.vc/compare/api-pricing · https://www.marketdata.app/education/stocks/stock-market-data-licensing/ · https://databento.com/docs/portal/live-data
- Payments: https://flexprice.io/blog/stripe-pricing-breakdown-2026 · https://toolradar.com/tools/stripe/pricing · https://aspireapp.com/us/blog/stripe-alternatives · https://www.techrepublic.com/de/article/stripe-alternatives/ · https://fitsmallbusiness.com/adyen-vs-stripe/
- Database: https://www.bytebase.com/blog/database-as-a-service-dbaas-provider/ · https://selfhost.dev/managed-postgresql-comparison-2026/ · https://wikidocs.net/blog/@infoplant/25721/ · https://oneuptime.com/blog/post/2026-01-21-postgresql-rds-aurora-comparison/view
- Brokers: https://snaptrade.com/brokerage-api · https://snaptrade.com/snaptrade-vs-plaid · https://docs.snaptrade.com/docs/broker-access-guide.md · https://www.shyft.ai/tools/snaptrade
- Servers and networking: https://www.techplained.com/best-backend-hosting-nodejs · https://findstack.com/resources/railway-vs-render-vs-fly-io · https://www.factualminds.com/tools/aws-fargate-pricing-calculator/ · https://www.bacancytechnology.com/blog/aws-data-transfer-pricing · https://spendark.com/blog/eks-vs-aks-vs-gke-pricing/
- Runtime: https://upstash.com/blog/durable-workflow-engines-compared-every-major-option-in-2026 · https://automationatlas.io/answers/inngest-vs-temporal-2026/ · https://hookdeck.com/webhooks/platforms/inngest-alternatives · https://www.synadia.com/blog/jetstream-reliable-delivery-dlq-replay · https://www.webpronews.com/why-one-database-might-tame-your-workflow-nightmares/ · https://pypi.org/project/nautilus_trader/1.226.0/
