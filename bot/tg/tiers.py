"""Perintah Fase 3 — Kerja 24/7 (tiga tier).

Perintah (tanpa parameter; semua pilihan lewat tombol inline):
/tier, /otomatis, /laporan, /bandingkan.

Callback yang ditangani di sini: "tier:*", "otomatis:*", "target:*",
"login:*", "laporan:*" — dipanggil dari handlers.on_callback.

Penegakan tier di KODE (bukan cuma di UI): /bandingkan butuh
Profesional; siklus otomatis hanya menjalankan aksi sesuai tier yang
tersimpan (lihat bot/core/tiers.py + bot/core/auto.py). Bila tier
pengguna lebih rendah, perintah ditolak dengan pesan yang menyebut
tier yang dibutuhkan.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from ..core import auto as auto_mod
from ..core import jobs as jobs_mod
from ..core import plan as plan_mod
from ..core import save as save_mod
from ..core import sim as sim_mod
from ..core import target as target_mod
from ..core import tiers as tiers_mod
from ..core.cloud import CloudError, NoCloudData, SessionExpired
from . import keyboards as kb
from .status import NotLinked, fetch_latest_state, format_rupiah

log = logging.getLogger(__name__)

TIER_BANDINGKAN_FITUR = "rencana_level"


def _fitur_tier(n: int) -> list[str]:
    """Nama fitur yang tersedia pada tier n (minimum <= n)."""
    return [tiers_mod.FITUR_NAMA[f]
            for f, minimum in tiers_mod.FITUR_MIN_TIER.items()
            if minimum <= n]


def _teks_tier(n: int) -> str:
    nama = tiers_mod.TIER_NAMA[n]
    return (
        f"Tier {n} — {nama}\n{tiers_mod.TIER_DESKRIPSI[n]}\n"
        f"Fitur: {', '.join(_fitur_tier(n))}"
    )


def _keyboard_tier(tier_sekarang: int) -> InlineKeyboardMarkup:
    baris = []
    for n in (1, 2, 3):
        label = tiers_mod.TIER_NAMA[n]
        if n == tier_sekarang:
            label += " (aktif)"
        baris.append([InlineKeyboardButton(label, callback_data=f"tier:{n}")])
    baris.append([InlineKeyboardButton("Kembali ke Menu",
                                       callback_data="menu:root")])
    return InlineKeyboardMarkup(baris)


async def cmd_tier(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return
    store = context.bot_data["store"]
    if store.get_user(message.chat_id) is None:
        await message.reply_text("Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    tier = store.get_tier(message.chat_id)
    otomatis = store.get_otomatis(message.chat_id)
    teks = (
        "Kerja 24/7 — pilih tier.\n\n"
        f"Tier aktif: {tier} ({tiers_mod.TIER_NAMA[tier]}), "
        f"otomatisasi: {'nyala' if otomatis else 'mati'}.\n\n"
        + "\n\n".join(_teks_tier(n) for n in (1, 2, 3))
        + "\n\nPilih tier untuk melihat penjelasan dan mengaktifkannya."
    )
    await message.reply_text(teks, reply_markup=_keyboard_tier(tier))


async def cmd_otomatis(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tampilkan status otomatisasi + tombol Nyalakan/Matikan.

    Sengaja TANPA parameter (on/off lewat tombol) sesuai §15:
    perintah hanya untuk meta-action.
    """
    message = update.message
    if message is None:
        return
    store = context.bot_data["store"]
    if store.get_user(message.chat_id) is None:
        await message.reply_text("Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    teks, markup = _panel_otomatis(store, message.chat_id)
    await message.reply_text(teks, reply_markup=markup)


def _panel_otomatis(store, chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Teks + tombol panel /otomatis (dipakai perintah dan callback)."""
    tier = store.get_tier(chat_id)
    otomatis = store.get_otomatis(chat_id)
    jam = store.get_jam_otomatis(chat_id)
    mode = store.get_mode_target(chat_id)
    teks = (
        f"Otomatisasi: {'NYALA' if otomatis else 'MATI'}\n"
        f"Tier: {tier} ({tiers_mod.TIER_NAMA[tier]})\n"
        f"Jam siklus harian: {jam:02d}.00 WIB\n"
        f"Mode Target Level: "
        f"{'NYALA — target Level ' + str(mode['target_tingkat']) + ' (siklus ' + str(mode['siklus']) + ')' if mode else 'MATI'}\n\n"
        "Bila nyala, bot menjalankan siklus tiap hari pada jam itu: "
        "ambil simpanan terbaru, jalankan aksi sesuai tier, unggah sekali. "
        "Game harus TERTUTUP saat siklus jalan — bila game terbuka dan "
        "mengunggah, siklus dibatalkan supaya tidak ada yang tertimpa."
    )
    baris = [
        [InlineKeyboardButton(
            "Nyalakan" if not otomatis else "Matikan",
            callback_data="otomatis:nyala" if not otomatis else "otomatis:mati")],
    ]
    if mode:
        baris.append([InlineKeyboardButton(
            "Berhentikan Mode Target", callback_data="target:berhenti")])
    else:
        baris.append([InlineKeyboardButton(
            "Mode Target Level", callback_data="target:pilih")])
    baris.append([InlineKeyboardButton("Kembali ke Menu",
                                       callback_data="menu:root")])
    return teks, InlineKeyboardMarkup(baris)


def _keyboard_pilih_level() -> InlineKeyboardMarkup:
    """Tombol pilih level tujuan Mode Target (2-10, tanpa parameter)."""
    baris = []
    angka = list(range(2, target_mod.LEVEL_MAKSIMAL + 1))
    for i in range(0, len(angka), 3):
        baris.append([
            InlineKeyboardButton(f"Level {n}",
                                 callback_data=f"target:konfirmasi:{n}")
            for n in angka[i:i + 3]
        ])
    baris.append([InlineKeyboardButton("Batal", callback_data="target:batal")])
    return InlineKeyboardMarkup(baris)


async def cmd_laporan(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return
    await _kirim_laporan(message, context, hari=1)


async def _kirim_laporan(message, context, hari: int) -> None:
    chat_id = message.chat_id
    store = context.bot_data["store"]
    if store.get_user(chat_id) is None:
        await message.reply_text("Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    try:
        state = await fetch_latest_state(context, chat_id)
    except NotLinked:
        await message.reply_text("Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    except SessionExpired:
        await message.reply_text(
            "Sesi login habis. Kirim ulang akun.json dari game dengan /link.")
        return
    except NoCloudData:
        await message.reply_text("Belum ada simpanan di cloud.")
        return
    except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
        await message.reply_text(f"Tidak bisa mengambil laporan: {exc}")
        return
    label = "harian" if hari == 1 else "mingguan"
    sejak = int((datetime.now(auto_mod.WIB) - timedelta(days=hari)).timestamp())
    audit = store.get_audit(chat_id, sejak)
    ringkasan = state["ringkasan"]
    slot = state["slot"]
    baris = [
        f"Laporan {label} — {ringkasan.get('nama') or 'warung'} "
        f"(level {ringkasan.get('level')}, hari {ringkasan.get('hari')})",
        f"Uang: {format_rupiah(ringkasan['uang'])}",
        f"Pelanggan dilayani total: {int(slot.get('total_pembeli', 0))}",
    ]
    lacak = store.get_login_lacak(chat_id)
    if lacak["hari_ke"]:
        baris.append(
            f"Login harian (dilacak bot): hari ke-{lacak['hari_ke']} "
            f"(terakhir {lacak['tanggal'] or '-'})")
    peringkat = store.get_peringkat(chat_id, "semua")
    if peringkat and peringkat["peringkat"]:
        baris.append(
            f"Peringkat papan: #{peringkat['peringkat']} "
            f"dari {peringkat['jumlah_warung']} warung")
    if audit:
        baris.append("")
        baris.append(f"Aksi otomatis ({len(audit)}):")
        for entri in reversed(audit):
            waktu = datetime.fromtimestamp(
                entri["waktu"], auto_mod.WIB).strftime("%d %b %H:%M")
            baris.append(
                f"- {waktu} {entri['aksi']}"
                + (f": {entri['detail']}" if entri["detail"] else ""))
    else:
        baris.append("")
        baris.append("Tidak ada aksi otomatis tercatat di periode ini.")
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(
                "Laporan Mingguan" if hari == 1 else "Laporan Harian",
                callback_data="laporan:minggu" if hari == 1 else "laporan:harian")],
            [InlineKeyboardButton("Kembali ke Menu", callback_data="menu:root")],
        ]
    )
    await message.reply_text("\n".join(baris), reply_markup=markup)


async def cmd_bandingkan(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return
    store = context.bot_data["store"]
    if store.get_user(message.chat_id) is None:
        await message.reply_text("Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    try:
        tiers_mod.require_tier(store.get_tier(message.chat_id),
                               TIER_BANDINGKAN_FITUR)
    except tiers_mod.TierError as exc:
        await message.reply_text(str(exc))
        return
    try:
        state = await fetch_latest_state(context, message.chat_id)
    except NotLinked:
        await message.reply_text("Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    except SessionExpired:
        await message.reply_text(
            "Sesi login habis. Kirim ulang akun.json dari game dengan /link.")
        return
    except NoCloudData:
        await message.reply_text("Belum ada simpanan di cloud.")
        return
    except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
        await message.reply_text(f"Tidak bisa membandingkan: {exc}")
        return
    await message.reply_text(
        "Membandingkan strategi harga (simulasi 1 hari, seed sama)…")
    teks = _bandingkan_strategi(state["slot"], context.bot_data["data"])
    await message.reply_text(teks, reply_markup=kb.back_to_menu())


def _bandingkan_strategi(slot: dict, data: sim_mod.GameData) -> str:
    """Bandingkan 4 strategi harga dalam simulasi 1 hari (seed sama).

    Strategi: harga sekarang; ikut harga pasar; murah 10%; terbaik
    (brute force per barang, ulang=1 supaya cepat). Hasil = PROYEKSI.
    """
    seed = 12345
    strategi: list[tuple[str, dict]] = []

    sekarang = sim_mod.simulate(slot, data, 1, seed=seed)
    strategi.append(("Harga sekarang", sekarang))

    slot_pasar = sim_mod._normalisasi_slot(slot)
    khusus = dict(slot_pasar.get("harga_jual_khusus", {}) or {})
    for item_id in data.urutan_barang:
        if data.katalog[item_id]["jenis"] != "fisik":
            continue
        if item_id not in (slot.get("barang_terbuka", []) or []):
            continue
        if int((slot.get("stok", {}) or {}).get(item_id, 0)) <= 0:
            continue
        khusus[item_id] = sim_mod.harga_pasar(data, item_id, slot)
    slot_pasar["harga_jual_khusus"] = khusus
    strategi.append(("Ikut harga pasar",
                     sim_mod.simulate(slot_pasar, data, 1, seed=seed)))

    slot_murah = sim_mod._normalisasi_slot(slot)
    khusus = dict(slot_murah.get("harga_jual_khusus", {}) or {})
    for item_id in data.urutan_barang:
        if data.katalog[item_id]["jenis"] != "fisik":
            continue
        if item_id not in (slot.get("barang_terbuka", []) or []):
            continue
        if int((slot.get("stok", {}) or {}).get(item_id, 0)) <= 0:
            continue
        lantai = sim_mod.lantai_harga(data, item_id, slot)
        langkah = sim_mod.langkah_harga(data, item_id)
        harga = sim_mod.harga_jual(data, item_id, slot)
        murah = max(lantai, (int(harga * 0.9) // langkah) * langkah)
        khusus[item_id] = murah
    slot_murah["harga_jual_khusus"] = khusus
    strategi.append(("Murah 10%",
                     sim_mod.simulate(slot_murah, data, 1, seed=seed)))

    terbaik = plan_mod.harga_terbaik(slot, data, seed=seed, ulang=1)
    slot_terbaik = sim_mod._normalisasi_slot(slot)
    khusus = dict(slot_terbaik.get("harga_jual_khusus", {}) or {})
    for entri in terbaik:
        khusus[entri["id"]] = entri["harga_terbaik"]
    slot_terbaik["harga_jual_khusus"] = khusus
    strategi.append(("Harga terbaik (brute force)",
                     sim_mod.simulate(slot_terbaik, data, 1, seed=seed)))

    baris = ["Perbandingan strategi harga — simulasi 1 hari (proyeksi):"]
    for nama, hasil in strategi:
        baris.append(
            f"{nama}: omzet {format_rupiah(hasil['omzet'])} · "
            f"laba {format_rupiah(hasil['laba'])} · "
            f"dilayani {hasil['dilayani']} · batal {hasil['batal']}")
    pemenang = max(strategi, key=lambda s: s[1]["laba"])
    baris.append(f"\nLaba tertinggi (proyeksi): {pemenang[0]}.")
    baris.append("Ini proyeksi simulasi, bukan hasil main sungguhan.")
    return "\n".join(baris)


# -- callback ----------------------------------------------------------

async def _tangani_target(query, context, chat_id: int, data: str) -> bool:
    """Callback Mode Target Level: pilih/konfirmasi/mulai/berhenti.

    Alur (tanpa parameter perintah, §15): pilih level -> konfirmasi
    (apa yang akan bot belanjakan) -> mulai. Mulai memvalidasi ulang
    tier + level tujuan terhadap save terbaru — tombol lama yang
    kedaluwarsa ditolak, bukan dijalankan buta.
    """
    from ..core import tiers as tiers_core

    store = context.bot_data["store"]
    scheduler = context.bot_data.get("scheduler")

    if data == "target:pilih":
        try:
            tiers_core.require_tier(store.get_tier(chat_id), "mode_target")
        except tiers_core.TierError as exc:
            await query.edit_message_text(str(exc),
                                          reply_markup=kb.back_to_menu())
            return True
        mode = store.get_mode_target(chat_id)
        if mode is not None:
            await query.edit_message_text(
                "Mode Target sudah nyala "
                f"(target Level {mode['target_tingkat']}). Berhentikan dulu "
                "bila mau ganti target.",
                reply_markup=kb.back_to_menu(),
            )
            return True
        await query.edit_message_text(
            "Mode Target Level — pilih level tujuan. Bot jalan tiap "
            f"{target_mod.INTERVAL_MENIT} menit (1 hari game per siklus) "
            "sampai level itu tercapai.",
            reply_markup=_keyboard_pilih_level(),
        )
        return True

    if data == "target:batal":
        teks, markup = _panel_otomatis(store, chat_id)
        await query.edit_message_text(teks, reply_markup=markup)
        return True

    if data == "target:berhenti":
        if store.get_mode_target(chat_id) is None:
            await query.edit_message_text(
                "Mode Target sedang tidak nyala.",
                reply_markup=kb.back_to_menu(),
            )
            return True
        store.hapus_mode_target(chat_id)
        if scheduler is not None:
            jobs_mod.hapus_mode_target(scheduler, chat_id)
        store.log_audit(chat_id, "mode_target_berhenti", "manual")
        await query.edit_message_text(
            "Mode Target Level DIMATIKAN.",
            reply_markup=kb.back_to_menu(),
        )
        return True

    bagian = data.split(":")
    if len(bagian) != 3 or not bagian[2].isdigit():
        return True
    target = int(bagian[2])
    if not 2 <= target <= target_mod.LEVEL_MAKSIMAL:
        return True

    if bagian[1] == "konfirmasi":
        try:
            tiers_core.require_tier(store.get_tier(chat_id), "mode_target")
        except tiers_core.TierError as exc:
            await query.edit_message_text(str(exc),
                                          reply_markup=kb.back_to_menu())
            return True
        try:
            state = await fetch_latest_state(context, chat_id)
        except NotLinked:
            await query.edit_message_text("Belum ada akun tertaut.",
                                          reply_markup=kb.back_to_menu())
            return True
        except SessionExpired:
            await query.edit_message_text(
                "Sesi login habis. Kirim ulang akun.json dengan /link.",
                reply_markup=kb.back_to_menu(),
            )
            return True
        except (NoCloudData, CloudError, save_mod.PackageError,
                save_mod.SlotError) as exc:
            await query.edit_message_text(f"Tidak bisa mengambil status: {exc}",
                                          reply_markup=kb.back_to_menu())
            return True
        level_sekarang = int(state["ringkasan"]["level"])
        if target <= level_sekarang:
            await query.edit_message_text(
                f"Sudah Level {level_sekarang} — pilih target di atas itu.",
                reply_markup=_keyboard_pilih_level(),
            )
            return True
        await query.edit_message_text(
            f"Mode Target Level {target} (sekarang Level {level_sekarang}).\n\n"
            "Bot akan jalan terus tiap "
            f"{target_mod.INTERVAL_MENIT} menit, 1 hari game per siklus:\n"
            "- simulasi jualan + restock + isi tugas (seperti siklus harian)\n"
            "- BAYAR misi cerita Agus bila uang cukup (misi harus lunas "
            "sebelum naik level)\n"
            "- BELI upgrade syarat level bila uang cukup (yang termurah)\n\n"
            "Siklus harian dimatikan selama mode ini nyala (satu otomatisasi "
            "saja). Mode berhenti sendiri saat target tercapai, bila uang "
            "habis dan rak kosong, bila diusir, atau bila game mengunggah "
            "di tengah jalan (bentrok).",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "Ya, mulai", callback_data=f"target:mulai:{target}")],
                [InlineKeyboardButton("Batal", callback_data="target:batal")],
            ]),
        )
        return True

    if bagian[1] == "mulai":
        try:
            tiers_core.require_tier(store.get_tier(chat_id), "mode_target")
        except tiers_core.TierError as exc:
            await query.edit_message_text(str(exc),
                                          reply_markup=kb.back_to_menu())
            return True
        try:
            state = await fetch_latest_state(context, chat_id)
        except NotLinked:
            await query.edit_message_text("Belum ada akun tertaut.",
                                          reply_markup=kb.back_to_menu())
            return True
        except SessionExpired:
            await query.edit_message_text(
                "Sesi login habis. Kirim ulang akun.json dengan /link.",
                reply_markup=kb.back_to_menu(),
            )
            return True
        except (NoCloudData, CloudError, save_mod.PackageError,
                save_mod.SlotError) as exc:
            await query.edit_message_text(f"Tidak bisa mengambil status: {exc}",
                                          reply_markup=kb.back_to_menu())
            return True
        level_sekarang = int(state["ringkasan"]["level"])
        if target <= level_sekarang:
            await query.edit_message_text(
                f"Sudah Level {level_sekarang} — pilih target di atas itu.",
                reply_markup=_keyboard_pilih_level(),
            )
            return True
        # Satu otomatisasi saja: matikan siklus harian bila nyala.
        if store.get_otomatis(chat_id):
            store.set_otomatis(chat_id, False)
            if scheduler is not None:
                jobs_mod.hapus_siklus(scheduler, chat_id)
        store.set_mode_target(chat_id, target)
        if scheduler is not None:
            jobs_mod.atur_mode_target(scheduler, context.application, chat_id)
        store.log_audit(chat_id, "mode_target_mulai",
                        f"Level {level_sekarang} -> {target}")
        await query.edit_message_text(
            f"Mode Target Level {target} DINYALAKAN "
            f"(dari Level {level_sekarang}).\n"
            f"Bot jalan tiap {target_mod.INTERVAL_MENIT} menit, 1 hari game "
            "per siklus. Kabar hanya saat naik level atau mode berhenti.\n"
            "Game harus TERTUTUP selama mode nyala.",
            reply_markup=kb.back_to_menu(),
        )
        return True
    return True


async def on_callback_tier(update, context: ContextTypes.DEFAULT_TYPE,
                           query, data: str) -> bool:
    """Tangani callback tier:/otomatis:/login:/laporan:. True bila ditangani."""
    from ..core import jobs as jobs_mod

    chat_id = query.message.chat_id if query.message else 0
    store = context.bot_data["store"]

    if data.startswith("tier:"):
        bagian = data.split(":")
        if len(bagian) == 2 and bagian[1].isdigit():
            n = int(bagian[1])
            if n not in (1, 2, 3):
                await query.edit_message_text(
                    "Tier tidak dikenal.", reply_markup=_keyboard_tier(store.get_tier(chat_id)))
                return True
            teks = (
                f"Aktifkan Tier {n} — {tiers_mod.TIER_NAMA[n]}?\n\n"
                f"{tiers_mod.TIER_DESKRIPSI[n]}\n\n"
                "Yang akan berjalan otomatis tiap hari pada "
                f"{store.get_jam_otomatis(chat_id):02d}.00 WIB:\n"
                + "\n".join(f"- {f}" for f in _fitur_tier(n))
                + "\n\nGame harus TERTUTUP saat siklus jalan. "
                  "Bot mengambil simpanan terbaru, mengubahnya, lalu "
                  "mengunggah sekali. Bila game terbuka dan mengunggah, "
                  "siklus dibatalkan supaya tidak ada yang tertimpa."
            )
            await query.edit_message_text(
                teks,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton(
                            f"Ya, Aktifkan Tier {n}",
                            callback_data=f"tier:konfirm:{n}")],
                        [InlineKeyboardButton("Batal",
                                              callback_data="tier:menu")],
                    ]
                ),
            )
            return True
        if data == "tier:menu":
            tier = store.get_tier(chat_id)
            await query.edit_message_text(
                "Kerja 24/7 — pilih tier.\n\n"
                + "\n\n".join(_teks_tier(n) for n in (1, 2, 3)),
                reply_markup=_keyboard_tier(tier),
            )
            return True
        if len(bagian) == 3 and bagian[1] == "konfirm" and bagian[2].isdigit():
            n = int(bagian[2])
            if n not in (1, 2, 3):
                await query.edit_message_text("Tier tidak dikenal.")
                return True
            store.set_tier(chat_id, n)
            store.set_otomatis(chat_id, True)
            scheduler = context.bot_data.get("scheduler")
            if scheduler is not None:
                jobs_mod.atur_siklus(scheduler, context.application,
                                     chat_id, store.get_jam_otomatis(chat_id))
            store.log_audit(chat_id, "tier_aktif",
                            f"Tier {n} ({tiers_mod.TIER_NAMA[n]})")
            await query.edit_message_text(
                f"Tier {n} ({tiers_mod.TIER_NAMA[n]}) aktif. "
                "Siklus otomatis jalan tiap hari pada "
                f"{store.get_jam_otomatis(chat_id):02d}.00 WIB. "
                "Matikan kapan saja dengan /otomatis.",
                reply_markup=kb.back_to_menu(),
            )
            return True
        return True

    if data.startswith("otomatis:"):
        if data == "otomatis:nyala":
            # Satu otomatisasi saja yang jalan: Mode Target dimatikan.
            if store.get_mode_target(chat_id) is not None:
                store.hapus_mode_target(chat_id)
                scheduler = context.bot_data.get("scheduler")
                if scheduler is not None:
                    jobs_mod.hapus_mode_target(scheduler, chat_id)
                store.log_audit(chat_id, "mode_target_berhenti",
                                "diganti siklus harian")
            store.set_otomatis(chat_id, True)
            scheduler = context.bot_data.get("scheduler")
            if scheduler is not None:
                jobs_mod.atur_siklus(scheduler, context.application,
                                     chat_id, store.get_jam_otomatis(chat_id))
            store.log_audit(chat_id, "otomatis_nyala",
                            f"tier {store.get_tier(chat_id)}")
            await query.edit_message_text(
                "Otomatisasi DINYALAKAN. Siklus jalan tiap hari pada "
                f"{store.get_jam_otomatis(chat_id):02d}.00 WIB.",
                reply_markup=kb.back_to_menu(),
            )
            return True
        if data == "otomatis:mati":
            store.set_otomatis(chat_id, False)
            scheduler = context.bot_data.get("scheduler")
            if scheduler is not None:
                jobs_mod.hapus_siklus(scheduler, chat_id)
            store.log_audit(chat_id, "otomatis_mati")
            await query.edit_message_text(
                "Otomatisasi DIMATIKAN. Tidak ada siklus yang jalan lagi.",
                reply_markup=kb.back_to_menu(),
            )
            return True
        return True

    if data.startswith("target:"):
        return await _tangani_target(query, context, chat_id, data)

    if data.startswith("login:"):
        if data == "login:lewat":
            await query.edit_message_text(
                "Dilewati. Pengingat besok tetap muncul bila belum klaim.")
            return True
        bagian = data.split(":")
        if len(bagian) == 3 and bagian[1] == "klaim" and bagian[2].isdigit():
            n = int(bagian[2])
            lacak = store.get_login_lacak(chat_id)
            hari_ini = auto_mod.tanggal_wib()
            harapan = auto_mod.login_berikut(int(lacak["hari_ke"]),
                                            str(lacak["tanggal"]), hari_ini)
            if harapan is None:
                await query.edit_message_text(
                    "Sudah dicatat hari ini — tidak perlu klaim dua kali.")
                return True
            if n != harapan:
                await query.edit_message_text(
                    f"Pengingat ini sudah kedaluwarsa (hari ke-{n}, "
                    f"seharusnya hari ke-{harapan}). "
                    "Pengingat baru akan datang besok pagi.")
                return True
            siklus = int(lacak["siklus"])
            store.set_login_lacak(chat_id, n, hari_ini, siklus)
            store.log_audit(chat_id, "login_klaim", f"hari ke-{n}")
            await query.edit_message_text(
                f"Dicatat: login harian hari ke-{n} sudah diklaim. "
                f"{'Kalender 30 hari selesai.' if n >= 30 else 'Pengingat besok pagi.'}")
            return True
        return True

    if data.startswith("laporan:"):
        if data == "laporan:minggu":
            await _edit_laporan(query, context, hari=7)
            return True
        if data == "laporan:harian":
            await _edit_laporan(query, context, hari=1)
            return True
        return True

    return False


async def _edit_laporan(query, context, hari: int) -> None:
    """Versi edit-pesan dari laporan (untuk tombol di layar laporan)."""
    chat_id = query.message.chat_id
    store = context.bot_data["store"]
    try:
        state = await fetch_latest_state(context, chat_id)
    except NotLinked:
        await query.edit_message_text("Belum ada akun tertaut. Tautkan dulu dengan /link.")
        return
    except SessionExpired:
        await query.edit_message_text(
            "Sesi login habis. Kirim ulang akun.json dari game dengan /link.")
        return
    except NoCloudData:
        await query.edit_message_text("Belum ada simpanan di cloud.")
        return
    except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
        await query.edit_message_text(f"Tidak bisa mengambil laporan: {exc}")
        return
    label = "harian" if hari == 1 else "mingguan"
    sejak = int((datetime.now(auto_mod.WIB) - timedelta(days=hari)).timestamp())
    audit = store.get_audit(chat_id, sejak)
    ringkasan = state["ringkasan"]
    slot = state["slot"]
    baris = [
        f"Laporan {label} — {ringkasan.get('nama') or 'warung'} "
        f"(level {ringkasan.get('level')}, hari {ringkasan.get('hari')})",
        f"Uang: {format_rupiah(ringkasan['uang'])}",
        f"Pelanggan dilayani total: {int(slot.get('total_pembeli', 0))}",
    ]
    if audit:
        baris.append("")
        baris.append(f"Aksi otomatis ({len(audit)}):")
        for entri in reversed(audit):
            waktu = datetime.fromtimestamp(
                entri["waktu"], auto_mod.WIB).strftime("%d %b %H:%M")
            baris.append(
                f"- {waktu} {entri['aksi']}"
                + (f": {entri['detail']}" if entri["detail"] else ""))
    else:
        baris.append("")
        baris.append("Tidak ada aksi otomatis tercatat di periode ini.")
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(
                "Laporan Mingguan" if hari == 1 else "Laporan Harian",
                callback_data="laporan:minggu" if hari == 1 else "laporan:harian")],
            [InlineKeyboardButton("Kembali ke Menu", callback_data="menu:root")],
        ]
    )
    await query.edit_message_text("\n".join(baris), reply_markup=markup)
