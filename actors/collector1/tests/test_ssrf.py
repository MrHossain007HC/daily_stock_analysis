from conftest import ScriptedFetcher, ok, run

from collector1.http_client import GuardedFetcher, TransportResponse
from collector1.models import Limits
from collector1.safety import assess_url_policy, ip_is_blocked


class Transport:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        return self.responses.get(url, TransportResponse(200, {}, b"ok"))


def test_policy_blocks_private_stocknow_and_local_urls():
    allowed = ["dsebd.org", "stocknow.com.bd", "sec.gov.bd"]
    cases = {
        "http://127.0.0.1/latest": "raw_ip_not_allowed",
        "http://169.254.169.254/latest/meta-data": "raw_ip_not_allowed",
        "http://localhost/admin": "denied_host",
        "file:///etc/passwd": "scheme_not_allowed",
        "ftp://www.dsebd.org/a.csv": "scheme_not_allowed",
        "https://user:pass@www.dsebd.org/a.csv": "userinfo_not_allowed",
        "https://stocknow.com.bd/api/history": "denied_host",
        "https://10.0.0.5/a.csv": "raw_ip_not_allowed",
    }
    for url, reason in cases.items():
        decision = assess_url_policy(url, allowed)
        assert decision.allowed is False, url
        assert decision.reason == reason, url
    assert ip_is_blocked("127.0.0.1")
    assert ip_is_blocked("169.254.169.254")
    assert ip_is_blocked("10.1.1.1")
    assert ip_is_blocked("::1")
    public = assess_url_policy("https://www.dsebd.org/latest_share_price_scroll_l.php", allowed)
    assert public.allowed is True
    assert public.host == "www.dsebd.org"


def test_redirect_and_dns_to_private_addresses_do_not_connect():
    start = "https://www.dsebd.org/jump"
    transport = Transport(
        {start: TransportResponse(302, {"location": "http://169.254.169.254/latest/meta-data"}, b"")}
    )
    fetcher = GuardedFetcher(transport, ["dsebd.org"], Limits(max_redirects=3), resolver=lambda _host: ["8.8.8.8"])
    result = fetcher.fetch(start)
    assert transport.urls == [start]
    assert result.blocked is True
    assert result.error == "raw_ip_not_allowed"

    transport = Transport({})
    fetcher = GuardedFetcher(transport, ["dsebd.org"], Limits(), resolver=lambda _host: ["127.0.0.1"])
    result = fetcher.fetch("https://www.dsebd.org/prices.csv")
    assert transport.urls == []
    assert result.error == "ssrf_blocked"
    assert result.retryable is False


def test_pipeline_does_not_fetch_denied_hosts():
    fetcher = ScriptedFetcher([ok("https://stocknow.com.bd/a.csv", b"x", "text/csv")])
    result = run(mode="fetch_public", eod_urls=["https://stocknow.com.bd/a.csv"], fetcher=fetcher)
    assert fetcher.urls == []
    assert result.failure_manifest["rows"][0]["reason"] == "denied_host"
    assert result.failure_manifest["rows"][0]["promoted"] is False
    assert result.failure_manifest["rows"][0]["retryable"] is False
