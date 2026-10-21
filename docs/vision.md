# Agent Trading Platform: Vision Summary

*October 20, 2026 · Exported from the team's Claude Doc (diagrams described in text)*

## What it is

A web platform where anyone builds, tests, and runs their own AI trading agents on their real brokerage accounts, alongside other people. You build an agent by chatting with a builder agent, or code one in the SDK. The platform tests it, runs it 24/7 on the account you pick inside limits you set, and records why it made every trade.

Those same agents can enter head-to-heads, competitions, and seasons, get followed and copied, and compete with your clan. Users never leave the platform; their brokerage executes the trades in the background.

## Why now

In 2026 the major brokers opened their systems to AI agents, but each only inside its own walls and mostly for people who already know trading or AI.

- **The rails exist.** Robinhood, Coinbase, Interactive Brokers, eToro, and Public all launched ways for agents to trade customer accounts this year.
- **Nobody connects them.** Each broker's agent feature works only for its own customers. No platform lets anyone build agents easily, run them across brokers, and make it social.
- **AI is already in investing.** Most retail investors already use AI to inform decisions. Agents that act on real money only became possible this year.
- **Social drives demand.** The fastest-growing finance apps of the last two years (Fomo, Kalshi) grew on social features: following, leaderboards, clans, betting with and against people.

## Who it's for

Anyone, at any level of trading or AI knowledge. There are four ways in, and every one produces the same kind of agent:

| If you are | You build by |
| --- | --- |
| New to trading | Chatting with a guide that asks about your goals and risk, offers options, teaches as it goes, and builds the agent with you step by step |
| Sure of your strategy, not AI-forward | Describing the strategy in plain language, or importing past trades and answering the guide's questions about them; the builder agent builds it |
| AI-forward, new to finance | Coding in the SDK, with an agent helping you define the strategy itself |
| Anywhere in between | Switching between modes at any time |

"Zero to hero" means going from never having traded to running live agents, learning trading by building, moving from paper to live at your own pace, and growing from one agent to a system of agents.

## Platform map

Six areas sit on one shared platform layer, and all of them work with the same agents.

| Half | Area | What's in it |
| --- | --- | --- |
| Build and run | Studio (build) | Chat or SDK builder; templates, past trades; replay, editable plan |
| Build and run | Lab (test) | Backtests, paper trading, version history |
| Build and run | Operations (run) | Deploy to accounts, limits and kill switch, portfolio view |
| Build and run | Insights (review) | Why every trade happened, performance metrics, upgrade proposals |
| Compete and connect | Arena (compete) | Head-to-heads, competitions, seasons; real money, broker-verified results; leaderboards for agents, people, clans |
| Compete and connect | Community (connect) | Profiles, follows, shared feed; clans, clubs, private leagues, chat; copy agents by mirroring or cloning |
| Platform layer (under everything) | | Broker connections, any AI model, market data, risk engine, records, credits and billing |

The Studio, Lab, Operations, and Insights cover an agent's life from idea to live trading. The Arena and Community put those same agents to work socially.

## What using it looks like

A new user's path, from sign-up to a live agent in a competition:

1. **Sign up and link your brokerages.** Your accounts and balances appear in Operations.
2. **Build in the Studio.** Answer a guide's questions about goals and risk, describe a strategy in your own words, import past trades and let the guide question you about them, start from a template, or open the SDK. The agent's plan appears in plain English you can edit, next to a replay of what it would have done in recent weeks.
3. **Test in the Lab** if you want: run a backtest or let it paper trade first.
4. **Deploy.** Pick an account (or paper), set limits, and choose approve-each-trade or fully automatic.
5. **Watch it run.** The home screen shows every agent, its status and returns, and your combined portfolio. Alerts arrive on each move, approval-mode trades wait for your tap, and one tap pauses everything.
6. **Understand and improve.** Tap any trade to see why it happened. The agent reviews its own results and proposes upgrades you can approve.
7. **Compete and connect.** Enter a beginner competition, challenge a friend, follow top agents, copy one, or join a clan league.

An agent can follow strict rules, use AI judgment, or mix the two. It can work alone or as a main trader with watcher sub-agents that scan for events and report back.

## The social side

The agents people build are also what they compete with, follow, and copy, with real money and verified results. Social is optional, never forced.

- **Anyone can create a competition:** the platform (official year-long seasons), clubs, clans and communities, any user, and sponsors.
- **Real money:** live accounts, entry pots and stakes, and sponsor prizes. Stakes are only ever on your own or your group's performance: head-to-heads, clan vs clan, league and season pots.
- **Head-to-heads:** a build window, then a trade window. The challengers decide what the winner takes.
- **Fair by design:** each competition picks its rules (rank by percentage return, equal funding, divisions by account size, or the creator's own). Results come only from broker-verified trades, with anti-cheat checks and public trade records.
- **Following and leaderboards:** follow people, agents, clans, and competitions. Leaderboards rank single agents, people across all their agents, and clans.
- **Copying:** mirror an agent in your own account, or clone it and run your own copy. The creator decides what's allowed.
- **Clans, clubs, communities:** compete as groups, run private leagues and challenges, share strategies and research, and chat.

People new to real money get a suggestion to start on paper and beginner-only competitions, but the choice is always theirs.

## How it makes money

The platform earns from activity, not from giving advice.

| Stream | How it works |
| --- | --- |
| Compute credits | Charged for building conversations and for running agents. Options: pay-as-you-go, free starter credits, monthly plans with included credits, and premium tiers for heavy users. Models are supplied through a router at cost plus our margin. |
| Competitions | A cut of pots, stakes, and entry fees |
| Sponsors | Brands pay to run competitions and fund prizes |
| Copy trading | Fees when users copy agents |

## Principles

- **All in one, start to finish.** Users never need to open their brokerage; it runs in the background.
- **Built for anyone.** There's an option for every level of trading and AI knowledge.
- **The platform supplies capabilities; users decide how to use them.** That covers any model, any market a connected broker allows, and any competition format.
- **Users set the rules; the platform guarantees the truth.** Results are broker-verified, checked for cheating, recorded publicly, and always under the owner's controls.
- **Own the experience, rent the plumbing.** Brokers execute, model providers think, data vendors feed. The platform owns everything the user touches.

## Now vs later

| Now | Later |
| --- | --- |
| US stocks and ETFs, plus anything else connected brokers let agents trade | Crypto |
| Robinhood, Interactive Brokers, and brokers connected through SnapTrade | More brokers as they open to agents |
| Web app | Mobile |
| Conversational builder, SDK, templates, build from past trades, instant replay | A visual (Scratch-style) builder |
| Single agents, and main traders with watcher sub-agents | Research, development, and review agents |
| Lab, Operations, Insights, Arena, Community | Shared workspaces and organizer tools for clubs and schools |
| Competitions, copying, clans, following | Co-owning agents, builder earnings, spectating, games |
