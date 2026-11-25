"""Handler /cuan — mode cuan (beli stok murah, jual mahal, pelanggan ramai).

Pola sama dengan aksi cepat Fase 5: ambil state aktif -> terapkan
perubahan MURNI -> konfirmasi sebelum upload (pending "cepat").
"""

from __future__ import annotations

import logging

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
