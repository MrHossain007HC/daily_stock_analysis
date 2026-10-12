---
name: daily-stock-analysis
description: Call DSA REST for stock analysis. Prefer DecisionSignal. Top-5 WR strategies only. Compact JSON replies.
---

# DSA Grok Bot

Need `DSA_BASE_URL` (no trailing slash). Bot consumes DSA REST only. Never call Apify. Never set `GROK_BOT_*`. Do not use LiteLLM / xAI as DSA.

## Roster (only these skills)

| id | WR | use |
| --- | --- | --- |
| `brk55_mom_wr627` | 62.7% | 55d high + momentum |
| `brk55_wr614` | 61.4% | 55d high |
| `bb_reclaim_brk55_wr609` | 60.9% | BB reclaim then 55d high |
| `patience_named_reason_wr603` | 60.3% | wait for named reason |
| `superbot_learner_wr548` | 54.8% | trend+news learner |

Do not load Weather / Adaptive / Tactical or other builtin YAML. One skill per call.

## Flow

1. Parse code: A-share 6 digits, HK `hk00700`, US `AAPL`. If only a Chinese name, ask for the code.
2. Default: `GET {DSA_BASE_URL}/api/v1/decision-signals/latest/{stock_code}`. Skip re-analysis when a fresh signal exists.
3. Full run only if user asks to re-analyze or no signal: `POST {DSA_BASE_URL}/api/v1/analysis/analyze` with `async_mode: true` from the first request.

```json
{"stock_code":"<code>","report_type":"simple","force_refresh":true,"async_mode":true,"notify":true,"skills":["brk55_mom_wr627"]}
```

Poll `GET {DSA_BASE_URL}/api/v1/analysis/status/{task_id}` until `completed`. Report is `result.report` (not root `report`).
4. Market review: `POST .../market-review` → 202 `task_id` → same status URL → `market_review_report`.
5. Health: `GET {DSA_BASE_URL}/api/health`.

Never sync-timeout then retry async. On 409 use `existing_task_id`.

## Reply (≤120 tokens)

Always include the strategy plan (name+WR, ideal_buy, stop, target, entry). Use JSON:

```json
{"code":"AAPL","skill":"brk55_mom_wr627","wr":"62.7%","action":"watch","plan":{"entry":"n/a","ideal_buy":"n/a","stop":"n/a","target":"n/a"},"why":""}
```

Read `action`/`action_label` and `report.strategy.ideal_buy|stop_loss|take_profit` (async prefix `result.`). DecisionSignal is advice only. Do not place orders.
