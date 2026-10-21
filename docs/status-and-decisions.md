# Status, Decisions, and Open Questions

*Exported from the team's Claude Doc, status updated October 21, 2026.*

## Where things stand

The platform is in planning: the vision is locked, infrastructure is researched, v0 is defined, and this repo is the starting point for building v0. No product code has been written yet.

| Area | Status |
| --- | --- |
| Vision and scope | Locked: definition, platform areas, builder paths, competition rules, revenue model (`docs/vision.md`, `docs/prd-and-technical.md`) |
| Infrastructure | Researched with costs and alternatives (`docs/infrastructure-full.md`, `docs/infrastructure-decisions.md`, `docs/big-ticket-costs.md`) |
| v0 | Defined: one agent, real AWS stack, paper + Alpaca, replay (`docs/v0/SPEC.md`, `docs/v0/PLAN.md`) |
| Markets and brokers | US stocks first; v0 on Alpaca; Robinhood, IBKR, Schwab, Tradier next; crypto deferred; trading access still to confirm per broker |
| Team | das and Aryan cover platform and backend, AI agents, trading systems and data, and frontend and design; time commitment not decided |
| Build | Repo created; no vendor contracts; no budget or timeline committed |
| Legal | No lawyers engaged yet on platform status, auto-mirroring, or paid contests |

**Proposed next steps**

1. Settle how much time das and Aryan can give, and who leads what.
2. Build v0 (`docs/v0/PLAN.md`).
3. Confirm broker trading access: Robinhood's agent terms, IBKR third-party OAuth, Schwab and Tradier commercial approval, SnapTrade plans.
4. Engage a securities lawyer and a contest lawyer with the questions below.
5. Pick a working name.

## Locked decisions

These came directly from Ayan's answers and should not be reopened without a reason.

| Area | Decision |
| --- | --- |
| Platform | One platform with two equal halves: building and running agents, and the social side. Social is never forced. |
| Users | Built for anyone. The user is the main profile; their agents sit underneath. |
| Building | Conversational builder for everyone (guided, plain-language, SDK with an agent co-pilot). The SDK is for AI-forward builders. No visual builder for now. Agent library and templates are core. |
| Builder extras | Start from a template then chat, build from past trades (after an import, the builder questions you about them), instant replay, and an editable plain-English strategy view |
| Agents | Any strategy style (strict rules, AI judgment, hybrids, anything else). Single agents, or a main trader with watcher sub-agents. Many agents per user. |
| Improving | Iterate on paper or straight on live funds. The agent can propose its own upgrades. New versions roll out automatically, where the owner chooses, or by copier opt-in. Competitions don't force a version lock. |
| Brokers | Linked at onboarding. Agents trade whatever brokers allow. Users never leave the platform. First brokers: Robinhood, Interactive Brokers, and SnapTrade-connected brokers (v0 uses Alpaca for testing). |
| Markets | US stocks and ETFs first. Crypto deferred. |
| Surface | Web app |
| Models and data | Any model through a platform gateway, billed to users as credits; no user API keys. Platform market data, news and social feeds, and premium add-ons; no user-supplied sources. |
| Competitions | Anyone can create them. Real money only (live accounts, pots and stakes, sponsor prizes). Fairness set per competition. Broker-verified results. Stakes only on your own or your group's performance. |
| Social | Follow people, agents, clans, and competitions. Leaderboards for agents, people, and clans. Copying by mirror or clone, with the creator setting permissions. |
| Controls | Limits, approve each trade or run fully automatic, kill switch, alerts |
| New users | Suggest paper first, offer beginner-only competitions, no forced limits |
| Revenue | Compute credits (pay-as-you-go, starter credits, plans, tiers), a cut of pots and entries, sponsors, copy fees |
| Team | das and Aryan cover platform and backend, AI agents, trading systems and data, and frontend and design |

## Open questions

- [ ] Platform name and brand
- [ ] How much time das and Aryan can commit, and who leads what
- [ ] Robinhood: may a hosted platform act as the agent for many users through Robinhood's agent connection?
- [ ] Interactive Brokers: apply for third-party OAuth on the Web API
- [ ] SnapTrade: production approval, and whether Robinhood or IBKR trading can be enabled
- [ ] Past-trade import: which brokers give enough trade history, and how far back
- [ ] How "the winner takes the pot plus profits" works when profits sit in separate brokerage accounts
- [ ] Pots and stakes: which licensed escrow or payments partner, and which states to block
- [ ] Copy trading: an adviser partner or our own registration for auto-mirroring (cloning launches first)
- [ ] Pricing: credit price, plan tiers, and margin over model cost
- [ ] Market data: Databento display terms vs EODHD's reported free redistribution
- [ ] Success measures to adopt

## Later backlog

| Theme | Ideas |
| --- | --- |
| Markets and access | Crypto, mobile apps, more brokers |
| Building | Visual (Scratch-style) builder; research, development, and review agents |
| Groups | Shared workspaces; organizer tools for clubs, universities, and schools |
| Agent economy | Co-owning or backing other people's agents, a fund run by everyone's agents, builder earnings |
| Play | Fantasy-style drafts of agents, live agent battles to watch, your agent vs famous traders, your agent vs the big AI models |
| Games | Challenges like "beat the S&P," quick daily and weekly contests, badges and levels, learn-by-playing missions |
| Ecosystem | Scouting and hiring top builders, clans co-building shared agents, combined signals from all agents, other apps using our agents |

## Questions for lawyers

These need securities and gaming lawyers before any money feature launches. This list is not legal advice.

1. **Platform status:** does hosting user-built agents that trade in users' own brokerage accounts make us an investment adviser or a broker? Which design keeps it a software tool?
2. **Auto-mirroring:** what is the registration path or partner structure for automatically mirroring other people's agents?
3. **Copy fees:** what do fees on copying mean for compensation rules?
4. **Pots, stakes, and entry fees:** which states allow paid contests? Should prizes come from company funds rather than pooled entries? What are the geofencing, ID-verification, and tax-reporting requirements?
5. **Head-to-heads:** can two players stake against each other directly, or only enter contests with preset prizes?
6. **Sponsor prizes:** what rules apply to free-entry, sponsor-funded competitions?
7. **Holding money:** does holding stakes require money-transmission licenses, or can a licensed partner carry that?
8. **Beginners:** which design rules keep real-money competition features clear of gamification enforcement?

## Sources

Research links are listed in `docs/infrastructure-full.md` and `docs/big-ticket-costs.md`. Product and market sources from the original research:

- Robinhood agent accounts: https://robinhood.com/us/en/newsroom/robinhood-is-now-open-to-agents/
- Robinhood Social: https://robinhood.com/us/en/newsroom/robinhood-social-beta
- Coinbase for Agents: https://siliconangle.com/2026/06/11/coinbase-agents-lets-ai-assistants-trade-crypto-move-money/
- eToro agents: https://www.etoro.com/news-and-analysis/press-releases/etoro-launches-new-app-ai-first-smart-and-social/
- Public agents: https://www.cdomagazine.tech/aiml/public-launches-ai-agents-to-automate-trading-strategies
- Brokers with AI agent connections: https://www.stockbrokers.com/guides/ai-agent-brokers
- Fomo growth: https://www.kucoin.com/news/flash/fomo-raises-75m-at-550m-valuation-microstrategy-slows-btc-buys
- Kalshi growth: https://forklog.com/en/kalshis-u-s-traffic-soars-16-fold-in-a-year/
- Retail investors using AI: https://hedgefundalpha.com/news/retail-investors-now-use-ai-to-inform-investment-decisions/
- Copy-trading registration (Dub): https://fortune.com/2025/08/15/gen-z-millenial-ceo-stock-market-investments-influencers-financial-advisors
- Contest player funds: https://www.legalsportsreport.com/12919/segregation-of-dfs-player-funds/
- Paid trading contests by state: https://www.terms.law/Trading-Legal/guides/trading-contest-state-matrix.html
- Gamification enforcement: https://www.velaw.com/insights/game-over-robinhood-pays-7-5-million-to-resolve-gamification-securities-violations/
- End of the pattern day trader rule: https://us.etrade.com/knowledge/library/margin/pattern-day-trading-rule-change
