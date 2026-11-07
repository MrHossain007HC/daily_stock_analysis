import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from collector1.http_client import FetchResult
from collector1.models import CollectorConfig, Limits
from collector1.pipeline import run_collector

PUBLIC = "https://www.dsebd.org/data/eod.csv"


class Clock:
    def __init__(self, start=0.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ScriptedFetcher:
    def __init__(self, results):
        self.results = list(results)
        self.urls = []

    def fetch(self, url):
        self.urls.append(url)
        item = self.results.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def encode(payload):
    if isinstance(payload, str):
        payload = payload.encode()
    return base64.b64encode(payload).decode()


def staged(content, url=PUBLIC, **extra):
    item = {
        "sourceUrl": extra.pop("sourceUrl", url),
        "fileName": extra.pop("fileName", "eod.csv"),
        "kind": extra.pop("kind", "eod"),
        "declaredMime": extra.pop("declaredMime", "text/csv"),
    }
    if content is not None:
        item["contentBase64"] = encode(content)
    item.update(extra)
    return item


def run(files=None, fetcher=None, checkpoint=None, clock=None, **config):
    limits = config.pop("limits", None)
    cfg = CollectorConfig(staged_files=files or [], **config)
    if limits is not None:
        cfg.limits = limits
    return run_collector(cfg, fetcher=fetcher, checkpoint=checkpoint, clock=clock)


def ok(url, body, content_type):
    return FetchResult(True, 200, url, {"content-type": content_type}, body, None, False, False)


def failure(status, retryable):
    return FetchResult(False, status, "", {}, b"", f"http_{status}", retryable, False)
