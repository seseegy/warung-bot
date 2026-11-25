"""Handler /unlimited — set nilai save ke angka besar / buka semua.

Alur: /unlimited -> menu 7 aksi -> aksi numerik memilih nilai
(99.999.999 atau custom ketik sendiri) -> konfirmasi -> upload
lewat jalur pending yang sama seperti /uang (``confirm.py``).

Mode baca saja memblokir fitur ini (aksi tulis), sama seperti
Aksi Cepat.
"""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from ..core import save as save_mod
from ..core import unlimited as unlimited_mod
from ..core.cloud import CloudError, NoCloudData, SessionExpired
from . import keyboards as kb
from .confirm import PENDING_KEY, build_pending_unlimited
from .status import NotLinked, diizinkan, fetch_latest_state

log = logging.getLogger(__name__)

PESAN_BACA_SAJA = ("Mode baca saja aktif — aksi tulis dimatikan. "
                   "Matikan dulu di Pengaturan / Mini App.")


def _format(nilai: int) -> str:
    return f"{nilai:,}".replace(",", ".")


def _tolak_baca_saja(context, chat_id: int) -> str | None:
    if context.bot_data["store"].get_baca_saja(chat_id):
        return PESAN_BACA_SAJA
    return None


def _menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Stok Unlimited",
                                 callback_data="unlimited:stok"),
            InlineKeyboardButton("Uang + QRIS",
                                 callback_data="unlimited:uang"),
        ],
        [
            InlineKeyboardButton("Buka Semua Barang",
                                 callback_data="unlimited:barang"),
            InlineKeyboardButton("Semua Upgrade",
                                 callback_data="unlimited:upgrade"),
        ],
        [
            InlineKeyboardButton("Cerita Tamat",
                                 callback_data="unlimited:cerita"),
            InlineKeyboardButton("Level Maksimum",
                                 callback_data="unlimited:level"),
        ],
        [
            InlineKeyboardButton("Total Pembeli",
                                 callback_data="unlimited:pembeli"),
        ],
        [
            InlineKeyboardButton("Kembali ke Menu",
                                 callback_data="menu:root"),
        ],
    ])


def _menu_teks(state: dict, data) -> str:
    slot = state["slot"]
    baris = [
        f"Unlimited — Slot {int(state['nomor_slot'])} "
        f"(simpanan online v{state['versi']})",
        "Pilih yang mau di-set:",
        "",
    ]
    for aksi in unlimited_mod.AKSI_SEMUA:
        baris.append(
            f"- {unlimited_mod.LABEL_AKSI[aksi]}: "
            f"{unlimited_mod.nilai_sekarang(slot, data, aksi)}")
    baris.append("")
    baris.append("Pastikan game sedang tertutup sebelum menerapkan.")
    return "\n".join(baris)


async def _ambil_state(context, chat_id: int):
    """(state, None) atau (None, pesan_error)."""
    try:
        return await fetch_latest_state(context, chat_id), None
    except NotLinked:
        return None, "Belum ada akun tertaut. Tautkan dulu dengan /link."
    except SessionExpired:
        return None, ("Sesi login habis. Kirim ulang akun.json dari "
                      "game dengan /link.")
    except NoCloudData:
        return None, "Akun tertaut, tapi belum ada simpanan di cloud."
    except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
        return None, f"Gagal mengambil simpanan: {exc}"


async def cmd_unlimited(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/unlimited — menu set nilai save ke angka besar / buka semua."""
    message = update.message
    if message is None or not diizinkan(context, message.chat_id):
        return
    tolak = _tolak_baca_saja(context, message.chat_id)
    if tolak:
        await message.reply_text(tolak, reply_markup=kb.main_menu())
        return
    state, error = await _ambil_state(context, message.chat_id)
    if error:
        await message.reply_text(error, reply_markup=kb.main_menu())
        return
    await message.reply_text(
        _menu_teks(state, context.bot_data["data"]),
        reply_markup=_menu_keyboard())


async def _edit(query, teks: str, markup=None) -> None:
    try:
        await query.edit_message_text(teks, reply_markup=markup)
    except Exception as exc:  # noqa: BLE001
        if "not modified" in str(exc).lower():
            return
        log.warning("edit pesan unlimited gagal, kirim pesan baru: %s", exc)
        try:
            await query.message.reply_text(teks, reply_markup=markup)
        except Exception:  # noqa: BLE001
            log.exception("pesan pengganti unlimited juga gagal")


async def _tampilkan_menu(query, context) -> None:
    state, error = await _ambil_state(context, query.message.chat_id)
    if error:
        await _edit(query, error, kb.main_menu())
        return
    await _edit(query, _menu_teks(state, context.bot_data["data"]),
                _menu_keyboard())


async def _buat_pending(query, context, aksi: str,
                        nilai: int | None) -> None:
    state, error = await _ambil_state(context, query.message.chat_id)
    if error:
        await _edit(query, error, kb.main_menu())
        return
    try:
        pending, teks = build_pending_unlimited(
            state, context.bot_data["data"], aksi, nilai)
    except ValueError as exc:
        await _edit(query, f"Tidak bisa: {exc}", _menu_keyboard())
        return
    context.user_data[PENDING_KEY] = pending
    await _edit(query, teks, kb.confirm_keyboard("unlimited", pending.get("token")))


async def on_callback_unlimited(update,
                                context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Tangani callback ``unlimited:...``. True bila ditangani."""
    query = update.callback_query
    if query is None:
        return False
    data_cb = query.data or ""
    if not data_cb.startswith("unlimited:"):
        return False
    # Callback sudah dijawab handlers.on_callback — menjawab lagi
    # ditolak Telegram dan bisa membuat tombol terlihat mati.
    chat_id = query.message.chat_id
    tolak = _tolak_baca_saja(context, chat_id)
    if tolak:
        await _edit(query, tolak, kb.main_menu())
        return True
    bagian = data_cb.split(":")
    if len(bagian) == 2 and bagian[1] == "menu":
        # Keluar dari alur input custom: jangan biarkan awaiting basi
        # menelan teks berikutnya.
        context.user_data.pop("awaiting", None)
        context.user_data.pop("unlimited_aksi", None)
        await _tampilkan_menu(query, context)
        return True
    if len(bagian) == 2 and bagian[1] in unlimited_mod.AKSI_SEMUA:
        aksi = bagian[1]
        if aksi in unlimited_mod.AKSI_NUMERIK:
            state, error = await _ambil_state(context, chat_id)
            if error:
                await _edit(query, error, kb.main_menu())
                return True
            teks = (
                f"{unlimited_mod.LABEL_AKSI[aksi]}\n"
                f"Sekarang: "
                f"{unlimited_mod.nilai_sekarang(state['slot'], context.bot_data['data'], aksi)}\n"
                f"Mau di-set ke berapa? Batas maks "
                f"{_format(unlimited_mod.BATAS_NILAI[aksi])}."
            )
            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        _format(unlimited_mod.ANGKA_BESAR),
                        callback_data=f"unlimited:nilai:{aksi}:"
                                      f"{unlimited_mod.ANGKA_BESAR}"),
                    InlineKeyboardButton(
                        "Custom",
                        callback_data=f"unlimited:custom:{aksi}"),
                ],
                [
                    InlineKeyboardButton("Kembali",
                                         callback_data="unlimited:menu"),
                ],
            ])
            await _edit(query, teks, markup)
        else:
            await _buat_pending(query, context, aksi, None)
        return True
    if len(bagian) == 4 and bagian[1] == "nilai":
        aksi = bagian[2]
        try:
            nilai = unlimited_mod.validasi_nilai(aksi, int(bagian[3]))
        except (ValueError, TypeError):
            await _edit(query, "Nilai tidak valid.", _menu_keyboard())
            return True
        await _buat_pending(query, context, aksi, nilai)
        return True
    if len(bagian) == 3 and bagian[1] == "custom":
        aksi = bagian[2]
        if aksi not in unlimited_mod.AKSI_NUMERIK:
            await _edit(query, "Tombol tidak dikenal.", _menu_keyboard())
            return True
        context.user_data["awaiting"] = "unlimited_input"
        context.user_data["unlimited_aksi"] = aksi
        await _edit(
            query,
            f"Ketik nilai untuk {unlimited_mod.LABEL_AKSI[aksi]}.\n"
            f"Contoh: 5000000, 5jt, 99.999.999\n"
            f"Batas maks {_format(unlimited_mod.BATAS_NILAI[aksi])}. "
            "Ketik /batal untuk membatalkan.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("Kembali",
                                     callback_data="unlimited:menu"),
            ]]))
        return True
    await _edit(query, "Tombol tidak dikenal.", _menu_keyboard())
    return True


async def on_text_unlimited(update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    """Input teks nilai custom /unlimited (awaiting=unlimited_input)."""
    from .handlers import _parse_jumlah

    message = update.message
    if message is None or not diizinkan(context, message.chat_id):
        return
    aksi = str(context.user_data.pop("unlimited_aksi", ""))
    context.user_data.pop("awaiting", None)
    if aksi not in unlimited_mod.AKSI_NUMERIK:
        await message.reply_text(
            "Sesi input Unlimited sudah berakhir. Mulai lagi dari "
            "/unlimited.", reply_markup=kb.main_menu())
        return
    nilai = _parse_jumlah(message.text or "")
    if nilai is None:
        await message.reply_text(
            "Nilai tidak terbaca. Contoh yang valid: 5000000, 5jt, "
            "99.999.999. Mulai lagi dari /unlimited.",
            reply_markup=kb.main_menu())
        return
    try:
        nilai = unlimited_mod.validasi_nilai(aksi, nilai)
    except ValueError as exc:
        await message.reply_text(
            f"Nilai tidak valid: {exc}. Mulai lagi dari /unlimited.",
            reply_markup=kb.main_menu())
        return
    state, error = await _ambil_state(context, message.chat_id)
    if error:
        await message.reply_text(error, reply_markup=kb.main_menu())
        return
    pending, teks = build_pending_unlimited(
        state, context.bot_data["data"], aksi, nilai)
    context.user_data[PENDING_KEY] = pending
    await message.reply_text(teks, reply_markup=kb.confirm_keyboard("unlimited", pending.get("token")))
