"""Handler Fase 5: aksi cepat, slot, backup/rollback, rencana, statistik.

Pola Fase 1-4 dipertahankan: inline keyboard teks polos tanpa emoji,
satu pesan per layar (callback mengedit pesan yang sama), konfirmasi
sebelum setiap upload (pending "cepat"/"rollback" di tg/confirm.py),
teks bebas untuk /jual dan /beli (BUKAN argumen perintah — sesuai
RANCANGAN §15: ketik "mi goreng 5", lalu /batal bila berubah pikiran).

Penjaga yang ditegakkan di sini (bukan hanya di UI):
- mode baca saja (Fase 4) memblokir semua aksi tulis;
- tier Standar untuk aksi cepat (/jual, /beli, /ngopi, /tutup);
- batas harian (Fase 3) menolak kenaikan uang yang melewati batas;
- rollback butuh konfirmasi ganda (pilih arsip -> tinjau -> konfirmasi
  upload); arsip rusak ditolak sebelum ada yang diunggah.
"""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from ..core import auto as auto_mod
from ..core import backup as backup_mod
from ..core import cepat as cepat_mod
from ..core import save as save_mod
from ..core import strategi as strategi_mod
from ..core import statistik as statistik_mod
from ..core import tiers as tiers_mod
from ..core.cloud import CloudError, NoCloudData, SessionExpired
from . import keyboards as kb
from .confirm import (
    PENDING_KEY,
    build_pending_cepat,
    build_pending_rollback,
)
from .status import (
    NotLinked,
    fetch_latest_state,
    format_disimpan,
    format_rupiah,
)

log = logging.getLogger(__name__)


def _allowed(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    allowed = context.bot_data.get("allowed")
    if not allowed:
        return True
    return chat_id in allowed


async def _edit(query, teks: str, markup=None) -> None:
    """Edit pesan callback; abaikan 'Message is not modified'."""
    try:
        await query.edit_message_text(teks, reply_markup=markup)
    except Exception as exc:
        if "not modified" not in str(exc).lower():
            raise


async def _ambil_state_aktif(context, chat_id: int):
    """Ambil state terbaru pada slot yang dipakai bot.

    Resolusi slot (pilihan /slot, lalu slot terbaik) terjadi di dalam
    ``fetch_latest_state`` — satu titik untuk semua fitur, supaya
    status/simulasi/siklus otomatis tidak menyimpang dari pilihan
    pengguna. Mengembalikan (state, pesan_error)."""
    try:
        state = await fetch_latest_state(context, chat_id)
        return state, None
    except NotLinked:
        return None, "Belum ada akun tertaut. Tautkan dulu dengan /link."
    except SessionExpired:
        return None, "Sesi login habis. Kirim ulang akun.json dari game dengan /link."
    except NoCloudData:
        return None, "Belum ada simpanan di cloud."
    except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
        return None, f"Tidak bisa mengambil simpanan: {exc}"


def _cek_tulis(context, chat_id: int, butuh_tier: bool = True) -> str | None:
    """Pesan penolakan bila aksi tulis tidak boleh jalan, None bila boleh.

    Mode baca saja memblokir semua tulis; aksi cepat butuh tier Standar.
    """
    store = context.bot_data["store"]
    if store.get_baca_saja(chat_id):
        return ("Mode baca saja aktif — aksi tulis dimatikan. "
                "Matikan dulu di Pengaturan / Mini App.")
    if butuh_tier:
        try:
            tiers_mod.require_tier(store.get_tier(chat_id), "aksi_cepat")
        except tiers_mod.TierError as exc:
            return str(exc)
    return None


def _cek_batas(context, chat_id: int, uang_awal: int,
               uang_akhir: int) -> str | None:
    """Pesan penolakan bila kenaikan uang melewati batas harian."""
    store = context.bot_data["store"]
    batas = store.get_batas_harian(chat_id)
    cek = auto_mod.cek_batas_harian(uang_awal, uang_akhir, batas)
    if cek["melewati"]:
        return (f"Kenaikan uang {format_rupiah(cek['selisih'])} melewati "
                f"batas harian {format_rupiah(batas)}. Aksi dibatalkan — "
                "naikkan batas di /tier bila memang disengaja.")
    return None


def _audit(pending: dict, aksi: str, detail: str) -> None:
    """Sisipkan info audit ke pending — dicatat handlers._konfirm_callback
    setelah upload sukses."""
    pending["audit"] = {"aksi": aksi, "detail": detail}


# -- menu aksi cepat ---------------------------------------------------------

def cepat_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Jual", callback_data="cepat:cmd:jual"),
                InlineKeyboardButton("Beli", callback_data="cepat:cmd:beli"),
            ],
            [
                InlineKeyboardButton("Ngopi", callback_data="cepat:cmd:ngopi"),
                InlineKeyboardButton("Tutup Warung",
                                     callback_data="cepat:cmd:tutup"),
            ],
            [
                InlineKeyboardButton("Slot", callback_data="cepat:cmd:slot"),
                InlineKeyboardButton("Backup",
                                     callback_data="cepat:cmd:backup"),
            ],
            [
                InlineKeyboardButton("Rencana",
                                     callback_data="cepat:cmd:rencana"),
                InlineKeyboardButton("Statistik",
                                     callback_data="cepat:cmd:statistik"),
            ],
            [
                InlineKeyboardButton("Kembali ke Menu",
                                     callback_data="menu:root"),
            ],
        ]
    )


TEKS_MENU_CEPAT = (
    "Aksi Cepat — edit simpanan langsung (bukan simulasi):\n"
    "Jual / Beli: ketik barang dan jumlah, contoh: mi goreng 5\n"
    "Ngopi: isi energi +30 dari stok minuman (1x sehari)\n"
    "Tutup Warung: tutup hari ini, bayar biaya/sewa, tidur ke hari baru\n"
    "Slot: pilih slot 1-6 yang dipakai bot\n"
    "Backup: lihat arsip harian / pulihkan simpanan lama\n"
    "Rencana: rencana 7 hari (restock + upgrade)\n"
    "Statistik: barang laku & omzet dari riwayat save"
)


async def _tampilkan_menu_cepat(query, context) -> None:
    await _edit(query, TEKS_MENU_CEPAT, cepat_menu_keyboard())


# -- /jual, /beli (teks bebas) ----------------------------------------------

async def cmd_jual(update, context) -> None:
    message = update.message
    if message is None or not _allowed(context, message.chat_id):
        return
    err = _cek_tulis(context, message.chat_id)
    if err:
        await message.reply_text(err, reply_markup=kb.main_menu())
        return
    context.user_data["awaiting"] = "cepat_jual"
    await message.reply_text(
        "Jual barang — ketik barang dan jumlah, contoh: mi goreng 5\n"
        "Harga memakai harga jual di save (batas atas game berlaku).\n"
        "Kirim /batal bila berubah pikiran.",
        reply_markup=kb.back_to_menu(),
    )


async def cmd_beli(update, context) -> None:
    message = update.message
    if message is None or not _allowed(context, message.chat_id):
        return
    err = _cek_tulis(context, message.chat_id)
    if err:
        await message.reply_text(err, reply_markup=kb.main_menu())
        return
    context.user_data["awaiting"] = "cepat_beli"
    await message.reply_text(
        "Beli stok — ketik barang dan jumlah, contoh: beras 10\n"
        "Biaya = harga modal x jumlah. Stok datang via kurir saat game "
        "dibuka, bukan instan.\n"
        "Kirim /batal bila berubah pikiran.",
        reply_markup=kb.back_to_menu(),
    )


async def on_text_cepat(update, context) -> bool:
    """Input teks untuk /jual / /beli. True bila ditangani."""
    message = update.message
    if message is None or not message.text:
        return False
    awaiting = context.user_data.get("awaiting")
    if awaiting not in ("cepat_jual", "cepat_beli"):
        return False
    context.user_data.pop("awaiting", None)
    chat_id = message.chat_id
    data = context.bot_data["data"]
    err = _cek_tulis(context, chat_id)
    if err:
        await message.reply_text(err, reply_markup=kb.main_menu())
        return True
    try:
        item_id, jumlah = cepat_mod.parse_perintah(message.text, data)
    except cepat_mod.CepatError as exc:
        await message.reply_text(
            f"Tidak bisa dipahami: {exc}\n"
            "Contoh: mi goreng 5 (atau kirim /batal)",
            reply_markup=kb.back_to_menu(),
        )
        return True
    state, err_state = await _ambil_state_aktif(context, chat_id)
    if err_state:
        await message.reply_text(err_state, reply_markup=kb.main_menu())
        return True
    try:
        if awaiting == "cepat_jual":
            hasil = cepat_mod.jual_barang(state["slot"], data, item_id, jumlah)
            ringkasan = (
                f"Jual {hasil['jumlah']}x {hasil['nama']} "
                f"({format_rupiah(hasil['harga_satuan'])} per unit)\n"
                f"Omzet +{format_rupiah(hasil['omzet'])} · "
                f"Laba +{format_rupiah(hasil['laba'])}\n"
                f"Uang {format_rupiah(hasil['uang_awal'])} → "
                f"{format_rupiah(hasil['uang_akhir'])}"
                + (f" · Stok sisa {hasil['stok_akhir']}"
                   if hasil["stok_akhir"] is not None else "")
                + (" · Naik level!" if hasil["naik_level"] else ""))
            aksi = "jual"
        else:
            hasil = cepat_mod.beli_barang(state["slot"], data, item_id, jumlah)
            ringkasan = (
                f"Beli {hasil['jumlah']}x {hasil['nama']} "
                f"({format_rupiah(hasil['harga_modal'])} per unit)\n"
                f"Biaya {format_rupiah(hasil['biaya'])}\n"
                f"Uang {format_rupiah(hasil['uang_awal'])} → "
                f"{format_rupiah(hasil['uang_akhir'])} · "
                f"Kiriman {hasil['kiriman_total']} unit (diantar kurir "
                f"saat game dibuka)")
            aksi = "beli"
    except cepat_mod.CepatError as exc:
        await message.reply_text(str(exc), reply_markup=kb.back_to_menu())
        return True
    err_batas = _cek_batas(context, chat_id, hasil["uang_awal"],
                           hasil["uang_akhir"])
    if err_batas:
        await message.reply_text(err_batas, reply_markup=kb.main_menu())
        return True
    pending, teks = build_pending_cepat(state, hasil["slot"], ringkasan)
    _audit(pending, aksi, ringkasan.replace("\n", " "))
    context.user_data[PENDING_KEY] = pending
    await message.reply_text(
        teks, reply_markup=kb.confirm_keyboard("cepat", pending.get("token")))
    return True


# -- /ngopi, /tutup ----------------------------------------------------------

async def cmd_ngopi(update, context) -> None:
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
    try:
        hasil = cepat_mod.ngopi(state["slot"], context.bot_data["data"])
    except cepat_mod.CepatError as exc:
        await message.reply_text(str(exc), reply_markup=kb.back_to_menu())
        return
    ringkasan = (
        f"Ngopi ({hasil['nama_minuman']})\n"
        f"Energi {hasil['energi_awal']:.0f} → {hasil['energi_akhir']:.0f} "
        f"(+{hasil['energi_akhir'] - hasil['energi_awal']:.0f})")
    pending, teks = build_pending_cepat(state, hasil["slot"], ringkasan)
    _audit(pending, "ngopi", ringkasan.replace("\n", " "))
    context.user_data[PENDING_KEY] = pending
    await message.reply_text(
        teks, reply_markup=kb.confirm_keyboard("cepat", pending.get("token")))


async def cmd_tutup(update, context) -> None:
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
    hasil = cepat_mod.tutup_hari_bot(state["slot"], context.bot_data["data"])
    baris = [
        f"Tutup hari {hasil['hari_lama']} → tidur ke hari {hasil['hari_baru']}",
        f"Omzet hari ini {format_rupiah(hasil['omzet'])} · "
        f"Laba {format_rupiah(hasil['laba'])} · "
        f"Barang terjual {hasil['barang']}",
        f"Biaya harian {format_rupiah(hasil['biaya_harian'])}"
        + (f" · Sewa {format_rupiah(hasil['sewa'])}"
           if hasil["sewa"] else ""),
        f"Uang {format_rupiah(hasil['uang_awal'])} → "
        f"{format_rupiah(hasil['uang_akhir'])}",
    ]
    if hasil["tunggakan_sewa"]:
        baris.append(
            f"Peringatan: tunggakan sewa {format_rupiah(hasil['tunggakan_sewa'])} "
            f"({hasil['minggu_tunggak']} minggu).")
    if hasil["diusir"]:
        baris.append("PERINGATAN: warung DIUSIR (tunggakan 3 minggu).")
    ringkasan = "\n".join(baris)
    err_batas = _cek_batas(context, message.chat_id, hasil["uang_awal"],
                           hasil["uang_akhir"])
    if err_batas:
        await message.reply_text(err_batas, reply_markup=kb.main_menu())
        return
    pending, teks = build_pending_cepat(state, hasil["slot"], ringkasan)
    _audit(pending, "tutup", ringkasan.replace("\n", " "))
    context.user_data[PENDING_KEY] = pending
    await message.reply_text(
        teks, reply_markup=kb.confirm_keyboard("cepat", pending.get("token")))


# -- /slot -------------------------------------------------------------------

def _format_slot_list(daftar: list, aktif: int | None) -> str:
    baris = ["Slot warung (6 slot game):"]
    for entri in daftar:
        nomor = entri["nomor"]
        tanda = " [dipakai bot]" if aktif == nomor else (
            " [terbaik]" if aktif is None and entri.get("terbaik") else "")
        if entri.get("kosong"):
            baris.append(f"Slot {nomor}: (kosong){tanda}")
        elif entri.get("rusak"):
            baris.append(f"Slot {nomor}: (rusak — {entri.get('alasan', '?')})")
        else:
            baris.append(
                f"Slot {nomor}: \"{entri['nama_warung'] or '(belum bernama)'}\" "
                f"Level {entri['level']} · Hari {entri['hari']} · "
                f"Uang {format_rupiah(entri['uang'])}"
                f" · disimpan {format_disimpan(entri['disimpan'])}{tanda}")
    baris.append("")
    baris.append("Tanpa pilihan, bot memakai slot terbaik (level lalu hari).")
    return "\n".join(baris)


def slot_keyboard(daftar: list, aktif: int | None) -> InlineKeyboardMarkup:
    baris = []
    for entri in daftar:
        if entri.get("kosong") or entri.get("rusak"):
            continue
        label = f"Pakai Slot {entri['nomor']}"
        if aktif == entri["nomor"]:
            label += " (aktif)"
        baris.append([InlineKeyboardButton(
            label, callback_data=f"cepat:slot:{entri['nomor']}")])
    baris.append([InlineKeyboardButton(
        "Slot Terbaik (otomatis)", callback_data="cepat:slot:0")])
    baris.append([InlineKeyboardButton(
        "Kembali ke Menu", callback_data="menu:root")])
    return InlineKeyboardMarkup(baris)


async def cmd_slot(update, context) -> None:
    message = update.message
    if message is None or not _allowed(context, message.chat_id):
        return
    state, err_state = await _ambil_state_aktif(context, message.chat_id)
    if err_state:
        await message.reply_text(err_state, reply_markup=kb.main_menu())
        return
    store = context.bot_data["store"]
    aktif = store.get_slot_aktif(message.chat_id)
    daftar = cepat_mod.daftar_slot(state["paket"])
    try:
        nomor_terbaik, _ = save_mod.best_slot(state["paket"])
        for entri in daftar:
            if entri["nomor"] == nomor_terbaik:
                entri["terbaik"] = True
    except (save_mod.SlotError, save_mod.PackageError):
        pass
    await message.reply_text(
        _format_slot_list(daftar, aktif),
        reply_markup=slot_keyboard(daftar, aktif),
    )


# -- /backup + rollback -------------------------------------------------------

def _format_backup_list(daftar: list) -> str:
    if not daftar:
        return ("Belum ada arsip paket. Arsip dibuat otomatis tiap hari "
                "jam 03.00 WIB, dan sebelum tiap upload bot.")
    baris = ["Arsip paket cloud (satu per hari):"]
    for entri in daftar:
        baris.append(
            f"{entri['tanggal']} — v{entri['versi']}")
    baris.append("")
    baris.append("Tekan Pulihkan untuk mengembalikan arsip sebagai "
                 "versi baru (butuh konfirmasi 2 langkah).")
    return "\n".join(baris)


def backup_keyboard(daftar: list) -> InlineKeyboardMarkup:
    baris = [
        [InlineKeyboardButton(
            f"Pulihkan {entri['tanggal']}",
            callback_data=f"cepat:rollback:{entri['id']}")]
        for entri in daftar
    ]
    baris.append([InlineKeyboardButton(
        "Kembali ke Menu", callback_data="menu:root")])
    return InlineKeyboardMarkup(baris)


async def cmd_backup(update, context) -> None:
    message = update.message
    if message is None or not _allowed(context, message.chat_id):
        return
    store = context.bot_data["store"]
    session = store.get_user(message.chat_id)
    if session is None:
        await message.reply_text("Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    daftar = backup_mod.daftar_arsip(store, message.chat_id)
    await message.reply_text(
        _format_backup_list(daftar),
        reply_markup=backup_keyboard(daftar),
    )


async def _tampilkan_rollback_langkah1(query, context, backup_id: int) -> None:
    """Langkah 1 rollback: tinjau arsip -> [Ya, pulihkan] / [Batal]."""
    chat_id = query.message.chat_id
    store = context.bot_data["store"]
    try:
        arsip = backup_mod.muat_arsip(store, chat_id, backup_id)
    except backup_mod.BackupError as exc:
        await _edit(query, f"Arsip tidak bisa dipulihkan: {exc}",
                    kb.back_to_menu())
        return
    ringkasan = backup_mod.ringkasan_arsip(arsip["paket"])
    teks = (
        f"Pulihkan arsip {arsip['tanggal']} (v{arsip['versi']})?\n"
        f"Arsip: \"{ringkasan['nama_warung'] or '(belum bernama)'}\" "
        f"Level {ringkasan['level']} · Hari {ringkasan['hari']} · "
        f"Uang {format_rupiah(ringkasan['uang'])}\n"
        "Progres setelah tanggal arsip akan HILANG.\n"
        "Ini langkah 1 dari 2 — masih bisa batal.")
    await _edit(
        query, teks,
        InlineKeyboardMarkup(
            [[
                InlineKeyboardButton(
                    "Ya, Pulihkan",
                    callback_data=f"cepat:rollback_ya:{backup_id}"),
                InlineKeyboardButton("Batal", callback_data="batal:"),
            ]]
        ),
    )


async def _tampilkan_rollback_langkah2(query, context, backup_id: int) -> None:
    """Langkah 2 rollback: konfirmasi upload standar (confirm_keyboard)."""
    chat_id = query.message.chat_id
    store = context.bot_data["store"]
    err = _cek_tulis(context, chat_id, butuh_tier=False)
    if err:
        await _edit(query, err, kb.main_menu())
        return
    try:
        arsip = backup_mod.muat_arsip(store, chat_id, backup_id)
    except backup_mod.BackupError as exc:
        await _edit(query, f"Arsip tidak bisa dipulihkan: {exc}",
                    kb.back_to_menu())
        return
    state, err_state = await _ambil_state_aktif(context, chat_id)
    if err_state:
        await _edit(query, err_state, kb.main_menu())
        return
    pending, teks = build_pending_rollback(
        state, arsip["paket"], arsip["tanggal"], arsip["versi"])
    _audit(pending, "rollback",
           f"pulihkan arsip {arsip['tanggal']} v{arsip['versi']}")
    context.user_data[PENDING_KEY] = pending
    await _edit(query, teks, kb.confirm_keyboard("rollback", pending.get("token")))


# -- /rencana, /statistik ------------------------------------------------------

def _format_rencana(rencana: dict) -> str:
    baris = [
        f"Rencana {rencana['jumlah_hari']} hari "
        f"(hari {rencana['hari_awal']}–{rencana['hari_akhir'] - 1}):",
        f"Uang {format_rupiah(rencana['uang_awal'])} → "
        f"{format_rupiah(rencana['uang_akhir'])}",
        f"Omzet {format_rupiah(rencana['omzet'])} · "
        f"Laba {format_rupiah(rencana['laba'])} · "
        f"Biaya {format_rupiah(rencana['biaya_harian'])} · "
        f"Sewa {format_rupiah(rencana['sewa'])} · "
        f"Hadiah {format_rupiah(rencana['hadiah'])}",
        f"Dilayani {rencana['dilayani']} · Batal {rencana['batal']}",
        "",
    ]
    if rencana["restock"]:
        baris.append("Restock (habis dalam simulasi):")
        for r in rencana["restock"]:
            baris.append(
                f"- {r['nama']}: stok {r['stok_awal']} → {r['stok_akhir']} "
                f"(terjual {r['terjual']}) — beli {r['saran_beli']} "
                f"({format_rupiah(r['biaya'])})")
    else:
        baris.append("Restock: stok cukup untuk 7 hari simulasi.")
    if rencana["sudah_habis"]:
        nama = ", ".join(r["nama"] for r in rencana["sudah_habis"])
        baris.append(
            f"Stok sudah 0 sejak awal (tidak terukur di simulasi): {nama}.")
    if rencana["upgrade"]:
        baris.append("")
        baris.append("Upgrade (cepat balik modal):")
        for u in rencana["upgrade"]:
            cukup = "uang cukup di akhir rencana" if u["uang_cukup_akhir"] else "uang belum cukup"
            baris.append(
                f"- {u['nama']}: {format_rupiah(u['harga'])} — balik modal "
                f"{u['hari_balik_modal']} hari ({cukup})")
    naik = rencana["kapan_naik"]
    if naik.get("naik") and naik.get("hari") is not None:
        baris.append("")
        baris.append(
            f"Naik level dalam {naik['hari']} hari (simulasi).")
    elif naik.get("blocker"):
        baris.append("")
        baris.append("Naik level terhalang: " + "; ".join(naik["blocker"]))
    if rencana["diusir"]:
        baris.append("")
        baris.append("PERINGATAN: dalam rencana ini warung DIUSIR "
                     "(tunggakan sewa 3 minggu).")
    baris.append("")
    baris.append("Proyeksi simulasi, bukan hasil main sungguhan — RNG, "
                 "event acak, dan pilihan cerita tidak disimulasikan.")
    return "\n".join(baris)


async def cmd_rencana(update, context) -> None:
    message = update.message
    if message is None or not _allowed(context, message.chat_id):
        return
    state, err_state = await _ambil_state_aktif(context, message.chat_id)
    if err_state:
        await message.reply_text(err_state, reply_markup=kb.main_menu())
        return
    rencana = strategi_mod.rencana_7_hari(
        state["slot"], context.bot_data["data"], context.bot_data["tugas"])
    await message.reply_text(
        _format_rencana(rencana), reply_markup=kb.back_to_menu())


def _format_statistik(stat: dict) -> str:
    baris = [
        f"Statistik — Hari {stat['hari']}:",
        f"Hari ini: omzet {format_rupiah(stat['hari_ini']['omzet'])} · "
        f"laba {format_rupiah(stat['hari_ini']['laba'])} · "
        f"terjual {stat['hari_ini']['terjual']} · "
        f"dilayani {stat['hari_ini']['dilayani']} · "
        f"batal {stat['hari_ini']['batal']}",
        "",
    ]
    if stat["terlaris_hari_ini"]:
        t = stat["terlaris_hari_ini"]
        baris.append(
            f"Barang terlaris hari ini: {t['nama']} — {t['jumlah']} terjual "
            f"({format_rupiah(t['omzet'])}).")
        if len(stat["per_barang_hari_ini"]) > 1:
            baris.append("Lainnya hari ini:")
            for p in stat["per_barang_hari_ini"][1:5]:
                baris.append(
                    f"- {p['nama']}: {p['jumlah']} "
                    f"({format_rupiah(p['omzet'])})")
    else:
        baris.append("Belum ada penjualan hari ini.")
    baris.append("")
    baris.append(
        f"Riwayat {stat['jumlah_hari_riwayat']} hari: "
        f"omzet total {format_rupiah(stat['total_omzet'])} · "
        f"rata-rata {format_rupiah(stat['rata_omzet_hari'])}/hari · "
        f"barang {stat['total_barang']} · "
        f"dilayani {stat['total_dilayani']} · batal {stat['total_batal']}")
    if stat["hari_terbaik"]:
        baris.append(
            f"Hari terbaik: hari {stat['hari_terbaik']['hari']} "
            f"({format_rupiah(stat['hari_terbaik']['omzet'])}).")
    if stat["hari_terburuk"]:
        baris.append(
            f"Hari terburuk: hari {stat['hari_terburuk']['hari']} "
            f"({format_rupiah(stat['hari_terburuk']['omzet'])}).")
    baris.append("")
    baris.append("Pelanggan tersering: " + stat["alasan_tanpa_pelanggan"])
    return "\n".join(baris)


async def cmd_statistik(update, context) -> None:
    message = update.message
    if message is None or not _allowed(context, message.chat_id):
        return
    state, err_state = await _ambil_state_aktif(context, message.chat_id)
    if err_state:
        await message.reply_text(err_state, reply_markup=kb.main_menu())
        return
    stat = statistik_mod.statistik_slot(state["slot"],
                                        context.bot_data["data"])
    await message.reply_text(
        _format_statistik(stat), reply_markup=kb.back_to_menu())


# -- callback -----------------------------------------------------------------

async def on_callback_cepat(update, context, query, data_str: str) -> None:
    """Callback 'cepat:*' (dirutekan dari handlers.on_callback)."""
    chat_id = query.message.chat_id if query.message else 0
    bagian = data_str.split(":")
    if len(bagian) < 2:
        await _edit(query, "Tombol tidak dikenal.", kb.main_menu())
        return
    aksi = bagian[1]

    if aksi == "menu":
        await _tampilkan_menu_cepat(query, context)
        return

    if aksi == "cmd":
        if len(bagian) < 3:
            await _edit(query, "Tombol tidak dikenal.", kb.main_menu())
            return
        perintah = bagian[2]
        # Jalankan alur perintah yang sama seperti /<perintah>, tapi dari
        # tombol: buat update tiruan dengan message = pesan callback.
        tiruan = _UpdateTiruan(query.message)
        if perintah == "jual":
            await cmd_jual(tiruan, context)
        elif perintah == "beli":
            await cmd_beli(tiruan, context)
        elif perintah == "ngopi":
            await cmd_ngopi(tiruan, context)
        elif perintah == "tutup":
            await cmd_tutup(tiruan, context)
        elif perintah == "slot":
            await cmd_slot(tiruan, context)
        elif perintah == "backup":
            await cmd_backup(tiruan, context)
        elif perintah == "rencana":
            await cmd_rencana(tiruan, context)
        elif perintah == "statistik":
            await cmd_statistik(tiruan, context)
        else:
            await _edit(query, "Tombol tidak dikenal.", kb.main_menu())
        return

    if aksi == "slot":
        if len(bagian) < 3:
            await _edit(query, "Tombol tidak dikenal.", kb.main_menu())
            return
        try:
            nomor = int(bagian[2])
        except ValueError:
            await _edit(query, "Tombol tidak dikenal.", kb.main_menu())
            return
        store = context.bot_data["store"]
        if nomor == 0:
            store.set_slot_aktif(chat_id, None)
            teks = ("Slot aktif dikembalikan ke slot terbaik (level lalu "
                    "hari).")
        else:
            state, err_state = await _ambil_state_aktif(context, chat_id)
            if err_state:
                await _edit(query, err_state, kb.main_menu())
                return
            daftar = cepat_mod.daftar_slot(state["paket"])
            entri = next((e for e in daftar if e["nomor"] == nomor), None)
            if entri is None or entri.get("kosong") or entri.get("rusak"):
                await _edit(query, f"Slot {nomor} kosong/rusak.",
                            kb.back_to_menu())
                return
            store.set_slot_aktif(chat_id, nomor)
            teks = (f"Slot aktif: slot {nomor} "
                    f"\"{entri['nama_warung'] or '(belum bernama)'}\" "
                    f"Level {entri['level']} · Hari {entri['hari']}. "
                    "Bot memakai slot ini untuk status, simulasi, "
                    "aksi cepat, dan siklus otomatis.")
        store.log_audit(chat_id, "pilih_slot", teks)
        await _edit(query, teks, kb.back_to_menu())
        return

    if aksi == "rollback":
        if len(bagian) < 3:
            await _edit(query, "Tombol tidak dikenal.", kb.main_menu())
            return
        try:
            backup_id = int(bagian[2])
        except ValueError:
            await _edit(query, "Tombol tidak dikenal.", kb.main_menu())
            return
        await _tampilkan_rollback_langkah1(query, context, backup_id)
        return

    if aksi == "rollback_ya":
        if len(bagian) < 3:
            await _edit(query, "Tombol tidak dikenal.", kb.main_menu())
            return
        try:
            backup_id = int(bagian[2])
        except ValueError:
            await _edit(query, "Tombol tidak dikenal.", kb.main_menu())
            return
        await _tampilkan_rollback_langkah2(query, context, backup_id)
        return

    await _edit(query, "Tombol tidak dikenal.", kb.main_menu())


class _PesanTiruan:
    """Pesan tiruan: reply_text mengedit pesan tombol, bukan pesan baru.

    Pola bot satu pesan per layar — handler perintah yang dipanggil
    dari tombol harus mengedit pesan yang sama.
    """

    def __init__(self, message) -> None:
        self._message = message
        self.chat_id = message.chat_id
        self.text = getattr(message, "text", None)

    async def reply_text(self, teks: str, reply_markup=None, **kwargs):
        try:
            return await self._message.edit_text(
                teks, reply_markup=reply_markup, **kwargs)
        except Exception:  # noqa: BLE001 - pesan sama/sudah terhapus
            return await self._message.reply_text(
                teks, reply_markup=reply_markup, **kwargs)


class _UpdateTiruan:
    """Update tiruan supaya handler perintah bisa dipakai dari tombol."""

    def __init__(self, message) -> None:
        self.message = _PesanTiruan(message)
