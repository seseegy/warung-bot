"""Tes Fase 2 — handler Telegram (bot/tg/sim.py): format pesan + input teks.

Tidak ada panggilan Supabase live: _ambil_state di-monkeypatch.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.core import plan as plan_mod
from bot.core import sim as sim_mod
from bot.tg import sim as sim_tg


def _fake_context(game_data, store=None, awaiting=None):
    ctx = SimpleNamespace(
        bot_data={"data": game_data, "store": store,
                  "scheduler": None, "application": None},
        user_data={"awaiting": awaiting} if awaiting else {},
    )
    return ctx


def _fake_message(teks, chat_id=123):
    return SimpleNamespace(chat_id=chat_id, text=teks,
                           reply_text=AsyncMock())


def _fake_update(message):
    return SimpleNamespace(message=message)


# -- format -------------------------------------------------------------------

def test_format_sim_result_memuat_disclaimer(rich_slot, game_data):
    hasil = sim_mod.simulate(rich_slot, game_data, 1, seed=4)
    teks = sim_tg.format_sim_result(hasil, rich_slot, 1)
    assert "Proyeksi simulasi" in teks
    assert "Omzet" in teks and "Laba" in teks
    assert "Uang" in teks


def test_format_stok_table_rekomendasi_beli(rich_slot, game_data):
    teks = sim_tg.format_stok_table(game_data, rich_slot)
    # mi_goreng stok 20 -> tidak muncul; telur stok 10 -> tidak muncul.
    # Turunkan stok supaya muncul rekomendasi.
    slot = copy.deepcopy(rich_slot)
    slot["stok"]["beras"] = 2
    slot["stok"]["gula"] = 0
    teks = sim_tg.format_stok_table(game_data, slot)
    assert "Beras 1 kg" in teks
    assert "Gula pasir" in teks
    assert "Total biaya" in teks
    assert "Kurir reguler" in teks


def test_format_stok_table_semua_cukup(rich_slot, game_data):
    teks = sim_tg.format_stok_table(game_data, rich_slot)
    assert "tidak ada yang mendesak" in teks


def test_format_kapan_level_terakhir(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 10
    hasil = plan_mod.kapan_naik(slot, game_data)
    teks = sim_tg._format_kapan(hasil, slot)
    assert "level terakhir" in teks


def test_format_kapan_nol_hari(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["progres"] = {"pelanggan": 15, "barang": 25, "omzet": 100000,
                       "khusus": 5}
    hasil = plan_mod.kapan_naik(slot, game_data)
    teks = sim_tg._format_kapan(hasil, slot)
    assert "sudah bisa naik" in teks


def test_format_roi_kosong(rich_slot, game_data):
    assert "belum ada yang bisa dibeli" in sim_tg._format_roi([])


def test_keyboard_sim_tanpa_emoji():
    """Semua label tombol Fase 2 harus ASCII murni (teks polos)."""
    for markup in (sim_tg.sim_menu_keyboard(), sim_tg.sim_apply_keyboard(),
                   sim_tg.harga_apply_keyboard(),
                   sim_tg.jadwal_keyboard(None),
                   sim_tg.jadwal_keyboard({"jam": 7, "aktif": True})):
        for baris in markup.inline_keyboard:
            for tombol in baris:
                assert tombol.text.isascii(), tombol.text
                assert len(tombol.callback_data.encode()) < 64


# -- input teks -----------------------------------------------------------------

async def test_on_text_whatif_valid(rich_slot, game_data, monkeypatch):
    state = {"slot": rich_slot,
             "ringkasan": {"id_papan": "x"},
             "versi": 1}

    async def _ambil(context, chat_id):
        return state, None

    monkeypatch.setattr(sim_tg, "_ambil_state", _ambil)
    message = _fake_message("mi_goreng 3000, teh_botol 4000")
    ctx = _fake_context(game_data, awaiting="whatif_input")
    assert await sim_tg.on_text_whatif(_fake_update(message), ctx) is True
    assert "awaiting" not in ctx.user_data
    message.reply_text.assert_awaited_once()
    teks = message.reply_text.await_args.args[0]
    assert "Mie goreng" in teks
    assert "Proyeksi simulasi" in teks


async def test_on_text_whatif_barang_tidak_dikenal(game_data):
    message = _fake_message("tidak_ada 5000")
    ctx = _fake_context(game_data, awaiting="whatif_input")
    assert await sim_tg.on_text_whatif(_fake_update(message), ctx) is True
    teks = message.reply_text.await_args.args[0]
    assert "tidak dikenal" in teks


async def test_on_text_whatif_bukan_giliran(game_data):
    message = _fake_message("mi_goreng 3000")
    ctx = _fake_context(game_data, awaiting=None)
    assert await sim_tg.on_text_whatif(_fake_update(message), ctx) is False
    message.reply_text.assert_not_awaited()


async def test_on_text_jadwal_valid(store, game_data):
    message = _fake_message("7")
    ctx = _fake_context(game_data, store=store, awaiting="jadwal_jam")
    assert await sim_tg.on_text_jadwal(_fake_update(message), ctx) is True
    assert store.get_jadwal(123)["jam"] == 7
    teks = message.reply_text.await_args.args[0]
    assert "07:00" in teks


async def test_on_text_jadwal_tidak_valid(store, game_data):
    message = _fake_message("25")
    ctx = _fake_context(game_data, store=store, awaiting="jadwal_jam")
    assert await sim_tg.on_text_jadwal(_fake_update(message), ctx) is True
    assert store.get_jadwal(123) is None
    teks = message.reply_text.await_args.args[0]
    assert "0-23" in teks
