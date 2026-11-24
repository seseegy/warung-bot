"""Tes core/cloud.py dengan mock transport httpx (TANPA panggilan live)."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from bot.core.cloud import (
    CloudError,
    ConflictError,
    NoCloudData,
    SessionExpired,
    SupabaseClient,
)

P_DATA_CONTOH = "1:H4sIAAAAAAAAAw=="


def _mock_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    try:
        isi = json.loads(request.content.decode() or "{}")
    except json.JSONDecodeError:
        isi = {}
    # -- refresh token --
    if path == "/auth/v1/token" and "refresh_token" in str(request.url):
        if isi.get("refresh_token") == "refresh-TOKEN-valid":
            return httpx.Response(
                200,
                json={
                    "access_token": "access-TOKEN-baru",
                    "refresh_token": "refresh-TOKEN-baru",
                    "expires_in": 3600,
                    "token_type": "bearer",
                    "user": {"id": "uuid-1", "email": "akunling427@gmail.com"},
                },
            )
        return httpx.Response(401, json={"error": "invalid_grant"})
    # -- RPC akun --
    if path == "/rest/v1/rpc/akun_ambil":
        if request.headers.get("Authorization") != "Bearer access-TOKEN-valid" and request.headers.get(
            "Authorization"
        ) != "Bearer access-TOKEN-baru":
            return httpx.Response(401, json={"code": "42501", "message": "permission denied"})
        if isi.get("kosong"):
            return httpx.Response(200, json={"ok": False, "alasan": "tidak_ada"})
        return httpx.Response(200, json={"ok": True, "versi": 8, "data": P_DATA_CONTOH})
    if path == "/rest/v1/rpc/akun_simpan":
        if isi.get("p_paksa"):
            return httpx.Response(200, json={"ok": True, "versi": 9})
        if int(isi.get("p_versi_dasar", 0)) < 8:
            return httpx.Response(200, json={"ok": False, "alasan": "bentrok"})
        return httpx.Response(200, json={"ok": True, "versi": 9})
    return httpx.Response(404, json={"error": "not found"})


@pytest.fixture()
def client():
    transport = httpx.MockTransport(_mock_handler)
    c = SupabaseClient(transport=transport)
    yield c


def _session(**overrides):
    s = {
        "akses": "access-TOKEN-valid",
        "segar": "refresh-TOKEN-valid",
        "habis": int(time.time()) + 3600,
        "user_id": "uuid-1",
        "email": "akunling427@gmail.com",
    }
    s.update(overrides)
    return s


async def test_ensure_token_pakai_token_masih_berlaku(client):
    """Token berlaku > 90 dtk -> TIDAK ada panggilan HTTP sama sekali."""
    calls = {"n": 0}

    def counting(request):
        calls["n"] += 1
        return _mock_handler(request)

    c2 = SupabaseClient(transport=httpx.MockTransport(counting))
    sesi = _session()
    hasil = await c2.ensure_token(sesi)
    assert hasil is sesi
    assert calls["n"] == 0


async def test_ensure_token_refresh_bila_sisa_kurang_90_detik(client):
    sesi = _session(habis=int(time.time()) + 30)
    baru = await client.ensure_token(sesi)
    assert baru["akses"] == "access-TOKEN-baru"
    assert baru["segar"] == "refresh-TOKEN-baru"
    assert baru["habis"] > int(time.time()) + 3500
    assert baru["user_id"] == "uuid-1"


async def test_ensure_token_refresh_401_jadi_session_expired(client):
    sesi = _session(habis=0, segar="refresh-TOKEN-rusak")
    with pytest.raises(SessionExpired):
        await client.ensure_token(sesi)


async def test_refresh_tanpa_token_jadi_session_expired(client):
    sesi = _session(habis=0, segar="")
    with pytest.raises(SessionExpired):
        await client.ensure_token(sesi)


async def test_fetch_cloud_ok(client):
    data, _ = await client.fetch_cloud(_session())
    assert data["versi"] == 8
    assert data["data"] == P_DATA_CONTOH


async def test_fetch_cloud_tanpa_data(client):
    # Simulasi akun_ambil ok=false dengan payload penanda "kosong".
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"ok": False, "alasan": "tidak_ada"})
        if req.url.path == "/rest/v1/rpc/akun_ambil"
        else _mock_handler(req)
    )
    c2 = SupabaseClient(transport=transport)
    with pytest.raises(NoCloudData):
        await c2.fetch_cloud(_session())


async def test_fetch_cloud_401_jadi_session_expired(client):
    sesi = _session(akses="access-TOKEN-salah")
    with pytest.raises(SessionExpired):
        await client.fetch_cloud(sesi)


async def test_upload_cloud_ok(client):
    data, _ = await client.upload_cloud(
        _session(), P_DATA_CONTOH, 8, "3a5dd8081fa92f174078ce3ca639fa07"
    )
    assert data["versi"] == 9


async def test_upload_cloud_bentrok(client):
    with pytest.raises(ConflictError):
        await client.upload_cloud(
            _session(), P_DATA_CONTOH, 7, "3a5dd8081fa92f174078ce3ca639fa07"
        )


async def test_upload_cloud_paksa_lolos(client):
    data, _ = await client.upload_cloud(
        _session(), P_DATA_CONTOH, 7, "3a5dd8081fa92f174078ce3ca639fa07", paksa=True
    )
    assert data["versi"] == 9


async def test_no_cloud_data_membawa_sesi_refresh():
    """Refresh terjadi dulu, lalu akun_ambil ok=false.

    Sesi hasil refresh HARUS ikut di exception — kalau dibuang, token
    refresh baru (yang sudah di-rotasi server) hilang dan akun terkunci
    sampai /link ulang.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/v1/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access-TOKEN-baru",
                    "refresh_token": "refresh-TOKEN-baru",
                    "expires_in": 3600,
                    "user": {"id": "uuid-1", "email": "a@b.c"},
                },
            )
        if request.url.path == "/rest/v1/rpc/akun_ambil":
            return httpx.Response(200, json={"ok": False, "alasan": "tidak_ada"})
        return httpx.Response(404, json={})

    c = SupabaseClient(transport=httpx.MockTransport(handler))
    sesi = _session(habis=0)  # kedaluwarsa -> refresh dulu
    with pytest.raises(NoCloudData) as excinfo:
        await c.fetch_cloud(sesi)
    sesi_baru = excinfo.value.session
    assert sesi_baru is not None
    assert sesi_baru["akses"] == "access-TOKEN-baru"
    assert sesi_baru["segar"] == "refresh-TOKEN-baru"


async def test_upload_cloud_tanpa_id_papan(client):
    with pytest.raises(CloudError):
        await client.upload_cloud(_session(), P_DATA_CONTOH, 8, "")
