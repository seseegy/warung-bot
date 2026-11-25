"""Tugas terjadwal Fase 2: laporan harian (APScheduler).

Satu job per chat: ``laporan:<chat_id>``, CronTrigger tiap hari pada jam
WIB yang diatur pengguna lewat /jadwal. Preferensi disimpan di Store
(tabel ``jadwal``) dan dimuat ulang saat bot start.

Job mengirim pesan BARU yang singkat (bukan mengedit): ringkasan uang,
level, tugas, stok menipis, sewa bila Minggu — dengan tombol
[Lihat Status]. Bila sesi mati -> kabari sekali lalu nonaktifkan jadwal
(supaya tidak spam tiap hari). Bila akun sudah tidak tertaut -> job
dihapus diam-diam. Gangguan cloud sesaat -> lewati hari itu (log saja).
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import save as save_mod
from .cloud import CloudError, NoCloudData, SessionExpired

log = logging.getLogger(__name__)

WIB = ZoneInfo("Asia/Jakarta")


def build_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone=WIB)


def job_id(chat_id: int) -> str:
    return f"laporan:{chat_id}"


def atur_laporan(scheduler: AsyncIOScheduler, app, chat_id: int, jam: int) -> None:
    """Buat/ganti job laporan harian chat ini pada jam WIB (0-23).

    Hapus eksplisit dulu: APScheduler 3.11 ``replace_existing=True`` TIDAK
    mengganti job bila scheduler belum jalan (duplikat diam-diam) —
    diverifikasi di tes. ``remove_job`` bekerja dalam kedua keadaan.
    """
    if not 0 <= int(jam) <= 23:
        raise ValueError("jam harus 0-23")
    try:
        scheduler.remove_job(job_id(chat_id))
    except Exception:
        pass
    scheduler.add_job(
        kirim_laporan_harian,
        CronTrigger(hour=int(jam), minute=0, timezone=WIB),
        args=[app, int(chat_id)],
        id=job_id(chat_id),
        replace_existing=True,
    )


def hapus_laporan(scheduler: AsyncIOScheduler, chat_id: int) -> None:
    try:
        scheduler.remove_job(job_id(chat_id))
    except Exception:
        pass


# -- Fase 3: siklus otomatis harian -------------------------------------------

def siklus_job_id(chat_id: int) -> str:
    return f"otomatis:{chat_id}"


def atur_siklus(scheduler: AsyncIOScheduler, app, chat_id: int, jam: int) -> None:
    """Buat/ganti job siklus otomatis chat ini pada jam WIB (0-23)."""
    if not 0 <= int(jam) <= 23:
        raise ValueError("jam harus 0-23")
    try:
        scheduler.remove_job(siklus_job_id(chat_id))
    except Exception:
        pass
    scheduler.add_job(
        jalankan_siklus_otomatis,
        CronTrigger(hour=int(jam), minute=0, timezone=WIB),
        args=[app, int(chat_id)],
        id=siklus_job_id(chat_id),
        replace_existing=True,
    )


def hapus_siklus(scheduler: AsyncIOScheduler, chat_id: int) -> None:
    try:
        scheduler.remove_job(siklus_job_id(chat_id))
    except Exception:
        pass


def muat_semua_otomatis(scheduler: AsyncIOScheduler, app, store) -> int:
    """Muat ulang semua siklus otomatis aktif dari Store saat start."""
    jumlah = 0
    for row in store.all_otomatis():
        try:
            atur_siklus(scheduler, app, int(row["chat_id"]),
                        int(row.get("jam", 7)))
            jumlah += 1
        except Exception:
            log.exception("gagal memuat siklus otomatis chat %s",
                          row.get("chat_id"))
    return jumlah


# -- Fase 3+: Mode Target Level ----------------------------------------------

def target_job_id(chat_id: int) -> str:
    return f"target:{chat_id}"


def atur_mode_target(scheduler: AsyncIOScheduler, app, chat_id: int) -> None:
    """Buat/ganti job Mode Target chat ini (tiap 5 menit, WIB).

    Hapus eksplisit dulu (alasan sama seperti atur_laporan: APScheduler
    3.11 replace_existing tidak mengganti bila scheduler belum jalan).
    """
    from apscheduler.triggers.interval import IntervalTrigger

    from . import target as target_mod

    try:
        scheduler.remove_job(target_job_id(chat_id))
    except Exception:
        pass
    scheduler.add_job(
        jalankan_mode_target,
        IntervalTrigger(minutes=target_mod.INTERVAL_MENIT, timezone=WIB),
        args=[app, int(chat_id)],
        id=target_job_id(chat_id),
        replace_existing=True,
    )


def hapus_mode_target(scheduler: AsyncIOScheduler, chat_id: int) -> None:
    try:
        scheduler.remove_job(target_job_id(chat_id))
    except Exception:
        pass


def muat_semua_mode_target(scheduler: AsyncIOScheduler, app, store) -> int:
    """Muat ulang semua Mode Target aktif dari Store saat start."""
    jumlah = 0
    for row in store.all_mode_target():
        try:
            atur_mode_target(scheduler, app, int(row["chat_id"]))
            jumlah += 1
        except Exception:
            log.exception("gagal memuat mode target chat %s",
                          row.get("chat_id"))
    return jumlah


# -- Fase 3+: Mode Kejar Papan ----------------------------------------------

def kejar_job_id(chat_id: int) -> str:
    return f"kejar:{chat_id}"


def atur_mode_kejar(scheduler: AsyncIOScheduler, app, chat_id: int) -> None:
    """Buat/ganti job Mode Kejar Papan chat ini (tiap 5 menit, WIB).

    Hapus eksplisit dulu (alasan sama seperti atur_laporan: APScheduler
    3.11 replace_existing tidak mengganti bila scheduler belum jalan).
    """
    from apscheduler.triggers.interval import IntervalTrigger

    from . import kejar as kejar_mod

    try:
        scheduler.remove_job(kejar_job_id(chat_id))
    except Exception:
        pass
    scheduler.add_job(
        jalankan_mode_kejar,
        IntervalTrigger(minutes=kejar_mod.INTERVAL_MENIT, timezone=WIB),
        args=[app, int(chat_id)],
        id=kejar_job_id(chat_id),
        replace_existing=True,
    )


def hapus_mode_kejar(scheduler: AsyncIOScheduler, chat_id: int) -> None:
    try:
        scheduler.remove_job(kejar_job_id(chat_id))
    except Exception:
        pass


def muat_semua_mode_kejar(scheduler: AsyncIOScheduler, app, store) -> int:
    """Muat ulang semua Mode Kejar Papan aktif dari Store saat start."""
    jumlah = 0
    for row in store.all_mode_kejar():
        try:
            atur_mode_kejar(scheduler, app, int(row["chat_id"]))
            jumlah += 1
        except Exception:
            log.exception("gagal memuat mode kejar chat %s",
                          row.get("chat_id"))
    return jumlah


def _teks_pengingatan_login(app, chat_id: int, paket: dict) -> tuple[str | None, int | None]:
    """Teks pengingat klaim login harian (Pemula+), tanpa mengirim.

    JUJUR: bot TIDAK BISA mengklaim lewat cloud — state login tinggal di
    pengaturan.cfg HP (bukan paket cloud). Teks ini hanya mengingatkan;
    pengguna menekan "Sudah Klaim" setelah mengklaim di game, bot lalu
    mencatat streak di Store. Tanpa konfirmasi, streak tidak maju.

    Mengembalikan (teks, n) — ``(None, None)`` bila tidak perlu diingatkan.
    """
    from . import auto as auto_mod

    store = app.bot_data["store"]
    lacak = store.get_login_lacak(chat_id)
    hari_ini = auto_mod.tanggal_wib()
    n = auto_mod.login_berikut(int(lacak["hari_ke"]), str(lacak["tanggal"]),
                               hari_ini)
    if n is None:
        return None, None
    toko = paket.get("toko", {}) if isinstance(paket, dict) else {}
    tanpa_iklan = bool(toko.get("tanpa_iklan", False)) if isinstance(toko, dict) else False
    lemari = paket.get("lemari", []) if isinstance(paket, dict) else []
    punya_baju = auto_mod.BAJU_TESTER in (lemari or [])
    hadiah = auto_mod.hadiah_login(n, tanpa_iklan=tanpa_iklan,
                                   punya_baju=punya_baju)
    teks = (
        f"Pengingat login harian — hari ke-{n} dari 30:\n"
        f"Hadiah: {hadiah['teks']}.\n"
        "Klaim di game, lalu tekan Sudah Klaim supaya bot mencatat streak.\n"
        "(Bot tidak bisa mengklaim sendiri — catatan login hanya ada di HP.)"
    )
    return teks, n


async def _kirim_pengingatan_login(app, chat_id: int, paket: dict) -> None:
    """Kirim pengingat login sebagai pesan terpisah (dipakai jalur lain)."""
    teks, n = _teks_pengingatan_login(app, chat_id, paket)
    if teks is None or n is None:
        return
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text=teks,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(
                    "Sudah Klaim", callback_data=f"login:klaim:{n}"),
                  InlineKeyboardButton(
                      "Lewat Hari Ini", callback_data="login:lewat")]]
            ),
        )
    except Exception:
        log.exception("gagal mengirim pengingat login ke chat %s", chat_id)


def _ringkas_siklus(hasil: dict) -> list[str]:
    """Baris-baris laporan siklus dari hasil jalankan_siklus()."""
    baris = ["Siklus otomatis selesai:"]
    sim = hasil.get("sim")
    if sim is not None:
        laba = int(sim["laba"])
        baris.append(
            f"Simulasi 1 hari (terbaik dari {sim.get('percobaan', 1)}): "
            f"omzet {_format_rupiah(sim['omzet'])} · "
            f"laba {_format_rupiah(laba)} · "
            f"dilayani {sim['dilayani']} · batal {sim['batal']}")
        baris.append(
            f"Cuan hari ini: {_format_rupiah(laba)}"
            + (" (UNTUNG)" if laba > 0
               else " (RUGI)" if laba < 0 else " (IMPAS)"))
    if hasil.get("batas_terlampaui"):
        baris.append("Batas harian terlampaui — simulasi tidak diterapkan.")
    jaga = [a for a in hasil["aksi"]
            if a.get("aksi") == "jaga_saldo" and a.get("ok")]
    if jaga:
        total_jaga = sum(int(a.get("jumlah", 0)) for a in jaga)
        baris.append(
            f"Penjaga Saldo menambah {_format_rupiah(total_jaga)} supaya "
            "uang tidak minus (uang ditambah dari ketiadaan, tercatat di "
            "audit log).")
    beli = [a for a in hasil["aksi"] if a.get("aksi") == "beli_stok" and a.get("ok")]
    if beli:
        total = sum(int(a["biaya"]) for a in beli)
        rincian = ", ".join(f"{a['nama']} x{a['jumlah']}" for a in beli)
        baris.append(f"Auto-beli stok ({_format_rupiah(total)}): {rincian}")
    harga = [a for a in hasil["aksi"]
             if a.get("aksi") in ("harga_pasar", "harga_dinamis") and a.get("ok")]
    if harga:
        rincian = ", ".join(
            f"{a['nama']} {_format_rupiah(a['lama'])}→{_format_rupiah(a['baru'])}"
            for a in harga)
        baris.append(f"Harga diubah: {rincian}")
    tugas = [a for a in hasil["aksi"] if a.get("aksi") == "isi_tugas"]
    if tugas and tugas[0].get("ok"):
        blok = tugas[0].get("blockers") or []
        baris.append("Progres tugas diisi penuh."
                     + (f" Perhatian: {'; '.join(blok)}" if blok else ""))
    elif tugas:
        baris.append(f"Isi tugas gagal: {tugas[0].get('alasan', '-')}")
    for kunci, label in (("bayar_sewa", "Sewa dibayar"),
                         ("cicil_sewa", "Sewa dicicil"),
                         ("bayar_zakat", "Zakat dibayar"),
                         ("bayar_motor", "Cicilan motor dibayar")):
        entri = [a for a in hasil["aksi"] if a.get("aksi") == kunci and a.get("ok")]
        if entri:
            baris.append(f"{label}: {_format_rupiah(entri[0].get('dibayar', 0))}.")
    gagal = [a for a in hasil["aksi"] if not a.get("ok")
             and a.get("aksi") in ("bayar_sewa", "bayar_zakat", "bayar_motor")]
    for a in gagal:
        baris.append(f"{a.get('aksi')}: {a.get('alasan', 'gagal')}")
    baris.append(
        f"Uang {_format_rupiah(hasil['uang_awal'])} → "
        f"{_format_rupiah(hasil['uang_akhir'])}")
    return baris


async def _cek_peringkat(app, chat_id: int, id_papan: str, slot: dict) -> None:
    """Lacak peringkat (Profesional): ambil papan, bandingkan dengan
    yang tersimpan, kabari bila disalip. Gagal -> diam (log saja)."""
    from . import papan as papan_mod

    store = app.bot_data["store"]
    cloud = app.bot_data["cloud"]
    try:
        data = await cloud.fetch_papan("semua", id_papan)
    except Exception as exc:
        log.warning("cek peringkat chat %s gagal: %s", chat_id, exc)
        return
    kode = papan_mod.kode_papan(id_papan)
    # Jumlah pembeli kumulatif dari save (total_pembeli, game_state.gd:98).
    total = slot.get("total_pembeli")
    try:
        total = int(total) if total is not None else None
    except (TypeError, ValueError):
        total = None
    hasil = papan_mod.parse_papan(data, kode, total)
    baru = hasil["peringkat"]
    lama_row = store.get_peringkat(chat_id, "semua")
    lama = lama_row["peringkat"] if lama_row else None
    store.save_peringkat(chat_id, "semua", baru, hasil["jumlah_warung"])
    if baru is None:
        return
    arah = papan_mod.bandingkan_peringkat(lama, baru)
    if arah == "turun":
        atas = hasil["atas"]
        teks = (f"Peringkatmu turun: #{lama} → #{baru} "
                f"dari {hasil['jumlah_warung']} warung.")
        if atas:
            teks += (f" Di atasmu: {atas['nama']} "
                     f"({atas['pembeli']} pembeli).")
        try:
            await app.bot.send_message(chat_id=chat_id, text=teks)
        except Exception:
            log.exception("gagal mengirim peringatan peringkat ke %s", chat_id)
    elif arah == "naik" and lama is not None:
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=f"Peringkatmu naik: #{lama} → #{baru}.")
        except Exception:
            log.exception("gagal mengirim kabar peringkat ke %s", chat_id)


async def jalankan_siklus_otomatis(app, chat_id: int) -> None:
    """Job siklus otomatis harian (Fase 3).

    Urutan: ambil state terbaru -> pengingat login -> jalankan siklus
    murni -> unggah sekali -> laporkan. Bentrok/sesi habis -> jeda
    otomatisasi (otomatis=0) + beri tahu pengguna; TIDAK mencoba lagi
    diam-diam sampai pengguna menyalakan ulang.
    """
    from . import auto as auto_mod
    from ..tg.confirm import execute_upload
    from ..tg.status import fetch_latest_state

    store = app.bot_data["store"]
    data = app.bot_data["data"]
    tugas_data = app.bot_data["tugas"]
    session = store.get_user(chat_id)
    if session is None:
        scheduler = app.bot_data.get("scheduler")
        if scheduler is not None:
            hapus_siklus(scheduler, chat_id)
        return
    if not store.get_otomatis(chat_id):
        scheduler = app.bot_data.get("scheduler")
        if scheduler is not None:
            hapus_siklus(scheduler, chat_id)
        return
    tier = store.get_tier(chat_id)
    batas = store.get_batas_harian(chat_id)
    ctx = SimpleNamespace(bot_data=app.bot_data)
    try:
        state = await fetch_latest_state(ctx, chat_id)
    except SessionExpired:
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text="Sesi login habis. Siklus otomatis dimatikan — "
                     "kirim ulang akun.json dengan /link untuk menyalakan lagi.")
        except Exception:
            pass
        store.set_otomatis(chat_id, False)
        scheduler = app.bot_data.get("scheduler")
        if scheduler is not None:
            hapus_siklus(scheduler, chat_id)
        return
    except (NoCloudData, CloudError, save_mod.PackageError,
            save_mod.SlotError) as exc:
        log.warning("siklus otomatis chat %s dilewati: %s", chat_id, exc)
        return

    # Pengingat login harian (tidak mengubah save) — digabung ke laporan
    # siklus (bukan pesan terpisah) supaya chat tidak penuh.
    pengingat_teks, pengingat_n = _teks_pengingatan_login(
        app, chat_id, state["paket"])

    # Siklus murni (tanpa I/O).
    hasil = auto_mod.jalankan_siklus(state["slot"], data, tugas_data,
                                     tier, batas)

    # Unggah sekali (dengan cek versi seperti alur konfirmasi).
    pending = {
        "kind": "siklus",
        "id_papan": state["ringkasan"]["id_papan"],
        "p_data": None,
        "versi_dasar": int(state["versi"]),
        "slot_akhir": hasil["slot"],
        "ringkasan": "Siklus otomatis harian diterapkan",
    }
    try:
        teks, status = await execute_upload(ctx, chat_id, pending)
    except Exception:
        log.exception("siklus otomatis chat %s gagal saat upload", chat_id)
        return
    if status == "bentrok":
        store.set_otomatis(chat_id, False)
        scheduler = app.bot_data.get("scheduler")
        if scheduler is not None:
            hapus_siklus(scheduler, chat_id)
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text="Siklus otomatis BERHENTI: simpanan di cloud berubah "
                     "(kemungkinan game baru saja mengunggah).\n"
                     "Jalankan /sync, pastikan tidak ada yang tertimpa, "
                     "lalu nyalakan lagi dengan /otomatis on.",
            )
        except Exception:
            pass
        return
    if status == "sesi_habis":
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text="Sesi login habis. Siklus otomatis dimatikan — "
                     "kirim ulang akun.json dengan /link.")
        except Exception:
            pass
        scheduler = app.bot_data.get("scheduler")
        if scheduler is not None:
            hapus_siklus(scheduler, chat_id)
        return
    if status != "ok":
        log.warning("siklus otomatis chat %s gagal: %s", chat_id, teks)
        return

    # Sukses: catat audit tiap aksi + laporkan.
    for a in hasil["aksi"]:
        detail = str(a.get("alasan", "") or a.get("nama", "") or "")
        if a.get("aksi") == "simulasi" and a.get("ok"):
            detail = (f"omzet {_format_rupiah(a.get('omzet', 0))}, "
                      f"laba {_format_rupiah(a.get('laba', 0))}")
        elif a.get("aksi") in ("beli_stok", "bayar_sewa", "cicil_sewa",
                               "bayar_zakat", "bayar_motor") and a.get("ok"):
            detail = _format_rupiah(a.get("dibayar", a.get("biaya", 0)))
        elif a.get("aksi") == "jaga_saldo" and a.get("ok"):
            detail = (f"+{_format_rupiah(a.get('jumlah', 0))} "
                      f"(dari {_format_rupiah(a.get('dari', 0))})")
        store.log_audit(chat_id, str(a.get("aksi", "?")), detail)

    # Diusir (dari simulasi)? Berhenti total — kios sudah hilang.
    if hasil["slot"].get("diusir"):
        store.set_otomatis(chat_id, False)
        scheduler = app.bot_data.get("scheduler")
        if scheduler is not None:
            hapus_siklus(scheduler, chat_id)
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text="PERINGATAN: dalam simulasi siklus ini warung DIUSIR "
                     "(tunggakan sewa mencapai 3 minggu). Siklus otomatis "
                     "dimatikan. Periksa warungmu di game segera.",
            )
        except Exception:
            pass
        return

    # Lacak peringkat (Profesional).
    if tier >= 3 and state["ringkasan"]["id_papan"]:
        await _cek_peringkat(app, chat_id, state["ringkasan"]["id_papan"],
                             hasil["slot"])

    baris = _ringkas_siklus(hasil)
    markup = None
    if pengingat_teks and pengingat_n is not None:
        baris.insert(0, pengingat_teks)
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(
                "Sudah Klaim", callback_data=f"login:klaim:{pengingat_n}"),
              InlineKeyboardButton(
                  "Lihat Status", callback_data="menu:status")]]
        )
    else:
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Lihat Status",
                                   callback_data="menu:status")]]
        )
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text="\n\n".join(baris),
            reply_markup=markup,
        )
    except Exception:
        log.exception("gagal mengirim laporan siklus ke chat %s", chat_id)


async def _matikan_mode_target(app, chat_id: int, alasan: str,
                               kabari: bool = True, info_jaga: int = 0) -> None:
    """Matikan Mode Target: hapus state + job, lalu kabari pengguna.

    ``info_jaga`` = total top-up Penjaga Saldo pada siklus terakhir (0
    bila tidak ada) — disebutkan di pesan berhenti supaya pengguna tahu
    uangnya ditambah.
    """
    from . import target as target_mod

    store = app.bot_data["store"]
    mode = store.get_mode_target(chat_id)
    store.hapus_mode_target(chat_id)
    scheduler = app.bot_data.get("scheduler")
    if scheduler is not None:
        hapus_mode_target(scheduler, chat_id)
    store.log_audit(chat_id, "mode_target_berhenti", alasan)
    if not kabari:
        return
    teks = (f"Mode Target Level berhenti. "
            f"{target_mod.teks_berhenti(alasan)}")
    if info_jaga > 0:
        teks += (f"\nPenjaga Saldo menambah {_format_rupiah(info_jaga)} "
                 "pada siklus terakhir.")
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text=teks,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Lihat Status",
                                       callback_data="menu:status")]]
            ),
        )
    except Exception:
        log.exception("gagal mengabari berhenti mode target ke %s", chat_id)


async def jalankan_mode_target(app, chat_id: int) -> None:
    """Satu siklus Mode Target Level (Fase 3+), tiap 5 menit.

    Urutan: ambil state terbaru -> Penjaga Saldo (perbaiki uang minus
    sebelum cek berhenti) -> cek berhenti -> satu siklus target
    (bayar misi + beli upgrade syarat + siklus harian) -> unggah sekali.
    Diam pada siklus biasa (tidak spam); kabari hanya saat naik level,
    target tercapai, atau berhenti karena masalah. Bentrok/sesi habis ->
    mode dimatikan + pengguna diberi tahu; TIDAK mencoba lagi diam-diam.
    """
    from . import auto as auto_mod
    from . import target as target_mod
    from ..tg.confirm import execute_upload
    from ..tg.status import fetch_latest_state

    store = app.bot_data["store"]
    data = app.bot_data["data"]
    tugas_data = app.bot_data["tugas"]
    session = store.get_user(chat_id)
    mode = store.get_mode_target(chat_id)
    if session is None or mode is None:
        scheduler = app.bot_data.get("scheduler")
        if scheduler is not None:
            hapus_mode_target(scheduler, chat_id)
        return
    target_tingkat = int(mode["target_tingkat"])
    tier = store.get_tier(chat_id)
    batas = store.get_batas_harian(chat_id)
    ctx = SimpleNamespace(bot_data=app.bot_data)
    try:
        state = await fetch_latest_state(ctx, chat_id)
    except SessionExpired:
        await _matikan_mode_target(app, chat_id, "sesi_habis")
        return
    except (NoCloudData, CloudError, save_mod.PackageError,
            save_mod.SlotError) as exc:
        log.warning("mode target chat %s dilewati: %s", chat_id, exc)
        return

    # Penjaga Saldo — perbaiki uang save SEBELUM cek berhenti: bila save
    # minus (mis. -Rp30.000 dari insiden 24 Nov 2026), mode memperbaiki
    # di siklus ini, bukan berhenti sebelum siklus pertama. Top-up baru
    # dicatat di audit bila siklus ini berhasil diunggah (di bawah);
    # bila upload gagal/bentrok, perbaikan dibuang bersama siklus.
    slot_masuk, tambah_awal = auto_mod.jaga_saldo(state["slot"])

    # Sudah sampai target (mis. sir main sendiri dan naik level)?
    alasan = target_mod.alasan_berhenti(slot_masuk, target_tingkat,
                                        int(mode["siklus"]))
    if alasan is not None:
        await _matikan_mode_target(app, chat_id, alasan)
        return

    hasil = target_mod.satu_siklus_target(slot_masuk, data, tugas_data,
                                          tier, batas)
    siklus_baru = store.tambah_siklus_target(chat_id)

    pending = {
        "kind": "siklus",
        "id_papan": state["ringkasan"]["id_papan"],
        "p_data": None,
        "versi_dasar": int(state["versi"]),
        "slot_akhir": hasil["slot"],
        "ringkasan": "Mode Target Level: 1 hari diterapkan",
    }
    try:
        teks, status = await execute_upload(ctx, chat_id, pending)
    except Exception:
        log.exception("mode target chat %s gagal saat upload", chat_id)
        return
    if status == "bentrok":
        await _matikan_mode_target(app, chat_id, "bentrok")
        return
    if status == "sesi_habis":
        await _matikan_mode_target(app, chat_id, "sesi_habis")
        return
    if status != "ok":
        log.warning("mode target chat %s gagal: %s", chat_id, teks)
        return

    # Sukses: catat audit untuk aksi yang membelanjakan uang + penjaga
    # saldo (awal siklus + yang terjadi di dalam siklus).
    total_jaga = int(tambah_awal)
    if tambah_awal > 0:
        store.log_audit(chat_id, "jaga_saldo",
                        f"+{_format_rupiah(tambah_awal)} (awal siklus)")
    for a in hasil["aksi"]:
        if a.get("aksi") in ("bayar_misi", "beli_upgrade") and a.get("ok"):
            store.log_audit(chat_id, str(a["aksi"]),
                            _format_rupiah(a.get("jumlah", 0)))
        elif a.get("aksi") == "jaga_saldo" and a.get("ok"):
            total_jaga += int(a.get("jumlah", 0))
            store.log_audit(chat_id, "jaga_saldo",
                            f"+{_format_rupiah(a.get('jumlah', 0))}")

    if hasil["slot"].get("diusir"):
        await _matikan_mode_target(app, chat_id, "diusir",
                                   info_jaga=total_jaga)
        return
    alasan = target_mod.alasan_berhenti(hasil["slot"], target_tingkat,
                                        siklus_baru)
    if alasan is not None:
        await _matikan_mode_target(app, chat_id, alasan,
                                   info_jaga=total_jaga)
        return
    if hasil["naik"]:
        level_baru = int(hasil["tingkat_akhir"]) + 1
        teks = (f"Mode Target: naik ke Level {level_baru} "
                f"(target Level {target_tingkat}).")
        if total_jaga > 0:
            teks += (f"\nPenjaga Saldo menambah "
                     f"{_format_rupiah(total_jaga)} pada siklus ini.")
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=teks,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Lihat Status",
                                           callback_data="menu:status")]]
                ),
            )
        except Exception:
            log.exception("gagal mengabari naik level mode target %s", chat_id)


async def _matikan_mode_kejar(app, chat_id: int, alasan: str,
                              kabari: bool = True,
                              teks_khusus: str | None = None,
                              info_jaga: int = 0) -> None:
    """Matikan Mode Kejar Papan: hapus state + job, lalu kabari pengguna.

    ``teks_khusus`` menggantikan teks alasan generik (dipakai saat
    target tercapai, supaya pesan menyebut peringkat + total pembeli).
    ``info_jaga`` = total top-up Penjaga Saldo pada siklus terakhir (0
    bila tidak ada) — disebutkan di pesan berhenti supaya pengguna tahu
    uangnya ditambah.
    """
    from . import kejar as kejar_mod

    store = app.bot_data["store"]
    store.hapus_mode_kejar(chat_id)
    scheduler = app.bot_data.get("scheduler")
    if scheduler is not None:
        hapus_mode_kejar(scheduler, chat_id)
    store.log_audit(chat_id, "mode_kejar_berhenti", alasan)
    if not kabari:
        return
    teks = teks_khusus or (
        f"Mode Kejar Papan berhenti. {kejar_mod.teks_berhenti(alasan)}")
    if info_jaga > 0:
        teks += (f"\nPenjaga Saldo menambah {_format_rupiah(info_jaga)} "
                 "pada siklus terakhir.")
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text=teks,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Lihat Status",
                                       callback_data="menu:status")]]
            ),
        )
    except Exception:
        log.exception("gagal mengabari berhenti mode kejar ke %s", chat_id)


async def jalankan_mode_kejar(app, chat_id: int) -> None:
    """Satu siklus Mode Kejar Papan (Fase 3+), tiap 5 menit.

    Urutan: ambil state terbaru -> Penjaga Saldo (perbaiki uang minus
    sebelum cek berhenti) -> baca papan live (batas target segar)
    -> cek berhenti -> satu siklus kejar (bayar misi + beli upgrade
    syarat + siklus harian) -> unggah sekali. Diam pada siklus biasa
    (tidak spam); kabari hanya saat target tercapai atau berhenti karena
    masalah. Bentrok/sesi habis -> mode dimatikan + pengguna diberi tahu;
    TIDAK mencoba lagi diam-diam. Papan gagal dibaca -> siklus dilewati
    (target tidak ditebak), mode tetap nyala.
    """
    from . import auto as auto_mod
    from . import kejar as kejar_mod
    from ..tg.confirm import execute_upload
    from ..tg.status import fetch_latest_state

    store = app.bot_data["store"]
    cloud = app.bot_data["cloud"]
    data = app.bot_data["data"]
    tugas_data = app.bot_data["tugas"]
    session = store.get_user(chat_id)
    mode = store.get_mode_kejar(chat_id)
    if session is None or mode is None:
        scheduler = app.bot_data.get("scheduler")
        if scheduler is not None:
            hapus_mode_kejar(scheduler, chat_id)
        return
    target_peringkat = int(mode["target_peringkat"])
    tier = store.get_tier(chat_id)
    batas = store.get_batas_harian(chat_id)
    ctx = SimpleNamespace(bot_data=app.bot_data)
    try:
        state = await fetch_latest_state(ctx, chat_id)
    except SessionExpired:
        await _matikan_mode_kejar(app, chat_id, "sesi_habis")
        return
    except (NoCloudData, CloudError, save_mod.PackageError,
            save_mod.SlotError) as exc:
        log.warning("mode kejar chat %s dilewati: %s", chat_id, exc)
        return

    # Penjaga Saldo — perbaiki uang save SEBELUM cek berhenti (alasan
    # yang sama seperti Mode Target: minus diperbaiki di siklus ini,
    # bukan jadi alasan berhenti sebelum siklus pertama).
    slot_masuk, tambah_awal = auto_mod.jaga_saldo(state["slot"])

    # Baca papan live: batas target segar (baris peringkat target bisa
    # naik bila pemain lain menyalip). Gagal -> lewati siklus ini.
    id_papan = state["ringkasan"].get("id_papan") or ""
    if not id_papan:
        log.warning("mode kejar chat %s dilewati: tanpa id_papan", chat_id)
        return
    try:
        data_papan = await cloud.fetch_papan("semua", id_papan)
    except Exception as exc:
        log.warning("mode kejar chat %s dilewati: papan gagal: %s",
                    chat_id, exc)
        return
    target_pembeli = kejar_mod.target_pembeli_dari_papan(
        data_papan, target_peringkat)
    if target_pembeli is None:
        log.warning("mode kejar chat %s dilewati: peringkat %d tidak ada "
                    "di papan", chat_id, target_peringkat)
        return

    # Sudah masuk target (mis. sir main sendiri dan pembeli naik)?
    alasan = kejar_mod.alasan_berhenti(slot_masuk, target_pembeli,
                                       int(mode["siklus"]))
    if alasan is not None:
        if alasan == "target_tercapai":
            total = int(slot_masuk.get("total_pembeli", 0))
            await _matikan_mode_kejar(
                app, chat_id, alasan,
                teks_khusus=(
                    f"Mode Kejar Papan: MASUK {target_peringkat} BESAR! "
                    f"Total pembeli {total} sudah mencapai batas peringkat "
                    f"{target_peringkat} ({target_pembeli}). Buka game "
                    "sekali supaya skor terkirim ke papan."))
        else:
            await _matikan_mode_kejar(app, chat_id, alasan)
        return

    hasil = kejar_mod.satu_siklus_kejar(slot_masuk, data, tugas_data,
                                        tier, batas)
    # Hitungan siklus hanya untuk siklus yang DITERAPKAN (upload sukses):
    # bila upload gagal, hari sim dibuang dan siklus tidak dihitung.
    siklus_baru = int(mode["siklus"]) + 1

    pending = {
        "kind": "siklus",
        "id_papan": state["ringkasan"]["id_papan"],
        "p_data": None,
        "versi_dasar": int(state["versi"]),
        "slot_akhir": hasil["slot"],
        "ringkasan": "Mode Kejar Papan: 1 hari diterapkan",
    }
    try:
        teks, status = await execute_upload(ctx, chat_id, pending)
    except Exception:
        log.exception("mode kejar chat %s gagal saat upload", chat_id)
        return
    if status == "bentrok":
        await _matikan_mode_kejar(app, chat_id, "bentrok")
        return
    if status == "sesi_habis":
        await _matikan_mode_kejar(app, chat_id, "sesi_habis")
        return
    if status != "ok":
        log.warning("mode kejar chat %s gagal: %s", chat_id, teks)
        return
    store.tambah_siklus_kejar(chat_id)

    # Sukses: catat audit untuk aksi yang membelanjakan uang + penjaga
    # saldo (awal siklus + yang terjadi di dalam siklus).
    total_jaga = int(tambah_awal)
    if tambah_awal > 0:
        store.log_audit(chat_id, "jaga_saldo",
                        f"+{_format_rupiah(tambah_awal)} (awal siklus)")
    for a in hasil["aksi"]:
        if a.get("aksi") in ("bayar_misi", "beli_upgrade") and a.get("ok"):
            store.log_audit(chat_id, str(a["aksi"]),
                            _format_rupiah(a.get("jumlah", 0)))
        elif a.get("aksi") == "jaga_saldo" and a.get("ok"):
            total_jaga += int(a.get("jumlah", 0))
            store.log_audit(chat_id, "jaga_saldo",
                            f"+{_format_rupiah(a.get('jumlah', 0))}")

    if hasil["slot"].get("diusir"):
        await _matikan_mode_kejar(app, chat_id, "diusir",
                                  info_jaga=total_jaga)
        return
    alasan = kejar_mod.alasan_berhenti(hasil["slot"], target_pembeli,
                                       siklus_baru)
    if alasan is not None:
        if alasan == "target_tercapai":
            total = int(hasil["slot"].get("total_pembeli", 0))
            teks = (f"Mode Kejar Papan: MASUK {target_peringkat} BESAR! "
                    f"Total pembeli {total} sudah mencapai batas peringkat "
                    f"{target_peringkat} ({target_pembeli}). Buka game "
                    "sekali supaya skor terkirim ke papan.")
            if total_jaga > 0:
                teks += (f"\nPenjaga Saldo menambah "
                         f"{_format_rupiah(total_jaga)} pada siklus ini.")
            await _matikan_mode_kejar(app, chat_id, alasan,
                                      teks_khusus=teks)
        else:
            await _matikan_mode_kejar(app, chat_id, alasan,
                                      info_jaga=total_jaga)
        return
    # Siklus biasa: kirim statistik cuan singkat (fitur /cuan — atas
    # permintaan pengguna). Bukan spam penuh: satu baris per hari game.
    if cuan_aktif_slot(hasil["slot"]):
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=_teks_cuan_kejar(hasil),
            )
        except Exception:
            log.exception("gagal mengirim statistik cuan ke chat %s", chat_id)


def _teks_cuan_kejar(hasil: dict) -> str:
    """Satu baris statistik cuan hari ini untuk Mode Kejar (mode cuan)."""
    sim = hasil.get("sim") or {}
    laba = int(sim.get("laba", 0))
    omzet = int(sim.get("omzet", 0))
    if laba > 0:
        tanda = "UNTUNG"
    elif laba < 0:
        tanda = "RUGI"
    else:
        tanda = "IMPAS"
    hari = int(hasil["slot"].get("hari", 0))
    return (f"Cuan hari {hari}: omzet {_format_rupiah(omzet)} · "
            f"laba {_format_rupiah(laba)} ({tanda})")


def cuan_aktif_slot(slot: dict) -> bool:
    """Mode cuan aktif di slot? (import sim untuk menghindari cyclic)."""
    from . import sim as sim_mod
    return sim_mod.cuan_aktif(slot)


def muat_semua_jadwal(scheduler: AsyncIOScheduler, app, store) -> int:
    """Muat ulang semua jadwal aktif dari Store saat start. Return jumlah."""
    jumlah = 0
    for row in store.all_jadwal():
        if not row.get("aktif"):
            continue
        try:
            atur_laporan(scheduler, app, int(row["chat_id"]), int(row["jam"]))
            jumlah += 1
        except Exception:
            log.exception("gagal memuat jadwal chat %s", row.get("chat_id"))
    return jumlah


def _jam_trigger(job) -> int | None:
    """Jam CronTrigger sebuah job (None bila bukan cron per jam tunggal).

    APScheduler 3.11 menyimpan ekspresi field sebagai objek
    ``RangeExpression`` (bukan int): satu jam berarti ``first == last``.
    """
    trigger = getattr(job, "trigger", None)
    for field in getattr(trigger, "fields", []) or []:
        if getattr(field, "name", "") == "hour":
            exprs = list(getattr(field, "expressions", []) or [])
            if len(exprs) != 1:
                return None
            expr = exprs[0]
            first = getattr(expr, "first", None)
            last = getattr(expr, "last", None)
            if first is not None and first == last:
                try:
                    return int(first)
                except (TypeError, ValueError):
                    return None
            try:
                return int(str(expr))
            except (TypeError, ValueError):
                return None
    return None


def sinkronkan_semua(scheduler: AsyncIOScheduler, app, store) -> dict:
    """Samakan job scheduler dengan isi Store.

    Dipakai job interval tiap 10 menit (Fase 4): perubahan pengaturan dari
    Mini App (API adalah proses terpisah — ia hanya menulis DB) berlaku
    tanpa restart bot. Idempotent: job yang jamnya sudah benar dibiarkan
    (tidak dihapus-dibuat ulang, supaya tidak ada jadwal yang terlewat
    bila sinkronisasi berjalan tepat di menit eksekusi).
    Mengembalikan {"laporan": n, "otomatis": n, "target": n, "kejar": n,
    "dihapus": n} — jumlah job yang DIUBAH (bukan yang sudah benar).
    """
    hasil = {"laporan": 0, "otomatis": 0, "target": 0, "kejar": 0,
             "dihapus": 0}
    ingin_laporan = {
        int(r["chat_id"]): int(r["jam"])
        for r in store.all_jadwal() if r.get("aktif")
    }
    for chat_id, jam in ingin_laporan.items():
        job = scheduler.get_job(job_id(chat_id))
        if job is not None and _jam_trigger(job) == jam:
            continue  # Sudah benar — dibiarkan, tidak dihitung sebagai perubahan.
        try:
            atur_laporan(scheduler, app, chat_id, jam)
            hasil["laporan"] += 1
        except Exception:
            log.exception("gagal menyinkronkan laporan chat %s", chat_id)
    ingin_otomatis = {
        int(r["chat_id"]): int(r.get("jam", 7)) for r in store.all_otomatis()
    }
    for chat_id, jam in ingin_otomatis.items():
        job = scheduler.get_job(siklus_job_id(chat_id))
        if job is not None and _jam_trigger(job) == jam:
            continue  # Sudah benar — dibiarkan, tidak dihitung sebagai perubahan.
        try:
            atur_siklus(scheduler, app, chat_id, jam)
            hasil["otomatis"] += 1
        except Exception:
            log.exception("gagal menyinkronkan siklus chat %s", chat_id)
    ingin_target = {
        int(r["chat_id"]): int(r["target_tingkat"])
        for r in store.all_mode_target()
    }
    for chat_id in ingin_target:
        if scheduler.get_job(target_job_id(chat_id)) is not None:
            continue  # Sudah benar — dibiarkan.
        try:
            atur_mode_target(scheduler, app, chat_id)
            hasil["target"] += 1
        except Exception:
            log.exception("gagal menyinkronkan mode target chat %s", chat_id)
    ingin_kejar = {
        int(r["chat_id"]) for r in store.all_mode_kejar()
    }
    for chat_id in ingin_kejar:
        if scheduler.get_job(kejar_job_id(chat_id)) is not None:
            continue  # Sudah benar — dibiarkan.
        try:
            atur_mode_kejar(scheduler, app, chat_id)
            hasil["kejar"] += 1
        except Exception:
            log.exception("gagal menyinkronkan mode kejar chat %s", chat_id)
    for job in list(scheduler.get_jobs()):
        jid = str(job.id or "")
        try:
            cid = int(jid.split(":", 1)[1])
        except (IndexError, ValueError):
            continue
        if jid.startswith("laporan:") and cid not in ingin_laporan:
            hapus_laporan(scheduler, cid)
            hasil["dihapus"] += 1
        elif jid.startswith("otomatis:") and cid not in ingin_otomatis:
            hapus_siklus(scheduler, cid)
            hasil["dihapus"] += 1
        elif jid.startswith("target:") and cid not in ingin_target:
            hapus_mode_target(scheduler, cid)
            hasil["dihapus"] += 1
        elif jid.startswith("kejar:") and cid not in ingin_kejar:
            hapus_mode_kejar(scheduler, cid)
            hasil["dihapus"] += 1
    return hasil


async def _sinkronisasi_berkala(app) -> None:
    """Pembungkus async untuk job interval sinkronisasi."""
    scheduler = app.bot_data.get("scheduler")
    store = app.bot_data.get("store")
    if scheduler is None or store is None:
        return
    try:
        sinkronkan_semua(scheduler, app, store)
    except Exception:
        log.exception("sinkronisasi jadwal gagal")


def atur_sinkronisasi(scheduler: AsyncIOScheduler, app) -> None:
    """Daftarkan job interval 10 menit untuk sinkronisasi jadwal."""
    from apscheduler.triggers.interval import IntervalTrigger

    try:
        scheduler.remove_job("sinkronisasi")
    except Exception:
        pass
    scheduler.add_job(
        _sinkronisasi_berkala,
        IntervalTrigger(minutes=10),
        args=[app],
        id="sinkronisasi",
        replace_existing=True,
    )


def _format_rupiah(nilai: int) -> str:
    return f"Rp{int(nilai):,}".replace(",", ".")


# -- Fase 5: pemantauan global (satu job untuk semua chat) -------------------

def atur_pemantauan(scheduler: AsyncIOScheduler, app) -> None:
    """Daftarkan 4 job global Fase 5 (semua WIB):

    - pasar_senin: Senin 07.00 — notifikasi harga pasar.
    - cek_versi: harian 07.05 — cek versi game baru.
    - backup_harian: harian 03.00 — arsip paket cloud.
    - adu_laris_jumat: Jumat 17.00 — pengingat adu laris mingguan.

    Pola yang sama seperti atur_sinkronisasi: hapus eksplisit dulu
    (``replace_existing`` tidak cukup bila scheduler belum jalan).
    """
    tugas = [
        ("pasar_senin", notifikasi_pasar_senin,
         CronTrigger(day_of_week="mon", hour=7, minute=0, timezone=WIB)),
        ("cek_versi", cek_versi_game_job,
         CronTrigger(hour=7, minute=5, timezone=WIB)),
        ("backup_harian", backup_harian_job,
         CronTrigger(hour=3, minute=0, timezone=WIB)),
        ("adu_laris_jumat", pengingat_adu_laris_job,
         CronTrigger(day_of_week="fri", hour=17, minute=0, timezone=WIB)),
    ]
    for job_id_f5, fungsi, trigger in tugas:
        try:
            scheduler.remove_job(job_id_f5)
        except Exception:
            pass
        scheduler.add_job(
            fungsi, trigger, args=[app], id=job_id_f5, replace_existing=True,
        )


async def notifikasi_pasar_senin(app) -> None:
    """Job Senin pagi: bandingkan ``harga_pasaran`` save terbaru dengan
    snapshot minggu lalu (meta 'pasaran'); kabari bila ada perubahan.

    Jalan pertama per chat: simpan snapshot diam-diam (tidak ada
    pembanding — tidak mengirim apa-apa). CATATAN: pasaran di save baru
    berubah setelah game dimainkan hari Senin (``_perbarui_pasaran``
    jalan di game, bukan di server) — jadi notifikasi muncul saat bot
    PERTAMA KALI melihat pasaran baru, belum tentu tepat Senin 07.00
    bila game belum dibuka.
    """
    import json

    from . import monitor as monitor_mod
    from . import sim as sim_mod
    from ..tg.status import fetch_latest_state

    store = app.bot_data["store"]
    data = app.bot_data["data"]
    ctx = SimpleNamespace(bot_data=app.bot_data)
    for chat_id in store.all_chat_ids():
        try:
            state = await fetch_latest_state(ctx, chat_id)
        except Exception as exc:
            log.warning("notifikasi pasar chat %s dilewati: %s", chat_id, exc)
            continue
        pasaran_baru = state["slot"].get("harga_pasaran") or {}
        if not isinstance(pasaran_baru, dict):
            pasaran_baru = {}
        mentah = store.meta_get(chat_id, "pasaran")
        if mentah is None:
            store.meta_set(chat_id, "pasaran",
                           json.dumps(pasaran_baru, ensure_ascii=False))
            continue
        try:
            pasaran_lama = json.loads(mentah)
        except (json.JSONDecodeError, TypeError):
            pasaran_lama = {}
        if not isinstance(pasaran_lama, dict):
            pasaran_lama = {}
        perubahan = monitor_mod.bandingkan_pasaran(
            pasaran_lama, pasaran_baru, data, state["slot"])
        store.meta_set(chat_id, "pasaran",
                       json.dumps(pasaran_baru, ensure_ascii=False))
        if not perubahan:
            continue
        baris = ["Harga pasar minggu ini berubah:"]
        for p in perubahan:
            baris.append(f"- {p['nama']}: {p['saran']}")
        peringatan = monitor_mod.peringatan_harga(data, state["slot"])
        if peringatan:
            baris.append("")
            baris.append("Harga jualmu jauh dari pasar:")
            for w in peringatan:
                arah = ("terlalu mahal" if w["arah"] == "mahal"
                        else "terlalu murah")
                baris.append(
                    f"- {w['nama']}: {_format_rupiah(w['harga_jual'])} vs "
                    f"pasar {_format_rupiah(w['harga_pasar'])} ({arah})")
                if w["arah"] == "murah" and w["di_lantai"]:
                    baris[-1] += " — sudah di lantai, tidak bisa diturunkan"
        if not sim_mod.agen_aktif(state["slot"]):
            baris.append("")
            baris.append(
                "Catatan: harga pasar baru berpengaruh setelah agen aktif "
                "(Level 2).")
        try:
            markup = None
            if sim_mod.agen_aktif(state["slot"]):
                # Tombol langsung ke pratinjau /harga_pasar (callback
                # sim:harga_pasar mengambil state segar sendiri).
                markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(
                        "Terapkan harga pasar",
                        callback_data="sim:harga_pasar")]])
            await app.bot.send_message(chat_id=chat_id, text="\n".join(baris),
                                       reply_markup=markup)
        except Exception:
            log.exception("gagal mengirim notifikasi pasar ke chat %s",
                          chat_id)


async def cek_versi_game_job(app) -> None:
    """Job cek versi harian: fetch versi.json SEKALI; bila server lebih
    baru dari game (kode > 49 / versi > 1.2), kabari tiap chat SEKALI
    per kode baru (meta 'versi_diberitahu'). Gagal fetch = diam (log
    saja) — bukan bukti ada/tidak ada update."""
    from . import monitor as monitor_mod

    store = app.bot_data["store"]
    try:
        data_json = await monitor_mod.fetch_versi_json()
    except monitor_mod.VersionCheckError as exc:
        log.warning("cek versi game dilewati: %s", exc)
        return
    hasil = monitor_mod.cek_versi(data_json)
    if not hasil["diketahui"] or not hasil["ada_update"]:
        return
    kode = str(hasil["kode_server"])
    for chat_id in store.all_chat_ids():
        if store.meta_get(chat_id, "versi_diberitahu") == kode:
            continue
        teks = (
            f"Update game baru: versi {hasil['versi_server']} "
            f"(kode {hasil['kode_server']}). Perbarui di Play Store. "
            "Bot memakai rumus game 1.2, jadi hitungannya bisa bergeser "
            "setelah update.")
        try:
            await app.bot.send_message(chat_id=chat_id, text=teks)
            store.meta_set(chat_id, "versi_diberitahu", kode)
        except Exception:
            log.exception("gagal mengirim kabar update ke %s", chat_id)


async def backup_harian_job(app) -> None:
    """Job backup harian 03.00: arsipkan paket cloud tiap chat (satu
    arsip per hari; ``backup.arsipkan_harian`` menolak duplikat).
    Diam bila sukses maupun gagal sesaat (log saja) — tidak ada pesan
    ke pengguna."""
    from . import backup as backup_mod
    from ..tg.status import fetch_latest_state

    store = app.bot_data["store"]
    ctx = SimpleNamespace(bot_data=app.bot_data)
    for chat_id in store.all_chat_ids():
        try:
            state = await fetch_latest_state(ctx, chat_id)
        except Exception as exc:
            log.warning("backup harian chat %s dilewati: %s", chat_id, exc)
            continue
        try:
            backup_mod.arsipkan_harian(store, chat_id, state["versi"],
                                       state["p_data"])
        except Exception:
            log.exception("backup harian chat %s gagal", chat_id)


async def pengingat_adu_laris_job(app) -> None:
    """Job Jumat 17.00: pengingat adu laris mingguan (tier Profesional —
    yang melacak peringkat). Sekali per minggu per chat (meta
    'adu_laris_minggu' = Senin minggu berjalan). Bila peringkat minggu
    ini belum diketahui, diam (tidak ada yang bisa diingatkan)."""
    from . import monitor as monitor_mod
    from . import papan as papan_mod
    from ..tg.status import fetch_latest_state

    store = app.bot_data["store"]
    cloud = app.bot_data["cloud"]
    minggu = papan_mod.minggu_wib()
    ctx = SimpleNamespace(bot_data=app.bot_data)
    for chat_id in store.all_chat_ids():
        if store.get_tier(chat_id) < 3:
            continue
        if store.meta_get(chat_id, "adu_laris_minggu") == minggu:
            continue
        session = store.get_user(chat_id)
        if session is None:
            continue
        id_papan = session.get("p_id_papan") or ""
        try:
            state = await fetch_latest_state(ctx, chat_id)
            id_papan = state["ringkasan"]["id_papan"] or id_papan
            total = state["slot"].get("total_pembeli")
            try:
                total = int(total) if total is not None else None
            except (TypeError, ValueError):
                total = None
        except Exception as exc:
            log.warning("pengingat adu laris chat %s dilewati: %s",
                        chat_id, exc)
            continue
        if not id_papan:
            continue
        try:
            data_papan = await cloud.fetch_papan("minggu", id_papan)
        except Exception as exc:
            log.warning("pengingat adu laris chat %s: papan gagal: %s",
                        chat_id, exc)
            continue
        kode = papan_mod.kode_papan(id_papan)
        hasil = papan_mod.parse_papan(data_papan, kode, total)
        lama_row = store.get_peringkat(chat_id, "minggu")
        lama = lama_row["peringkat"] if lama_row else None
        store.save_peringkat(chat_id, "minggu", hasil["peringkat"],
                             hasil["jumlah_warung"])
        teks = monitor_mod.teks_pengingat_adu_laris(
            lama, hasil["peringkat"], hasil["jumlah_warung"])
        if teks is None:
            continue
        try:
            await app.bot.send_message(chat_id=chat_id, text=teks)
            store.meta_set(chat_id, "adu_laris_minggu", minggu)
        except Exception:
            log.exception("gagal mengirim pengingat adu laris ke %s", chat_id)


async def kirim_laporan_harian(app, chat_id: int) -> None:
    """Job: ambil state terbaru, kirim ringkasan pagi."""
    store = app.bot_data["store"]
    cloud = app.bot_data["cloud"]
    tugas_data = app.bot_data["tugas"]
    session = store.get_user(chat_id)
    if session is None:
        scheduler = app.bot_data.get("scheduler")
        if scheduler is not None:
            hapus_laporan(scheduler, chat_id)
        return
    ctx = SimpleNamespace(bot_data=app.bot_data)
    try:
        from ..tg.status import fetch_latest_state

        state = await fetch_latest_state(ctx, chat_id)
    except SessionExpired:
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text="Sesi login habis. Laporan harian dimatikan — "
                     "kirim ulang akun.json dengan /link untuk menyalakan lagi.",
            )
        except Exception:
            pass
        jadwal = store.get_jadwal(chat_id)
        if jadwal is not None:
            store.set_jadwal(chat_id, int(jadwal["jam"]), aktif=False)
        scheduler = app.bot_data.get("scheduler")
        if scheduler is not None:
            hapus_laporan(scheduler, chat_id)
        return
    except (NoCloudData, CloudError, save_mod.PackageError,
            save_mod.SlotError) as exc:
        log.warning("laporan harian chat %s dilewati: %s", chat_id, exc)
        return
    slot = state["slot"]
    ringkasan = state["ringkasan"]
    stok = slot.get("stok", {}) or {}
    menipis = [k for k, v in stok.items()
               if isinstance(v, (int, float)) and 0 < v <= 2]
    habis = [k for k, v in stok.items()
             if isinstance(v, (int, float)) and v <= 0]
    tingkat = int(slot.get("tingkat", 0))
    try:
        target = save_mod.task_targets(tugas_data, tingkat)
    except save_mod.TaskError:
        target = None
    baris = [
        "Laporan harian warungmu:",
        f"Uang {_format_rupiah(ringkasan['uang'])} · "
        f"QRIS {_format_rupiah(ringkasan['qris'])}",
        f"Level {ringkasan['level']} · Hari {ringkasan['hari']}",
    ]
    if target is not None:
        progres = slot.get("progres", {}) or {}
        baris.append(
            f"Tugas Lv {ringkasan['level']}: pelanggan "
            f"{int(progres.get('pelanggan', 0))}/{int(target.get('pelanggan', 0))} · "
            f"barang {int(progres.get('barang', 0))}/{int(target.get('barang', 0))} · "
            f"omzet {_format_rupiah(int(progres.get('omzet', 0)))}"
            f"/{_format_rupiah(int(target.get('omzet', 0)))}"
        )
    if menipis:
        baris.append("Stok menipis: " + ", ".join(menipis))
    if habis:
        baris.append("Stok habis: " + ", ".join(habis))
    hari = int(slot.get("hari", 1))
    if hari % 7 == 6:
        baris.append("Besok Minggu: sewa kios jatuh tempo.")
    if int(slot.get("minggu_tunggak", 0) or 0) > 0:
        baris.append(
            f"Peringatan: tunggakan sewa {int(slot.get('minggu_tunggak', 0))} minggu "
            f"({_format_rupiah(int(slot.get('tunggakan_sewa', 0) or 0))}) — "
            "diusir bila mencapai 3 minggu.")
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text="\n".join(baris),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Lihat Status",
                                       callback_data="menu:status")]]
            ),
        )
    except Exception:
        log.exception("gagal mengirim laporan harian ke chat %s", chat_id)
