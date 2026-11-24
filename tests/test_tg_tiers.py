"""Tes Fase 3 — handler Telegram tier/otomatis/laporan/bandingkan.

Tidak ada panggilan Supabase live: fetch_latest_state di-monkeypatch.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.core import auto as auto_mod
from bot.tg import tiers as tiers_tg


def _fake_context(game_data, store=None):
    return SimpleNamespace(
        bot_data={"data": game_data, "store": store,
                  "scheduler": None, "application": None},
        user_data={},
    )


def _fake_message(teks="", chat_id=123):
    return SimpleNamespace(chat_id=chat_id, text=teks,
                           reply_text=AsyncMock())


def _fake_update(message):
    return SimpleNamespace(message=message)


def _fake_query(data, chat_id=123):
    return SimpleNamespace(
        data=data,
        message=SimpleNamespace(chat_id=chat_id),
        edit_message_text=AsyncMock(),
        answer=AsyncMock(),
    )


def _link(store):
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u", "versi": 1})


# -- /tier -------------------------------------------------------------------

async def test_cmd_tier_tanpa_akun(game_data, store):
    message = _fake_message()
    await tiers_tg.cmd_tier(_fake_update(message), _fake_context(game_data, store))
    assert "Belum ada akun" in message.reply_text.await_args.args[0]


async def test_cmd_tier_menampilkan_tiga_tier(game_data, store):
    _link(store)
    message = _fake_message()
    await tiers_tg.cmd_tier(_fake_update(message), _fake_context(game_data, store))
    teks = message.reply_text.await_args.args[0]
    assert "Pemula" in teks and "Standar" in teks and "Profesional" in teks
    markup = message.reply_text.await_args.kwargs["reply_markup"]
    data = [t.callback_data for baris in markup.inline_keyboard
            for t in baris]
    assert "tier:1" in data and "tier:2" in data and "tier:3" in data
    for baris in markup.inline_keyboard:
        for t in baris:
            assert t.text.isascii(), t.text  # tanpa emoji


async def test_callback_tier_menampilkan_konfirmasi(game_data, store):
    _link(store)
    query = _fake_query("tier:2")
    ctx = _fake_context(game_data, store)
    assert await tiers_tg.on_callback_tier(None, ctx, query, "tier:2") is True
    teks = query.edit_message_text.await_args.args[0]
    assert "Aktifkan Tier 2" in teks
    markup = query.edit_message_text.await_args.kwargs["reply_markup"]
    data = [t.callback_data for baris in markup.inline_keyboard
            for t in baris]
    assert "tier:konfirm:2" in data


async def test_callback_tier_konfirm_mengaktifkan(game_data, store):
    _link(store)
    query = _fake_query("tier:konfirm:2")
    ctx = _fake_context(game_data, store)
    await tiers_tg.on_callback_tier(None, ctx, query, "tier:konfirm:2")
    assert store.get_tier(123) == 2
    assert store.get_otomatis(123) is True
    assert any(e["aksi"] == "tier_aktif" for e in store.get_audit(123, 0))
    teks = query.edit_message_text.await_args.args[0]
    assert "Tier 2" in teks


async def test_callback_tier_tidak_dikenal(game_data, store):
    _link(store)
    query = _fake_query("tier:9")
    ctx = _fake_context(game_data, store)
    assert await tiers_tg.on_callback_tier(None, ctx, query, "tier:9") is True
    assert "tidak dikenal" in query.edit_message_text.await_args.args[0]


# -- /otomatis ---------------------------------------------------------------

async def test_callback_otomatis_mati_dan_nyala(game_data, store):
    _link(store)
    store.set_tier(123, 2)
    store.set_otomatis(123, True)
    ctx = _fake_context(game_data, store)
    query = _fake_query("otomatis:mati")
    await tiers_tg.on_callback_tier(None, ctx, query, "otomatis:mati")
    assert store.get_otomatis(123) is False
    assert any(e["aksi"] == "otomatis_mati" for e in store.get_audit(123, 0))
    query2 = _fake_query("otomatis:nyala")
    await tiers_tg.on_callback_tier(None, ctx, query2, "otomatis:nyala")
    assert store.get_otomatis(123) is True


async def test_cmd_otomatis_menampilkan_status(game_data, store):
    _link(store)
    message = _fake_message()
    await tiers_tg.cmd_otomatis(_fake_update(message),
                                _fake_context(game_data, store))
    teks = message.reply_text.await_args.args[0]
    assert "MATI" in teks
    assert "07.00 WIB" in teks


# -- login callback -----------------------------------------------------------

async def test_callback_login_klaim_mencatat_streak(game_data, store):
    _link(store)
    ctx = _fake_context(game_data, store)
    query = _fake_query("login:klaim:1")
    await tiers_tg.on_callback_tier(None, ctx, query, "login:klaim:1")
    lacak = store.get_login_lacak(123)
    assert lacak["hari_ke"] == 1
    assert lacak["tanggal"] == auto_mod.tanggal_wib()
    assert any(e["aksi"] == "login_klaim" for e in store.get_audit(123, 0))


async def test_callback_login_klaim_kedua_hari_sama_ditolak(game_data, store):
    _link(store)
    hari_ini = auto_mod.tanggal_wib()
    store.set_login_lacak(123, 1, hari_ini)
    ctx = _fake_context(game_data, store)
    query = _fake_query("login:klaim:2")
    await tiers_tg.on_callback_tier(None, ctx, query, "login:klaim:2")
    assert "Sudah dicatat" in query.edit_message_text.await_args.args[0]
    assert store.get_login_lacak(123)["hari_ke"] == 1


async def test_callback_login_lewat(game_data, store):
    _link(store)
    ctx = _fake_context(game_data, store)
    query = _fake_query("login:lewat")
    await tiers_tg.on_callback_tier(None, ctx, query, "login:lewat")
    assert "Dilewati" in query.edit_message_text.await_args.args[0]
    assert store.get_login_lacak(123)["hari_ke"] == 0


# -- /laporan -----------------------------------------------------------------

async def test_cmd_laporan_menampilkan_audit(game_data, store, monkeypatch,
                                            rich_slot):
    _link(store)
    store.log_audit(123, "beli_stok", "Beras x18")
    state = {"slot": rich_slot,
             "ringkasan": {"nama": "Warung Barokah", "level": 1, "hari": 1,
                           "uang": 500000, "id_papan": "x"},
             "versi": 1}

    async def _fetch(context, chat_id):
        return state

    monkeypatch.setattr("bot.tg.tiers.fetch_latest_state", _fetch)
    message = _fake_message()
    await tiers_tg.cmd_laporan(_fake_update(message),
                               _fake_context(game_data, store))
    teks = message.reply_text.await_args.args[0]
    assert "Laporan harian" in teks
    assert "beli_stok" in teks
    assert "Rp500.000" in teks


async def test_cmd_laporan_tanpa_audit(game_data, store, monkeypatch, rich_slot):
    _link(store)
    state = {"slot": rich_slot,
             "ringkasan": {"nama": "Warung Barokah", "level": 1, "hari": 1,
                           "uang": 500000, "id_papan": "x"},
             "versi": 1}

    async def _fetch(context, chat_id):
        return state

    monkeypatch.setattr("bot.tg.tiers.fetch_latest_state", _fetch)
    message = _fake_message()
    await tiers_tg.cmd_laporan(_fake_update(message),
                               _fake_context(game_data, store))
    assert "Tidak ada aksi otomatis" in message.reply_text.await_args.args[0]


# -- /bandingkan --------------------------------------------------------------

async def test_cmd_bandingkan_ditolak_di_tier_pemula(game_data, store):
    _link(store)
    store.set_tier(123, 1)
    message = _fake_message()
    await tiers_tg.cmd_bandingkan(_fake_update(message),
                                  _fake_context(game_data, store))
    teks = message.reply_text.await_args.args[0]
    assert "Profesional" in teks
    assert "Pemula" in teks


async def test_cmd_bandingkan_jalan_di_tier_profesional(
        game_data, store, monkeypatch, rich_slot):
    _link(store)
    store.set_tier(123, 3)
    state = {"slot": copy.deepcopy(rich_slot),
             "ringkasan": {"nama": "W", "level": 1, "hari": 1,
                           "uang": 500000, "id_papan": "x"},
             "versi": 1}

    async def _fetch(context, chat_id):
        return state

    monkeypatch.setattr("bot.tg.tiers.fetch_latest_state", _fetch)
    message = _fake_message()
    await tiers_tg.cmd_bandingkan(_fake_update(message),
                                  _fake_context(game_data, store))
    assert message.reply_text.await_count == 2
    teks = message.reply_text.await_args.args[0]
    assert "Perbandingan strategi harga" in teks
    assert "Harga sekarang" in teks
    assert "Ikut harga pasar" in teks
    assert "Murah 10%" in teks
    assert "Harga terbaik" in teks
    assert "proyeksi" in teks.lower()
