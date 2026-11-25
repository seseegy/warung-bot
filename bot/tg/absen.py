"""Handler /absen — absen harian game (fitur logika lokal).

- /absen — lihat status absen (nominal, posisi siklus, bonus 3/7/30).
- /absen_set <nominal> — atur hadiah harian (0 = mati).
- /absen_reset — kembalikan siklus ke hari ke-1.
"""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from ..core import absen as absen_mod
from . import keyboards as kb
from .status import format_rupiah

log = logging.getLogger(__name__)


def _status_teks(store, chat_id: int) -> str:
    data = store.get_absen(chat_id)
    nominal = data["nominal"]
    hari = data["hari_ke"]
    if nominal <= 0:
        return ("Absen harian MATI.\n"
                "Nyalakan dengan /absen_set <nominal>, contoh:\n"
                "/absen_set 100000\n"
                "Bonus otomatis: hari ke-3 = 2x, ke-7 = 3x, ke-30 = 10x.\n"
                "Siklus berulang tiap 30 hari game.")
    baris = [
        f"Absen harian AKTIF: {format_rupiah(nominal)} per hari game.",
        f"Posisi siklus: hari ke-{absen_mod.berikutnya(hari)} "
        f"(siklus 1-30, berulang).",
        "Bonus otomatis: hari ke-3 = 2x, ke-7 = 3x, ke-30 = 10x.",
        "Uang masuk otomatis setiap siklus harian game diterapkan "
        "(otomatis/Target/Kejar).",
        "Matikan dengan /absen_set 0 · Reset siklus dengan /absen_reset.",
    ]
    return "\n".join(baris)


async def cmd_absen(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/absen — lihat status absen harian."""
    message = update.message
    if message is None:
        return
    store = context.bot_data["store"]
    await message.reply_text(
        _status_teks(store, message.chat_id), reply_markup=kb.main_menu())


async def cmd_absen_set(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/absen_set <nominal> — atur hadiah absen (0 = mati)."""
    message = update.message
    if message is None:
        return
    store = context.bot_data["store"]
    args = (context.args or []) if hasattr(context, "args") else []
    if not args:
        await message.reply_text(
            "Ketik: /absen_set <nominal>\n"
            "Contoh: /absen_set 100000\n"
            "Set 0 untuk mematikan absen.",
            reply_markup=kb.main_menu())
        return
    try:
        nominal = int(str(args[0]).replace(".", "").replace(",", "")
                      .replace("rp", "").strip())
    except ValueError:
        await message.reply_text(
            "Nominal harus angka. Contoh: /absen_set 100000",
            reply_markup=kb.main_menu())
        return
    if nominal < 0:
        await message.reply_text(
            "Nominal tidak boleh negatif.", reply_markup=kb.main_menu())
        return
    store.set_absen_nominal(message.chat_id, nominal)
    if nominal == 0:
        await message.reply_text(
            "Absen harian DIMATIKAN.", reply_markup=kb.main_menu())
    else:
        await message.reply_text(
            f"Absen harian diatur: {format_rupiah(nominal)} per hari game.\n"
            "Bonus otomatis: hari ke-3 = 2x, ke-7 = 3x, ke-30 = 10x.\n"
            + _status_teks(store, message.chat_id),
            reply_markup=kb.main_menu())


async def cmd_absen_reset(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/absen_reset — kembalikan siklus absen ke hari ke-1."""
    message = update.message
    if message is None:
        return
    store = context.bot_data["store"]
    store.set_absen_hari_ke(message.chat_id, 0)
    await message.reply_text(
        "Siklus absen dikembalikan ke hari ke-1.",
        reply_markup=kb.main_menu())


NOMINAL_PRESET = [50_000, 100_000, 250_000, 500_000, 1_000_000]


def _keyboard_absen(aktif: bool) -> InlineKeyboardMarkup:
    baris = []
    for i in range(0, len(NOMINAL_PRESET), 2):
        baris.append([
            InlineKeyboardButton("Set " + format_rupiah(n),
                                 callback_data=f"absen:set:{n}")
            for n in NOMINAL_PRESET[i:i + 2]
        ])
    kaki = []
    if aktif:
        kaki.append(InlineKeyboardButton("Matikan Absen",
                                         callback_data="absen:set:0"))
    kaki.append(InlineKeyboardButton("Reset Siklus",
                                     callback_data="absen:reset"))
    baris.append(kaki)
    baris.append([InlineKeyboardButton("Kembali ke Menu",
                                      callback_data="menu:root")])
    return InlineKeyboardMarkup(baris)


async def on_callback_absen(update, context, query, data_str: str) -> None:
    """Callback 'absen:*' (dirutekan dari handlers.on_callback)."""
    from .handlers import _edit

    chat_id = query.message.chat_id if query.message else 0
    store = context.bot_data["store"]
    bagian = data_str.split(":")
    aksi = bagian[1] if len(bagian) >= 2 else "menu"

    if aksi == "menu":
        status = store.get_absen(chat_id)
        await _edit(query, _status_teks(store, chat_id),
                    _keyboard_absen(status["nominal"] > 0))
        return
    if aksi == "set" and len(bagian) >= 3:
        try:
            nominal = int(bagian[2])
        except ValueError:
            nominal = -1
        if nominal < 0:
            await _edit(query, "Nominal tidak valid.", _keyboard_absen(True))
            return
        store.set_absen_nominal(chat_id, nominal)
        await _edit(query, _status_teks(store, chat_id),
                    _keyboard_absen(nominal > 0))
        return
    if aksi == "reset":
        store.set_absen_hari_ke(chat_id, 0)
        status = store.get_absen(chat_id)
        await _edit(query, "Siklus absen dikembalikan ke hari ke-1.\n\n"
                    + _status_teks(store, chat_id),
                    _keyboard_absen(status["nominal"] > 0))
        return
    await _edit(query, "Tombol tidak dikenal.", kb.main_menu())
