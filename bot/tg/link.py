"""Alur /link: terima file akun.json -> validasi -> simpan -> uji akun_ambil.

Lokasi file di HP (RANCANGAN §4): 
``/data/data/com.neopawstudio.warunglife/files/akun.json`` (butuh root/VMOS).
File hanya ada SETELAH akun ditautkan di dalam game, bukan sekadar login
Google di HP.
"""

from __future__ import annotations

import json

from telegram import Update
from telegram.ext import ContextTypes

from ..core import save as save_mod
from ..core.cloud import CloudError, NoCloudData, SessionExpired
from ..core.store import validate_akun_json
from .keyboards import back_to_menu, link_keyboard
from .status import format_rupiah

PANDUAN_LINK = (
    "Untuk menautkan akun, kirim file akun.json dari game.\n\n"
    "Cara mengambilnya (butuh root / VMOS):\n"
    "1. Buka file manager root, masuk ke\n"
    "   /data/data/com.neopawstudio.warunglife/files/\n"
    "2. Salin file akun.json lalu kirim ke chat ini.\n\n"
    "File itu berisi token loginmu — bot menyimpannya terenkripsi dan "
    "tidak pernah menampilkannya di chat. Kirim /batal untuk berhenti."
)

CARA_AMBIL = (
    "File akun.json hanya ada setelah akun ditautkan DI DALAM game "
    "(menu Pengaturan / Akun), bukan sekadar login Google di HP.\n\n"
    "Jalur di HP: /data/data/com.neopawstudio.warunglife/files/akun.json\n"
    "Folder itu hanya bisa dibuka dengan akses root (mis. VMOS Cloud "
    "dengan root, atau file manager root).\n\n"
    "Setelah akun ditautkan di game, kirim file akun.json ke chat ini."
)


async def start_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Perintah /link: minta file akun.json."""
    if update.message is None:
        return
    context.user_data["awaiting"] = "akun_json"
    await update.message.reply_text(PANDUAN_LINK, reply_markup=link_keyboard())


async def show_cara_ambil(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    # Sudah dijawab handlers.on_callback; answer kedua ditolak Telegram.
    await query.edit_message_text(CARA_AMBIL, reply_markup=back_to_menu())


async def receive_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Terima dokumen — hanya diproses bila sedang menunggu akun.json."""
    message = update.message
    if message is None or message.document is None:
        return
    if context.user_data.get("awaiting") != "akun_json":
        await message.reply_text(
            "Bot tidak sedang menunggu file. Kirim /link dulu bila mau "
            "menautkan akun.",
            reply_markup=back_to_menu(),
        )
        return
    # awaiting TIDAK dikeluarkan di sini: file yang salah harus bisa
    # langsung diganti file koreksi tanpa /link ulang. Ia dikeluarkan
    # setelah file valid tersimpan.
    doc = message.document
    if not (doc.file_name or "").endswith(".json"):
        await message.reply_text(
            "File harus bernama akun.json. Periksa lagi file yang dikirim.",
            reply_markup=link_keyboard(),
        )
        return
    if doc.file_size and doc.file_size > 100_000:
        await message.reply_text(
            "File terlalu besar untuk akun.json — periksa lagi file yang dikirim.",
            reply_markup=link_keyboard(),
        )
        return
    try:
        tg_file = await doc.get_file()
        raw = await tg_file.download_as_bytearray()
    except Exception as exc:  # unduh dari server Telegram gagal
        await message.reply_text(
            f"Tidak bisa mengunduh file dari Telegram: {exc}",
            reply_markup=link_keyboard(),
        )
        return
    try:
        data = json.loads(bytes(raw).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        await message.reply_text(
            "File bukan JSON yang valid — pastikan itu akun.json dari game, "
            "bukan file lain.",
            reply_markup=link_keyboard(),
        )
        return

    valid, errors, warnings = validate_akun_json(data)
    if not valid:
        await message.reply_text(
            "File akun.json tidak valid:\n- " + "\n- ".join(errors),
            reply_markup=link_keyboard(),
        )
        return

    store = context.bot_data["store"]
    cloud = context.bot_data["cloud"]
    chat_id = message.chat_id
    session = dict(data)
    session.setdefault("versi", 0)
    session.setdefault("sidik", "")
    store.save_user(chat_id, session)
    context.user_data.pop("awaiting", None)

    peringatan = ""
    if warnings:
        peringatan = "\n(" + " ".join(warnings) + ")"

    # Uji tautan dengan akun_ambil (RANCANGAN §4 langkah 3).
    try:
        cloud_data, session = await cloud.fetch_cloud(session)
    except SessionExpired:
        store.delete_user(chat_id)
        context.user_data["awaiting"] = "akun_json"
        await message.reply_text(
            "Token di file ini sudah mati (server menolak refresh). "
            "Login ulang akun di game, lalu kirim akun.json yang baru.",
            reply_markup=link_keyboard(),
        )
        return
    except NoCloudData as exc:
        if getattr(exc, "session", None):
            store.update_session(chat_id, exc.session)
        await message.reply_text(
            "Akun tertaut, tapi belum ada simpanan di cloud.\n"
            "Buka game, pastikan akun tertaut di sana, dan biarkan game "
            "mengunggah sekali (atau main sebentar lalu tutup game).\n"
            "Setelah itu kirim /sync.",
            reply_markup=back_to_menu(),
        )
        return
    except CloudError as exc:
        if getattr(exc, "session", None):
            store.update_session(chat_id, exc.session)
        else:
            store.update_session(chat_id, session)
        await message.reply_text(
            f"Akun tersimpan, tapi uji ambil cloud gagal: {exc}\n"
            "Coba /sync lagi nanti.",
            reply_markup=back_to_menu(),
        )
        return

    # Sukses: simpan versi/sidik/kemajuan dari cloud.
    store.update_session(chat_id, session)
    try:
        paket = save_mod.decode_package(cloud_data["data"])
        nomor_slot, slot = save_mod.best_slot(paket)
        ringkasan = save_mod.slot_summary(slot)
        session["versi"] = int(cloud_data["versi"])
        session["sidik"] = save_mod.compute_sidik(paket)
        session["p_id_papan"] = ringkasan["id_papan"] or session.get("p_id_papan", "")
        session["kemajuan"] = {
            "level": ringkasan["level"],
            "hari": ringkasan["hari"],
            "nama": ringkasan["nama_warung"],
            "uang": ringkasan["uang"],
            "qris": ringkasan["qris"],
            "disimpan": ringkasan["disimpan"],
        }
        store.update_session(chat_id, session)
        info = (
            f"Warung \"{ringkasan['nama_warung'] or '(belum bernama)'}\" — "
            f"Level {ringkasan['level']} · Hari {ringkasan['hari']} · "
            f"Uang {format_rupiah(ringkasan['uang'])}"
        )
    except (save_mod.PackageError, save_mod.SlotError) as exc:
        info = f"Simpanan cloud ada (v{cloud_data['versi']}) tapi isinya tidak bisa dibaca bot: {exc}"
    email = str(data.get("email", "")) or "-"
    await message.reply_text(
        f"Akun tertaut: {email} (simpanan online v{cloud_data['versi']}).{peringatan}\n{info}\n"
        "Kirim /status untuk melihat warungmu.",
        reply_markup=back_to_menu(),
    )
