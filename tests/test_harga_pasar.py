"""Tes fitur /harga_pasar — terapkan harga mengikuti pasaran, manual.

Tidak ada panggilan Supabase live, kecuali satu tes execute_upload yang
memakai MockTransport httpx (pola tests/test_confirm_fase2.py).
Menguji: penolakan tier, agen belum aktif, tanpa entri pasaran, semua
harga sudah sama, pratinjau lama -> baru + pending kind "harga",
callback Senin (sim:harga_pasar) menuju pratinjau, tombol notifikasi
Senin, dan upload hasil pasaran (teks "Harga pasar diterapkan").
"""

from __future__ import annotations

import copy
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from bot.core import auto as auto_mod
from bot.core import jobs as jobs_mod
from bot.core import save as save_mod
from bot.core.cloud import SupabaseClient
from bot.tg import sim as sim_tg
from bot.tg import status as status_mod
from bot.tg.confirm import (
    PENDING_KEY,
    build_pending_harga_pasar,
    execute_upload,
)


def _fake_context(game_data, store, tugas_data=None):
    return SimpleNamespace(
        bot_data={"data": game_data, "store": store, "tugas": tugas_data,
                  "scheduler": None, "application": None},
        user_data={},
    )


def _fake_message(teks, chat_id=123):
    return SimpleNamespace(chat_id=chat_id, text=teks,
                           reply_text=AsyncMock())


def _fake_update(message):
    return SimpleNamespace(message=message)


def _fake_query(chat_id=123):
    message = SimpleNamespace(chat_id=chat_id, text="",
                              reply_text=AsyncMock(),
                              edit_message_text=AsyncMock())
    return SimpleNamespace(message=message, answer=AsyncMock(),
                           edit_message_text=AsyncMock())


def _fake_state(slot, paket, p_data, versi=8):
    return {
        "versi": versi,
        "p_data": p_data,
        "paket": paket,
        "nomor_slot": 1,
        "slot": slot,
        "ringkasan": {"id_papan": "3a5dd8081fa92f174078ce3ca639fa07",
                      "nama_warung": "Warung Barokah", "level": 2,
                      "hari": 120, "uang": 4500000, "qris": 120000,
                      "disimpan": "2026-11-24 10:39:21"},
        "session": {},
    }


async def _mock_state(monkeypatch, state):
    dipanggil = {"n": 0}

    async def _ambil(context, chat_id):
        dipanggil["n"] += 1
        return state, None

    monkeypatch.setattr(sim_tg, "_ambil_state", _ambil)
    return dipanggil


def _slot_pasar(rich_slot, tingkat=1, pasaran=None, khusus=None):
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = tingkat
    slot["harga_pasaran"] = dict(pasaran or {})
    slot["harga_jual_khusus"] = dict(khusus or {})
    return slot


# -- penolakan ---------------------------------------------------------------

async def test_cmd_harga_pasar_tier_pemula_ditolak(
        monkeypatch, rich_slot, game_data, store, tugas_data,
        sample_package, sample_p_data, akun_json_valid):
    # Tier default Pemula (tidak di-set): ditolak SEBELUM ambil state.
    store.save_user(123, akun_json_valid)
    state = _fake_state(copy.deepcopy(rich_slot), sample_package,
                        sample_p_data)
    dipanggil = await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data)
    message = _fake_message("/harga_pasar")
    await sim_tg.cmd_harga_pasar(_fake_update(message), ctx)
    assert dipanggil["n"] == 0
    assert PENDING_KEY not in ctx.user_data
    assert "Standar" in message.reply_text.call_args[0][0]


async def test_cmd_harga_pasar_agen_belum_aktif(
        monkeypatch, rich_slot, game_data, store, tugas_data,
        sample_package, sample_p_data, akun_json_valid):
    store.save_user(123, akun_json_valid)
    store.set_tier(123, 2)
    slot = _slot_pasar(rich_slot, tingkat=0,
                       pasaran={"mi_goreng": 1.1})
    state = _fake_state(slot, sample_package, sample_p_data)
    await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data)
    message = _fake_message("/harga_pasar")
    await sim_tg.cmd_harga_pasar(_fake_update(message), ctx)
    teks = message.reply_text.call_args[0][0]
    assert "belum aktif" in teks and "Level 2" in teks
    assert PENDING_KEY not in ctx.user_data


# -- tidak ada yang berubah ---------------------------------------------------

async def test_cmd_harga_pasar_tanpa_entri_pasaran(
        monkeypatch, rich_slot, game_data, store, tugas_data,
        sample_package, sample_p_data, akun_json_valid):
    store.save_user(123, akun_json_valid)
    store.set_tier(123, 2)
    slot = _slot_pasar(rich_slot, tingkat=1, pasaran={})
    state = _fake_state(slot, sample_package, sample_p_data)
    await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data)
    message = _fake_message("/harga_pasar")
    await sim_tg.cmd_harga_pasar(_fake_update(message), ctx)
    teks = message.reply_text.call_args[0][0]
    assert "Tidak ada perubahan pasaran minggu ini" in teks
    assert PENDING_KEY not in ctx.user_data


async def test_cmd_harga_pasar_semua_sudah_sama(
        monkeypatch, rich_slot, game_data, store, tugas_data,
        sample_package, sample_p_data, akun_json_valid):
    store.save_user(123, akun_json_valid)
    store.set_tier(123, 2)
    # Harga pasar mi_goreng (faktor 1,1) = Rp3.900; sudah diterapkan.
    slot = _slot_pasar(rich_slot, tingkat=1, pasaran={"mi_goreng": 1.1},
                       khusus={"mi_goreng": 3900})
    state = _fake_state(slot, sample_package, sample_p_data)
    await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data)
    message = _fake_message("/harga_pasar")
    await sim_tg.cmd_harga_pasar(_fake_update(message), ctx)
    teks = message.reply_text.call_args[0][0]
    assert "Semua harga sudah mengikuti harga pasar" in teks
    assert PENDING_KEY not in ctx.user_data


# -- pratinjau + pending ------------------------------------------------------

async def test_cmd_harga_pasar_pratinjau_dan_pending(
        monkeypatch, rich_slot, game_data, store, tugas_data,
        sample_package, sample_p_data, akun_json_valid):
    store.save_user(123, akun_json_valid)
    store.set_tier(123, 2)
    slot = _slot_pasar(rich_slot, tingkat=1,
                       pasaran={"mi_goreng": 1.1, "beras": 0.9})
    state = _fake_state(slot, sample_package, sample_p_data)
    await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data)
    message = _fake_message("/harga_pasar")
    await sim_tg.cmd_harga_pasar(_fake_update(message), ctx)
    teks = message.reply_text.call_args[0][0]
    assert "harga pasar" in teks
    assert "Mie goreng: Rp3.500 → Rp3.900" in teks
    assert "Beras 1 kg: Rp15.000 → Rp13.500" in teks
    assert "6 barang lain sudah mengikuti pasar" in teks
    # Tanpa angka laba (bukan harga terbaik): tidak ada "laba/hari".
    assert "laba/hari" not in teks
    assert "/hari" not in teks
    markup = message.reply_text.call_args[1]["reply_markup"]
    data_callback = [b.callback_data for r in markup.inline_keyboard
                     for b in r]
    assert "konfirm:tanya:harga" in data_callback
    pending = ctx.user_data.get(PENDING_KEY)
    assert pending is not None
    assert pending["kind"] == "harga"
    assert pending.get("sumber") == "pasar"
    assert pending["harga_baru"] == {"mi_goreng": 3900, "beras": 13500}
    assert pending["versi_dasar"] == 8


def test_build_pending_harga_pasar_teks(rich_slot, game_data):
    slot = _slot_pasar(rich_slot, tingkat=1,
                       pasaran={"mi_goreng": 1.1, "beras": 0.9})
    _, perubahan = auto_mod.auto_harga_pasar(slot, game_data)
    berubah = [p for p in perubahan if p.get("ok")]
    state = {"versi": 8,
             "ringkasan": {"id_papan": "3a5dd8081fa92f174078ce3ca639fa07"}}
    harga_baru = {p["id"]: p["baru"] for p in berubah}
    pending, teks = build_pending_harga_pasar(state, harga_baru, berubah)
    assert pending["kind"] == "harga"
    assert pending["harga_baru"] == {"mi_goreng": 3900, "beras": 13500}
    assert "Terapkan harga pasar" in teks
    assert "Mie goreng: Rp3.500 → Rp3.900" in teks
    assert "laba/hari" not in teks


# -- callback Senin -----------------------------------------------------------

async def test_callback_senin_harga_pasar_menuju_pratinjau(
        monkeypatch, rich_slot, game_data, store, tugas_data,
        sample_package, sample_p_data, akun_json_valid):
    store.save_user(123, akun_json_valid)
    store.set_tier(123, 2)
    slot = _slot_pasar(rich_slot, tingkat=1,
                       pasaran={"mi_goreng": 1.1})
    state = _fake_state(slot, sample_package, sample_p_data)
    dipanggil = await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data)
    query = _fake_query()
    update = SimpleNamespace(callback_query=query)
    await sim_tg.on_callback_sim(update, ctx, query, "sim:harga_pasar")
    # State segar diambil (bukan dari konteks pesan).
    assert dipanggil["n"] == 1
    teks = query.edit_message_text.call_args[0][0]
    assert "harga pasar" in teks
    assert "Mie goreng: Rp3.500 → Rp3.900" in teks
    pending = ctx.user_data.get(PENDING_KEY)
    assert pending is not None and pending["kind"] == "harga"


# -- upload hasil pasaran ------------------------------------------------------

@pytest.fixture()
def ctx_mock_cloud(store, tugas_data, sample_p_data):
    """Context palsu: cloud mock mengembalikan paket contoh (v8)."""
    diunggah = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        isi = json.loads(request.content.decode() or "{}")
        if path == "/rest/v1/rpc/akun_ambil":
            return httpx.Response(
                200, json={"ok": True, "versi": 8, "data": sample_p_data})
        if path == "/rest/v1/rpc/akun_simpan":
            diunggah["p_data"] = isi.get("p_data")
            diunggah["p_versi_dasar"] = isi.get("p_versi_dasar")
            return httpx.Response(200, json={"ok": True, "versi": 9})
        return httpx.Response(404, json={})

    cloud = SupabaseClient(transport=httpx.MockTransport(handler))
    store.save_user(123, {
        "akses": "access-TOKEN-valid", "segar": "refresh-TOKEN-valid",
        "habis": int(time.time()) + 3600, "user_id": "uuid-1",
        "email": "akunling427@gmail.com", "versi": 8})
    ctx = SimpleNamespace(
        bot_data={"store": store, "cloud": cloud, "tugas": tugas_data})
    return ctx, diunggah


async def test_execute_upload_harga_pasar(
        ctx_mock_cloud, sample_slot, game_data):
    ctx, diunggah = ctx_mock_cloud
    from bot.tg.status import fetch_latest_state

    state = await fetch_latest_state(ctx, 123)
    slot = dict(state["slot"])
    slot["tingkat"] = 1
    slot["barang_terbuka"] = ["mi_goreng", "beras"]
    slot["harga_jual_khusus"] = {}
    slot["harga_pasaran"] = {"mi_goreng": 1.1}
    _, perubahan = auto_mod.auto_harga_pasar(slot, game_data)
    berubah = [p for p in perubahan if p.get("ok")]
    harga_baru = {p["id"]: p["baru"] for p in berubah}
    pending, _ = build_pending_harga_pasar(state, harga_baru, berubah)
    teks, status = await execute_upload(ctx, 123, pending)
    assert status == "ok"
    assert "Harga pasar diterapkan" in teks
    assert "Harga terbaik" not in teks
    paket = save_mod.decode_package(diunggah["p_data"])
    _, slot_baru = save_mod.best_slot(paket)
    assert slot_baru["harga_jual_khusus"]["mi_goreng"] == 3900


# -- tombol notifikasi Senin ---------------------------------------------------

def _fake_app(store, game_data, tugas_data):
    return SimpleNamespace(
        bot_data={"store": store, "cloud": None, "data": game_data,
                  "tugas": tugas_data},
        bot=SimpleNamespace(send_message=AsyncMock()),
    )


def _fake_state_job(slot, p_data="p_data-contoh", versi=8):
    return {
        "versi": versi, "p_data": p_data, "paket": {"slot": {"1": "{}"}},
        "nomor_slot": 1, "slot": slot,
        "ringkasan": {"id_papan": "3a5dd8081fa92f174078ce3ca639fa07",
                      "nama_warung": "Warung Barokah", "level": 2,
                      "hari": 120, "uang": 4500000, "qris": 120000,
                      "disimpan": "2026-11-24 10:39:21"},
        "session": {},
    }


async def test_notifikasi_senin_tombol_harga_pasar(
        monkeypatch, rich_slot, game_data, tugas_data, store,
        akun_json_valid):
    store.save_user(123, akun_json_valid)
    slot = _slot_pasar(rich_slot, tingkat=1, pasaran={})
    state = _fake_state_job(slot)

    async def _fetch(context, chat_id, nomor_slot=None):
        return copy.deepcopy(state)
    monkeypatch.setattr(status_mod, "fetch_latest_state", _fetch)
    app = _fake_app(store, game_data, tugas_data)
    await jobs_mod.notifikasi_pasar_senin(app)  # snapshot awal
    app.bot.send_message.assert_not_called()
    slot["harga_pasaran"] = {"mi_goreng": 1.15}
    await jobs_mod.notifikasi_pasar_senin(app)
    assert app.bot.send_message.call_count == 1
    markup = app.bot.send_message.call_args[1].get("reply_markup")
    assert markup is not None
    data_callback = [b.callback_data for r in markup.inline_keyboard
                     for b in r]
    assert "sim:harga_pasar" in data_callback


async def test_notifikasi_senin_tanpa_tombol_bila_agen_mati(
        monkeypatch, rich_slot, game_data, tugas_data, store,
        akun_json_valid):
    store.save_user(123, akun_json_valid)
    slot = _slot_pasar(rich_slot, tingkat=0, pasaran={})
    state = _fake_state_job(slot)

    async def _fetch(context, chat_id, nomor_slot=None):
        return copy.deepcopy(state)
    monkeypatch.setattr(status_mod, "fetch_latest_state", _fetch)
    app = _fake_app(store, game_data, tugas_data)
    await jobs_mod.notifikasi_pasar_senin(app)  # snapshot awal
    slot["harga_pasaran"] = {"mi_goreng": 1.15}
    await jobs_mod.notifikasi_pasar_senin(app)
    assert app.bot.send_message.call_count == 1
    assert app.bot.send_message.call_args[1].get("reply_markup") is None
