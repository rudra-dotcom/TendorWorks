import socket
from unittest.mock import Mock

import httpx
import pytest

from tender.research import ResearchWorker, allowed_url


def test_web_allowlist_and_private_addresses(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    assert not allowed_url("https://cpwd.gov.in/publication.pdf", ["cpwd.gov.in"])
    assert not allowed_url("http://cpwd.gov.in/publication.pdf", ["cpwd.gov.in"])
    assert not allowed_url("https://cpwd.gov.in.attacker.org/file", ["cpwd.gov.in"])
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])
    assert allowed_url("https://cpwd.gov.in/publication.pdf", ["cpwd.gov.in"])


def test_official_search_caches_candidate_without_promoting(settings, monkeypatch):
    settings.web_enabled = True
    gateway = Mock(settings=settings)
    worker = ResearchWorker(gateway)
    monkeypatch.setattr("tender.research.allowed_url", lambda *a: True)
    html = b'<html><a href="/rates.pdf">Plinth Area Rates 2025</a></html>'
    monkeypatch.setattr(
        "tender.research.httpx.stream",
        lambda *a, **k: httpx.Response(200, content=html, request=httpx.Request("GET", a[1])),
    )
    # httpx.Response itself needs a context manager wrapper for stream-style tests.
    from contextlib import contextmanager

    @contextmanager
    def stream(*args, **kwargs):
        yield httpx.Response(200, content=html, request=httpx.Request("GET", args[1]))

    monkeypatch.setattr("tender.research.httpx.stream", stream)
    fetch = Mock(return_value="candidate-id")
    monkeypatch.setattr(worker, "fetch", fetch)
    first = worker.discover("cpwd", "building", "tenant-a")
    second = worker.discover("cpwd", "building", "tenant-a")
    assert first["status"] == "candidates_require_review" and second["cached"]
    fetch.assert_called_once()
    gateway.approve_pack.assert_not_called()


def test_redirect_private_target_rejected(settings, monkeypatch):
    from contextlib import contextmanager

    gateway = Mock(settings=settings)

    @contextmanager
    def stream(*args, **kwargs):
        yield httpx.Response(
            302, headers={"location": "http://127.0.0.1/private"}, request=httpx.Request("GET", args[1])
        )

    monkeypatch.setattr(
        "tender.research.allowed_url", lambda url, hosts: url.startswith("https://cpwd.gov.in")
    )
    monkeypatch.setattr("tender.research.httpx.stream", stream)
    with pytest.raises(ValueError, match="host"):
        ResearchWorker(gateway).fetch("https://cpwd.gov.in/source", "source", "cpwd", "a")
