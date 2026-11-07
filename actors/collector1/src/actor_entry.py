"""Apify Actor entrypoint for Collector1."""

from __future__ import annotations

import time

from .collector1.models import config_from_input
from .collector1.pipeline import run_collector


async def run_actor() -> None:
    from apify import Actor

    async with Actor:
        payload = await Actor.get_input() or {}
        if not isinstance(payload, dict):
            Actor.log.error("Collector1 input must be a JSON object")
            raise ValueError("Collector1 input must be a JSON object")
        try:
            config, inline_checkpoint = config_from_input(payload)
        except ValueError as exc:
            Actor.log.error("Invalid Collector1 input")
            raise ValueError(str(exc)) from exc
        checkpoint = None
        if config.resume:
            if isinstance(inline_checkpoint, dict):
                checkpoint = inline_checkpoint
            else:
                stored = await Actor.get_value("CHECKPOINT")
                if isinstance(stored, dict):
                    checkpoint = stored
        Actor.log.info(
            "Collector1 starting mode=%s staged=%s eod_urls=%s document_urls=%s",
            config.mode,
            len(config.staged_files),
            len(config.eod_urls),
            len(config.document_urls),
        )
        try:
            result = run_collector(config, checkpoint=checkpoint, sleeper=time.sleep)
        except ValueError as exc:
            Actor.log.error("Collector1 rejected the checkpoint or input")
            raise ValueError(str(exc)) from exc
        if result.records:
            await Actor.push_data(result.records)
        await Actor.set_value("CHECKPOINT", result.checkpoint)
        await Actor.set_value("COVERAGE_MANIFEST", result.coverage_manifest)
        await Actor.set_value("FAILURE_MANIFEST", result.failure_manifest)
        await Actor.set_value("RUN_SUMMARY", result.run_summary)
        Actor.log.info(
            "Collector1 finished requests=%s bytes=%s accepted=%s quarantine=%s failures=%s stopped=%s",
            result.run_summary["requests"],
            result.run_summary["bytes"],
            result.run_summary["accepted"],
            result.run_summary["quarantine"],
            result.run_summary["failures"],
            result.run_summary["stoppedReason"],
        )
