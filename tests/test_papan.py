"""Tes Fase 3 — papan peringkat (bot/core/papan.py + cloud.fetch_papan).

Baris daftar: [nama, pembeli, kode, bintang, level, omzet, jempol,
jempol_saya] (papan_peringkat.gd:94). Kode = md5(id_papan)[:12].
"""

from __future__ import annotations

import hashlib

import httpx
import pytest

from bot.core import papan as papan_mod
from bot.core.cloud import CloudError, SupabaseClient


def _daftar():
    return [
        ["A", 500, "kode_a", 5, 10, 9000000, 3, 0],
        ["B", 400, "kode_b", 4, 8, 7000000, 2, 0],
        ["C", 300, "kode_c", 3, 5, 5000000, 1, 0],
    ]


def test_kode_papan_md5_12():
    assert papan_mod.kode_papan("abc") == hashlib.md5(b"abc").hexdigest()[:12]
    assert len(papan_mod.kode_papan("x")) == 12


def test_minggu_wib_senin():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    # Rabu 2026-11-25 -> Senin 2026-11-23.
    saat = datetime(2026, 11, 25, 10, 0, tzinfo=ZoneInfo("Asia/Jakarta"))
    assert papan_mod.minggu_wib(saat) == "2026-11-23"


def test_parse_papan_ditemukan():
    hasil = papan_mod.parse_papan({"daftar": _daftar(), "jumlah_warung": 500},
                                  "kode_b", 400)
    assert hasil["ditemukan"] is True
    assert hasil["peringkat"] == 2
    assert hasil["kamu"]["nama"] == "B"
    assert hasil["atas"]["nama"] == "A"
    assert hasil["bawah"]["nama"] == "C"
    assert hasil["jumlah_warung"] == 500


def test_parse_papan_tidak_ditemukan_posisi_sisipan():
    # 350 pembeli: di antara B (400) dan C (300) -> peringkat 3.
    hasil = papan_mod.parse_papan({"daftar": _daftar()}, "kode_saya", 350)
    assert hasil["ditemukan"] is False
    assert hasil["peringkat"] == 3
    assert hasil["kamu"] is None
    assert hasil["atas"]["nama"] == "B"
    assert hasil["bawah"]["nama"] == "C"


def test_parse_papan_tanpa_pembeli_tidak_menebak():
    hasil = papan_mod.parse_papan({"daftar": _daftar()}, "kode_saya", None)
    assert hasil["peringkat"] is None


def test_parse_papan_daftar_kosong():
    hasil = papan_mod.parse_papan({"daftar": []}, "kode_saya", 10)
    assert hasil["peringkat"] is None
    assert hasil["total_baris"] == 0


def test_bandingkan_peringkat():
    assert papan_mod.bandingkan_peringkat(None, 5) == "baru"
    assert papan_mod.bandingkan_peringkat(10, 5) == "naik"
    assert papan_mod.bandingkan_peringkat(5, 10) == "turun"
    assert papan_mod.bandingkan_peringkat(5, 5) == "tetap"
    assert papan_mod.bandingkan_peringkat(5, None) == "tidak_diketahui"


# -- fetch_papan (mock transport) ---------------------------------------------

def _client(handler):
    return SupabaseClient(
        base_url="https://test.supabase.co",
        api_key="key-test",
        transport=httpx.MockTransport(handler),
    )


async def test_fetch_papan_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/v1/rpc/ambil_papan2"
        assert request.headers["apikey"] == "key-test"
        assert "authorization" not in request.headers  # anonim
        import json

        data = json.loads(request.read())
        assert data["p_jenis"] == "semua"
        assert data["p_hp"] == ""
        return httpx.Response(200, json={"daftar": _daftar(),
                                         "jumlah_warung": 500})

    client = _client(handler)
    data = await client.fetch_papan("semua", "id-x")
    assert data["jumlah_warung"] == 500
    await client.close()


async def test_fetch_papan_http_gagal():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    client = _client(handler)
    with pytest.raises(CloudError):
        await client.fetch_papan("semua", "id-x")
    await client.close()


async def test_fetch_papan_tanpa_daftar_ditolak():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    with pytest.raises(CloudError):
        await client.fetch_papan("semua", "id-x")
    await client.close()


async def test_fetch_papan_adu_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/v1/rpc/ambil_papan_adu_laris"
        return httpx.Response(200, json={"daftar": []})

    client = _client(handler)
    data = await client.fetch_papan_adu("id-x")
    assert data["daftar"] == []
    await client.close()
