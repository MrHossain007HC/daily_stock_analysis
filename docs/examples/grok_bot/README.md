# Grok Bot Skill 示例

给 2026-08-11 [Grok Bot](https://x.ai/bot) 用的最小 Skill 包。只调用 DSA 已有 REST，不引入新 API、`GROK_BOT_*` 环境变量或 MCP server。Bot 不直接调 Apify。

把 [`SKILL.md`](SKILL.md) 拷进 Bot 的 Skills 目录，按 [`desks.md`](desks.md) 为每个模型建一条 Routine（一 desk 一 skill）。设置 `DSA_BASE_URL`（例如 `http://127.0.0.1:8000`），并先让 DSA 以 `python main.py --serve-only` 或 Docker 长期运行。Web / 桌面端策略选择器会标出这 5 个 WR 策略，报告页始终展示策略计划。

## Top 5 roster（名称含胜率）

| skill id | display | Sel/paper WR |
| --- | --- | --- |
| `brk55_mom_wr627` | BRK55 Mom WR62.7% | 62.7% |
| `brk55_wr614` | BRK55 WR61.4% | 61.4% |
| `bb_reclaim_brk55_wr609` | BB Reclaim BRK55 WR60.9% | 60.9% |
| `patience_named_reason_wr603` | Patience Named Reason WR60.3% | 60.3% |
| `superbot_learner_wr548` | Super Bot Learner WR54.8% | 54.8% |

YAML 在仓库 `strategies/`，`default_active: false`，不影响默认多头趋势。Grok Bot 调用分析时必须传 `skills: ["<id>"]`。

完整边界、DecisionSignal Routine、认证限制见 [Grok Bot 集成](../../grok-bot-integration.md)。openclaw 用户看 [openclaw Skill](../../openclaw-skill-integration.md)，契约相同。
