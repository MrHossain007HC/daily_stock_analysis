# -*- coding: utf-8 -*-
"""Grok Bot top-5 pack: WR-named skills stay opt-in and are the only Bot roster."""

from __future__ import annotations

import unittest
from pathlib import Path

from unittest.mock import patch

from src.agent.skills.base import load_skill_from_yaml, load_skills_from_directory
from src.analyzer import AnalysisResult
from src.config import Config
from src.notification import NotificationService
from src.report_language import format_strategy_plan_compact, resolve_strategy_plan


GROK_BOT_TOP5 = (
    "brk55_mom_wr627",
    "brk55_wr614",
    "bb_reclaim_brk55_wr609",
    "patience_named_reason_wr603",
    "superbot_learner_wr548",
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


class TestGrokBotTop5Pack(unittest.TestCase):
    def test_wr_named_yaml_is_opt_in_and_loads(self) -> None:
        for skill_id in GROK_BOT_TOP5:
            skill = load_skill_from_yaml(_REPO_ROOT / "strategies" / f"{skill_id}.yaml")
            self.assertEqual(skill.name, skill_id)
            self.assertFalse(skill.default_active)
            self.assertFalse(skill.default_router)
            self.assertIn("WR", skill.display_name)
            self.assertIn("WR", skill.instructions)

    def test_builtin_catalog_keeps_legacy_strategies(self) -> None:
        skills = {item.name: item for item in load_skills_from_directory(_REPO_ROOT / "strategies")}
        self.assertIn("bull_trend", skills)
        self.assertIn("chan_theory", skills)
        self.assertTrue(skills["bull_trend"].default_active)
        for skill_id in GROK_BOT_TOP5:
            self.assertIn(skill_id, skills)
            self.assertFalse(skills[skill_id].default_active)

    def test_skill_md_roster_is_top5_only(self) -> None:
        skill_md = (_REPO_ROOT / "docs" / "examples" / "grok_bot" / "SKILL.md").read_text(encoding="utf-8")
        desks = (_REPO_ROOT / "docs" / "examples" / "grok_bot" / "desks.md").read_text(encoding="utf-8")
        for skill_id in GROK_BOT_TOP5:
            self.assertIn(skill_id, skill_md)
            self.assertIn(skill_id, desks)
        self.assertNotIn("weather", skill_md.lower())
        self.assertNotIn("tactical", skill_md.lower())
        self.assertIn("Never call Apify", skill_md)
        self.assertIn("strategy plan", skill_md.lower())

    def test_strategy_plan_always_present_even_without_sniper(self) -> None:
        result = AnalysisResult(
            code="AAPL",
            name="Apple",
            sentiment_score=50,
            trend_prediction="震荡",
            operation_advice="观望",
            dashboard={},
        )
        plan = resolve_strategy_plan(result, "zh")
        self.assertEqual(plan["ideal_buy"], "N/A")
        self.assertEqual(plan["stop_loss"], "N/A")
        self.assertEqual(plan["take_profit"], "N/A")
        compact = format_strategy_plan_compact(result, "zh")
        self.assertIn("策略计划", compact)
        self.assertIn("N/A", compact)

    def test_strategy_plan_uses_wr_skill_name(self) -> None:
        result = AnalysisResult(
            code="AAPL",
            name="Apple",
            sentiment_score=72,
            trend_prediction="看多",
            operation_advice="买入",
            dashboard={
                "strategy_synthesis": {
                    "final_signal": "buy",
                    "consensus_level": "high",
                    "conflict_severity": "none",
                    "conflict_count": 0,
                    "supporting_skills": [{"skill_id": "brk55_mom_wr627", "signal": "buy"}],
                },
                "battle_plan": {
                    "sniper_points": {
                        "ideal_buy": "180",
                        "stop_loss": "170",
                        "take_profit": "195",
                    },
                    "position_strategy": {"entry_plan": "break 55d high"},
                },
            },
        )
        plan = resolve_strategy_plan(result, "en")
        self.assertIn("WR62.7%", plan["strategy_name"])
        self.assertEqual(plan["ideal_buy"], "180")
        self.assertEqual(plan["entry_plan"], "break 55d high")

    @patch("src.notification.get_config")
    def test_mail_fallback_always_mentions_strategy_plan(self, mock_get_config) -> None:
        mock_get_config.return_value = Config(
            stock_list=[],
            report_renderer_enabled=False,
            report_language="zh",
            report_show_llm_model=False,
        )
        service = NotificationService()
        result = AnalysisResult(
            code="AAPL",
            name="Apple",
            sentiment_score=50,
            trend_prediction="震荡",
            operation_advice="观望",
            dashboard={"core_conclusion": {"one_sentence": "等待"}},
        )
        mail = service.generate_dashboard_report([result], report_date="2026-10-12")
        self.assertIn("策略计划", mail)
        self.assertIn("N/A", mail)


if __name__ == "__main__":
    unittest.main()
