# v0 Specification

**Goal:** prove the core backend loop on the real architecture. One agent, defined by hand, runs 24/5 on our AWS stack. It trades through our own paper broker and an Alpaca paper account, can replay any historical day through the exact same pipeline, then goes live with small real money.

**Not the goal:** user-facing product. No builder UI, no multi-user, no social, no billing.

---

## 1. Scope

**In:**
- One agent in the real schema, with two variants: rules-only, and rules plus one AI filter.
- Market data adapter (Alpaca free feed, swappable).
- Watch engine, NATS job queue, decision worker, LiteLLM gateway.
- Risk engine, order management, our paper broker, Alpaca broker adapter (paper, then live).
- Replay with a simulated clock, decision log, reconciliation.
- Bare control panel and CLI, Terraform for AWS.

**Out:** conversational builder, SDK and sandboxes, past-trade import, multi-user and login beyond one admin, social, competitions, billing, SnapTrade, Databento, ClickHouse, Centrifugo, Robinhood/IBKR (Robinhood is a stretch test only).

## 2. Architecture

```
market data adapter ──► NATS: md.bars.<symbol>
        │ (live: Alpaca websocket; replay: historical file/API + simulated clock)
        ▼
watch engine ── computes indicators once per symbol, evaluates agent conditions
        │      publishes job with message ID = f"{instance_id}:{bar_ts}"
        ▼
NATS JetStream work queue: jobs.wake  (dedup window on)
        ▼
decision worker(s) ── load agent version + state (Postgres)
        │            rules → optional AI filter via LiteLLM (Haiku)
        │            writes decision row (inputs, model output, reasoning)
        ▼
risk engine (in-process module, plain code) ── approve / block / hold for approval
        ▼
order manager ── order row with unique client_order_id (Postgres unique constraint)
        ▼
broker adapter ── PaperBroker | AlpacaBroker(paper) | AlpacaBroker(live)
        ▼
fills ──► ledger + positions + decision log ──► reconciliation loop (every cycle)
```

**One engine, three modes.** The only things that change between backtest/replay, paper, and live are the **Clock** (simulated vs real), the **MarketDataSource** (historical vs live), and the **Broker** (PaperBroker vs AlpacaBroker). All other code paths are identical.

## 3. Stack

| Concern | Choice |
|---|---|
| Language | Python 3.12, `uv` for dependencies, `ruff` + `mypy` + `pytest` |
| Services | asyncio processes; FastAPI for the control API |
| Messaging | NATS 2.x with JetStream (`nats-py`) |
| Database | Postgres 16 (RDS in AWS, Docker locally); SQLAlchemy 2 + Alembic |
| Schemas | Pydantic v2 (agent definition, messages) |
| Broker and data | `alpaca-py` (paper + live trading; free IEX data feed) |
| AI | LiteLLM proxy container → Anthropic `claude-haiku-5-5` |
| Indicators | Our own implementations (SMA, EMA, RSI) on polars/numpy; no native TA-Lib in v0 |
| Local dev | Docker Compose (Postgres, NATS, LiteLLM, services); **local only** |
| Cloud | Terraform → AWS: ECS on EC2 (Arm/Graviton), RDS t4g.micro, KMS, CloudWatch logs; no NAT gateway in v0 |
| Observability | Structured JSON logs, OpenTelemetry, Grafana Cloud free tier, Sentry free tier |
| Control panel | FastAPI + server-rendered HTML (Jinja/HTMX) and a `typer` CLI |

## 4. Agent definition (v0 subset of the full schema)

```json
{
  "agent_id": "rsi-ma-basic",
  "version": 1,
  "name": "RSI + moving average, rules only",
  "universe": ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"],
  "schedule": {"timeframe": "5Min", "session": "regular"},
  "indicators": [
    {"id": "rsi14", "type": "RSI", "period": 14},
    {"id": "sma50", "type": "SMA", "period": 50}
  ],
  "entry": {"all": [
    {"lhs": "rsi14", "op": "<", "rhs": 30},
    {"lhs": "close", "op": ">", "rhs": "sma50"}
  ]},
  "exit": {"any": [
    {"lhs": "rsi14", "op": ">", "rhs": 60},
    {"type": "stop_loss_pct", "value": 1.0},
    {"type": "take_profit_pct", "value": 2.0}
  ]},
  "sizing": {"type": "fixed_notional", "usd": 200},
  "ai_filter": null,
  "guardrails": {
    "max_position_usd": 500,
    "max_open_positions": 3,
    "max_daily_loss_usd": 50,
    "approval_mode": "auto"
  }
}
```

**AI variant:** same, with:

```json
"ai_filter": {
  "model": "claude-haiku-5-5",
  "prompt": "Given this signal snapshot, answer TAKE or SKIP with one sentence of reasoning.",
  "fail_mode": "skip"
}
```

- Guardrails are enforced by the risk engine, never by the agent.
- Exits use broker-native stop and limit orders where the broker supports them.
- Examples live in `agents/examples/`.

## 5. NATS layout

| Stream / subject | Retention | Purpose |
|---|---|---|
| `MD` / `md.bars.<symbol>` | Limits (keep ~7 days) | Bars from the data adapter (replayable) |
| `JOBS` / `jobs.wake` | Work queue, explicit ack, dedup window ≥ 2 min | One message per (instance, bar) |
| `JOBS_DLQ` / `jobs.dlq` | Limits | Jobs that hit max delivery attempts or terminal errors (we build this; NATS has none built in) |
| `EVENTS` / `events.>` | Limits | Order, fill, risk, and reconciliation events for the control panel and alerts |

Locally use a single node (R1). In AWS, plan for 3 nodes (R3) before live scale; v0 can start on R1.

## 6. Postgres tables

| Table | Key fields |
|---|---|
| `agents` | id, name, created_at |
| `agent_versions` | agent_id, version, definition_json (immutable), created_at |
| `instances` | id, agent_id, version, mode (`replay`/`paper`/`alpaca_paper`/`alpaca_live`), status (`running`/`paused`/`killed`), account_ref |
| `broker_accounts` | id, broker, encrypted_credentials (KMS ciphertext), is_live |
| `bars` | symbol, timeframe, ts, OHLCV (for replay cache) |
| `decisions` | id, instance_id, bar_ts, inputs_json, rule_result, model_request_hash, model_output, reasoning, action, latency_ms, cost_usd |
| `orders` | id, **client_order_id (unique)**, instance_id, decision_id, symbol, side, qty/notional, type, limit/stop, state, broker_order_id, timestamps |
| `order_events` | order_id, from_state, to_state, payload, ts |
| `fills` | id, order_id, qty, price, fee, ts, broker_fill_id (unique) |
| `positions` | instance_id, symbol, qty, avg_price |
| `ledger_entries` | instance_id, account (cash/position/fees), amount, ref, ts (double-entry) |
| `risk_events` | instance_id, decision_id, rule, outcome, detail |
| `reconciliation_runs` | instance_id, ts, status, diffs_json |
| `llm_cache` | request_hash (unique), response, model, created_at (deterministic replay) |

**Order states:** `proposed → approved → submitted → accepted → partially_filled → filled`. Also `→ canceled | rejected | expired` from any open state. Every transition is logged in `order_events`.

## 7. Components

### Market data adapter
- Interface: `MarketDataSource.stream(symbols, timeframe)` and `history(symbols, start, end, timeframe)`.
- `AlpacaDataSource` (live websocket + historical REST, IEX feed) and `ReplayDataSource` (reads `bars` or Parquet and emits on the simulated clock).
- Publishes normalized bars to `md.bars.<symbol>`.

### Watch engine
- Subscribes to `md.bars.*`. Keeps rolling windows per symbol. Computes each indicator **once per symbol and timeframe**, shared across instances.
- Evaluates every running instance's entry and exit conditions.
- Publishes `jobs.wake` with message ID `{instance_id}:{bar_ts}`. Only one active watch engine per partition (Postgres advisory lock).

### Decision worker
- Pull consumer on `jobs.wake`. Loads agent version and position state, runs rules, then the AI filter if configured.
- AI calls go through LiteLLM; the request hash and response are cached in `llm_cache`. In replay, cached responses are reused, so re-runs are deterministic.
- Writes a `decisions` row, calls the risk engine, then the order manager.
- Acks only after the decision is committed. On error: NAK with backoff. After max deliveries, publish to `jobs.dlq` and alert.

### Risk engine
Pure functions. Checks, in order:
1. Instance status (killed or paused blocks everything).
2. Global kill switch.
3. Market hours.
4. Max position.
5. Max open positions.
6. Max daily loss.
7. Buying power (from the broker or paper ledger).
8. Duplicate or conflicting open orders.

Approval mode `manual` parks the order in `proposed` until approved in the control panel or CLI. Every outcome is written to `risk_events`.

### Order manager
- Creates the order with `client_order_id = f"{instance_id}-{decision_id}"`; the Postgres unique constraint makes retries safe.
- Submits through the broker interface, tracks state by polling or streaming trade updates, and writes fills, positions, and ledger entries in one transaction.

### Broker interface

```
submit_order(order) -> BrokerOrderRef
cancel_order(ref)
get_order(ref) -> status, fills
list_open_orders()
get_positions()
get_account() -> cash, buying_power, equity
stream_trade_updates() (optional)
```

- `PaperBroker`: fills market orders at the next bar's open plus slippage (configurable bps, default 5). Fills limit/stop orders when the bar's range crosses the price. Applies a fee model (default $0). Works in replay and live-paper.
- `AlpacaBroker(paper|live)`: wraps `alpaca-py`. **Live requires `ALLOW_LIVE_TRADING=true` and `is_live=true` on the account row; otherwise it refuses.**

### Replay
- A `SimClock` drives everything (`now()`, `sleep_until()`), with speed 1x–50x or "as fast as possible".
- `ReplayDataSource` emits historical bars into NATS. Workers and the risk engine run unchanged.
- Results go into a separate `run_id`, so replays never touch paper or live records.
- CLI: `atp replay --agent rsi-ma-basic --date 2026-10-14 --speed 20`.

### Reconciliation
- Every N seconds (and on startup), compare broker positions and open orders with our `positions` and `orders`.
- Any diff: write `reconciliation_runs`, emit `events.reconcile.mismatch`, alert, and pause the instance.

### Control panel and CLI
- **Panel pages:** instances (start/pause/kill), global kill switch, positions, orders with state history, decision log (inputs, reasoning, model output), pending approvals, replay runs.
- **CLI:** `atp agent load`, `atp instance start|pause|kill`, `atp kill-all`, `atp replay`, `atp reconcile`, `atp decisions tail`.
- Single admin auth (token in an environment variable) for v0.

## 8. Security and safety rules
- Paper is the default everywhere. Live trading needs both the environment flag and a live account row.
- Broker credentials are encrypted with KMS in AWS (a local key in dev) and never logged, never sent to LLMs, never committed.
- `.env` is never committed; `.env.example` lists the variables.
- The kill switch stops order submission immediately and cancels open orders.

## 9. Acceptance tests (v0 is done when all pass)

| # | Test | Pass condition |
|---|---|---|
| 1 | Replay parity | A historical day at 20x matches a straightforward reference backtest within tolerance; two re-runs give identical decisions and orders |
| 2 | Paper soak | 2 weeks running 24/5 on Alpaca paper: zero duplicate orders, zero missed triggers, reconciliation clean |
| 3 | Worker crash | Kill a worker mid-job: the job retries, and the order is not duplicated (unique key holds) |
| 4 | Watch engine restart | Restart mid-session: no missed triggers (bars replayed from the `MD` stream) |
| 5 | Broker failures | Injected 5xx errors, timeouts, expired keys: retry with backoff, alert, instance pauses safely |
| 6 | Kill switch | Global kill stops new orders and cancels open ones within 5 seconds |
| 7 | Market-open burst | Replay 9:30am with 1,000 copies of the agent: queue lag stays within ~1 bar; no guardrail breaches |
| 8 | Live | 1 week on Alpaca live with $100–500: every trade has a decision row with reasoning; positions match the broker |
| 9 | AI cost | Per-decision model cost recorded; daily cost per instance visible |
| 10 | Infra | `terraform apply` from clean gives a working stack; `terraform destroy` removes it |
