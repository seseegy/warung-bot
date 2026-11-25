"""Handler Fase 2: simulasi, harga terbaik, stok, jadwal, perencana.

Pola Fase 1 dipertahankan: inline keyboard teks polos tanpa emoji, satu
pesan per layar (callback mengedit pesan yang sama), konfirmasi sebelum
setiap upload (lihat tg/confirm.py: pending "simulasi"/"harga").

Semua angka di sini adalah PROYEKSI simulasi, bukan hasil main sungguhan
— setiap pesan hasil mencantumkan itu dengan jelas.
"""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..core import auto as auto_mod
from ..core import plan as plan_mod
from ..core import save as save_mod
from ..core import sim as sim_mod
from ..core import tiers as tiers_mod
from ..core.cloud import CloudError, NoCloudData, SessionExpired
from . import keyboards as kb
from .confirm import (
    PENDING_KEY,
    build_pending_harga,
    build_pending_harga_pasar,
    build_pending_simulasi,
)
from .status import (
    NotLinked,
    fetch_latest_state,
    format_rupiah,
)

log = logging.getLogger(__name__)

DISCLAIMER = (
    "Proyeksi simulasi, bukan hasil main sungguhan — RNG, event acak, "
    "dan pilihan cerita tidak disimulasikan.")

JAM_LAPORAN_PILIHAN = [6, 7, 8, 9, 12, 18, 20]


# -- keyboard ------------------------------------------------------------

def sim_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Simulasi 1 Hari", callback_data="sim:hari:1"),
                InlineKeyboardButton("Simulasi 3 Hari", callback_data="sim:hari:3"),
            ],
            [
                InlineKeyboardButton("Simulasi 7 Hari", callback_data="sim:hari:7"),
            ],
            [
                InlineKeyboardButton("Harga Terbaik", callback_data="sim:harga"),
                InlineKeyboardButton("Stok", callback_data="sim:stok"),
            ],
            [
                InlineKeyboardButton("Kapan Naik", callback_data="sim:kapan"),
                InlineKeyboardButton("ROI Upgrade", callback_data="sim:roi"),
            ],
            [
                InlineKeyboardButton("What-If Harga", callback_data="sim:whatif"),
                InlineKeyboardButton("Jadwal Laporan", callback_data="sim:jadwal"),
            ],
            [
                InlineKeyboardButton("Kembali ke Menu", callback_data="menu:root"),
            ],
        ]
    )


def sim_apply_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Terapkan ke Save",
                                     callback_data="konfirm:tanya:simulasi"),
                InlineKeyboardButton("Batal", callback_data="konfirm:tidak:simulasi"),
            ],
        ]
    )


def harga_apply_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Terapkan Semua Harga",
                                     callback_data="konfirm:tanya:harga"),
                InlineKeyboardButton("Batal", callback_data="konfirm:tidak:harga"),
            ],
        ]
    )


def jadwal_keyboard(jadwal: dict | None) -> InlineKeyboardMarkup:
    baris = []
    pilihan = [InlineKeyboardButton(f"{jam:02d}:00", callback_data=f"jadwal:jam:{jam}")
               for jam in JAM_LAPORAN_PILIHAN]
    baris.append(pilihan[:4])
    baris.append(pilihan[4:])
    baris.append([InlineKeyboardButton("Ketik Jam Sendiri",
                                       callback_data="jadwal:ketik")])
    if jadwal and jadwal.get("aktif"):
        baris.append([InlineKeyboardButton("Matikan Laporan",
                                           callback_data="jadwal:mati")])
    elif jadwal:
        baris.append([InlineKeyboardButton("Nyalakan Lagi",
                                           callback_data="jadwal:nyala")])
    baris.append([InlineKeyboardButton("Kembali ke Menu",
                                       callback_data="menu:root")])
    return InlineKeyboardMarkup(baris)


# -- format ---------------------------------------------------------------

def format_sim_result(hasil: dict, slot: dict, jumlah_hari: int) -> str:
    baris = [
        f"Simulasi {jumlah_hari} hari (Hari {hasil['hari_awal']} → "
        f"{hasil['hari_akhir'] - 1}):",
        f"Omzet {format_rupiah(hasil['omzet'])} · "
        f"Laba {format_rupiah(hasil['laba'])}",
        f"Uang {format_rupiah(hasil['uang_awal'])} → "
        f"{format_rupiah(hasil['uang_akhir'])}",
        f"QRIS {format_rupiah(hasil['qris_awal'])} → "
        f"{format_rupiah(hasil['qris_akhir'])}",
        f"Dilayani {hasil['dilayani']} · Batal {hasil['batal']} · "
        f"Datang {hasil['datang']}",
    ]
    if hasil["tingkat_akhir"] > hasil["tingkat_awal"]:
        baris.append(
            f"Naik level {hasil['tingkat_awal'] + 1} → "
            f"{hasil['tingkat_akhir'] + 1} (hadiah sudah masuk ke uang).")
    if hasil["tunggakan_sewa"] > 0:
        baris.append(
            f"Peringatan: tunggakan sewa "
            f"{format_rupiah(hasil['tunggakan_sewa'])} "
            f"({hasil['minggu_tunggak']} minggu).")
    libur = sum(1 for h in hasil["hari"] if h.get("libur"))
    if libur:
        baris.append(f"{libur} hari Jumat (libur, tidak ada penjualan).")
    baris.append("")
    baris.append(DISCLAIMER)
    return "\n".join(baris)


def format_stok_table(data, slot: dict) -> str:
    stok = slot.get("stok", {}) or {}
    kiriman = slot.get("kiriman_stok", {}) or {}
    tas = slot.get("tas_grosir", {}) or {}
    terbuka = set(slot.get("barang_terbuka", []) or [])
    uang = int(slot.get("uang", 0))
    baris = ["Stok warung (target isi: 20 per barang):"]
    total_biaya = 0
    rekomendasi = []
    for item_id in data.urutan_barang:
        item = data.katalog[item_id]
        if item["jenis"] != "fisik" or item_id not in terbuka:
            continue
        ada = int(stok.get(item_id, 0))
        if ada > 5:
            continue
        sisa_muat = max(sim_mod.MAKS_STOK_BARANG - ada
                        - int(kiriman.get(item_id, 0))
                        - int(tas.get(item_id, 0)), 0)
        modal = sim_mod.harga_modal(data, item_id, slot)
        perlu = min(max(0, 20 - ada), sisa_muat)
        if perlu <= 0:
            baris.append(f"{item['nama']}: stok {ada} — rak penuh, tidak bisa tambah.")
            continue
        biaya = modal * perlu
        total_biaya += biaya
        rekomendasi.append((item["nama"], ada, perlu, biaya, modal))
        baris.append(
            f"{item['nama']}: stok {ada} → beli {perlu} "
            f"({format_rupiah(biaya)}, modal {format_rupiah(modal)}/pcs)")
    if not rekomendasi and len(baris) == 1:
        baris.append("Semua barang stoknya di atas 5 — tidak ada yang mendesak.")
    else:
        kurir = _info_kurir(data, slot)
        baris.append("")
        baris.append(f"Total biaya: {format_rupiah(total_biaya)} "
                     f"(uang sekarang {format_rupiah(uang)})")
        baris.append(f"Kurir reguler: {kurir}")
        if total_biaya > uang:
            baris.append("Peringatan: uang tidak cukup untuk semua rekomendasi.")
        baris.append("Ini rekomendasi saja — pembelian stok belum diterapkan.")
    return "\n".join(baris)


def _info_kurir(data, slot: dict) -> str:
    """Durasi + ongkir kurir reguler (game_state.gd:5618, KURIR)."""
    d = 20.0
    if sim_mod.efek_upgrade(data, slot.get("upgrade", []) or [], "kurir"):
        d = min(d, sim_mod.efek_upgrade(data, slot.get("upgrade", []) or [], "kurir"))
    if slot.get("motor_baru"):
        d *= 0.6
    detik = max(30.0 * d / 20.0, 1.0)
    level = int(slot.get("tingkat", 0)) + 1
    ongkir = 0 if level <= sim_mod.ONGKIR_REGULER_GRATIS_SAMPAI_LEVEL else 10000
    return f"~{detik:.0f} detik, ongkir {format_rupiah(ongkir)}"


# -- perintah ---------------------------------------------------------------

async def _ambil_state(context, chat_id: int):
    """Ambil state terbaru; kembalikan (state, pesan_error)."""
    try:
        return await fetch_latest_state(context, chat_id), None
    except NotLinked:
        return None, "Belum ada akun tertaut. Tautkan dulu dengan /link."
    except SessionExpired:
        return None, "Sesi login habis. Kirim ulang akun.json dari game dengan /link."
    except NoCloudData:
        return None, "Belum ada simpanan di cloud."
    except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
        return None, f"Tidak bisa mengambil simpanan: {exc}"


async def cmd_simulasi(update, context) -> None:
    message = update.message
    if message is None:
        return
    state, err = await _ambil_state(context, message.chat_id)
    if err:
        await message.reply_text(err)
        return
    await message.reply_text(
        "Simulasi — pilih berapa hari mau disimulasikan dari simpanan "
        "terbaru. Hasilnya proyeksi; terapkan hanya bila kamu setuju.",
        reply_markup=sim_menu_keyboard(),
    )


async def cmd_harga_terbaik(update, context) -> None:
    message = update.message
    if message is None:
        return
    await _jalankan_harga_terbaik(message, context, edit=False)


async def cmd_harga_pasar(update, context) -> None:
    message = update.message
    if message is None:
        return
    await _jalankan_harga_pasar(message, context, edit=False)


async def cmd_stok(update, context) -> None:
    message = update.message
    if message is None:
        return
    state, err = await _ambil_state(context, message.chat_id)
    if err:
        await message.reply_text(err)
        return
    await message.reply_text(
        format_stok_table(context.bot_data["data"], state["slot"]),
        reply_markup=kb.back_to_menu(),
    )


async def cmd_jadwal(update, context) -> None:
    message = update.message
    if message is None:
        return
    await _tampilkan_jadwal(message, context)


async def _tampilkan_jadwal(message, context) -> None:
    jadwal = context.bot_data["store"].get_jadwal(message.chat_id)
    if jadwal is None:
        teks = ("Laporan harian belum diatur.\n"
                "Pilih jam (WIB) — bot akan mengirim ringkasan warung tiap "
                "pagi pada jam itu.")
    elif jadwal.get("aktif"):
        teks = (f"Laporan harian aktif tiap {jadwal['jam']:02d}:00 WIB.\n"
                "Pilih jam lain untuk mengubah, atau matikan.")
    else:
        teks = (f"Laporan harian mati (terakhir {jadwal['jam']:02d}:00 WIB).\n"
                "Pilih jam untuk menyalakan lagi.")
    await message.reply_text(teks, reply_markup=jadwal_keyboard(jadwal))


async def cmd_kapan_naik(update, context) -> None:
    message = update.message
    if message is None:
        return
    state, err = await _ambil_state(context, message.chat_id)
    if err:
        await message.reply_text(err)
        return
    hasil = plan_mod.kapan_naik(state["slot"], context.bot_data["data"])
    await message.reply_text(_format_kapan(hasil, state["slot"]),
                             reply_markup=kb.back_to_menu())


def _format_kapan(hasil: dict, slot: dict) -> str:
    tingkat = int(slot.get("tingkat", 0))
    if hasil.get("alasan") == "sudah level terakhir":
        return "Sudah di level terakhir (Level 11 'Coming Soon') — tidak ada tugas lagi."
    baris = [f"Naik ke Level {tingkat + 2}:"]
    if hasil["hari"] == 0:
        baris.append("Progres sudah memenuhi target — sudah bisa naik "
                     "(game akan menaikkan saat berikutnya mengecek tugas).")
    elif hasil["naik"]:
        baris.append(f"Perkiraan {hasil['hari']} hari lagi pada laju simulasi.")
    else:
        baris.append(f"Belum naik dalam {plan_mod.MAKS_HARI_KAPAN_NAIK} hari simulasi.")
    baris.append(f"Laju rata-rata: omzet {format_rupiah(hasil['rata_omzet'])}/hari · "
                 f"laba {format_rupiah(hasil['rata_laba'])}/hari.")
    if hasil["blocker"]:
        baris.append("")
        baris.append("Penghalang (harus diatasi dulu di game):")
        baris.extend(f"- {b}" for b in hasil["blocker"])
    baris.append("")
    baris.append(DISCLAIMER)
    return "\n".join(baris)


async def cmd_roi_upgrade(update, context) -> None:
    message = update.message
    if message is None:
        return
    state, err = await _ambil_state(context, message.chat_id)
    if err:
        await message.reply_text(err)
        return
    hasil = plan_mod.roi_upgrade(state["slot"], context.bot_data["data"])
    await message.reply_text(_format_roi(hasil),
                             reply_markup=kb.back_to_menu())


def _format_roi(hasil: list) -> str:
    if not hasil:
        return ("Semua upgrade sudah dimiliki, atau belum ada yang bisa dibeli "
                "di level ini.")
    baris = ["ROI upgrade — diurutkan dari yang paling cepat balik modal:",
             "(perkiraan 3 hari simulasi; laba tambahan bersih sudah "
             "dikurangi biaya harian upgrade)"]
    for entri in hasil:
        if entri["hari_balik_modal"] is not None:
            baris.append(
                f"{entri['nama']}: {format_rupiah(entri['harga'])} → "
                f"balik modal ~{entri['hari_balik_modal']} hari "
                f"(+{format_rupiah(entri['laba_tambahan_per_hari'])}/hari)")
        else:
            baris.append(
                f"{entri['nama']}: {format_rupiah(entri['harga'])} → "
                f"tidak terukur ({entri['catatan']})")
        if not entri["uang_cukup"]:
            baris[-1] += " — uang belum cukup"
    return "\n".join(baris)


async def cmd_whatif(update, context) -> None:
    message = update.message
    if message is None:
        return
    state, err = await _ambil_state(context, message.chat_id)
    if err:
        await message.reply_text(err)
        return
    data = context.bot_data["data"]
    terbuka = set(state["slot"].get("barang_terbuka", []) or [])
    daftar = [f"{i} ({data.katalog[i]['nama']})"
              for i in data.urutan_barang
              if data.katalog[i]["jenis"] == "fisik" and i in terbuka]
    context.user_data["awaiting"] = "whatif_input"
    await message.reply_text(
        "What-if harga — ketik harga yang mau dicoba, satu barang per baris "
        "atau dipisah koma.\n"
        "Contoh:\nmi_goreng 4000\nteh_botol 5000\n\n"
        "Barang yang bisa diubah: " + ", ".join(daftar) + "\n\n"
        "Kirim /batal untuk berhenti.",
        reply_markup=kb.back_to_menu(),
    )


# -- callback ---------------------------------------------------------------

async def on_callback_sim(update, context, query, data_str: str) -> None:
    """Router callback awalan sim:/jadwal:/whatif: (dipanggil handlers)."""
    chat_id = query.message.chat_id if query.message else 0
    if data_str.startswith("sim:"):
        await _callback_sim(query, context, data_str)
        return
    if data_str.startswith("jadwal:"):
        await _callback_jadwal(query, context, data_str)
        return


async def _callback_sim(query, context, data_str: str) -> None:
    from .handlers import _edit

    chat_id = query.message.chat_id
    bagian = data_str.split(":")
    if data_str == "sim:menu":
        await _edit(query,
                    "Simulasi & Perencana — pilih apa yang mau dihitung dari "
                    "simpanan terbaru. Semua hasil adalah proyeksi.",
                    sim_menu_keyboard())
        return
    if len(bagian) >= 3 and bagian[1] == "hari":
        try:
            jumlah_hari = int(bagian[2])
        except ValueError:
            await _edit(query, "Jumlah hari tidak dikenal.", sim_menu_keyboard())
            return
        state, err = await _ambil_state(context, chat_id)
        if err:
            await _edit(query, err, kb.back_to_menu())
            return
        hasil = sim_mod.simulate(state["slot"], context.bot_data["data"],
                                 jumlah_hari)
        pending, teks = build_pending_simulasi(state, hasil)
        context.user_data[PENDING_KEY] = pending
        await _edit(query, _teks_sim_dengan_konfirmasi(
            hasil, state, pending, teks), sim_apply_keyboard())
        return
    if data_str == "sim:harga":
        await _jalankan_harga_terbaik(query, context, edit=True)
        return
    if data_str == "sim:harga_pasar":
        await _jalankan_harga_pasar(query, context, edit=True)
        return
    if data_str == "sim:stok":
        state, err = await _ambil_state(context, chat_id)
        if err:
            await _edit(query, err, kb.back_to_menu())
            return
        await _edit(query, format_stok_table(context.bot_data["data"], state["slot"]),
                    kb.back_to_menu())
        return
    if data_str == "sim:kapan":
        state, err = await _ambil_state(context, chat_id)
        if err:
            await _edit(query, err, kb.back_to_menu())
            return
        hasil = plan_mod.kapan_naik(state["slot"], context.bot_data["data"])
        await _edit(query, _format_kapan(hasil, state["slot"]), kb.back_to_menu())
        return
    if data_str == "sim:roi":
        state, err = await _ambil_state(context, chat_id)
        if err:
            await _edit(query, err, kb.back_to_menu())
            return
        hasil = plan_mod.roi_upgrade(state["slot"], context.bot_data["data"])
        await _edit(query, _format_roi(hasil), kb.back_to_menu())
        return
    if data_str == "sim:whatif":
        await _mulai_whatif_callback(query, context)
        return
    if data_str == "sim:jadwal":
        await _tampilkan_jadwal_callback(query, context)
        return
    await _edit(query, "Tombol tidak dikenal.", sim_menu_keyboard())


def _teks_sim_dengan_konfirmasi(hasil: dict, state: dict, pending: dict,
                                teks_konfirmasi: str) -> str:
    """Gabung ringkasan simulasi + layar konfirmasi terapkan."""
    ringkasan = format_sim_result(hasil, state["slot"], len(hasil["hari"]))
    return ringkasan + "\n\n" + teks_konfirmasi


async def _mulai_whatif_callback(query, context) -> None:
    from .handlers import _edit

    chat_id = query.message.chat_id
    state, err = await _ambil_state(context, chat_id)
    if err:
        await _edit(query, err, kb.back_to_menu())
        return
    data = context.bot_data["data"]
    terbuka = set(state["slot"].get("barang_terbuka", []) or [])
    daftar = [f"{i} ({data.katalog[i]['nama']})"
              for i in data.urutan_barang
              if data.katalog[i]["jenis"] == "fisik" and i in terbuka]
    context.user_data["awaiting"] = "whatif_input"
    await _edit(query,
                "What-if harga — ketik harga yang mau dicoba, satu barang "
                "per baris atau dipisah koma.\n"
                "Contoh:\nmi_goreng 4000\nteh_botol 5000\n\n"
                "Barang yang bisa diubah: " + ", ".join(daftar) + "\n\n"
                "Kirim /batal untuk berhenti.",
                kb.back_to_menu())


async def _jalankan_harga_terbaik(target, context, edit: bool) -> None:
    """Hitung harga terbaik lalu tampilkan (pesan baru atau edit)."""
    from .handlers import _edit

    if edit:
        chat_id = target.message.chat_id
        await _edit(target, "Menghitung harga terbaik (simulasi per barang, "
                    "mungkin butuh beberapa detik)…", kb.back_to_menu())
    else:
        chat_id = target.chat_id
        await target.reply_text("Menghitung harga terbaik (simulasi per barang, "
                                "mungkin butuh beberapa detik)…")
    state, err = await _ambil_state(context, chat_id)
    if err:
        if edit:
            await _edit(target, err, kb.back_to_menu())
        else:
            await target.reply_text(err)
        return
    hasil = plan_mod.harga_terbaik(state["slot"], context.bot_data["data"])
    if not hasil:
        teks = "Tidak ada barang fisik terbuka yang ada stoknya untuk dinilai."
        if edit:
            await _edit(target, teks, kb.back_to_menu())
        else:
            await target.reply_text(teks)
        return
    harga_baru = {e["id"]: e["harga_terbaik"] for e in hasil
                  if e["harga_terbaik"] != e["harga_sekarang"]}
    baris = ["Harga terbaik (laba/hari dari simulasi 1 hari, 2 seed):"]
    for e in hasil:
        naik = e["laba_terbaik"] - e["laba_sekarang"]
        tanda = "↑" if naik > 0 else ("=" if naik == 0 else "↓")
        baris.append(
            f"{e['nama']} (stok {e['stok']}): "
            f"{format_rupiah(e['harga_sekarang'])} → "
            f"{format_rupiah(e['harga_terbaik'])} "
            f"({format_rupiah(e['laba_sekarang'])} → "
            f"{format_rupiah(e['laba_terbaik'])}/hari) {tanda}")
    baris.append("")
    baris.append(DISCLAIMER)
    pending, teks_konfirmasi = build_pending_harga(state, harga_baru, hasil)
    context.user_data[PENDING_KEY] = pending
    teks = "\n".join(baris) + "\n\n" + teks_konfirmasi
    if edit:
        await _edit(target, teks, harga_apply_keyboard())
    else:
        await target.reply_text(teks, reply_markup=harga_apply_keyboard())


async def _jalankan_harga_pasar(target, context, edit: bool) -> None:
    """Terapkan harga ikut pasaran, manual (pesan baru atau edit).

    Satu-satunya sumber logika adalah ``auto_harga_pasar`` yang sudah
    ada — tidak ada rumus baru di sini. Agen belum aktif / tanpa entri
    pasaran / semua harga sudah sama ditangani sebagai pesan, bukan
    pending.
    """
    from .handlers import _edit

    if edit:
        chat_id = target.message.chat_id
    else:
        chat_id = target.chat_id
    store = context.bot_data["store"]
    try:
        tiers_mod.require_tier(store.get_tier(chat_id), "auto_harga_pasar")
    except tiers_mod.TierError as exc:
        if edit:
            await _edit(target, str(exc), kb.back_to_menu())
        else:
            await target.reply_text(str(exc))
        return
    state, err = await _ambil_state(context, chat_id)
    if err:
        if edit:
            await _edit(target, err, kb.back_to_menu())
        else:
            await target.reply_text(err)
        return
    data = context.bot_data["data"]
    slot = state["slot"]
    _, perubahan = auto_mod.auto_harga_pasar(slot, data)
    gagal = [p for p in perubahan if not p.get("ok")]
    if gagal:
        # Satu-satunya kasus gagal auto_harga_pasar: agen belum aktif
        # (level < 2, LEVEL_AGEN di game).
        teks = (
            "Agen harga pasar belum aktif — info harga pasar baru dibuka "
            f"di Level 2 (warungmu sekarang Level "
            f"{int(slot.get('tingkat', 0)) + 1}). "
            "Naik ke Level 2 dulu, lalu coba lagi.")
        if edit:
            await _edit(target, teks, kb.back_to_menu())
        else:
            await target.reply_text(teks)
        return
    berubah = [p for p in perubahan if p.get("ok")]
    if not berubah:
        pasaran = slot.get("harga_pasaran") or {}
        if not pasaran:
            teks = ("Tidak ada perubahan pasaran minggu ini — save belum "
                    "punya data harga pasar. Pasaran baru muncul setelah "
                    "game dimainkan hari Senin (agen Pak Misran "
                    "mengumumkannya).")
        else:
            teks = ("Semua harga sudah mengikuti harga pasar minggu ini — "
                    "tidak ada yang perlu diubah.")
        if edit:
            await _edit(target, teks, kb.back_to_menu())
        else:
            await target.reply_text(teks)
        return
    terbuka = set(slot.get("barang_terbuka", []) or [])
    total_fisik = sum(
        1 for item_id in data.urutan_barang
        if data.katalog[item_id]["jenis"] == "fisik"
        and item_id in terbuka)
    tidak_berubah = total_fisik - len(berubah)
    harga_baru = {p["id"]: p["baru"] for p in berubah}
    baris = ["Harga pasar minggu ini — yang berubah:"]
    for p in berubah:
        baris.append(
            f"{p['nama']}: {format_rupiah(p['lama'])} → "
            f"{format_rupiah(p['baru'])}")
    if tidak_berubah > 0:
        baris.append(f"{tidak_berubah} barang lain sudah mengikuti pasar.")
    pending, teks_konfirmasi = build_pending_harga_pasar(
        state, harga_baru, berubah)
    context.user_data[PENDING_KEY] = pending
    teks = "\n".join(baris) + "\n\n" + teks_konfirmasi
    if edit:
        await _edit(target, teks, harga_apply_keyboard())
    else:
        await target.reply_text(teks, reply_markup=harga_apply_keyboard())


async def _tampilkan_jadwal_callback(query, context) -> None:
    from .handlers import _edit

    chat_id = query.message.chat_id
    jadwal = context.bot_data["store"].get_jadwal(chat_id)
    if jadwal is None:
        teks = ("Laporan harian belum diatur.\n"
                "Pilih jam (WIB) — bot akan mengirim ringkasan warung tiap "
                "pagi pada jam itu.")
    elif jadwal.get("aktif"):
        teks = (f"Laporan harian aktif tiap {jadwal['jam']:02d}:00 WIB.\n"
                "Pilih jam lain untuk mengubah, atau matikan.")
    else:
        teks = (f"Laporan harian mati (terakhir {jadwal['jam']:02d}:00 WIB).\n"
                "Pilih jam untuk menyalakan lagi.")
    await _edit(query, teks, jadwal_keyboard(jadwal))


async def _callback_jadwal(query, context, data_str: str) -> None:
    from .handlers import _edit
    from ..core import jobs as jobs_mod

    chat_id = query.message.chat_id
    store = context.bot_data["store"]
    scheduler = context.bot_data.get("scheduler")
    bagian = data_str.split(":")
    if len(bagian) >= 3 and bagian[1] == "jam":
        try:
            jam = int(bagian[2])
        except ValueError:
            await _edit(query, "Jam tidak dikenal.", jadwal_keyboard(store.get_jadwal(chat_id)))
            return
        store.set_jadwal(chat_id, jam, aktif=True)
        if scheduler is not None:
            jobs_mod.atur_laporan(scheduler, context.application, chat_id, jam)
        await _edit(query, f"Laporan harian aktif tiap {jam:02d}:00 WIB.",
                    jadwal_keyboard(store.get_jadwal(chat_id)))
        return
    if data_str == "jadwal:ketik":
        context.user_data["awaiting"] = "jadwal_jam"
        await _edit(query, "Ketik jam laporan harian (0-23, WIB). Contoh: 7\n"
                    "Kirim /batal untuk berhenti.", kb.back_to_menu())
        return
    if data_str == "jadwal:mati":
        jadwal = store.get_jadwal(chat_id)
        if jadwal is not None:
            store.set_jadwal(chat_id, int(jadwal["jam"]), aktif=False)
        if scheduler is not None:
            jobs_mod.hapus_laporan(scheduler, chat_id)
        await _edit(query, "Laporan harian dimatikan.",
                    jadwal_keyboard(store.get_jadwal(chat_id)))
        return
    if data_str == "jadwal:nyala":
        jadwal = store.get_jadwal(chat_id)
        jam = int(jadwal["jam"]) if jadwal else 7
        store.set_jadwal(chat_id, jam, aktif=True)
        if scheduler is not None:
            jobs_mod.atur_laporan(scheduler, context.application, chat_id, jam)
        await _edit(query, f"Laporan harian aktif lagi tiap {jam:02d}:00 WIB.",
                    jadwal_keyboard(store.get_jadwal(chat_id)))
        return
    await _edit(query, "Tombol tidak dikenal.", jadwal_keyboard(store.get_jadwal(chat_id)))


# -- input teks bebas ---------------------------------------------------------

async def on_text_whatif(update, context) -> bool:
    """Tangani input what-if. True bila ditangani (awaiting whatif_input)."""
    message = update.message
    if message is None or not message.text:
        return False
    if context.user_data.get("awaiting") != "whatif_input":
        return False
    context.user_data.pop("awaiting", None)
    from .handlers import _parse_jumlah

    data = context.bot_data["data"]
    harga_baru: dict = {}
    kesalahan: list[str] = []
    potongan = message.text.replace("\n", ",").split(",")
    for bagian in potongan:
        bagian = bagian.strip()
        if not bagian:
            continue
        kata = bagian.split()
        if len(kata) < 2:
            kesalahan.append(f"'{bagian}' — format: <id_barang> <harga>")
            continue
        item_id = kata[0].lower()
        harga = _parse_jumlah(" ".join(kata[1:]))
        if harga is None or harga <= 0:
            kesalahan.append(f"'{bagian}' — harga tidak bisa dipahami")
            continue
        if item_id not in data.katalog:
            kesalahan.append(f"barang tidak dikenal: {item_id}")
            continue
        harga_baru[item_id] = harga
    if kesalahan:
        await message.reply_text(
            "Input tidak bisa dipakai:\n" + "\n".join(f"- {k}" for k in kesalahan)
            + "\n\nCoba lagi dari Simulasi → What-If Harga.",
            reply_markup=kb.back_to_menu(),
        )
        return True
    if not harga_baru:
        await message.reply_text(
            "Tidak ada harga yang dimasukkan. Coba lagi dari Simulasi → "
            "What-If Harga.",
            reply_markup=kb.back_to_menu(),
        )
        return True
    state, err = await _ambil_state(context, message.chat_id)
    if err:
        await message.reply_text(err)
        return True
    try:
        hasil = plan_mod.whatif(state["slot"], data, harga_baru)
    except sim_mod.SimError as exc:
        await message.reply_text(f"Tidak bisa menghitung what-if: {exc}",
                                 reply_markup=kb.back_to_menu())
        return True
    baris = ["What-if harga (simulasi 1 hari, seed sama):"]
    for item_id, harga in hasil["harga_dipakai"].items():
        nama = data.katalog[item_id]["nama"]
        lama = sim_mod.harga_jual(data, item_id, state["slot"])
        baris.append(f"{nama}: {format_rupiah(lama)} → {format_rupiah(harga)}")
    for c in hasil["catatan"]:
        baris.append(f"Catatan: {c}")
    s0, s1 = hasil["sekarang"], hasil["usulan"]
    baris += [
        "",
        f"Omzet: {format_rupiah(s0['omzet'])} → {format_rupiah(s1['omzet'])}",
        f"Laba: {format_rupiah(s0['laba'])} → {format_rupiah(s1['laba'])}",
        f"Dilayani: {s0['dilayani']} → {s1['dilayani']} · "
        f"Batal: {s0['batal']} → {s1['batal']}",
        f"Uang akhir: {format_rupiah(s0['uang_akhir'])} → "
        f"{format_rupiah(s1['uang_akhir'])}",
        "",
        DISCLAIMER,
    ]
    pending, teks_konfirmasi = build_pending_harga(
        state, hasil["harga_dipakai"],
        [{"id": i, "nama": data.katalog[i]["nama"],
          "harga_sekarang": sim_mod.harga_jual(data, i, state["slot"]),
          "harga_terbaik": h,
          "laba_sekarang": s0["laba"], "laba_terbaik": s1["laba"]}
         for i, h in hasil["harga_dipakai"].items()])
    context.user_data[PENDING_KEY] = pending
    await message.reply_text("\n".join(baris) + "\n\n" + teks_konfirmasi,
                             reply_markup=harga_apply_keyboard())
    return True


async def on_text_jadwal(update, context) -> bool:
    """Tangani input jam laporan. True bila ditangani."""
    message = update.message
    if message is None or not message.text:
        return False
    if context.user_data.get("awaiting") != "jadwal_jam":
        return False
    context.user_data.pop("awaiting", None)
    from ..core import jobs as jobs_mod

    teks = message.text.strip()
    try:
        jam = int(teks)
    except ValueError:
        await message.reply_text("Jam harus angka 0-23. Contoh: 7",
                                 reply_markup=kb.back_to_menu())
        return True
    if not 0 <= jam <= 23:
        await message.reply_text("Jam harus 0-23.",
                                 reply_markup=kb.back_to_menu())
        return True
    store = context.bot_data["store"]
    store.set_jadwal(message.chat_id, jam, aktif=True)
    scheduler = context.bot_data.get("scheduler")
    if scheduler is not None:
        jobs_mod.atur_laporan(scheduler, context.application, message.chat_id, jam)
    await message.reply_text(f"Laporan harian aktif tiap {jam:02d}:00 WIB.",
                             reply_markup=kb.back_to_menu())
    return True
