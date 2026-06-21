"""Offline tests for source_discovery pure logic (no network)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import source_discovery as sd  # noqa: E402


def test_reconstruct_abstract_orders_by_position():
    inv = {"opinion": [2], "Scaling": [0], "spaces": [3], "deliberation": [1]}
    assert sd._reconstruct_abstract(inv) == "Scaling deliberation opinion spaces"


def test_reconstruct_abstract_empty():
    assert sd._reconstruct_abstract(None) == ""
    assert sd._reconstruct_abstract({}) == ""


def test_dedup_key_prefers_doi_then_oa_then_title():
    assert sd._dedup_key({"doi": "10.1/AbC"}) == "doi:10.1/abc"
    assert sd._dedup_key({"doi": None, "openalex_id": "W42"}) == "oa:W42"
    assert sd._dedup_key({"title": "  Polis Paper "}) == "title:polis paper"


def test_dedup_collapses_same_doi_across_queries(monkeypatch):
    a = {"doi": "10.1/x", "title": "A", "query": "q1"}
    b = {"doi": "10.1/X", "title": "A dup", "query": "q2"}  # same DOI, diff case
    monkeypatch.setattr(sd, "search_openalex", lambda q, *a_, **k: [a] if q == "q1" else [b])
    out = sd.run(["q1", "q2"], use_crossref=False)
    assert len(out) == 1 and out[0]["query"] == "q1"


def test_run_respects_max_total(monkeypatch):
    monkeypatch.setattr(sd, "search_openalex",
                        lambda q, *a_, **k: [{"doi": f"10/{q}{i}", "title": str(i)} for i in range(10)])
    assert len(sd.run(["q"], max_total=3)) == 3


def test_run_survives_a_failing_backend(monkeypatch):
    def boom(*a_, **k): raise RuntimeError("api down")
    monkeypatch.setattr(sd, "search_openalex", boom)
    assert sd.run(["q"]) == []   # logged + skipped, no crash


def test_ddg_unwrap_decodes_redirect():
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fdemos.co.uk%2Freport.pdf&rut=x"
    assert sd._ddg_unwrap(href) == "https://demos.co.uk/report.pdf"
    assert sd._ddg_unwrap("https://direct.org/x") == "https://direct.org/x"


def test_search_web_parses_results(monkeypatch):
    html = ('<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fknoca.eu%2Fr.pdf">'
            'KNOCA <b>Polis</b> report</a>'
            '<a class="result__a" href="https://demos.co.uk/x">Demos paper</a>')
    monkeypatch.setattr(sd, "_get_text", lambda url, data=None: html)
    out = sd.search_web("klimarat polis", per_query=10)
    assert len(out) == 2
    assert out[0]["url"] == "https://knoca.eu/r.pdf" and out[0]["source_api"] == "web"
    assert out[0]["title"] == "KNOCA Polis report"   # tags stripped


def test_backends_select_web_and_dedup_by_url(monkeypatch):
    monkeypatch.setattr(sd, "search_web",
                        lambda q, n=25: [{"title": "R", "url": "http://x/r.pdf/", "doi": None,
                                          "openalex_id": None, "source_api": "web"}])
    out = sd.run(["q1", "q2"], backends=["web"])  # same url across queries -> 1
    assert len(out) == 1 and out[0]["source_api"] == "web"


def test_unknown_backend_is_skipped_not_fatal(monkeypatch):
    # bogus backend raises inside _call_backend -> caught, run still returns
    assert sd.run(["q"], backends=["bogus"]) == []


def _http_error(code, retry_after=None):
    import email.message
    import urllib.error
    h = email.message.Message()
    if retry_after is not None:
        h["Retry-After"] = retry_after
    return urllib.error.HTTPError("http://x", code, "err", h, None)


def test_retry_after_honors_seconds_then_backoff():
    assert sd._retry_after(_http_error(429, "5"), 0) == 5.0
    assert sd._retry_after(_http_error(429, "Wed, 21 Oct 2099 07:28:00 GMT"), 2) == 4  # date -> backoff
    assert sd._retry_after(_http_error(503, None), 3) == 8                              # 2**3


def test_read_retries_on_429_then_succeeds(monkeypatch):
    import urllib.request

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"OK"

    calls = {"n": 0}

    def fake_open(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429, "0")
        return _Resp()

    monkeypatch.setattr(sd, "_rate_limit", lambda url: None)
    monkeypatch.setattr(sd.time, "sleep", lambda s: None)
    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    assert sd._read(urllib.request.Request("http://x")) == b"OK"
    assert calls["n"] == 2   # retried once


def test_read_raises_after_exhausting_retries(monkeypatch):
    import urllib.request
    monkeypatch.setattr(sd, "_rate_limit", lambda url: None)
    monkeypatch.setattr(sd.time, "sleep", lambda s: None)
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: (_ for _ in ()).throw(_http_error(503, "0")))
    import urllib.error
    try:
        sd._read(urllib.request.Request("http://x"))
        assert False, "should raise"
    except urllib.error.HTTPError as e:
        assert e.code == 503


def test_host_blocking_ssrf():
    for bad in ["http://localhost/x", "http://127.0.0.1/x", "http://169.254.169.254/latest",
                "http://10.0.0.5/", "http://192.168.1.1/", "http://[::1]/", "http://foo.local/"]:
        assert not sd._safe_public_url(bad), f"should block {bad}"
    for ok in ["http://demos.co.uk/r.pdf", "https://arxiv.org/abs/x"]:
        assert sd._safe_public_url(ok), f"should allow {ok}"


def test_safe_public_url_rejects_non_http_scheme():
    assert not sd._safe_public_url("file:///etc/passwd")
    assert not sd._safe_public_url("gopher://x/")


def test_clean_collapses_control_chars():
    assert sd._clean("a\nb\tc\x00d") == "a b c d"


def test_search_web_drops_ssrf_candidates(monkeypatch):
    html = ('<a class="result__a" href="http://169.254.169.254/meta">metadata</a>'
            '<a class="result__a" href="https://demos.co.uk/ok.pdf">good</a>')
    monkeypatch.setattr(sd, "_get_text", lambda url, data=None: html)
    out = sd.search_web("q")
    assert len(out) == 1 and out[0]["url"] == "https://demos.co.uk/ok.pdf"
