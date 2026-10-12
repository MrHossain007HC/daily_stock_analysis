# Grok Bot desks (copy-paste Routines)

One desk = one top-5 skill. Do not hardcode a `grok-*` model id. DSA already has the YAML; the Bot only passes `skills`.

Set `DSA_BASE_URL`. Prefer DecisionSignal. Re-analyze only on the morning Routine or when asked. Keep replies as the compact JSON in `SKILL.md`. Mail/notify is DSA-side and always includes the strategy plan.

## Shared poll

```http
GET {DSA_BASE_URL}/api/v1/analysis/status/{task_id}
GET {DSA_BASE_URL}/api/v1/decision-signals/latest/{stock_code}
```

Replace `{skill}` and `{code}` in each desk.

## Desk 1 — BRK55 Mom WR62.7%

`skills: ["brk55_mom_wr627"]`

```json
{"stock_code":"{code}","report_type":"simple","force_refresh":false,"async_mode":true,"notify":true,"skills":["brk55_mom_wr627"]}
```

Use when trend is already up and a 55-day high break has momentum.

## Desk 2 — BRK55 WR61.4%

`skills: ["brk55_wr614"]`

```json
{"stock_code":"{code}","report_type":"simple","force_refresh":false,"async_mode":true,"notify":true,"skills":["brk55_wr614"]}
```

Use for a plain 55-day high break without a momentum overlay.

## Desk 3 — BB Reclaim BRK55 WR60.9%

`skills: ["bb_reclaim_brk55_wr609"]`

```json
{"stock_code":"{code}","report_type":"simple","force_refresh":false,"async_mode":true,"notify":true,"skills":["bb_reclaim_brk55_wr609"]}
```

Use after a Bollinger dip that reclaims mid/upper, then breaks the 55-day high.

## Desk 4 — Patience Named Reason WR60.3%

`skills: ["patience_named_reason_wr603"]`

```json
{"stock_code":"{code}","report_type":"simple","force_refresh":false,"async_mode":true,"notify":true,"skills":["patience_named_reason_wr603"]}
```

Default morning desk. Wait unless there is a named reason. Still return a strategy plan.

## Desk 5 — Super Bot Learner WR54.8%

`skills: ["superbot_learner_wr548"]`

```json
{"stock_code":"{code}","report_type":"simple","force_refresh":false,"async_mode":true,"notify":true,"skills":["superbot_learner_wr548"]}
```

Use when news + trend must be combined. News veto → watch/avoid.

## Not in this pack

Weather, Adaptive, Tactical, and Hold-book variants stay out of Grok Bot. Builtin `strategies/*.yaml` (bull_trend, chan_theory, …) stay in DSA for tests and the Web UI; do not pass them from this Skill.
