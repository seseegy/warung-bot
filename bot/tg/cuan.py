"""Handler /cuan — mode cuan (beli stok murah, jual mahal, pelanggan ramai).

Pola sama dengan aksi cepat Fase 5: ambil state aktif -> terapkan
perubahan MURNI -> konfirmasi sebelum upload (pending "cepat").
"""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from ..core import cuan as cuan_mod
from ..core import save as save_mod
from ..core.cloud import CloudError, NoCloudData, SessionExpired
from . import keyboards as kb
from .cepat import (
    _allowed,
    _ambil_state_aktif,
    _audit,
    _cek_tulis,
)
from .confirm import PENDING_KEY, build_pending_cepat
from .status import format_rupiah

log = logging.getLogger(__name__)


async def cmd_cuan(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/cuan — aktifkan mode cuan: beli stok murah sampai penuh, jual mahal."""
    message = update.message
    if message is None or not _allowed(context, message.chat_id):
        return
    err = _cek_tulis(context, message.chat_id)
    if err:
        await message.reply_text(err, reply_markup=kb.main_menu())
        return
    state, err_state = await _ambil_state_aktif(context, message.chat_id)
    if err_state:
        await message.reply_text(err_state, reply_markup=kb.main_menu())
        return
    data = context.bot_data["data"]
    hasil = cuan_mod.aktifkan_cuan(state["slot"], data)
    ringkasan = cuan_mod.ringkasan_cuan(hasil)
    pending, teks = build_pending_cepat(state, hasil["slot"], ringkasan)
    _audit(pending, "cuan", ringkasan.replace("\n", " "))
    context.user_data[PENDING_KEY] = pending
    await message.reply_text(
        teks, reply_markup=kb.confirm_keyboard("cepat"))


async def cmd_cuan_mati(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/cuan_mati — nonaktifkan mode cuan (kembali ke perilaku default)."""
    message = update.message
    if message is None or not _allowed(context, message.chat_id):
        return
    err = _cek_tulis(context, message.chat_id)
    if err:
        await message.reply_text(err, reply_markup=kb.main_menu())
        return
    state, err_state = await _ambil_state_aktif(context, message.chat_id)
    if err_state:
        await message.reply_text(err_state, reply_markup=kb.main_menu())
        return
    if not state["slot"].get("mode_cuan"):
        await message.reply_text(
            "Mode cuan belum aktif.", reply_markup=kb.main_menu())
        return
    slot_baru = cuan_mod.matikan_cuan(state["slot"])
    ringkasan = "Mode Cuan DIMATIKAN — kembali ke harga & keramaian normal."
    pending, teks = build_pending_cepat(state, slot_baru, ringkasan)
    _audit(pending, "cuan_mati", ringkasan)
    context.user_data[PENDING_KEY] = pending
    await message.reply_text(
        teks, reply_markup=kb.confirm_keyboard("cepat"))


def _teks_menu_cuan(slot: dict) -> str:
    aktif = bool(slot.get("mode_cuan"))
    return (
        "Mode Cuan — aturan ekonomi lokal diubah agar untung maksimal:\n"
        "- beli stok 80% lebih murah\n"
        "- jual harga maksimal (pelanggan tidak kabur karena mahal)\n"
        "- pelanggan 90% lebih ramai\n"
        "- stok tak terbatas (tidak habis)\n"
        "- batas harian diabaikan\n\n"
        f"Status: {'AKTIF' if aktif else 'MATI'}"
    )


async def on_callback_cuan(update, context, query, data_str: str) -> None:
    """Callback 'cuan:*' (dirutekan dari handlers.on_callback)."""
    from .cepat import _UpdateTiruan
    from .handlers import _edit

    chat_id = query.message.chat_id if query.message else 0
    aksi = data_str.split(":", 1)[1] if ":" in data_str else "menu"
    if aksi == "menu":
        state, err = await _ambil_state_aktif(context, chat_id)
        if err:
            await _edit(query, err, kb.main_menu())
            return
        aktif = bool(state["slot"].get("mode_cuan"))
        baris = [[InlineKeyboardButton(
            "Matikan Cuan" if aktif else "Aktifkan Cuan",
            callback_data="cuan:mati" if aktif else "cuan:aktif")]]
        baris.append([InlineKeyboardButton("Kembali ke Menu",
                                           callback_data="menu:root")])
        await _edit(query, _teks_menu_cuan(state["slot"]),
                    InlineKeyboardMarkup(baris))
        return
    if aksi == "aktif":
        await cmd_cuan(_UpdateTiruan(query.message), context)
        return
    if aksi == "mati":
        await cmd_cuan_mati(_UpdateTiruan(query.message), context)
        return
    await _edit(query, "Tombol tidak dikenal.", kb.main_menu())
