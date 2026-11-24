"""Tes Fase 5 — execute_upload kind "cepat" dan "rollback"
(bot/tg/confirm.py).

Mock transport httpx (TANPA panggilan live), pola yang sama seperti
test_confirm_fase2.py: akun_ambil mengembalikan paket contoh v8,
akun_simpan menerima bila p_versi_dasar >= 8.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import httpx

from bot.core import save as save_mod
from bot.tg.confirm import (
    build_pending_cepat,
    build_pending_rollback,
    execute_upload,
)
from bot.core.cloud import SupabaseClient
from bot.tg.status import fetch_latest_state


def _session(**overrides):
    s = {
        "akses": _TOKEN_AKSES,
        "segar": "refresh-TOKEN-valid",
        "habis": int(time.time()) + 3600,
        "user_id": "uuid-1",
        "email": "akunling427@gmail.com",
        "versi": 8,
    }
    s.update(overrides)
    return s


# Token palsu untuk mock transport (BUKAN token asli — hanya untuk tes).
_TOKEN_AKSES = "token-uji-valid-123"


def _ctx_mock(store, tugas_data, sample_p_data):
    diunggah = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        isi = json.loads(request.content.decode() or "{}")
        if path == "/rest/v1/rpc/akun_ambil":
            if request.headers.get("Authorization") != f"Bearer {_TOKEN_AKSES}":
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


async def test_execute_upload_cepat_ok(store, tugas_data, sample_p_data,
                                       game_data):
    ctx, diunggah, _ = _ctx_mock(store, tugas_data, sample_p_data)
    state = await fetch_latest_state(ctx, 123)
    slot_akhir = dict(state["slot"])
    slot_akhir["uang"] = 4507000  # simulasi hasil /jual 2x mi goreng
    pending, teks = build_pending_cepat(state, slot_akhir, "Jual 2x Mie goreng")
    assert "Jual 2x Mie goreng" in teks
    teks_hasil, status = await execute_upload(ctx, 123, pending)
    assert status == "ok", teks_hasil
    assert "Jual 2x Mie goreng" in teks_hasil
    paket = save_mod.decode_package(diunggah["p_data"])
    _, slot_baru = save_mod.best_slot(paket)
    assert int(slot_baru["uang"]) == 4507000
    assert diunggah["p_versi_dasar"] == 8
    assert diunggah["p_paksa"] is False
    # Paket lama dicadangkan sebelum ditimpa.
    assert store.get_latest_backup(123) is not None


async def test_execute_upload_cepat_tolak_bila_cloud_berubah(
        store, tugas_data, sample_p_data):
    ctx, diunggah, _ = _ctx_mock(store, tugas_data, sample_p_data)
    state = await fetch_latest_state(ctx, 123)
    slot_akhir = dict(state["slot"])
    slot_akhir["uang"] = 4507000
    pending, _ = build_pending_cepat(state, slot_akhir, "Jual 2x Mie goreng")
    pending["versi_dasar"] = 1  # basi: cloud sudah v8
    _, status = await execute_upload(ctx, 123, pending)
    assert status == "gagal"
    assert "p_data" not in diunggah  # tidak ada upload


async def test_execute_upload_rollback_ok(store, tugas_data, sample_p_data,
                                          sample_package):
    ctx, diunggah, _ = _ctx_mock(store, tugas_data, sample_p_data)
    state = await fetch_latest_state(ctx, 123)
    pending, teks = build_pending_rollback(
        state, sample_package, "2026-11-24", 8)
    assert "PERINGATAN" in teks
    assert "HILANG" in teks
    teks_hasil, status = await execute_upload(ctx, 123, pending)
    assert status == "ok", teks_hasil
    # Yang diunggah = paket arsip APA ADANYA, dengan versi dasar terbaru.
    assert diunggah["p_data"] == sample_p_data
    assert diunggah["p_versi_dasar"] == 8
    paket = save_mod.decode_package(diunggah["p_data"])
    assert paket["slot"]["1"] == sample_package["slot"]["1"]


async def test_execute_upload_rollback_arsip_rusak_ditolak(
        store, tugas_data, sample_p_data):
    ctx, diunggah, _ = _ctx_mock(store, tugas_data, sample_p_data)
    state = await fetch_latest_state(ctx, 123)
    pending = {
        "kind": "rollback",
        "id_papan": state["ringkasan"]["id_papan"],
        "p_data": "bukan-paket-valid",
        "versi_dasar": int(state["versi"]),
        "nomor_slot": None,
        "tanggal_arsip": "2026-11-24",
        "versi_arsip": 8,
    }
    _, status = await execute_upload(ctx, 123, pending)
    assert status == "gagal"
    assert "p_data" not in diunggah


async def test_build_pending_rollback_teks_memuat_perbandingan(
        store, tugas_data, sample_p_data, sample_package):
    ctx, _, _ = _ctx_mock(store, tugas_data, sample_p_data)
    state = await fetch_latest_state(ctx, 123)
    _, teks = build_pending_rollback(state, sample_package, "2026-11-24", 8)
    assert "2026-11-24" in teks
    assert "Warung Barokah" in teks
    assert "Level 2" in teks
