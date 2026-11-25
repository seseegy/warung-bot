"""Tes Mode Kerja 24/7 — routing callback + alasan berhenti.

Regresi bug 25 Nov 2026: tombol "Kerja 24/7 (terus)" (kerja:mulai)
tidak bereaksi apa-apa. Handler kerja:* ada di ``_tangani_kejar``,
tapi ``on_callback_tier`` tidak pernah meneruskan prefix "kerja:"
ke sana, jadi klik jatuh diam-diam tanpa pesan.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.core import kerja as kerja_mod
from bot.tg import tiers as tiers_tg


def _fake_context(game_data, store):
    return SimpleNamespace(
        bot_data={"data": game_data, "store": store,
                  "scheduler": None, "application": None, "cloud": None},
        application=None,
        user_data={},
    )


def _fake_query(data, chat_id=123):
    return SimpleNamespace(
        data=data,
        message=SimpleNamespace(chat_id=chat_id),
        edit_message_text=AsyncMock(),
        answer=AsyncMock(),
    )


def _link(store, tier=2):
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u", "versi": 1})
    store.set_tier(123, tier)


# -- routing callback --------------------------------------------------------

async def test_kerja_mulai_via_callback(game_data, store):
    _link(store)
    query = _fake_query("kerja:mulai")
    hasil = await tiers_tg.on_callback_tier(
        None, _fake_context(game_data, store), query, "kerja:mulai")
    assert hasil is True
    assert store.get_mode_kerja(123) is not None
    teks = query.edit_message_text.await_args.args[0]
    assert "Mode Kerja 24/7 NYALA" in teks


async def test_kerja_berhenti_via_callback(game_data, store):
    _link(store)
    store.set_mode_kerja(123)
    query = _fake_query("kerja:berhenti")
    hasil = await tiers_tg.on_callback_tier(
        None, _fake_context(game_data, store), query, "kerja:berhenti")
    assert hasil is True
    assert store.get_mode_kerja(123) is None
    teks = query.edit_message_text.await_args.args[0]
    assert "DIMATIKAN" in teks


async def test_kerja_mulai_mematikan_target_kejar_dan_otomatis(
        game_data, store):
    """Satu mode kerja saja: menyalakan Kerja 24/7 mematikan Mode
    Target, Mode Kejar, dan siklus otomatis harian."""
    _link(store)
    store.set_mode_target(123, 5)
    store.set_mode_kejar(123, 50, 20000)
    store.set_otomatis(123, True)
    query = _fake_query("kerja:mulai")
    await tiers_tg.on_callback_tier(
        None, _fake_context(game_data, store), query, "kerja:mulai")
    assert store.get_mode_kerja(123) is not None
    assert store.get_mode_target(123) is None
    assert store.get_mode_kejar(123) is None
    assert store.get_otomatis(123) is False


# -- alasan berhenti (murni) -------------------------------------------------

def test_alasan_berhenti_kerja():
    slot_sehat = {"uang": 100000, "stok": {"beras": 3}, "diusir": False}
    assert kerja_mod.alasan_berhenti(slot_sehat, 10) is None
    assert kerja_mod.alasan_berhenti(
        slot_sehat, kerja_mod.MAKS_SIKLUS) == "maks_siklus"
    assert kerja_mod.alasan_berhenti(
        {**slot_sehat, "diusir": True}, 10) == "diusir"
    assert kerja_mod.alasan_berhenti(
        {"uang": 0, "stok": {}, "diusir": False}, 10) == "macet"
    # Uang habis tapi stok masih ada: masih bisa jualan, lanjut.
    assert kerja_mod.alasan_berhenti(
        {"uang": 0, "stok": {"beras": 1}, "diusir": False}, 10) is None
