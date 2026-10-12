# -*- coding: utf-8 -*-
"""Apify last-resort search provider: optional, fail-open, last in the chain."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from src.search_service import ApifySearchProvider, SearchService


class TestApifySearchProvider(unittest.TestCase):
    def test_absent_token_does_not_register_provider(self) -> None:
        service = SearchService()
        self.assertFalse(any(p.name == "Apify" for p in service._providers))
        self.assertEqual(service._constructor_kwargs["apify_tokens"], [])

    def test_token_registers_provider_last(self) -> None:
        service = SearchService(tavily_keys=["tvly-test"], apify_tokens=["apify_api_test"])
        names = [p.name for p in service._providers]
        self.assertIn("Apify", names)
        self.assertEqual(names[-1], "Apify")
        rebuilt = SearchService(**service._constructor_kwargs)
        self.assertEqual(rebuilt._constructor_kwargs["apify_tokens"], ["apify_api_test"])

    def test_has_search_capability_when_only_apify_token(self) -> None:
        from src.config import Config

        config = Config(
            anspire_api_keys=[],
            bocha_api_keys=[],
            minimax_api_keys=[],
            tavily_api_keys=[],
            brave_api_keys=[],
            serpapi_keys=[],
            searxng_base_urls=[],
            searxng_public_instances_enabled=False,
            apify_tokens=["apify_api_only"],
        )
        self.assertTrue(config.has_search_capability_enabled())

        with patch.dict(os.environ, {"APIFY_TOKEN": "apify_api_only"}):
            loaded = Config._load_from_env()
            self.assertIn("apify_api_only", loaded.apify_tokens)

    def test_max_actor_chain_compresses_snippet(self) -> None:
        provider = ApifySearchProvider(["apify_api_test"])
        long_text = "A" * 400

        def fake_run(actor_id, api_key, payload, timeout_seconds):
            if actor_id == ApifySearchProvider._SEARCH_ACTOR:
                return [{
                    "title": "AAPL earnings",
                    "url": "https://example.com/aapl",
                    "text": "short",
                }]
            if actor_id == ApifySearchProvider._FETCH_ACTOR:
                return [{
                    "title": "AAPL earnings",
                    "url": "https://example.com/aapl",
                    "markdown": long_text,
                }]
            if actor_id == ApifySearchProvider._YAHOO_ACTOR:
                return [{
                    "headline": "Yahoo AAPL",
                    "url": "https://finance.yahoo.com/quote/AAPL",
                    "summary": "yahoo snippet",
                }]
            return []

        with patch.object(provider, "_run_actor", side_effect=fake_run):
            response = provider._do_search("AAPL stock news", "apify_api_test", max_results=5)

        self.assertTrue(response.success)
        self.assertEqual(response.provider, "Apify")
        self.assertGreaterEqual(len(response.results), 1)
        self.assertLessEqual(len(response.results[0].snippet), 240)
        self.assertTrue(any("yahoo" in (r.url or "").lower() or "Yahoo" in r.title for r in response.results))

    def test_actor_http_error_is_fail_open(self) -> None:
        provider = ApifySearchProvider(["apify_api_test"])
        failed = MagicMock()
        failed.status_code = 403
        failed.text = "forbidden"
        with patch("src.search_service.requests.post", return_value=failed):
            response = provider._do_search("AAPL", "apify_api_test", max_results=3)
        self.assertFalse(response.success)
        self.assertEqual(response.results, [])


class TestApifyWorkflowMapping(unittest.TestCase):
    def test_daily_analysis_maps_apify_token_secret(self) -> None:
        from pathlib import Path

        workflow = (
            Path(__file__).resolve().parents[1] / ".github" / "workflows" / "00-daily-analysis.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("APIFY_TOKEN: ${{ secrets.APIFY_TOKEN }}", workflow)


if __name__ == "__main__":
    unittest.main()
