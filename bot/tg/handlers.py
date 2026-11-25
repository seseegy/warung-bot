"""Router perintah & tombol Fase 1.

Perintah (RANCANGAN §15.2 — hanya meta-action, TANPA parameter):
/start, /menu, /bantuan, /batal, /link, /unlink, /status, /tugas,
/tugas_selesai, /sync, /upload_paksa.

Alur utama lewat tombol inline (teks polos, tanpa emoji). Satu pesan per
layar: callback mengedit pesan yang sama, bukan mengirim pesan baru.
Setiap upload didahului layar konfirmasi (lihat tg/confirm.py).

Allowlist: bila ALLOWED_CHAT_IDS diisi, chat di luar daftar diabaikan
diam-diam (hanya dicatat di log).
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ..core import save as save_mod
from ..core import tiers as tiers_core
from ..core.cloud import CloudError, NoCloudData, SessionExpired
from . import keyboards as kb
from .confirm import (
    PENDING_KEY,
    build_pending_tugas,
    build_pending_uang,
    execute_force_upload,
    execute_upload,
)
from .link import receive_document as link_receive_document
from .link import show_cara_ambil, start_link
from . import sim as sim_tg
from . import tiers as tiers_tg
from . import cepat as cepat_tg
from .status import (
    NotLinked,
    fetch_latest_state,
    format_rupiah,
    format_task_card,
    format_status_card,
)

log = logging.getLogger(__name__)

TEKS_BANTUAN = (
    "Perintah yang tersedia:\n"
    "/start — perkenalan + status tautan\n"
    "/menu — menu utama\n"
    "/link — tautkan akun (kirim akun.json)\n"
    "/unlink — hapus semua data akun dari bot\n"
    "/status — status warung dari cloud\n"
    "/tugas — tugas level berjalan\n"
    "/tugas_selesai — isi progres tugas sampai target\n"
    "/sync — ambil simpanan terbaru dari cloud\n"
    "/upload_paksa — timpa cloud setelah bentrok\n"
    "/simulasi — proyeksi 1/3/7 hari dari simpanan terbaru\n"
    "/harga_terbaik — harga per barang yang memaksimalkan laba\n"
    "/stok — stok menipis + rekomendasi beli\n"
    "/jadwal — atur jam laporan harian\n"
    "/kapan_naik — perkiraan hari sampai naik level\n"
    "/roi_upgrade — urutan upgrade dari yang paling cepat balik modal\n"
    "/whatif — coba harga lain, lihat dampaknya\n"
    "/tier — pilih tier Kerja 24/7 (Pemula/Standar/Profesional)\n"
    "/otomatis — nyalakan/matikan siklus otomatis harian\n"
    "/laporan — ringkasan harian/mingguan + aksi otomatis\n"
    "/bandingkan — bandingkan strategi harga (butuh tier Profesional)\n"
    "/jual — jual barang dari stok (ketik: mi goreng 5)\n"
    "/beli — beli stok (ketik: beras 10)\n"
    "/ngopi — isi energi +30 dari stok minuman\n"
    "/tutup — tutup warung, bayar biaya/sewa, tidur ke hari baru\n"
    "/slot — pilih slot 1-6 yang dipakai bot\n"
    "/backup — arsip paket harian / pulihkan simpanan lama\n"
    "/rencana — rencana 7 hari (restock + upgrade)\n"
    "/statistik — barang laku & omzet dari riwayat save\n"
    "/cuan — mode cuan: beli stok murah (80%), jual mahal, pelanggan ramai\n"
    "/cuan_mati — nonaktifkan mode cuan, kembali normal\n"
    "/bantuan — daftar ini\n"
    "/batal — batalkan alur yang sedang berjalan\n\n"
    "Catatan: game harus TERTUTUP saat bot mengunggah, supaya hasilnya "
    "tidak tertimpa. Setelah upload, buka game dan pilih simpanan cloud."
)

TEKS_START = (
    "Halo! Saya bot pendamping Warung Life Simulator.\n\n"
    "Saya membaca save warungmu dari cloud, lalu membantumu mengubahnya "
    "tanpa membuka game. Yang bisa saya lakukan:\n"
    "- Lihat status warung (uang, level, tugas)\n"
    "- Ubah uang dan isi progres tugas, lalu unggah ke cloud\n"
    "- Sinkron dengan simpanan online\n"
    "- Simulasikan 1/3/7 hari ke depan, cari harga terbaik, hitung kapan "
    "naik level dan ROI upgrade (semua proyeksi, bukan jaminan)\n"
    "- Kerja 24/7: pengingat login harian, siklus otomatis harian "
    "(simulasi, auto-beli stok, harga ikut pasar, auto-bayar sewa/zakat) "
    "sesuai tier yang dipilih — lihat /tier\n"
    "- Aksi cepat: /jual, /beli, /ngopi, /tutup, /slot, /backup, "
    "/rencana, /statistik — lihat /bantuan\n\n"
    "Yang saya TIDAK lakukan: memainkan game. Game harus tertutup saat "
    "saya mengunggah, kalau tidak hasilnya bisa tertimpa.\n\n"
    "Mulai dengan /link untuk menautkan akun."
)


def _allowed(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    allowed = context.bot_data.get("allowed")
    if not allowed:  # allowlist kosong -> semua boleh (dengan peringatan di log)
        return True
    return chat_id in allowed


async def _edit(query, teks: str, markup=None) -> None:
    """Edit pesan callback; abaikan 'Message is not modified'."""
    try:
        await query.edit_message_text(teks, reply_markup=markup)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


def _parse_jumlah(teks: str) -> int | None:
    """Parse input uang yang diketik: '5000000', '5.000.000', '500rb', '1,5jt'.

    Konvensi Indonesia: "," = desimal, "." = ribuan bila ada "," atau
    muncul >= 2x atau bagian pecahan tepat 3 digit ("5.000" = 5000);
    selain itu "." adalah desimal ("1.5jt" = 1.500.000, bukan 15.000.000).
    Mengembalikan int rupiah, atau None bila tidak bisa dipahami.
    Menolak negatif. Nol dikembalikan sebagai 0 (ditolak di pemanggil
    sebagai kemungkinan salah ketik — lihat on_text).
    """
    s = teks.strip().lower().replace("rp", "").strip()
    if not s:
        return None
    pengali = 1
    if s.endswith("jt"):
        pengali = 1_000_000
        s = s[:-2].strip()
    elif s.endswith("rb"):
        pengali = 1_000
        s = s[:-2].strip()
    s = s.replace(" ", "").replace("_", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") >= 2:
        s = s.replace(".", "")
    elif "." in s:
        bulat, _, pecah = s.partition(".")
        if len(pecah) == 3:
            s = bulat + pecah  # ribuan, mis. "5.000" = 5000
        # selain itu "." adalah desimal ("1.5")
    try:
        nilai = float(s)
    except ValueError:
        return None
    if nilai < 0:
        return None
    return int(nilai * pengali)


# -- perintah ----------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return
    if not _allowed(context, message.chat_id):
        log.warning("chat %s ditolak (di luar allowlist)", message.chat_id)
        return
    store = context.bot_data["store"]
    if store.get_user(message.chat_id) is None:
        await message.reply_text(
            TEKS_START,
            reply_markup=kb.InlineKeyboardMarkup(
                [[kb.InlineKeyboardButton("Tautkan Akun", callback_data="link:mulai")]]
            ),
        )
    else:
        await message.reply_text("Akun sudah tertaut.", reply_markup=kb.main_menu())


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return
    if not _allowed(context, message.chat_id):
        return
    store = context.bot_data["store"]
    session = store.get_user(message.chat_id)
    if session is None:
        await message.reply_text(
            "Belum ada akun tertaut. Tautkan dulu dengan /link.",
            reply_markup=kb.InlineKeyboardMarkup(
                [[kb.InlineKeyboardButton("Tautkan Akun", callback_data="link:mulai")]]
            ),
        )
        return
    await message.reply_text(
        f"Menu — akun {session.get('email') or '-'} "
        f"(simpanan online v{session.get('versi', 0)})",
        reply_markup=kb.main_menu(),
    )


async def cmd_bantuan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if not _allowed(context, update.message.chat_id):
        return
    await update.message.reply_text(TEKS_BANTUAN, reply_markup=kb.back_to_menu())


async def cmd_batal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return
    if not _allowed(context, message.chat_id):
        return
    context.user_data.pop("awaiting", None)
    context.user_data.pop(PENDING_KEY, None)
    await message.reply_text("Dibatalkan.", reply_markup=kb.main_menu())


async def cmd_unlink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return
    if not _allowed(context, message.chat_id):
        return
    store = context.bot_data["store"]
    if store.get_user(message.chat_id) is None:
        await message.reply_text("Belum ada akun tertaut.")
        return
    context.user_data[PENDING_KEY] = {"kind": "unlink"}
    await message.reply_text(
        "Putuskan tautan dan HAPUS semua data akun dari bot ini?\n"
        "Token, versi cloud, dan cadangan paket akan dihapus. "
        "Save di cloud TIDAK ikut terhapus.",
        reply_markup=kb.unlink_confirm_keyboard(),
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return
    if not _allowed(context, message.chat_id):
        return
    await _kirim_status(message, context)


def _teks_status(state: dict, context, chat_id: int) -> str:
    """Kartu status + baris otomatisasi (bila store tersedia)."""
    store = context.bot_data.get("store")
    otomatis = tier = jam = None
    if store is not None:
        try:
            otomatis = store.get_otomatis(chat_id)
            tier = store.get_tier(chat_id)
            jam = store.get_jam_otomatis(chat_id)
        except Exception:
            otomatis = tier = jam = None
    return format_status_card(
        state["ringkasan"], state["slot"], context.bot_data["tugas"], state["versi"],
        state.get("disinkronkan"), otomatis, tier, jam,
        context.bot_data.get("data"),
    )


async def _kirim_status(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = message.chat_id
    try:
        state = await fetch_latest_state(context, chat_id)
    except NotLinked:
        await message.reply_text(
            "Belum ada akun tertaut. Tautkan dulu dengan /link.",
            reply_markup=kb.InlineKeyboardMarkup(
                [[kb.InlineKeyboardButton("Tautkan Akun", callback_data="link:mulai")]]
            ),
        )
        return
    except SessionExpired:
        await message.reply_text(
            "Sesi login habis. Kirim ulang akun.json dari game dengan /link."
        )
        return
    except NoCloudData:
        await message.reply_text(
            "Akun tertaut, tapi belum ada simpanan di cloud. "
            "Buka game dan biarkan game mengunggah sekali, lalu /sync."
        )
        return
    except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
        await message.reply_text(f"Tidak bisa mengambil status: {exc}")
        return
    teks = _teks_status(state, context, message.chat_id)
    await message.reply_text(teks, reply_markup=kb.status_keyboard())


async def cmd_tugas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return
    if not _allowed(context, message.chat_id):
        return
    try:
        state = await fetch_latest_state(context, message.chat_id)
    except NotLinked:
        await message.reply_text("Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    except SessionExpired:
        await message.reply_text(
            "Sesi login habis. Kirim ulang akun.json dari game dengan /link."
        )
        return
    except NoCloudData:
        await message.reply_text("Belum ada simpanan di cloud.")
        return
    except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
        await message.reply_text(f"Tidak bisa mengambil tugas: {exc}")
        return
    await message.reply_text(
        format_task_card(state["slot"], context.bot_data["tugas"]),
        reply_markup=kb.status_keyboard(),
    )


async def cmd_tugas_selesai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return
    if not _allowed(context, message.chat_id):
        return
    try:
        state = await fetch_latest_state(context, message.chat_id)
    except NotLinked:
        await message.reply_text("Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    except SessionExpired:
        await message.reply_text(
            "Sesi login habis. Kirim ulang akun.json dari game dengan /link."
        )
        return
    except NoCloudData:
        await message.reply_text("Belum ada simpanan di cloud.")
        return
    except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
        await message.reply_text(f"Tidak bisa mengambil tugas: {exc}")
        return
    try:
        pending, teks = build_pending_tugas(state, context.bot_data["tugas"])
    except save_mod.TaskError as exc:
        await message.reply_text(f"Tidak bisa mengisi tugas: {exc}")
        return
    context.user_data[PENDING_KEY] = pending
    await message.reply_text(
        teks, reply_markup=kb.confirm_keyboard("tugas")
    )


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return
    if not _allowed(context, message.chat_id):
        return
    try:
        state = await fetch_latest_state(context, message.chat_id)
    except NotLinked:
        await message.reply_text("Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    except SessionExpired:
        await message.reply_text(
            "Sesi login habis. Kirim ulang akun.json dari game dengan /link."
        )
        return
    except NoCloudData:
        await message.reply_text("Belum ada simpanan di cloud.")
        return
    except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
        await message.reply_text(f"Sinkron gagal: {exc}")
        return
    teks = _teks_status(state, context, message.chat_id)
    await message.reply_text(
        "Sinkron selesai — ini simpanan terbaru dari cloud.\n\n" + teks,
        reply_markup=kb.status_keyboard(),
    )


async def cmd_upload_paksa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hanya bermakna setelah ada upload yang ditolak bentrok."""
    message = update.message
    if message is None:
        return
    if not _allowed(context, message.chat_id):
        return
    pending = context.user_data.get(PENDING_KEY) or {}
    if not pending.get("p_data"):
        await message.reply_text(
            "Tidak ada upload yang tertunda.\n"
            "/upload_paksa dipakai setelah bot gagal mengunggah karena "
            "bentrok — ulangi dulu perubahan yang mau diunggah "
            "(mis. Ubah Uang), lalu pilih 'Timpa dengan Punya Saya' "
            "saat pesan bentrok muncul."
        )
        return
    context.user_data[PENDING_KEY] = pending
    await message.reply_text(
        "Timpa simpanan online dengan hasil edit bot yang tadi ditolak?\n"
        "Simpanan cloud yang lebih baru akan TERTIMPA dan tidak bisa "
        "dikembalikan dari cloud (bot menyimpan cadangannya sebelum "
        "upload pertama).",
        reply_markup=kb.confirm_keyboard("paksa"),
    )


# -- callback ----------------------------------------------------------

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    if not _allowed(context, query.message.chat_id if query.message else 0):
        await query.answer()
        return
    await query.answer()
    data = query.data or ""
    chat_id = query.message.chat_id if query.message else 0

    if data.startswith("link:"):
        if data == "link:mulai":
            await start_link_via_callback(query, context)
        elif data == "link:cara":
            await show_cara_ambil(update, context)
        return
    if data.startswith("batal:"):
        context.user_data.pop("awaiting", None)
        context.user_data.pop(PENDING_KEY, None)
        await _edit(query, "Dibatalkan.", kb.main_menu())
        return

    if data == "menu:root":
        await _edit(query, "Menu.", kb.main_menu())
        return
    if data == "menu:status":
        await _tampilkan_status_callback(query, context)
        return
    if data == "menu:tugas":
        await _tampilkan_tugas_callback(query, context)
        return
    if data == "menu:uang":
        await _tampilkan_pilih_uang(query, context)
        return
    if data == "menu:sync":
        await _tampilkan_sync_callback(query, context)
        return
    if data == "menu:pengaturan":
        await _tampilkan_pengaturan(query, context)
        return

    if data == "status:refresh":
        await _tampilkan_status_callback(query, context)
        return
    if data == "tugas:isi":
        await _mulai_isi_tugas(query, context)
        return
    if data == "sync:ambil":
        await _tampilkan_sync_callback(query, context)
        return

    if data.startswith("uang:"):
        await _uang_callback(query, context, data)
        return

    if data.startswith("sim:") or data.startswith("jadwal:"):
        await sim_tg.on_callback_sim(update, context, query, data)
        return

    if data.startswith(("tier:", "otomatis:", "target:", "kejar:", "login:",
                        "laporan:")):
        await tiers_tg.on_callback_tier(update, context, query, data)
        return

    if data.startswith("cepat:"):
        await cepat_tg.on_callback_cepat(update, context, query, data)
        return

    if data.startswith("konfirm:"):
        await _konfirm_callback(query, context, data)
        return

    if data.startswith("bentrok:"):
        await _bentrok_callback(query, context, data)
        return

    await _edit(query, "Tombol tidak dikenal.", kb.main_menu())


async def start_link_via_callback(query, context) -> None:
    context.user_data["awaiting"] = "akun_json"
    from .link import PANDUAN_LINK

    await _edit(query, PANDUAN_LINK, kb.link_keyboard())


async def _tampilkan_status_callback(query, context) -> None:
    chat_id = query.message.chat_id
    try:
        state = await fetch_latest_state(context, chat_id)
    except NotLinked:
        await _edit(query, "Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    except SessionExpired:
        await _edit(query, "Sesi login habis. Kirim ulang akun.json dari game dengan /link.")
        return
    except NoCloudData:
        await _edit(query, "Akun tertaut, tapi belum ada simpanan di cloud.")
        return
    except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
        await _edit(query, f"Tidak bisa mengambil status: {exc}")
        return
    teks = _teks_status(state, context, chat_id)
    await _edit(query, teks, kb.status_keyboard())


async def _tampilkan_tugas_callback(query, context) -> None:
    chat_id = query.message.chat_id
    try:
        state = await fetch_latest_state(context, chat_id)
    except NotLinked:
        await _edit(query, "Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    except SessionExpired:
        await _edit(query, "Sesi login habis. Kirim ulang akun.json dari game dengan /link.")
        return
    except NoCloudData:
        await _edit(query, "Belum ada simpanan di cloud.")
        return
    except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
        await _edit(query, f"Tidak bisa mengambil tugas: {exc}")
        return
    await _edit(
        query,
        format_task_card(state["slot"], context.bot_data["tugas"]),
        kb.status_keyboard(),
    )


async def _tampilkan_sync_callback(query, context) -> None:
    chat_id = query.message.chat_id
    try:
        state = await fetch_latest_state(context, chat_id)
    except NotLinked:
        await _edit(query, "Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    except SessionExpired:
        await _edit(query, "Sesi login habis. Kirim ulang akun.json dari game dengan /link.")
        return
    except NoCloudData:
        await _edit(query, "Belum ada simpanan di cloud.")
        return
    except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
        await _edit(query, f"Sinkron gagal: {exc}")
        return
    teks = _teks_status(state, context, chat_id)
    await _edit(query, "Sinkron selesai — ini simpanan terbaru dari cloud.\n\n" + teks, kb.status_keyboard())


async def _tampilkan_pengaturan(query, context) -> None:
    chat_id = query.message.chat_id
    store = context.bot_data["store"]
    session = store.get_user(chat_id)
    if session is None:
        await _edit(query, "Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    tier = store.get_tier(chat_id)
    teks = (
        "Pengaturan\n\n"
        f"Akun: {session.get('email') or '-'}\n"
        f"Penyedia: {session.get('penyedia') or '-'}\n"
        f"Simpanan online: v{session.get('versi', 0)}\n"
        f"Tier: {tier} ({tiers_core.TIER_NAMA[tier]})\n"
        f"Otomatisasi: {'nyala' if store.get_otomatis(chat_id) else 'mati'} "
        f"(jam {store.get_jam_otomatis(chat_id):02d}.00 WIB)\n"
        f"Batas harian: {store.get_batas_harian(chat_id)}\n\n"
        "Putuskan tautan akan menghapus token dan semua data akun "
        "dari bot ini (save di cloud tidak ikut terhapus)."
    )
    await _edit(
        query,
        teks,
        kb.InlineKeyboardMarkup(
            [
                [kb.InlineKeyboardButton("Putuskan Tautan", callback_data="konfirm:tanya:unlink")],
                [kb.InlineKeyboardButton("Kembali ke Menu", callback_data="menu:root")],
            ]
        ),
    )


async def _tampilkan_pilih_uang(query, context) -> None:
    chat_id = query.message.chat_id
    try:
        state = await fetch_latest_state(context, chat_id)
    except NotLinked:
        await _edit(query, "Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    except SessionExpired:
        await _edit(query, "Sesi login habis. Kirim ulang akun.json dari game dengan /link.")
        return
    except NoCloudData:
        await _edit(query, "Belum ada simpanan di cloud.")
        return
    except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
        await _edit(query, f"Tidak bisa mengambil status: {exc}")
        return
    await _edit(
        query,
        f"Uang sekarang: {format_rupiah(state['ringkasan']['uang'])}\n"
        "Tombol cepat MENAMBAH ke uang sekarang. "
        "Ketik sendiri untuk mengganti total.",
        kb.money_keyboard(),
    )


async def _mulai_isi_tugas(query, context) -> None:
    chat_id = query.message.chat_id
    try:
        state = await fetch_latest_state(context, chat_id)
    except NotLinked:
        await _edit(query, "Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    except SessionExpired:
        await _edit(query, "Sesi login habis. Kirim ulang akun.json dari game dengan /link.")
        return
    except NoCloudData:
        await _edit(query, "Belum ada simpanan di cloud.")
        return
    except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
        await _edit(query, f"Tidak bisa mengambil tugas: {exc}")
        return
    try:
        pending, teks = build_pending_tugas(state, context.bot_data["tugas"])
    except save_mod.TaskError as exc:
        await _edit(query, f"Tidak bisa mengisi tugas: {exc}")
        return
    context.user_data[PENDING_KEY] = pending
    await _edit(query, teks, kb.confirm_keyboard("tugas"))


async def _uang_callback(query, context, data: str) -> None:
    chat_id = query.message.chat_id
    bagian = data.split(":")
    if len(bagian) >= 3 and bagian[1] == "tambah":
        try:
            delta = int(bagian[2])
        except ValueError:
            await _edit(query, "Nominal tidak dikenal.", kb.money_keyboard())
            return
        try:
            state = await fetch_latest_state(context, chat_id)
        except NotLinked:
            await _edit(query, "Belum ada akun tertaut. Tautkan dulu dengan /link.")
            return
        except SessionExpired:
            await _edit(query, "Sesi login habis. Kirim ulang akun.json dari game dengan /link.")
            return
        except NoCloudData:
            await _edit(query, "Belum ada simpanan di cloud.")
            return
        except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
            await _edit(query, f"Tidak bisa mengambil status: {exc}")
            return
        jumlah_baru = state["ringkasan"]["uang"] + delta
        if jumlah_baru > save_mod.UANG_MAKSIMAL:
            await _edit(
                query,
                f"Hasilnya {format_rupiah(jumlah_baru)} melebihi batas wajar "
                f"{format_rupiah(save_mod.UANG_MAKSIMAL)}.",
                kb.money_keyboard(),
            )
            return
        pending, teks = build_pending_uang(state, jumlah_baru)
        context.user_data[PENDING_KEY] = pending
        await _edit(query, teks, kb.confirm_keyboard("uang"))
        return
    if data == "uang:ketik":
        context.user_data["awaiting"] = "uang_input"
        await _edit(
            query,
            "Ketik jumlah uang TOTAL yang diinginkan (bukan tambahan).\n"
            "Contoh: 5000000, 5.000.000, 500rb, 1,5jt\n"
            "Kirim /batal untuk berhenti.",
        )
        return
    if data == "uang:pilih":
        await _tampilkan_pilih_uang(query, context)
        return
    await _edit(query, "Tombol tidak dikenal.", kb.main_menu())


async def _konfirm_callback(query, context, data: str) -> None:
    chat_id = query.message.chat_id
    bagian = data.split(":")
    # konfirm:<ya|tidak|tanya>:<aksi>
    if len(bagian) != 3:
        await _edit(query, "Tombol tidak dikenal.", kb.main_menu())
        return
    _, aksi_konfirm, aksi = bagian
    if aksi_konfirm == "tanya" and aksi == "unlink":
        context.user_data[PENDING_KEY] = {"kind": "unlink"}
        await _edit(
            query,
            "Putuskan tautan dan HAPUS semua data akun dari bot ini?\n"
            "Token, versi cloud, dan cadangan paket akan dihapus. "
            "Save di cloud TIDAK ikut terhapus.",
            kb.unlink_confirm_keyboard(),
        )
        return
    pending = context.user_data.get(PENDING_KEY) or {}
    if aksi_konfirm == "tidak":
        context.user_data.pop(PENDING_KEY, None)
        context.user_data.pop("awaiting", None)
        await _edit(query, "Dibatalkan.", kb.main_menu())
        return
    # aksi_konfirm == "ya"
    if aksi == "unlink":
        context.bot_data["store"].delete_user(chat_id)
        context.user_data.pop(PENDING_KEY, None)
        await _edit(query, "Tautan diputus. Semua data akun dihapus dari bot.")
        return
    if aksi in ("uang", "tugas", "simulasi", "harga", "cepat", "rollback"):
        if pending.get("kind") != aksi:
            await _edit(query, "Tidak ada aksi tertunda yang cocok. Mulai lagi dari Menu.", kb.main_menu())
            return
        teks, status = await execute_upload(context, chat_id, pending)
        context.user_data.pop(PENDING_KEY, None)
        if status == "ok" and isinstance(pending.get("audit"), dict):
            # Fase 5: catat aksi cepat/rollback manual ke log audit.
            context.bot_data["store"].log_audit(
                chat_id, str(pending["audit"].get("aksi", aksi)),
                str(pending["audit"].get("detail", "")))
        if status == "bentrok":
            # Pending dipertahankan (dengan p_data) untuk "Timpa".
            context.user_data[PENDING_KEY] = pending
            await _edit(query, teks, kb.conflict_keyboard())
        else:
            await _edit(query, teks, kb.back_to_menu())
        return
    if aksi == "paksa":
        if not pending.get("p_data"):
            await _edit(query, "Tidak ada upload tertunda yang bisa dipaksa.", kb.main_menu())
            return
        teks, status = await execute_force_upload(context, chat_id, pending)
        context.user_data.pop(PENDING_KEY, None)
        await _edit(query, teks, kb.back_to_menu())
        return
    await _edit(query, "Tombol tidak dikenal.", kb.main_menu())


async def _bentrok_callback(query, context, data: str) -> None:
    chat_id = query.message.chat_id
    if data == "bentrok:pakai":
        context.user_data.pop(PENDING_KEY, None)
        await _tampilkan_status_callback(query, context)
        return
    if data == "bentrok:timpa":
        pending = context.user_data.get(PENDING_KEY) or {}
        if not pending.get("p_data"):
            await _edit(query, "Tidak ada upload tertunda yang bisa dipaksa.", kb.main_menu())
            return
        teks, status = await execute_force_upload(context, chat_id, pending)
        context.user_data.pop(PENDING_KEY, None)
        await _edit(query, teks, kb.back_to_menu())
        return
    await _edit(query, "Tombol tidak dikenal.", kb.main_menu())


# -- teks bebas ----------------------------------------------------------

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Input bebas: what-if, jam jadwal, atau jumlah uang."""
    message = update.message
    if message is None or not message.text:
        return
    if not _allowed(context, message.chat_id):
        return
    awaiting = context.user_data.get("awaiting")
    if awaiting == "whatif_input":
        await sim_tg.on_text_whatif(update, context)
        return
    if awaiting == "jadwal_jam":
        await sim_tg.on_text_jadwal(update, context)
        return
    if awaiting in ("cepat_jual", "cepat_beli"):
        await cepat_tg.on_text_cepat(update, context)
        return
    if awaiting != "uang_input":
        await message.reply_text(
            "Perintah tidak dikenal. Kirim /bantuan untuk daftar perintah.",
            reply_markup=kb.main_menu(),
        )
        return
    context.user_data.pop("awaiting", None)
    jumlah = _parse_jumlah(message.text)
    if jumlah is None:
        await message.reply_text(
            "Jumlah tidak bisa dipahami. Contoh: 5000000, 5.000.000, 500rb, 1,5jt.\n"
            "Coba lagi dari Menu → Ubah Uang.",
            reply_markup=kb.main_menu(),
        )
        return
    if jumlah == 0:
        await message.reply_text(
            "Jumlah 0 tidak diterima (kemungkinan salah ketik). "
            "Coba lagi dari Menu → Ubah Uang.",
            reply_markup=kb.main_menu(),
        )
        return
    if jumlah > save_mod.UANG_MAKSIMAL:
        await message.reply_text(
            f"Jumlah melebihi batas wajar {format_rupiah(save_mod.UANG_MAKSIMAL)}.",
            reply_markup=kb.main_menu(),
        )
        return
    try:
        state = await fetch_latest_state(context, message.chat_id)
    except NotLinked:
        await message.reply_text("Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    except SessionExpired:
        await message.reply_text(
            "Sesi login habis. Kirim ulang akun.json dari game dengan /link."
        )
        return
    except NoCloudData:
        await message.reply_text("Belum ada simpanan di cloud.")
        return
    except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
        await message.reply_text(f"Tidak bisa mengambil status: {exc}")
        return
    pending, teks = build_pending_uang(state, jumlah)
    context.user_data[PENDING_KEY] = pending
    await message.reply_text(teks, reply_markup=kb.confirm_keyboard("uang"))


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if not _allowed(context, update.message.chat_id):
        return
    await link_receive_document(update, context)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Error handler global: catat lengkap, beri tahu pengguna secara umum.

    Token TIDAK PERNAH dicetak — context.error tidak berisi token.
    """
    log.exception("error saat menangani update: %s", context.error)
    if isinstance(update, Update) and update.effective_chat is not None:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Terjadi kesalahan di bot. Coba lagi sebentar lagi.",
            )
        except Exception:
            pass
