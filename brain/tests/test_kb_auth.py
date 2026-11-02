"""KB export authentication: ``KB_EXPORT_SERVICE_KEY`` sent as ``X-Service-Key`` to url sources (real local HTTP server).

The server mimics the one behaviour of Member C's ops-api that matters here: ``GET /v1/kb/export`` answers 401 without a
valid ``X-Service-Key``. These are tests of the Brain's loader against a local stand-in server, not of the real ops-api
(that run is documented in docs/INTEGRATION_TEST_PLAN.md).
"""
from __future__ import annotations

import dataclasses
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from resolvix_contracts.models import KBSource

from conftest import ROOT, make_settings
from resolvix_brain.brain import ResolvixBrain
from resolvix_brain.embeddings import LexicalEmbedder
from resolvix_brain.kb import KBCompileError, load_entries, load_entries_async
from resolvix_brain.settings import BrainSettings

EXPORT = ROOT / "contracts" / "kb" / "sample_kb_export.json"
GOOD_KEY = "test-service-key-not-a-real-secret"


class _Server:
    def __init__(self, mode: str = "key", redirect_to: str | None = None):
        outer = self
        self.seen: list[str | None] = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def do_GET(self):
                key = self.headers.get("X-Service-Key")
                outer.seen.append(key)
                if redirect_to:
                    self.send_response(302)
                    self.send_header("Location", redirect_to)
                    self.end_headers()
                    return
                if mode == "forbidden":
                    self.send_response(403)
                    self.end_headers()
                    return
                if mode == "key" and key != GOOD_KEY:
                    self.send_response(401)
                    self.end_headers()
                    return
                body = EXPORT.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1/kb/export"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    made = []

    def make(**kw):
        s = _Server(**kw)
        made.append(s)
        return s

    yield make
    for s in made:
        s.close()


def src(url: str) -> KBSource:
    return KBSource(kind="url", location=url)


def test_valid_key_loads_the_export(server):
    s = server()
    assert len(load_entries(src(s.url), service_key=GOOD_KEY)) == 12
    assert s.seen == [GOOD_KEY]


async def test_valid_key_async_loads_the_export(server):
    s = server()
    assert len(await load_entries_async(src(s.url), service_key=GOOD_KEY)) == 12


def test_missing_key_is_a_clear_401(server):
    s = server()
    with pytest.raises(KBCompileError) as e:
        load_entries(src(s.url))
    msg = e.value.problems[0]
    assert "HTTP 401" in msg and "KB_EXPORT_SERVICE_KEY" in msg
    assert s.seen == [None]                                   # no header at all when no key is configured


def test_invalid_key_is_a_clear_401_and_does_not_echo_the_key(server):
    s = server()
    bad = "wrong-key-value-12345"
    with pytest.raises(KBCompileError) as e:
        load_entries(src(s.url), service_key=bad)
    text = " ".join(e.value.problems) + str(e.value) + repr(e.value)
    assert "HTTP 401" in text and "rejected" in text and bad not in text
    assert s.seen == [bad]


def test_403_is_reported_as_forbidden(server):
    s = server(mode="forbidden")
    with pytest.raises(KBCompileError) as e:
        load_entries(src(s.url), service_key=GOOD_KEY)
    text = " ".join(e.value.problems)
    assert "HTTP 403" in text and "forbidden" in text and GOOD_KEY not in text


def test_server_that_needs_no_key_still_works_with_and_without_one(server):
    s = server(mode="open")
    assert len(load_entries(src(s.url))) == 12
    assert len(load_entries(src(s.url), service_key=GOOD_KEY)) == 12


def test_file_sources_ignore_the_key_and_never_use_the_network():
    assert len(load_entries(KBSource(kind="file", location=str(EXPORT)), service_key=GOOD_KEY)) == 12


def test_the_key_is_not_forwarded_across_a_redirect(server):
    other = server(mode="open")
    first = server(redirect_to=other.url)
    with pytest.raises(KBCompileError):                       # 302 is not followed, so it fails rather than leaking
        load_entries(src(first.url), service_key=GOOD_KEY)
    assert first.seen == [GOOD_KEY] and other.seen == []


def test_settings_read_the_env_var_and_never_print_it():
    s = BrainSettings.from_env({"KB_EXPORT_SERVICE_KEY": f"  {GOOD_KEY} ", "LLM_MODE": "mock"})
    assert s.kb_export_service_key == GOOD_KEY               # surrounding whitespace is trimmed
    assert GOOD_KEY not in repr(s) and GOOD_KEY not in str(s.safe_dict())
    assert BrainSettings.from_env({"LLM_MODE": "mock"}).kb_export_service_key == ""


async def test_reload_through_the_brain_with_key_missing_key_and_bad_key(server, caplog):
    s = server()
    caplog.set_level(logging.DEBUG)
    base = make_settings()

    async def reload_with(key: str):
        b = ResolvixBrain(dataclasses.replace(base, kb_export_service_key=key), embedder=LexicalEmbedder())
        await b.ready()                                       # default (file) KB is active
        before = b.store.active.kb.kb_version
        try:
            info = await b.reload_kb(src(s.url))
            return b, before, info, None
        except KBCompileError as exc:
            return b, before, None, exc

    b, before, info, err = await reload_with(GOOD_KEY)
    assert err is None and info.entry_count == 12 and b.store.last_source.location == s.url

    for key, needle in (("", "KB_EXPORT_SERVICE_KEY"), ("nope-nope-nope", "rejected")):
        b, before, info, err = await reload_with(key)
        assert err is not None and needle in err.problems[0]
        assert b.store.active.kb.kb_version == before         # a failed reload keeps the old KB active

    assert GOOD_KEY not in caplog.text and "nope-nope-nope" not in caplog.text
