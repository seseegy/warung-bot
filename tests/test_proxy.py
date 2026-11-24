"""Tes proxy eksplisit — bot jalan di host tanpa internet langsung.

Di VM ini egress harus lewat proxy (host: hatch-egress-proxy:3128) dan
``no_proxy`` host berisi "[::1]" yang tidak bisa di-parse httpx. Karena
itu proxy disampaikan eksplisit (bukan trust_env): main._proxy_dari_env()
+ HTTPXRequest(proxy=...) dan SupabaseClient(proxy=...).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from bot.core.cloud import CloudError, SupabaseClient
from bot.main import _proxy_dari_env

PROXY_PALSU = "http://user:pass@proxy.local:3128"


class _ProxyPerekam(BaseHTTPRequestHandler):
    """Proxy HTTP palsu: merekam request lalu menjawab JSON auth canned."""

    diamati: list[dict] = []

    def do_POST(self) -> None:
        panjang = int(self.headers.get("Content-Length", "0") or "0")
        self.rfile.read(panjang)
        _ProxyPerekam.diamati.append(
            {"path": self.path, "host": self.headers.get("Host", "")}
        )
        badan = json.dumps(
            {
                "access_token": "akses-baru",
                "refresh_token": "segar-baru",
                "expires_in": 3600,
                "user": {"id": "u1", "email": "a@b.c"},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(badan)))
        self.end_headers()
        self.wfile.write(badan)

    def log_message(self, *args: object) -> None:  # senyapkan log server
        pass


@pytest.fixture()
def proxy_palsu():
    _ProxyPerekam.diamati = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProxyPerekam)
    utas = threading.Thread(target=server.serve_forever, daemon=True)
    utas.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_proxy_dari_env_utamakan_https_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", PROXY_PALSU)
    monkeypatch.setenv("https_proxy", "http://lain:8080")
    monkeypatch.setenv("HTTP_PROXY", "http://lain-lain:8080")
    assert _proxy_dari_env() == PROXY_PALSU


def test_proxy_dari_env_fallback_ke_http_proxy(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.setenv("HTTP_PROXY", PROXY_PALSU)
    assert _proxy_dari_env() == PROXY_PALSU


def test_proxy_dari_env_kosong_bila_tidak_ada(monkeypatch):
    for kunci in (
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        monkeypatch.delenv(kunci, raising=False)
    assert _proxy_dari_env() is None


def test_proxy_dari_env_abaikan_string_kosong(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "   ")
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("all_proxy", raising=False)
    assert _proxy_dari_env() is None


async def test_supabase_client_proxy_eksplisit_dipakai(proxy_palsu):
    """Request HARUS lewat proxy palsu: proxy merekam URI absolut target
    dan menjawab JSON canned — bukti httpx memakai proxy eksplisit."""
    klien = SupabaseClient(
        base_url="http://target.local", proxy=proxy_palsu
    )
    try:
        hasil = await klien.refresh_tokens("segar-lama")
    finally:
        await klien.close()
    assert hasil["access_token"] == "akses-baru"
    assert hasil["refresh_token"] == "segar-baru"
    assert len(_ProxyPerekam.diamati) == 1
    # Proxy HTTP menerima URI absolut target, bukan path relatif.
    assert _ProxyPerekam.diamati[0]["path"].startswith(
        "http://target.local/auth/v1/token"
    )


async def test_supabase_client_proxy_mati_gagal_cepat():
    """Proxy menunjuk port tertutup -> CloudError (bukan hang)."""
    klien = SupabaseClient(proxy="http://127.0.0.1:9")
    try:
        with pytest.raises(CloudError):
            await klien.refresh_tokens("segar-palsu")
    finally:
        await klien.close()


async def test_supabase_client_tanpa_proxy_tetap_dibangun():
    klien = SupabaseClient(
        proxy=None, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    )
    try:
        assert klien.base_url.startswith("https://")
    finally:
        await klien.close()
