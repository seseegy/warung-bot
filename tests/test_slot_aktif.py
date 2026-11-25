"""Tes resolusi slot aktif — /slot dihormati semua jalur bot.

Regresi bug 25 Nov 2026: /slot menandai Slot 2 "[dipakai bot]", tapi
kartu status menampilkan Slot 1 karena hanya Aksi Cepat yang membaca
``slot_aktif``; status/simulasi/siklus otomatis jatuh ke slot terbaik.
Perbaikan: ``fetch_latest_state`` adalah SATU titik resolusi slot —
tanpa ``nomor_slot`` eksplisit ia memakai pilihan /slot (lalu slot
terbaik), dan semua pending membawa ``nomor_slot`` asal state-nya.
"""

from __future__ import annotations

import copy
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
    build_pending_tugas,
    build_pending_uang,
    execute_upload,
)
from bot.tg.status import fetch_latest_state


def _session():
    return {
        "akses": "access-TOKEN-valid",
        "segar": "refresh-TOKEN-valid",
        "habis": int(time.time()) + 3600,
        "user_id": "uuid-1",
        "email": "akunling427@gmail.com",
        "versi": 8,
    }


def _paket(sample_slot, slot2_rusak=False):
    """Paket 2 slot seperti kasus sir: Slot 1 Lv11/Hari181 (terbaik),
    Slot 2 Lv1/Hari1 (pilihan pengguna)."""
    s1 = copy.deepcopy(sample_slot)
    s1.update({"nama_warung": "rosdie", "tingkat": 10, "hari": 181,
               "uang": 4_580_100, "id_papan": "papan-slot-1"})
    s2 = copy.deepcopy(sample_slot)
    s2.update({"nama_warung": "rosdie", "tingkat": 0, "hari": 1,
               "uang": 176_600, "id_papan": "papan-slot-2"})
    slot_map = {"1": save_mod.serialize_slot(s1)}
    slot_map["2"] = "{rusak" if slot2_rusak else save_mod.serialize_slot(s2)
    paket = {
        "format": 1, "dari": "Android", "dibuat": "2026-11-25 12:55:00",
        "versi_game": "1.2", "slot": slot_map, "slot_terakhir": 2,
        "toko": {"tanpa_iklan": False, "pendukung": False,
                 "kode_pendukung": ""},
        "lemari": [],
    }
    return paket, slot_map


def _ctx(store, tugas_data, paket):
    p_data = save_mod.encode_package(paket)
    diunggah = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        isi = json.loads(request.content.decode() or "{}")
        if path == "/rest/v1/rpc/akun_ambil":
            if request.headers.get("Authorization") != "Bearer access-TOKEN-valid":
                return httpx.Response(401, json={"code": "42501"})
            return httpx.Response(
                200, json={"ok": True, "versi": 8, "data": p_data})
        if path == "/rest/v1/rpc/akun_simpan":
            diunggah["p_data"] = isi.get("p_data")
            return httpx.Response(200, json={"ok": True, "versi": 9})
        return httpx.Response(404, json={})

    cloud = SupabaseClient(transport=httpx.MockTransport(handler))
    store.save_user(123, _session())
    ctx = SimpleNamespace(
        bot_data={"store": store, "cloud": cloud, "tugas": tugas_data})
    return ctx, diunggah, cloud


# -- resolusi fetch --------------------------------------------------------

async def test_fetch_hormati_slot_aktif(store, tugas_data, sample_slot):
    paket, _ = _paket(sample_slot)
    ctx, _, cloud = _ctx(store, tugas_data, paket)
    store.set_slot_aktif(123, 2)
    state = await fetch_latest_state(ctx, 123)
    assert state["nomor_slot"] == 2
    assert state["ringkasan"]["level"] == 1
    assert state["ringkasan"]["uang"] == 176_600
    assert state["ringkasan"]["id_papan"] == "papan-slot-2"
    # Kemajuan sesi tetap slot terbaik (seperti akun.json game).
    assert state["session"]["kemajuan"]["level"] == 11
    await cloud.close()


async def test_fetch_tanpa_pilihan_pakai_slot_terbaik(
        store, tugas_data, sample_slot):
    paket, _ = _paket(sample_slot)
    ctx, _, cloud = _ctx(store, tugas_data, paket)
    state = await fetch_latest_state(ctx, 123)
    assert state["nomor_slot"] == 1
    assert state["ringkasan"]["level"] == 11
    await cloud.close()


async def test_fetch_slot_aktif_kosong_jatuh_ke_terbaik_dan_dibersihkan(
        store, tugas_data, sample_slot):
    paket, _ = _paket(sample_slot)
    ctx, _, cloud = _ctx(store, tugas_data, paket)
    store.set_slot_aktif(123, 3)  # slot 3 kosong di paket
    state = await fetch_latest_state(ctx, 123)
    assert state["nomor_slot"] == 1
    assert store.get_slot_aktif(123) is None
    await cloud.close()


async def test_fetch_slot_aktif_rusak_jatuh_ke_terbaik_dan_dibersihkan(
        store, tugas_data, sample_slot):
    paket, _ = _paket(sample_slot, slot2_rusak=True)
    ctx, _, cloud = _ctx(store, tugas_data, paket)
    store.set_slot_aktif(123, 2)
    state = await fetch_latest_state(ctx, 123)
    assert state["nomor_slot"] == 1
    assert store.get_slot_aktif(123) is None
    await cloud.close()


async def test_fetch_eksplisit_ketat(store, tugas_data, sample_slot):
    paket, _ = _paket(sample_slot, slot2_rusak=True)
    ctx, _, cloud = _ctx(store, tugas_data, paket)
    with pytest.raises(save_mod.SlotError):
        await fetch_latest_state(ctx, 123, nomor_slot=3)  # kosong
    with pytest.raises(save_mod.SlotError):
        await fetch_latest_state(ctx, 123, nomor_slot=2)  # rusak
    state = await fetch_latest_state(ctx, 123, nomor_slot=1)
    assert state["nomor_slot"] == 1
    await cloud.close()


# -- pending membawa slot asal state ----------------------------------------

async def test_pending_membawa_nomor_slot_asal_state(
        store, tugas_data, sample_slot, game_data):
    paket, _ = _paket(sample_slot)
    ctx, _, cloud = _ctx(store, tugas_data, paket)
    store.set_slot_aktif(123, 2)
    state = await fetch_latest_state(ctx, 123)
    pending_uang, teks_uang = build_pending_uang(state, 999_999)
    assert pending_uang["nomor_slot"] == 2
    assert "Slot 2" in teks_uang
    pending_tugas, teks_tugas = build_pending_tugas(state, tugas_data)
    assert pending_tugas["nomor_slot"] == 2
    assert "Slot 2" in teks_tugas
    hasil = sim_mod.simulate(state["slot"], game_data, 1, seed=4)
    pending_sim, teks_sim = build_pending_simulasi(state, hasil)
    assert pending_sim["nomor_slot"] == 2
    assert "Slot 2" in teks_sim
    pending_harga, teks_harga = build_pending_harga(
        state, {"mi_goreng": 3000},
        [{"id": "mi_goreng", "nama": "Mie goreng", "harga_sekarang": 3500,
          "harga_terbaik": 3000, "laba_sekarang": 1000, "laba_terbaik": 1200}])
    assert pending_harga["nomor_slot"] == 2
    assert "Slot 2" in teks_harga
    await cloud.close()


# -- upload mendarat di slot yang benar -------------------------------------

async def test_upload_simulasi_mendarat_di_slot_aktif_saja(
        store, tugas_data, sample_slot, game_data):
    paket, slot_map_awal = _paket(sample_slot)
    ctx, diunggah, cloud = _ctx(store, tugas_data, paket)
    store.set_slot_aktif(123, 2)
    state = await fetch_latest_state(ctx, 123)
    hasil = sim_mod.simulate(state["slot"], game_data, 1, seed=4)
    pending, _ = build_pending_simulasi(state, hasil)
    teks, status = await execute_upload(ctx, 123, pending)
    assert status == "ok", teks
    paket_baru = save_mod.decode_package(diunggah["p_data"])
    # Slot 1 tidak tersentuh sama sekali; Slot 2 = hasil simulasi.
    assert paket_baru["slot"]["1"] == slot_map_awal["1"]
    slot2 = save_mod.parse_slot(paket_baru["slot"]["2"])
    assert int(slot2["uang"]) == int(hasil["uang_akhir"])
    assert int(slot2["hari"]) == int(hasil["hari_akhir"])
    await cloud.close()


async def test_upload_uang_mendarat_di_slot_aktif_saja(
        store, tugas_data, sample_slot):
    paket, slot_map_awal = _paket(sample_slot)
    ctx, diunggah, cloud = _ctx(store, tugas_data, paket)
    store.set_slot_aktif(123, 2)
    state = await fetch_latest_state(ctx, 123)
    pending, _ = build_pending_uang(state, 999_999)
    teks, status = await execute_upload(ctx, 123, pending)
    assert status == "ok", teks
    paket_baru = save_mod.decode_package(diunggah["p_data"])
    assert paket_baru["slot"]["1"] == slot_map_awal["1"]
    slot2 = save_mod.parse_slot(paket_baru["slot"]["2"])
    assert int(slot2["uang"]) == 999_999
    await cloud.close()


async def test_upload_ditolak_bila_slot_pending_hilang(
        store, tugas_data, sample_slot, game_data):
    """Pending dari Slot 2 tidak boleh mendarat di slot lain bila
    Slot 2 hilang dari cloud sebelum konfirmasi."""
    paket, _ = _paket(sample_slot)
    ctx, diunggah, cloud = _ctx(store, tugas_data, paket)
    store.set_slot_aktif(123, 2)
    state = await fetch_latest_state(ctx, 123)
    hasil = sim_mod.simulate(state["slot"], game_data, 1, seed=4)
    pending, _ = build_pending_simulasi(state, hasil)
    pending["nomor_slot"] = 3  # slot 3 kosong di cloud
    teks, status = await execute_upload(ctx, 123, pending)
    assert status == "gagal"
    assert "slot 3 kosong" in teks
    assert "p_data" not in diunggah
    await cloud.close()
