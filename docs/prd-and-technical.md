# Product and Technical Requirements

*Exported from the team's Claude Doc (diagrams described in text).*

> **Superseded stack choices:** the technical sections here predate the infrastructure research. Where they conflict, follow `docs/v0/SPEC.md`, `docs/big-ticket-costs.md`, and `docs/infrastructure-decisions.md`. Specifically: **Temporal → NATS job queue + idempotent workers (DBOS for multi-step flows)**, **E2B → AWS Lambda for SDK code**, **OpenRouter → self-hosted LiteLLM**, **LEAN → NautilusTrader**, **market data → Databento** (Alpaca free feed in v0).

This covers what to build and how: product requirements first, then broker connections, then the technical design for awareness.

## Goals and non-goals

The product succeeds when anyone can go from no experience to a live, explainable agent on their own brokerage account, then compete and connect with it.

| Goals | Non-goals for now |
| --- | --- |
| Anyone builds a working agent by conversation or SDK | Holding trading money: it stays in users' brokerage accounts, and pots go through a licensed partner |
| Agents run 24/7 on users' own accounts, under owner controls, with every trade explained | Giving investment advice: users build and direct their own agents |
| Agents are social: real-money competitions, following, copying, clans | Crypto, mobile apps, a visual builder, and research, development, and review agents |
| Revenue comes from compute, competitions, sponsors, and copy fees | |

## Core concepts

The agent is the strategy; an instance is that strategy running in one place with its own money.

| Concept | Definition |
| --- | --- |
| Agent | One versioned strategy definition, owned by a user |
| Instance | One agent version running in one place: a live account, paper, a competition entry, or a copier's account. Each has its own positions and record. |
| Account | A brokerage account linked at onboarding. Deploying means picking one. |
| Version rollout | New versions update instances automatically or where the owner chooses. Copiers opt in. Competitions don't force a version lock. |
| Portfolio view | All of a user's agents and accounts, individually and combined |
| Decision log | Every trigger, signal, model output, order, risk check, and fill, with reasoning; replayable exactly |

Every agent, however it was built, has the same six parts. Each part can be strict or loose.

| Part | What it holds |
| --- | --- |
| Goal and instructions | Anything from exact rules to plain-language direction |
| Triggers | A schedule, market events, or continuous scanning |
| Tools | Market data, indicators, news and social feeds, AI models, and an order tool that always passes the risk engine |
| Sub-agents | Optional watchers that report signals to a main trader agent |
| Memory | What the agent has learned from its past trades |
| Guardrails | Limits, approvals, and the kill switch; the agent can never change them |

## Requirements by area

Everything below is in scope for the first full build unless the Status doc marks it later. (v0 scope is much smaller; see `docs/v0/SPEC.md`.)

### Onboarding
- Sign up, then link brokerages; linked accounts appear immediately.
- Optional import of past trades, so the builder agent can question the user about them and build a strategy from the answers.
- Plain-language risk notes; suggest paper first; never force limits.

### Studio (build)
- Three builder paths, switchable at any time: guided, plain-language, and SDK with an agent co-pilot.
- Templates and starter agents to begin from, then change by chat.
- Build from past trades (optional): after an import, the builder agent walks the user through those trades with questions and drafts a strategy from what it learns.
- Instant replay of recent weeks and an editable plain-English view of the strategy; every path produces the same agent definition.
- Watcher sub-agents, any model, platform data feeds, and premium data add-ons.
- Agents built elsewhere can connect through the SDK, under platform rules.

### Lab (test)
- Backtests, paper trading, experiments, comparisons, and version history.
- Every result labeled backtest, paper, or live, with a warning that AI-judged backtests can look too good.

### Operations (run)
- Deploy any version to a linked account or paper; many agents per user.
- Guardrails per instance: limits, approve-each-trade or automatic, kill switch, alerts.
- One portfolio view across all agents and accounts.

### Insights (understand)
- A decision log for every trade.
- Metrics: return, consistency, return vs the market, risk-adjusted return, drawdown, compute cost.
- Agent self-review that proposes upgrades for the owner to approve.

### Arena (compete)
- Creators: the platform (official seasons), clubs and clans, any user, sponsors.
- Formats: head-to-heads (build window, then trade window), open competitions, seasons, clan vs clan.
- Real money only: live accounts, pots and stakes, sponsor prizes. Stakes only on your own or your group's results.
- Challengers choose what the winner takes: the pot, the pot plus profits, or rank only.
- Fairness rules per competition (percentage return, equal funding, size divisions, creator rules), plus beginner-only events.
- Scores come only from broker-verified fills, with risk rules, anti-cheat checks, and public records.
- Leaderboards for agents, people, and clans.

### Community (connect)
- Profiles with agents listed underneath; owners choose what's public.
- Follow people, agents, clans, and competitions, with an activity feed and live trade streams.
- Clans, clubs, and communities: group competitions, private leagues, shared research, chat.
- Copying by mirror or clone; the creator sets permissions; the platform charges a copy fee.

### Billing
- Compute credits: pay-as-you-go, free starter credits, monthly plans, premium tiers.
- A compute budget per agent, with an automatic stop.
- A cut of pots and entries, sponsor billing, and copy fees.

## Non-functional requirements

| Area | Requirement |
| --- | --- |
| Reliability | Agents run 24/7 and survive crashes. No missed or duplicate orders; positions reconcile with the broker every cycle. |
| Security | Broker credentials never reach models or user code. Tokens live in a vault; SDK code runs in isolated sandboxes. |
| Auditability | Every decision and model output is recorded and can be replayed exactly. |
| Cost control | Cheap scanners run constantly and wake expensive models only when needed. Every agent has a compute budget. |
| Integrity | Competition scores come only from broker-reported fills. |
| Speed | Not high-frequency: decisions run on schedules or events, within seconds to minutes. |

## Success measures (proposed)

| Measure | Definition |
| --- | --- |
| North star | Weekly users who run an agent and take a follow-up action (inspect a decision, tweak, deploy a version, enter a competition) |
| Activation | Time from signup to first live agent |
| Depth | Live agents per active user |
| Social | Competitions completed, copies, and follows per user |
| Economics | Compute revenue per active user vs model and data cost |

## Broker connections

Users link a brokerage once at onboarding. From then on, agents trade through the platform's broker layer using a revocable token, never a password.

### How a trade flows
1. **Link.** The user approves the platform at their broker, through the broker's agent connection, OAuth, or SnapTrade's portal. The token goes into a vault; the same read access lets users import past trades.
2. **Decide.** The agent proposes an order: symbol, side, size, order type, and its reasoning.
3. **Check.** The risk engine checks limits, buying power, and approvals. Approval-mode orders wait for the owner's tap.
4. **Send.** The broker adapter converts the order to that broker's format and submits it with a unique key, so a retry can never place it twice.
5. **Confirm.** The platform tracks the order until it fills, partly fills, is canceled, or is rejected.
6. **Record.** Fills update the ledger, decision log, portfolio view, and competition scores. Positions reconcile with the broker every cycle.

### Routes to each first broker

| Broker | How the platform connects | What agents can trade | What to confirm |
| --- | --- | --- | --- |
| Robinhood | Robinhood's agent connection (its Trading MCP server), into a dedicated Agentic Account the user funds | Stocks during the beta; options, crypto, and futures planned | That a hosted platform may act as the agent for many users. Robinhood doesn't supervise or audit agents, so oversight is ours. |
| Interactive Brokers | IBKR Web API with third-party OAuth; users authorize the platform and can limit it to read-only | US stocks and ETFs first; options, futures, and global markets later | Third-party OAuth needs IBKR registration and compliance approval. IBKR's own AI connector keeps orders outside the AI session, so it isn't the trading route. |
| SnapTrade | One API and connection portal for many brokers | Trade-enabled on standard keys for US users: E*TRADE, Public, Webull, tastytrade, Moomoo | Robinhood and IBKR are read-only on standard keys, and some brokers need a production approval. About $2 per connected user per month. |

### Later routes
- **Alpaca:** OAuth lets approved apps trade users' Alpaca accounts, with paper accounts built in. Live trading for other users requires Alpaca's app review. *(Used first in v0 with our own account.)*
- **Webull direct:** Webull lets outside agents connect through OAuth (it's also on SnapTrade).
- **Crypto, when it returns:** Coinbase for Agents, or SnapTrade's Coinbase and Kraken connections.
- **Embedded brokerage:** users open accounts inside the platform through a partner such as Alpaca's Broker API. Most control, but puts the platform in the brokerage chain; legal review first.

### What the broker layer must handle

| Need | Detail |
| --- | --- |
| Capability registry | Per broker: asset types, order types, fractional shares, extended hours, short selling, and whether agents may trade unattended |
| Order confirmations | Some brokers ask follow-up questions before accepting an order (IBKR's reply step). The adapter answers within the owner's rules or holds the order. |
| Buying power | The pattern day trader rule ended on June 4, 2026; brokers now check margin intraday, so buying power can change mid-day. Re-check it before every order. Cash accounts still follow T+1 settlement. |
| Market hours | US stocks trade 9:30am to 4pm Eastern, with limited extended hours. Off-hours orders are queued, skipped, or sent as extended-hours limit orders, per the agent's rules. |
| Failures | Expired tokens and re-authorization, rate limits, outages (pause agents and alert the owner), partial fills, rejections |
| Verification | Competition scores read fills from the broker, never from the agent |
| Trade history import | Pull past orders and fills for the past-trades builder. Read access is enough, so SnapTrade's read-only Robinhood and IBKR connections work; IBKR also offers its Flex Web Service. |

## Architecture at a glance

The platform owns five services that form the agent loop; models, data, simulation, sandboxes, and brokers are rented.

*(Diagram, in text.)* Web app (Studio, Lab, Operations, Insights, Arena, Community) → **Builder** (chat or SDK to an agent) → **Runtime** (wakes agents 24/7) → **Risk engine** (limits and kill switch) → **Broker layer** (one interface for all brokers) → **Records** (every fill and its reason), which feed Insights and the Arena. Rented underneath: Models (OpenRouter → now LiteLLM + providers), Market data, Simulation (backtests and paper trading), Brokers (Robinhood, IBKR, SnapTrade), Code sandbox.

The runtime proposes orders, and the risk engine approves or blocks each one. Approved orders go through the broker layer to a live broker or to paper simulation. Every fill and its reason lands in the records that feed Insights and the Arena.

## The hardest parts of the build

The agents themselves are not the hard part. Running thousands of them reliably on real money, across brokers, with results people trust, is.

| Problem | Why it's hard | Approach |
| --- | --- | --- |
| Always-on runtime | Thousands of agents wake on schedules, events, and scans; they must survive crashes and never double-order | Shared watch engine + durable job queue, a unique key per order, and cheap scanners that wake large models only when needed *(originally Temporal; now NATS + workers)* |
| One agent definition | It must hold strict rules, loose AI judgment, hybrids, sub-agents, and guardrails, from any building path | One schema that the builder outputs from conversation; replay confirms behavior; the plain-English view and the SDK round-trip to it |
| Broker layer | Every broker differs in access, order types, confirmations, and failures | One adapter interface, a capability registry per broker, and constant reconciliation |
| Risk engine | It must stop bad orders even when the agent or model is wrong | Plain code outside the agent: limits, buying power, approvals, instant kill switch; agents can't edit guardrails |
| Versions and copying | One agent runs in many accounts with different sizes and update rules | A ledger per instance, rollout rules per instance, and mirror copies scaled to the copier's allocation |
| Trustworthy results | AI decisions aren't repeatable, and competitions invite cheating | Store every model output for exact replay; score only broker-reported fills; run collusion checks |
| Honest simulation | Backtests can flatter, especially when models already know later events | Realistic fills, fees, and slippage; label every result; weight live results most |
| User code and cost | SDK code is untrusted, and model calls can run up bills | Isolated microVM sandboxes with no credentials; meter every call into credits; per-agent budgets with automatic stop |
| Building from past trades | Trade histories vary by broker and rarely record why a trade was made | Import history through broker APIs or SnapTrade, summarize the patterns, then have the builder ask about specific trades before drafting |

## Recommended stack (original; see superseded note at top)

| Layer | Choice | Build or rent |
| --- | --- | --- |
| Web app | Next.js, TypeScript | Build |
| Services | Python | Build |
| Agent runtime | ~~Temporal~~ → NATS JetStream job queue + workers; DBOS for multi-step flows | Run open source, build the workflows |
| Models | ~~OpenRouter~~ → LiteLLM + direct providers / Bedrock; fast decision models for scanners | Rent models, build metering |
| Simulation | ~~LEAN~~ → NautilusTrader, plus our own replay through the live pipeline | Open source + build |
| Brokers | Robinhood agent connection, Interactive Brokers API, SnapTrade, Alpaca | Rent the rails, build the adapters |
| SDK sandbox | ~~E2B~~ → AWS Lambda (E2B for dev sessions) | Rent |
| Data | Databento (Alpaca free feed in v0), plus news and filings | Rent, build ingest |
| Storage | Postgres (RDS); ClickHouse later; Valkey/Redis | Rent / run |
| Billing, auth, secrets | Stripe, WorkOS, AWS KMS | Rent |
| Observability | OpenTelemetry, Grafana Cloud, Sentry, Langfuse | Rent free tiers |

## Build order and effort (full product)

Four stages, each gated on a working result, take a team of 3–5 engineers to a full live platform. The durations are estimates, not quotes.

| Stage | Duration (est.) | Contents | Gate to pass |
| --- | --- | --- | --- |
| 1 · Foundation | 4–6 weeks | Agent format, runtime, ledger, data feeds | An agent runs end to end on paper |
| 2 · Builder, Lab | 7–9 weeks | Chat builder, past-trade import, replay, backtests | A non-coder builds and paper-trades |
| 3 · Live | 6–8 weeks + approvals | Live brokers, risk engine, decision logs | Real orders, every trade explained |
| 4 · Arena | 6–8 weeks | Profiles, clans, follows, feed, verified contests | A verified real-money head-to-head |
| In parallel from day one | — | Broker approvals, and lawyers on pots and auto-copying (can take months) | — |
| After, ongoing | — | SDK depth, deeper sub-agent systems, more brokers, then money and copying | — |

## Risks and costs

The biggest risks are broker access and legal structure, not code. Engineering risks are covered in the hardest-parts table above. *(Current cost numbers live in `docs/big-ticket-costs.md`.)*

| Risk | Why it matters | Response |
| --- | --- | --- |
| Broker access | Each broker limits what agents may do | Confirm trading access per broker before building its adapter |
| Broker approvals | Brokers review apps that trade for other users | Apply early, in parallel with the build |
| Copy trading | Auto-mirroring other people's agents likely needs a registered-adviser path | Launch cloning first; add mirroring through an adviser partner or our own registration |
| Pots and stakes | State contest law varies, and holding stakes means holding money | A licensed escrow or payments partner, preset prizes, and restricted states blocked |
| Beginners with real money | Regulators have penalized game-like trading features | Plain risk language, paper first, beginner-only events, no celebration tied to trading frequency |
