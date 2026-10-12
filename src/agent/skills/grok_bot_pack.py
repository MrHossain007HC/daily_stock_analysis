# -*- coding: utf-8 -*-
"""Canonical Grok Bot top-5 roster (WR-named, opt-in)."""

from __future__ import annotations

from typing import FrozenSet, Iterable

GROK_BOT_TOP5_SKILL_IDS: tuple[str, ...] = (
    "brk55_mom_wr627",
    "brk55_wr614",
    "bb_reclaim_brk55_wr609",
    "patience_named_reason_wr603",
    "superbot_learner_wr548",
)

GROK_BOT_TOP5_SKILL_ID_SET: FrozenSet[str] = frozenset(GROK_BOT_TOP5_SKILL_IDS)


def is_grok_bot_pack_skill(skill_id: str | None) -> bool:
    return str(skill_id or "").strip() in GROK_BOT_TOP5_SKILL_ID_SET


def grok_bot_pack_skill_ids(skill_ids: Iterable[str] | None = None) -> tuple[str, ...]:
    if skill_ids is None:
        return GROK_BOT_TOP5_SKILL_IDS
    wanted = GROK_BOT_TOP5_SKILL_ID_SET
    return tuple(item for item in skill_ids if item in wanted)
