"""Tes Fase 2 — terapkan simulasi / harga terbaik ke cloud
(bot/tg/confirm.py: execute_upload kind "simulasi"/"harga").

Mock transport httpx (TANPA panggilan live). Menguji:
- simulasi diterapkan + diunggah, isi paket hasil edit benar
- harga diterapkan ke harga_jual_khusus slot
- versi cloud berubah sejak simulasi -> DITOLAK (tidak menimpa progres HP)
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import httpx
import pytest

from bot.core import save as save_mod
from bot.core import sim as sim_mod
from bot.core.cloud import SupabaseClient
from bot.tg.confirm import (
    build_pending_harga,
    build_pending_simulasi,
    execute_upload,
)


def _session(**overrides):
    s = {
        "akses": "access-TOKEN-valid",
        "segar": "refresh-TOKEN-valid",
        "habis": int(time.time()) + 3600,
        "user_id": "uuid-1",
        "email": "akunling427@gmail.com",
        "versi": 8,
    }
    s.update(overrides)
    return s


@pytest.fixture()
def ctx_mock(store, tugas_data, sample_p_data):
    """Context palsu: store berisi sesi valid, cloud mock yang
    mengembalikan paket contoh (versi 8) dan menerima upload."""
    diunggah = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        isi = json.loads(request.content.decode() or "{}")
        if path == "/rest/v1/rpc/akun_ambil":
            if request.headers.get("Authorization") != "Bearer access-TOKEN-valid":
                return httpx.Response(401, json={"code": "42501"})
            return httpx.Response(
                200, json={"ok": True, "versi": 8, "data": sample_p_data})
        if path == "/rest/v1/rpc/akun_simpan":
            diunggah["p_data"] = isi.get("p_data")
            diunggah["p_versi_dasar"] = isi.get("p_versi_dasar")
            diunggah["p_paksa"] = isi.get("p_paksa")
            if isi.get("p_paksa"):
                return httpx.Response(200, json={"ok": True, "versi": 9})
            if int(isi.get("p_versi_dasar", 0)) < 8:
                return httpx.Response(200, json={"ok": False, "alasan": "bentrok"})
            return httpx.Response(200, json={"ok": True, "versi": 9})
        return httpx.Response(404, json={})

    cloud = SupabaseClient(transport=httpx.MockTransport(handler))
    store.save_user(123, _session())
    ctx = SimpleNamespace(
        bot_data={"store": store, "cloud": cloud, "tugas": tugas_data})
    return ctx, diunggah, cloud


async def test_terapkan_simulasi_ok(ctx_mock, sample_slot, game_data, tugas_data):
    ctx, diunggah, cloud = ctx_mock
    # State seperti yang dilihat pengguna saat simulasi dibuat.
    from bot.tg.status import fetch_latest_state

    state = await fetch_latest_state(ctx, 123)
    hasil = sim_mod.simulate(state["slot"], game_data, 1, seed=4)
    pending, teks = build_pending_simulasi(state, hasil)
    assert "Proyeksi" in teks or "PROYEKSI" in teks
    teks_hasil, status = await execute_upload(ctx, 123, pending)
    assert status == "ok", teks_hasil
    assert "diterapkan dan diunggah" in teks_hasil
    # Isi paket yang diunggah = slot akhir simulasi.
    paket = save_mod.decode_package(diunggah["p_data"])
    _, slot_baru = save_mod.best_slot(paket)
    assert int(slot_baru["uang"]) == int(hasil["uang_akhir"])
    assert int(slot_baru["hari"]) == int(hasil["hari_akhir"])
    assert diunggah["p_versi_dasar"] == 8
    # Sesi diperbarui ke versi baru.
    assert ctx.bot_data["store"].get_user(123)["versi"] == 9
    await cloud.close()


async def test_terapkan_simulasi_ditolak_bila_cloud_berubah(
        ctx_mock, sample_slot, game_data):
    ctx, diunggah, cloud = ctx_mock
    from bot.tg.status import fetch_latest_state

    state = await fetch_latest_state(ctx, 123)
    hasil = sim_mod.simulate(state["slot"], game_data, 1, seed=4)
    pending, _ = build_pending_simulasi(state, hasil)
    pending["versi_dasar"] = 7  # cloud sudah v8 saat simulasi dibuat
    teks_hasil, status = await execute_upload(ctx, 123, pending)
    assert status == "gagal"
    assert "berubah sejak simulasi" in teks_hasil
    assert "p_data" not in diunggah  # tidak ada upload sama sekali
    await cloud.close()


async def test_terapkan_harga_ok(ctx_mock, game_data):
    ctx, diunggah, cloud = ctx_mock
    from bot.tg.status import fetch_latest_state

    state = await fetch_latest_state(ctx, 123)
    hasil = [{"id": "mi_goreng", "nama": "Mie goreng", "harga_sekarang": 3500,
              "harga_terbaik": 3000, "laba_sekarang": 1000, "laba_terbaik": 1200}]
    pending, teks = build_pending_harga(state, {"mi_goreng": 3000}, hasil)
    assert "Mie goreng" in teks
    teks_hasil, status = await execute_upload(ctx, 123, pending)
    assert status == "ok", teks_hasil
    paket = save_mod.decode_package(diunggah["p_data"])
    _, slot_baru = save_mod.best_slot(paket)
    assert int(slot_baru["harga_jual_khusus"]["mi_goreng"]) == 3000
    await cloud.close()


async def test_terapkan_harga_ditolak_bila_cloud_berubah(ctx_mock):
    ctx, diunggah, cloud = ctx_mock
    from bot.tg.status import fetch_latest_state

    state = await fetch_latest_state(ctx, 123)
    pending, _ = build_pending_harga(state, {"mi_goreng": 3000},
                                     [{"id": "mi_goreng", "nama": "Mie goreng",
                                       "harga_sekarang": 3500,
                                       "harga_terbaik": 3000,
                                       "laba_sekarang": 0, "laba_terbaik": 0}])
    pending["versi_dasar"] = 7
    teks_hasil, status = await execute_upload(ctx, 123, pending)
    assert status == "gagal"
    assert "berubah sejak harga dihitung" in teks_hasil
    assert "p_data" not in diunggah
    await cloud.close()
