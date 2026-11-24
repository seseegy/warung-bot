"""Tes Fase 5 — handler Telegram aksi cepat (bot/tg/cepat.py).

Tidak ada panggilan Supabase live: _ambil_state_aktif di-monkeypatch.
Menguji: alur teks /jual, penolakan (baca saja/tier), /slot, /backup +
rollback 2 langkah (langkah 1 TIDAK membuat pending/upload), format
/rencana dan /statistik.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.core import backup as backup_mod
from bot.tg import cepat as cepat_tg
from bot.tg.confirm import PENDING_KEY


def _fake_context(game_data, store, tugas_data, awaiting=None):
    return SimpleNamespace(
        bot_data={"data": game_data, "store": store, "tugas": tugas_data,
                  "scheduler": None, "application": None},
        user_data={"awaiting": awaiting} if awaiting else {},
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


def _atur_tier_standar(store, akun_json_valid):
    store.save_user(123, akun_json_valid)
    store.set_tier(123, 2)


async def _mock_state(monkeypatch, state):
    async def _ambil(context, chat_id):
        return state, None
    monkeypatch.setattr(cepat_tg, "_ambil_state_aktif", _ambil)


# -- penjaga: baca saja + tier -------------------------------------------------

def test_cek_tulis_baca_saja_memblokir(store, akun_json_valid):
    store.save_user(123, akun_json_valid)
    store.set_baca_saja(123, True)
    ctx = _fake_context(None, store, None)
    assert "baca saja" in (cepat_tg._cek_tulis(ctx, 123) or "")


def test_cek_tulis_tier_pemula_ditolak(store):
    ctx = _fake_context(None, store, None)
    assert "Standar" in (cepat_tg._cek_tulis(ctx, 123) or "")


def test_cek_tulis_tier_standar_lolos(store, akun_json_valid):
    _atur_tier_standar(store, akun_json_valid)
    ctx = _fake_context(None, store, None)
    assert cepat_tg._cek_tulis(ctx, 123) is None


def test_cek_batas_melewati_ditolak(store):
    ctx = _fake_context(None, store, None)
    assert cepat_tg._cek_batas(ctx, 123, 500000, 2000000) is not None
    assert cepat_tg._cek_batas(ctx, 123, 500000, 500700) is None


# -- /jual via teks -------------------------------------------------------------

async def test_on_text_jual_membuat_pending_cepat(
        monkeypatch, rich_slot, game_data, store, tugas_data,
        sample_package, sample_p_data, akun_json_valid):
    _atur_tier_standar(store, akun_json_valid)
    state = _fake_state(copy.deepcopy(rich_slot), sample_package,
                        sample_p_data)
    await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data, awaiting="cepat_jual")
    message = _fake_message("mi goreng 2")
    handled = await cepat_tg.on_text_cepat(_fake_update(message), ctx)
    assert handled is True
    assert "awaiting" not in ctx.user_data
    pending = ctx.user_data.get(PENDING_KEY)
    assert pending is not None
    assert pending["kind"] == "cepat"
    assert pending["slot_akhir"]["stok"]["mi_goreng"] == 18
    assert pending["slot_akhir"]["uang"] == 500000 + 2 * 3500
    teks = message.reply_text.call_args[0][0]
    assert "Jual 2x Mie goreng" in teks
    assert "Terapkan aksi ini" in teks


async def test_on_text_jual_barang_tidak_dikenal(
        monkeypatch, rich_slot, game_data, store, tugas_data,
        sample_package, sample_p_data, akun_json_valid):
    _atur_tier_standar(store, akun_json_valid)
    state = _fake_state(copy.deepcopy(rich_slot), sample_package,
                        sample_p_data)
    await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data, awaiting="cepat_jual")
    message = _fake_message("barang hantu 5")
    await cepat_tg.on_text_cepat(_fake_update(message), ctx)
    assert PENDING_KEY not in ctx.user_data
    assert "tidak ditemukan" in message.reply_text.call_args[0][0]


async def test_on_text_jual_tanpa_jumlah(
        monkeypatch, rich_slot, game_data, store, tugas_data,
        sample_package, sample_p_data, akun_json_valid):
    _atur_tier_standar(store, akun_json_valid)
    state = _fake_state(copy.deepcopy(rich_slot), sample_package,
                        sample_p_data)
    await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data, awaiting="cepat_jual")
    message = _fake_message("mi goreng")
    await cepat_tg.on_text_cepat(_fake_update(message), ctx)
    assert PENDING_KEY not in ctx.user_data
    assert "jumlah harus angka" in message.reply_text.call_args[0][0]


async def test_on_text_bukan_cepat_tidak_ditangani(game_data, store, tugas_data):
    ctx = _fake_context(game_data, store, tugas_data, awaiting="lain")
    message = _fake_message("mi goreng 2")
    assert await cepat_tg.on_text_cepat(_fake_update(message), ctx) is False


# -- /ngopi, /tutup -------------------------------------------------------------

async def test_cmd_ngopi_energi_penuh_ditolak(
        monkeypatch, rich_slot, game_data, store, tugas_data,
        sample_package, sample_p_data, akun_json_valid):
    _atur_tier_standar(store, akun_json_valid)
    state = _fake_state(copy.deepcopy(rich_slot), sample_package,
                        sample_p_data)
    await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data)
    message = _fake_message("/ngopi")
    await cepat_tg.cmd_ngopi(_fake_update(message), ctx)
    assert "masih segar" in message.reply_text.call_args[0][0]
    assert PENDING_KEY not in ctx.user_data


async def test_cmd_tutup_membuat_pending(
        monkeypatch, rich_slot, game_data, store, tugas_data,
        sample_package, sample_p_data, akun_json_valid):
    _atur_tier_standar(store, akun_json_valid)
    state = _fake_state(copy.deepcopy(rich_slot), sample_package,
                        sample_p_data)
    await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data)
    message = _fake_message("/tutup")
    await cepat_tg.cmd_tutup(_fake_update(message), ctx)
    pending = ctx.user_data.get(PENDING_KEY)
    assert pending is not None and pending["kind"] == "cepat"
    assert pending["slot_akhir"]["hari"] == 2
    assert "Tutup hari 1" in message.reply_text.call_args[0][0]


# -- /slot ----------------------------------------------------------------------

async def test_cmd_slot_daftar_enam_slot(
        monkeypatch, sample_slot, game_data, store, tugas_data,
        sample_package, sample_p_data):
    state = _fake_state(sample_slot, sample_package, sample_p_data)
    await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data)
    message = _fake_message("/slot")
    await cepat_tg.cmd_slot(_fake_update(message), ctx)
    teks = message.reply_text.call_args[0][0]
    assert "Slot 1" in teks and "Warung Barokah" in teks
    assert "Slot 6" in teks and "(kosong)" in teks
    markup = message.reply_text.call_args[1]["reply_markup"]
    data_callback = [b.callback_data for r in markup.inline_keyboard
                     for b in r]
    assert "cepat:slot:1" in data_callback
    assert "cepat:slot:0" in data_callback


async def test_callback_pilih_slot_menyimpan_pilihan(
        monkeypatch, sample_slot, game_data, store, tugas_data,
        sample_package, sample_p_data, akun_json_valid):
    store.save_user(123, akun_json_valid)
    state = _fake_state(sample_slot, sample_package, sample_p_data)
    await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data)
    query = _fake_query()
    update = SimpleNamespace(callback_query=query)
    await cepat_tg.on_callback_cepat(update, ctx, query, "cepat:slot:1")
    assert store.get_slot_aktif(123) == 1
    assert "Slot aktif: slot 1" in query.edit_message_text.call_args[0][0]


async def test_callback_slot_kosong_ditolak(
        monkeypatch, sample_slot, game_data, store, tugas_data,
        sample_package, sample_p_data, akun_json_valid):
    store.save_user(123, akun_json_valid)
    state = _fake_state(sample_slot, sample_package, sample_p_data)
    await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data)
    query = _fake_query()
    update = SimpleNamespace(callback_query=query)
    await cepat_tg.on_callback_cepat(update, ctx, query, "cepat:slot:4")
    assert store.get_slot_aktif(123) is None
    assert "kosong" in query.edit_message_text.call_args[0][0]


# -- /backup + rollback 2 langkah ----------------------------------------------

async def test_cmd_backup_daftar_dan_tombol_pulihkan(
        store, game_data, tugas_data, sample_p_data, akun_json_valid):
    store.save_user(123, akun_json_valid)
    backup_mod.arsipkan_harian(store, 123, 8, sample_p_data,
                               tanggal="2026-11-24")
    ctx = _fake_context(game_data, store, tugas_data)
    message = _fake_message("/backup")
    await cepat_tg.cmd_backup(_fake_update(message), ctx)
    teks = message.reply_text.call_args[0][0]
    assert "2026-11-24" in teks
    markup = message.reply_text.call_args[1]["reply_markup"]
    data_callback = [b.callback_data for r in markup.inline_keyboard
                     for b in r]
    assert any(d.startswith("cepat:rollback:") for d in data_callback)


async def test_rollback_langkah1_tidak_membuat_pending(
        store, game_data, tugas_data, sample_p_data, akun_json_valid):
    store.save_user(123, akun_json_valid)
    backup_mod.arsipkan_harian(store, 123, 8, sample_p_data,
                               tanggal="2026-11-24")
    arsip_id = backup_mod.daftar_arsip(store, 123)[0]["id"]
    ctx = _fake_context(game_data, store, tugas_data)
    query = _fake_query()
    update = SimpleNamespace(callback_query=query)
    await cepat_tg.on_callback_cepat(
        update, ctx, query, f"cepat:rollback:{arsip_id}")
    # Langkah 1: hanya layar tinjau — TIDAK ada pending, TIDAK ada upload.
    assert PENDING_KEY not in ctx.user_data
    teks = query.edit_message_text.call_args[0][0]
    assert "Pulihkan arsip 2026-11-24" in teks
    markup = query.edit_message_text.call_args[1]["reply_markup"]
    data_callback = [b.callback_data for r in markup.inline_keyboard
                     for b in r]
    assert f"cepat:rollback_ya:{arsip_id}" in data_callback


async def test_rollback_langkah2_membuat_pending_tanpa_upload(
        monkeypatch, rich_slot, game_data, store, tugas_data,
        sample_package, sample_p_data, akun_json_valid):
    store.save_user(123, akun_json_valid)
    backup_mod.arsipkan_harian(store, 123, 8, sample_p_data,
                               tanggal="2026-11-24")
    arsip_id = backup_mod.daftar_arsip(store, 123)[0]["id"]
    state = _fake_state(copy.deepcopy(rich_slot), sample_package,
                        sample_p_data)
    await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data)
    query = _fake_query()
    update = SimpleNamespace(callback_query=query)
    await cepat_tg.on_callback_cepat(
        update, ctx, query, f"cepat:rollback_ya:{arsip_id}")
    pending = ctx.user_data.get(PENDING_KEY)
    assert pending is not None and pending["kind"] == "rollback"
    assert pending["p_data"] == sample_p_data
    teks = query.edit_message_text.call_args[0][0]
    assert "PERINGATAN" in teks
    markup = query.edit_message_text.call_args[1]["reply_markup"]
    data_callback = [b.callback_data for r in markup.inline_keyboard
                     for b in r]
    assert "konfirm:ya:rollback" in data_callback


async def test_rollback_arsip_rusak_ditolak_di_langkah1(
        store, game_data, tugas_data, akun_json_valid):
    store.save_user(123, akun_json_valid)
    store.save_backup(123, 8, "H4sI_RUSAK!!!")
    arsip_id = backup_mod.daftar_arsip(store, 123)[0]["id"]
    ctx = _fake_context(game_data, store, tugas_data)
    query = _fake_query()
    update = SimpleNamespace(callback_query=query)
    await cepat_tg.on_callback_cepat(
        update, ctx, query, f"cepat:rollback:{arsip_id}")
    assert PENDING_KEY not in ctx.user_data
    assert "tidak bisa dipulihkan" in query.edit_message_text.call_args[0][0]


# -- /rencana, /statistik --------------------------------------------------------

async def test_cmd_rencana_format(
        monkeypatch, rich_slot, game_data, store, tugas_data,
        sample_package, sample_p_data):
    state = _fake_state(copy.deepcopy(rich_slot), sample_package,
                        sample_p_data)
    await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data)
    message = _fake_message("/rencana")
    await cepat_tg.cmd_rencana(_fake_update(message), ctx)
    teks = message.reply_text.call_args[0][0]
    assert "Rencana 7 hari" in teks
    assert "Proyeksi simulasi" in teks
    assert "Uang" in teks


async def test_cmd_statistik_format(
        monkeypatch, rich_slot, game_data, store, tugas_data,
        sample_package, sample_p_data):
    state = _fake_state(copy.deepcopy(rich_slot), sample_package,
                        sample_p_data)
    await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data)
    message = _fake_message("/statistik")
    await cepat_tg.cmd_statistik(_fake_update(message), ctx)
    teks = message.reply_text.call_args[0][0]
    assert "Statistik" in teks
    assert "Belum ada penjualan hari ini" in teks
    assert "Pelanggan tersering" in teks


async def test_callback_menu_cepat(
        monkeypatch, rich_slot, game_data, store, tugas_data,
        sample_package, sample_p_data, akun_json_valid):
    _atur_tier_standar(store, akun_json_valid)
    state = _fake_state(copy.deepcopy(rich_slot), sample_package,
                        sample_p_data)
    await _mock_state(monkeypatch, state)
    ctx = _fake_context(game_data, store, tugas_data)
    query = _fake_query()
    update = SimpleNamespace(callback_query=query)
    await cepat_tg.on_callback_cepat(update, ctx, query, "cepat:cmd:jual")
    assert ctx.user_data.get("awaiting") == "cepat_jual"
    assert "Jual barang" in query.message.reply_text.call_args[0][0]
