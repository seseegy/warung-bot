"""/unlimited — tes fungsi murni + alur Telegram + eksekusi upload."""

from __future__ import annotations

import asyncio
import copy
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from bot.core import save as save_mod
from bot.core import unlimited as unlim
from bot.core.cloud import SupabaseClient
from bot.tg import unlimited as unlim_tg
from bot.tg.confirm import PENDING_KEY, build_pending_unlimited, execute_upload

CHAT = 4242


# --- fungsi murni ----------------------------------------------------

def test_validasi_nilai():
    assert unlim.validasi_nilai("pembeli", 99_999_999) == 99_999_999
    with pytest.raises(ValueError):
        unlim.validasi_nilai("pembeli", 0)
    with pytest.raises(ValueError):
        unlim.validasi_nilai("stok", -5)
    with pytest.raises(ValueError):
        unlim.validasi_nilai("uang", unlim.BATAS_NILAI["uang"] + 1)
    with pytest.raises(ValueError):
        unlim.validasi_nilai("barang", 100)  # bukan aksi numerik
    with pytest.raises(ValueError):
        unlim.validasi_nilai("stok", True)


def test_terapkan_stok_semua_fisik(sample_slot, game_data):
    slot = copy.deepcopy(sample_slot)
    slot["barang_terbuka"] = ["mi_goreng", "token_listrik"]
    slot["stok"] = {"mi_goreng": 3}
    unlim.terapkan(slot, game_data, "stok", 99_999_999)
    assert slot["stok"]["mi_goreng"] == 99_999_999
    # Barang fisik terkunci ikut di-set (langsung terpakai saat terbuka).
    assert slot["stok"]["kopi_bubuk"] == 99_999_999
    # token_listrik = layanan, tidak punya stok.
    assert "token_listrik" not in slot["stok"]
    fisik = [i for i, b in game_data.katalog.items()
             if b.get("jenis") == "fisik"]
    assert all(slot["stok"][i] == 99_999_999 for i in fisik)


def test_terapkan_uang_dan_qris(sample_slot, game_data):
    slot = copy.deepcopy(sample_slot)
    unlim.terapkan(slot, game_data, "uang", 99_999_999)
    assert slot["uang"] == 99_999_999
    assert slot["saldo_digital"] == 99_999_999
    with pytest.raises(ValueError):
        unlim.terapkan(slot, game_data, "uang",
                       unlim.BATAS_NILAI["uang"] + 1)


def test_terapkan_barang_dan_upgrade(sample_slot, game_data):
    slot = copy.deepcopy(sample_slot)
    unlim.terapkan(slot, game_data, "barang")
    assert set(slot["barang_terbuka"]) == set(game_data.katalog.keys())
    assert len(slot["barang_terbuka"]) == 37
    unlim.terapkan(slot, game_data, "upgrade")
    assert set(slot["upgrade"]) == set(game_data.upgrade_by_id.keys())
    assert len(slot["upgrade"]) == 12


def test_terapkan_cerita_tamat_cermin_game(sample_slot, game_data):
    slot = copy.deepcopy(sample_slot)
    slot.update({"bab": 1, "misi_status": "aktif", "cerita_tamat": False})
    unlim.terapkan(slot, game_data, "cerita")
    assert slot["bab"] == len(game_data.cerita["bab"]) - 1
    assert slot["misi_status"] == ""
    assert slot["cerita_tamat"] is True


def test_terapkan_level_maksimum(sample_slot, game_data):
    slot = copy.deepcopy(sample_slot)
    slot["tingkat"] = 3
    slot["progres"] = {"pelanggan": 10, "barang": 5, "omzet": 100,
                       "khusus": 1}
    unlim.terapkan(slot, game_data, "level")
    assert slot["tingkat"] == 10
    assert slot["progres"] == {"pelanggan": 0, "barang": 0, "omzet": 0,
                               "khusus": 0}


def test_terapkan_pembeli(sample_slot, game_data):
    slot = copy.deepcopy(sample_slot)
    unlim.terapkan(slot, game_data, "pembeli", 99_999_999)
    assert slot["total_pembeli"] == 99_999_999


def test_terapkan_aksi_tidak_dikenal(sample_slot, game_data):
    with pytest.raises(ValueError):
        unlim.terapkan(copy.deepcopy(sample_slot), game_data, "energi", 100)


def test_pratinjau(sample_slot, game_data):
    teks = unlim.pratinjau(sample_slot, game_data, "pembeli", 99_999_999)
    assert "Total pembeli" in teks and "99.999.999" in teks


# --- alur Telegram + eksekusi ----------------------------------------

def _session():
    return {"akses": "access-TOKEN-valid", "segar": "refresh-TOKEN-valid",
            "habis": int(time.time()) + 3600, "user_id": "uuid-1",
            "email": "a@b.c", "versi": 8}


def _ctx(store, tugas_data, game_data, sample_slot):
    s1 = copy.deepcopy(sample_slot)
    s1.update({"nama_warung": "rosdie", "tingkat": 10, "hari": 181,
               "uang": 4_580_100, "total_pembeli": 1000,
               "id_papan": "papan-1"})
    s2 = copy.deepcopy(sample_slot)
    s2.update({"nama_warung": "rosdie", "tingkat": 0, "hari": 1,
               "uang": 176_600, "total_pembeli": 5,
               "id_papan": "papan-2"})
    slot_map = {"1": save_mod.serialize_slot(s1),
                "2": save_mod.serialize_slot(s2)}
    paket = {"format": 1, "dari": "Android", "dibuat": "2026-11-25 12:55:00",
             "versi_game": "1.2", "slot": slot_map, "slot_terakhir": 2,
             "toko": {"tanpa_iklan": False, "pendukung": False,
                      "kode_pendukung": ""}, "lemari": []}
    p_data = save_mod.encode_package(paket)
    diunggah = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        isi = json.loads(request.content.decode() or "{}")
        if path == "/rest/v1/rpc/akun_ambil":
            if request.headers.get("Authorization") != (
                    "Bearer " + _session()["akses"]):
                return httpx.Response(401, json={"code": "42501"})
            return httpx.Response(200, json={"ok": True, "versi": 8,
                                             "data": p_data})
        if path == "/rest/v1/rpc/akun_simpan":
            diunggah["p_data"] = isi.get("p_data")
            return httpx.Response(200, json={"ok": True, "versi": 9})
        return httpx.Response(404, json={})

    cloud = SupabaseClient(transport=httpx.MockTransport(handler))
    store.save_user(CHAT, _session())
    ctx = SimpleNamespace(
        bot_data={"store": store, "cloud": cloud, "tugas": tugas_data,
                  "data": game_data},
        user_data={})
    return ctx, diunggah


class _Query:
    def __init__(self, data):
        self.data = data
        self.message = SimpleNamespace(chat_id=CHAT)
        self.edited = []

    async def answer(self, *a, **k):
        return None

    async def edit_message_text(self, teks, reply_markup=None):
        self.edited.append((teks, reply_markup))


def _update_cb(data):
    return SimpleNamespace(callback_query=_Query(data))


def test_callback_pembeli_preset_buat_pending(store, tugas_data, game_data,
                                               sample_slot):
    ctx, _ = _ctx(store, tugas_data, game_data, sample_slot)
    store.set_slot_aktif(CHAT, 2)
    upd = _update_cb("unlimited:nilai:pembeli:99999999")
    assert asyncio.run(unlim_tg.on_callback_unlimited(upd, ctx)) is True
    pending = ctx.user_data[PENDING_KEY]
    assert pending["kind"] == "unlimited"
    assert pending["aksi"] == "pembeli"
    assert pending["nilai"] == 99_999_999
    assert pending["nomor_slot"] == 2
    teks, _ = upd.callback_query.edited[-1]
    assert "Slot 2" in teks and "papan peringkat" in teks


def test_callback_barang_langsung_pending(store, tugas_data, game_data,
                                          sample_slot):
    ctx, _ = _ctx(store, tugas_data, game_data, sample_slot)
    upd = _update_cb("unlimited:barang")
    assert asyncio.run(unlim_tg.on_callback_unlimited(upd, ctx)) is True
    pending = ctx.user_data[PENDING_KEY]
    assert pending["aksi"] == "barang" and pending["nilai"] is None


def test_callback_numerik_tampilkan_pilihan(store, tugas_data, game_data,
                                            sample_slot):
    ctx, _ = _ctx(store, tugas_data, game_data, sample_slot)
    upd = _update_cb("unlimited:stok")
    asyncio.run(unlim_tg.on_callback_unlimited(upd, ctx))
    teks, markup = upd.callback_query.edited[-1]
    assert "99.999.999" in str(markup)
    assert PENDING_KEY not in ctx.user_data


def test_custom_input_valid_dan_tidak_valid(store, tugas_data, game_data,
                                            sample_slot):
    ctx, _ = _ctx(store, tugas_data, game_data, sample_slot)
    upd = _update_cb("unlimited:custom:pembeli")
    asyncio.run(unlim_tg.on_callback_unlimited(upd, ctx))
    assert ctx.user_data["awaiting"] == "unlimited_input"

    balasan = []

    class _Msg:
        chat_id = CHAT
        text = "5jt"

        async def reply_text(self, teks, reply_markup=None):
            balasan.append(teks)

    upd2 = SimpleNamespace(message=_Msg())
    asyncio.run(unlim_tg.on_text_unlimited(upd2, ctx))
    assert ctx.user_data[PENDING_KEY]["nilai"] == 5_000_000

    ctx.user_data.clear()
    ctx.user_data.update({"awaiting": "unlimited_input",
                          "unlimited_aksi": "pembeli"})
    _Msg.text = "abc"
    asyncio.run(unlim_tg.on_text_unlimited(upd2, ctx))
    assert PENDING_KEY not in ctx.user_data
    assert "tidak terbaca" in balasan[-1]


def test_baca_saja_memblokir(store, tugas_data, game_data, sample_slot):
    ctx, _ = _ctx(store, tugas_data, game_data, sample_slot)
    store.set_baca_saja(CHAT, True)
    upd = _update_cb("unlimited:barang")
    asyncio.run(unlim_tg.on_callback_unlimited(upd, ctx))
    assert PENDING_KEY not in ctx.user_data
    assert "baca saja" in upd.callback_query.edited[-1][0]


def test_eksekusi_pembeli_hanya_slot_terpilih(store, tugas_data, game_data,
                                              sample_slot):
    ctx, diunggah = _ctx(store, tugas_data, game_data, sample_slot)
    store.set_slot_aktif(CHAT, 2)
    upd = _update_cb("unlimited:nilai:pembeli:99999999")
    asyncio.run(unlim_tg.on_callback_unlimited(upd, ctx))
    pending = ctx.user_data[PENDING_KEY]
    teks, status = asyncio.run(execute_upload(ctx, CHAT, pending))
    assert status == "ok"
    paket = save_mod.decode_package(diunggah["p_data"])
    slot1 = save_mod.parse_slot(paket["slot"]["1"])
    slot2 = save_mod.parse_slot(paket["slot"]["2"])
    assert slot2["total_pembeli"] == 99_999_999
    assert slot1["total_pembeli"] == 1000  # slot lain tidak tersentuh


def test_build_pending_unlimited_bawa_nomor_slot(game_data, sample_slot):
    state = {"slot": sample_slot, "versi": 8, "nomor_slot": 2,
             "ringkasan": {"id_papan": "papan-2"}}
    pending, teks = build_pending_unlimited(state, game_data, "level")
    assert pending["nomor_slot"] == 2
    assert "Slot 2" in teks and "Level 11" in teks


def test_ambil_state_paket_rusak_tidak_meledak(store, tugas_data, game_data,
                                               sample_slot):
    """Semua slot rusak -> pesan error, bukan exception lolos."""
    paket = {"format": 1, "slot": {"1": "{rusak"}, "slot_terakhir": 1}
    p_data = save_mod.encode_package(paket)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "versi": 8,
                                         "data": p_data})

    cloud = SupabaseClient(transport=httpx.MockTransport(handler))
    store.save_user(CHAT, _session())
    ctx = SimpleNamespace(
        bot_data={"store": store, "cloud": cloud, "tugas": tugas_data,
                  "data": game_data},
        user_data={})
    state, error = asyncio.run(unlim_tg._ambil_state(ctx, CHAT))
    assert state is None and error and "Gagal mengambil" in error


def test_menu_membersihkan_awaiting_custom(store, tugas_data, game_data,
                                           sample_slot):
    ctx, _ = _ctx(store, tugas_data, game_data, sample_slot)
    ctx.user_data.update({"awaiting": "unlimited_input",
                          "unlimited_aksi": "stok"})
    upd = _update_cb("unlimited:menu")
    asyncio.run(unlim_tg.on_callback_unlimited(upd, ctx))
    assert "awaiting" not in ctx.user_data
    assert "unlimited_aksi" not in ctx.user_data
    assert "Unlimited" in upd.callback_query.edited[-1][0]


def test_eksekusi_nilai_hilang_gagal_aman(store, tugas_data, game_data,
                                          sample_slot):
    """Pending numerik tanpa nilai -> status gagal, tidak upload."""
    ctx, diunggah = _ctx(store, tugas_data, game_data, sample_slot)
    pending = {"kind": "unlimited", "aksi": "pembeli", "nilai": None,
               "id_papan": "papan-1", "p_data": None, "versi_dasar": None,
               "nomor_slot": 1}
    teks, status = asyncio.run(execute_upload(ctx, CHAT, pending))
    assert status == "gagal" and "p_data" not in diunggah
