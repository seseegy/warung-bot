"""Alur perubahan save: konfirmasi -> ambil terbaru -> backup -> upload.

Aturan main bersama (RANCANGAN §8) yang ditegakkan di sini:
1. SEBELUM menulis, bot selalu ``akun_ambil`` dulu dan memakai
   ``p_versi_dasar`` terbaru. Edit diterapkan ke paket TERBARU, bukan ke
   paket yang sudah lama diambil — supaya progres dari HP tidak tertimpa.
2. Sebelum upload, paket lama dicadangkan di store (rollback).
3. Bentrok -> upload DITAHAN, pending disimpan, pengguna memilih
   [Pakai Simpanan Online] atau [Timpa dengan Punya Saya].
   "Timpa" mengirim ulang paket edit yang SAMA dengan ``p_paksa=true``
   dan ``p_versi_dasar`` yang sama seperti saat ditolak (bukan versi
   baru hasil ambil ulang — itu akan menyembunyikan konflik dari server).
"""

from __future__ import annotations

import time

from ..core import save as save_mod
from ..core.cloud import CloudError, ConflictError, NoCloudData, SessionExpired
from .status import fetch_latest_state, format_rupiah, format_rupiah_compact, progress_bar

PENDING_KEY = "pending"


def build_pending_uang(state: dict, jumlah_baru: int) -> tuple[dict, str]:
    """Pending ubah uang + teks konfirmasi (lama -> baru)."""
    lama = state["ringkasan"]["uang"]
    pending = {
        "kind": "uang",
        "jumlah_baru": int(jumlah_baru),
        "id_papan": state["ringkasan"]["id_papan"],
        "p_data": None,
        "versi_dasar": None,
    }
    teks = (
        "Ubah uang?\n"
        f"{format_rupiah(lama)} → {format_rupiah(jumlah_baru)}\n"
        f"Akan diunggah ke simpanan online (perkiraan v{state['versi'] + 1}).\n"
        "Pastikan game sedang tertutup.\n"
        "Tombol cepat menambah ke uang sekarang; ketik sendiri mengganti total."
    )
    return pending, teks


def build_pending_tugas(state: dict, tugas_data: dict) -> tuple[dict, str]:
    """Pending isi progres tugas + teks konfirmasi (termasuk blocker jujur)."""
    slot = state["slot"]
    hasil = save_mod.fill_task_progress(dict(slot), tugas_data)
    target = hasil["target"]
    progres = slot.get("progres", {}) if isinstance(slot.get("progres"), dict) else {}
    baris = [
        f"Isi progres tugas Lv {int(slot.get('tingkat', 0)) + 1}"
        f" — {target.get('nama', '')} sampai target?",
    ]
    for kunci, label in (
        ("pelanggan", "Pelanggan"),
        ("barang", "Barang"),
        ("omzet", "Omzet"),
    ):
        t = int(target.get(kunci, 0))
        p = int(progres.get(kunci, 0))
        nilai = (
            f"{format_rupiah_compact(p)} → {format_rupiah_compact(t)}"
            if kunci == "omzet"
            else f"{p} → {t}"
        )
        baris.append(f"{label:<10}{progress_bar(p, t)} {nilai}")
    khusus = target.get("khusus", {})
    if isinstance(khusus, dict) and khusus.get("target"):
        t = int(khusus.get("target", 0))
        p = int(progres.get("khusus", 0))
        baris.append(f"Khusus    {progress_bar(p, t)} {p} → {t}")
    baris.append(
        f"Hadiah {format_rupiah(int(target.get('hadiah', 0)))} dibayar game "
        "saat berikutnya mengecek tugas (mis. setelah 1 penjualan)."
    )
    if hasil["blockers"]:
        baris.append("")
        baris.append("Perhatian — hadiah BELUM tentu cair:")
        baris.extend(f"- {b}" for b in hasil["blockers"])
    baris.append("Pastikan game sedang tertutup.")
    pending = {
        "kind": "tugas",
        "id_papan": state["ringkasan"]["id_papan"],
        "p_data": None,
        "versi_dasar": None,
    }
    return pending, "\n".join(baris)


def build_pending_simulasi(state: dict, hasil: dict) -> tuple[dict, str]:
    """Pending terapkan hasil simulasi + teks konfirmasi.

    Slot akhir disimpan APA ADANYA (nilai absolut). Saat eksekusi, bot
    memeriksa versi cloud masih sama dengan saat simulasi dibuat — bila
    berubah, penerapan DITOLAK (minta simulasi ulang) supaya progres dari
    HP tidak tertimpa.
    """
    slot_akhir = hasil["slot_akhir"]
    pending = {
        "kind": "simulasi",
        "id_papan": state["ringkasan"]["id_papan"],
        "p_data": None,
        "versi_dasar": int(state["versi"]),
        "slot_akhir": slot_akhir,
        "jumlah_hari": len(hasil["hari"]),
    }
    naik = hasil["tingkat_akhir"] - hasil["tingkat_awal"]
    baris = [
        f"Terapkan hasil simulasi {len(hasil['hari'])} hari ke simpanan?",
        f"Uang {format_rupiah(hasil['uang_awal'])} → "
        f"{format_rupiah(hasil['uang_akhir'])}",
        f"QRIS {format_rupiah(hasil['qris_awal'])} → "
        f"{format_rupiah(hasil['qris_akhir'])}",
        f"Omzet {format_rupiah(hasil['omzet'])} · "
        f"Laba {format_rupiah(hasil['laba'])} · "
        f"Dilayani {hasil['dilayani']} · Batal {hasil['batal']}",
    ]
    if naik > 0:
        baris.append(f"Naik {naik} level (hadiah sudah masuk ke uang).")
    if hasil["tunggakan_sewa"] > 0:
        baris.append(
            f"Peringatan: tunggakan sewa {format_rupiah(hasil['tunggakan_sewa'])} "
            f"({hasil['minggu_tunggak']} minggu).")
    if hasil.get("diusir"):
        baris.append(
            "Peringatan: dalam simulasi ini warung DIUSIR (tunggakan sewa "
            "mencapai 3 minggu) — menerapkan hasil ini akan mengunggah "
            "save yang sudah diusir.")
    baris.append(
        "Ini PROYEKSI, bukan hasil main sungguhan — RNG, event acak, dan "
        "pilihan cerita tidak disimulasikan.")
    baris.append("Pastikan game sedang tertutup.")
    return pending, "\n".join(baris)


def build_pending_harga(state: dict, harga_baru: dict,
                        hasil: list) -> tuple[dict, str]:
    """Pending terapkan harga terbaik + teks konfirmasi."""
    pending = {
        "kind": "harga",
        "id_papan": state["ringkasan"]["id_papan"],
        "p_data": None,
        "versi_dasar": int(state["versi"]),
        "harga_baru": {k: int(v) for k, v in harga_baru.items()},
    }
    baris = ["Terapkan harga terbaik ke simpanan?"]
    for entri in hasil:
        if entri["id"] in harga_baru:
            baris.append(
                f"{entri['nama']}: {format_rupiah(entri['harga_sekarang'])} → "
                f"{format_rupiah(entri['harga_terbaik'])} "
                f"(laba/hari {format_rupiah(entri['laba_sekarang'])} → "
                f"{format_rupiah(entri['laba_terbaik'])})")
    baris.append("Harga dihitung dari simulasi — proyeksi, bukan jaminan.")
    baris.append("Pastikan game sedang tertutup.")
    return pending, "\n".join(baris)


def build_pending_harga_pasar(state: dict, harga_baru: dict,
                              perubahan: list) -> tuple[dict, str]:
    """Pending terapkan harga pasar + teks konfirmasi.

    Bentuk pending SAMA dengan ``build_pending_harga`` (kind "harga",
    jadi ``execute_upload`` memakainya tanpa cabang baru) — bedanya
    penanda ``"sumber": "pasar"`` (dipakai execute_upload untuk memilih
    kata "harga pasar" di pesan hasil) dan teks konfirmasi yang menyebut
    "harga pasar" tanpa angka laba: harga pasar tidak menjanjikan laba.
    """
    pending = {
        "kind": "harga",
        "sumber": "pasar",
        "id_papan": state["ringkasan"]["id_papan"],
        "p_data": None,
        "versi_dasar": int(state["versi"]),
        "harga_baru": {k: int(v) for k, v in harga_baru.items()},
    }
    baris = ["Terapkan harga pasar ke simpanan?"]
    for entri in perubahan:
        if entri["id"] in harga_baru:
            baris.append(
                f"{entri['nama']}: {format_rupiah(entri['lama'])} → "
                f"{format_rupiah(entri['baru'])}")
    baris.append(
        "Harga mengikuti harga pasar minggu ini (dari agen Pak Misran). "
        "Harga pasar bukan jaminan laba.")
    baris.append("Pastikan game sedang tertutup.")
    return pending, "\n".join(baris)


def build_pending_cepat(state: dict, slot_akhir: dict,
                        ringkasan_teks: str) -> tuple[dict, str]:
    """Pending aksi cepat Fase 5 (/jual, /beli, /ngopi, /tutup).

    Sama seperti simulasi: tolak bila cloud berubah sejak state diambil
    (``versi_dasar``), supaya progres dari HP tidak tertimpa.
    ``ringkasan_teks`` = satu-dua baris hasil aksi (dibuat handler).
    """
    pending = {
        "kind": "cepat",
        "id_papan": state["ringkasan"]["id_papan"],
        "p_data": None,
        "versi_dasar": int(state["versi"]),
        "nomor_slot": int(state["nomor_slot"]),
        "slot_akhir": slot_akhir,
        "ringkasan": ringkasan_teks,
    }
    baris = [
        "Terapkan aksi ini ke simpanan?",
        ringkasan_teks,
        "Pastikan game sedang tertutup.",
    ]
    return pending, "\n".join(baris)


def build_pending_rollback(state: dict, paket_arsip: dict, tanggal: str,
                           versi_arsip: int) -> tuple[dict, str]:
    """Pending rollback Fase 5: arsip diunggah sebagai versi baru.

    ``p_data`` arsip di-encode ulang dari paket yang SUDAH divalidasi
    (``backup.muat_arsip``). ``versi_dasar`` = versi cloud TERBARU saat
    ini (bukan versi arsip) — rollback adalah penimpaan sadar atas
    progres yang lebih baru, jadi konfirmasi ganda di handler adalah
    pengamannya, bukan cek versi.
    """
    from ..core import backup as backup_mod

    ringkasan = backup_mod.ringkasan_arsip(paket_arsip)
    pending = {
        "kind": "rollback",
        "id_papan": state["ringkasan"]["id_papan"],
        "p_data": save_mod.encode_package(paket_arsip),
        "versi_dasar": int(state["versi"]),
        "nomor_slot": None,
        "tanggal_arsip": tanggal,
        "versi_arsip": int(versi_arsip),
    }
    baris = [
        f"Pulihkan simpanan tanggal {tanggal} (v{versi_arsip})?",
        f"Arsip: \"{ringkasan['nama_warung'] or '(belum bernama)'}\" "
        f"Level {ringkasan['level']} · Hari {ringkasan['hari']} · "
        f"Uang {format_rupiah(ringkasan['uang'])}",
        f"Sekarang: \"{state['ringkasan']['nama_warung'] or '(belum bernama)'}\" "
        f"Level {state['ringkasan']['level']} · "
        f"Hari {state['ringkasan']['hari']} · "
        f"Uang {format_rupiah(state['ringkasan']['uang'])}",
        "PERINGATAN: progres setelah tanggal arsip akan HILANG. "
        "Paket cloud saat ini sudah dicadangkan otomatis sebelum "
        "pemulihan, jadi masih bisa dikembalikan lagi.",
        "Pastikan game sedang tertutup.",
    ]
    return pending, "\n".join(baris)


def conflict_text(versi_dasar: int) -> str:
    """Teks bentrok: server menolak karena cloud lebih baru dari versi dasar.

    Terjadi bila game/HP lain mengunggah DI ANTARA bot mengambil (vN) dan
    bot mengunggah — versi cloud saat ini tidak diketahui pasti, yang
    diketahui hanya: lebih baru dari vN.
    """
    return (
        "Simpanan di cloud berubah setelah bot mengambilnya "
        f"(bot memakai dasar v{versi_dasar} — kemungkinan game/HP lain "
        "baru saja mengunggah).\n"
        "Bot berhenti mengunggah supaya tidak ada yang tertimpa.\n"
        "Pilih: pakai simpanan online (buang hasil edit bot), atau "
        "timpa cloud dengan hasil edit bot."
    )


async def execute_upload(context, chat_id: int, pending: dict) -> tuple[str, str]:
    """Jalankan upload tertunda. Mengembalikan (teks_hasil, status).

    status: "ok" | "bentrok" | "sesi_habis" | "gagal".
    Pada "bentrok", pending diperbarui dengan paket edit + versi dasar
    agar bisa diulang paksa oleh pengguna.
    """
    store = context.bot_data["store"]
    cloud = context.bot_data["cloud"]
    tugas_data = context.bot_data["tugas"]
    try:
        # Pending aksi cepat membawa nomor slot pilihan pengguna; yang
        # lain memakai slot terbaik (tanpa kwarg — kompatibel dengan
        # pemanggil lama).
        if pending.get("nomor_slot") is not None:
            state = await fetch_latest_state(
                context, chat_id, nomor_slot=pending["nomor_slot"])
        else:
            state = await fetch_latest_state(context, chat_id)
    except SessionExpired:
        return ("Sesi login habis. Kirim ulang akun.json dari game dengan /link.", "sesi_habis")
    except NoCloudData:
        return ("Belum ada simpanan di cloud — tidak ada yang bisa diubah.", "gagal")
    except (CloudError, save_mod.PackageError, save_mod.SlotError) as exc:
        return (f"Tidak bisa mengambil simpanan terbaru: {exc}", "gagal")

    slot = dict(state["slot"])
    # Rollback membawa paket jadi (bukan slot edit) — diisi cabangnya.
    paket_baru = None
    p_data_baru = None
    if pending["kind"] == "uang":
        try:
            save_mod.set_uang(slot, int(pending["jumlah_baru"]))
        except ValueError as exc:
            return (f"Jumlah uang tidak valid: {exc}", "gagal")
        hasil_teks = (
            f"Uang jadi {format_rupiah(pending['jumlah_baru'])} "
            f"(simpanan online v{{versi}}). Buka game → pilih simpanan cloud."
        )
    elif pending["kind"] == "tugas":
        try:
            save_mod.fill_task_progress(slot, tugas_data)
        except save_mod.TaskError as exc:
            return (f"Tidak bisa mengisi tugas: {exc}", "gagal")
        hasil_teks = (
            "Progres tugas sudah diisi penuh dan diunggah "
            "(simpanan online v{versi}). Hadiah dibayar game saat "
            "mengecek tugas. Buka game → pilih simpanan cloud."
        )
    elif pending["kind"] == "simulasi":
        # Keamanan: tolak bila cloud berubah sejak simulasi dibuat.
        if int(state["versi"]) != int(pending.get("versi_dasar", -1)):
            return (
                "Simpanan di cloud berubah sejak simulasi dibuat "
                f"(simulasi dari v{pending.get('versi_dasar')}, "
                f"cloud sekarang v{state['versi']}). "
                "Jalankan simulasi ulang supaya tidak ada progres yang tertimpa.",
                "gagal",
            )
        slot = pending["slot_akhir"]
        jumlah_hari = int(pending.get("jumlah_hari", 1))
        hasil_teks = (
            f"Hasil simulasi {jumlah_hari} hari diterapkan dan diunggah "
            "(simpanan online v{versi}). Buka game → pilih simpanan cloud."
        )
    elif pending["kind"] == "siklus":
        # Siklus otomatis harian (Fase 3): sama seperti simulasi — tolak
        # bila cloud berubah sejak siklus mengambil state.
        if int(state["versi"]) != int(pending.get("versi_dasar", -1)):
            return (
                "Simpanan di cloud berubah sejak siklus otomatis mengambil "
                f"state (siklus dari v{pending.get('versi_dasar')}, "
                f"cloud sekarang v{state['versi']}). "
                "Siklus dibatalkan supaya tidak ada progres yang tertimpa.",
                "gagal",
            )
        slot = pending["slot_akhir"]
        hasil_teks = str(pending.get("ringkasan", "Siklus otomatis diunggah"))
        hasil_teks += " (simpanan online v{versi}). Buka game → pilih simpanan cloud."
    elif pending["kind"] == "harga":
        if int(state["versi"]) != int(pending.get("versi_dasar", -1)):
            return (
                "Simpanan di cloud berubah sejak harga dihitung "
                f"(dari v{pending.get('versi_dasar')}, "
                f"cloud sekarang v{state['versi']}). "
                + ("Hitung ulang harga pasar supaya tidak ada progres yang tertimpa."
                   if pending.get("sumber") == "pasar"
                   else "Hitung ulang harga terbaik supaya tidak ada progres yang tertimpa."),
                "gagal",
            )
        khusus = dict(slot.get("harga_jual_khusus", {}) or {})
        khusus.update({k: int(v) for k, v in pending["harga_baru"].items()})
        slot["harga_jual_khusus"] = khusus
        hasil_teks = (
            ("Harga pasar diterapkan dan diunggah "
             if pending.get("sumber") == "pasar"
             else "Harga terbaik diterapkan dan diunggah ")
            + "(simpanan online v{versi}). Buka game → pilih simpanan cloud."
        )
    elif pending["kind"] == "cepat":
        # Aksi cepat Fase 5: sama seperti simulasi — tolak bila cloud
        # berubah sejak state diambil.
        if int(state["versi"]) != int(pending.get("versi_dasar", -1)):
            return (
                "Simpanan di cloud berubah sejak aksi dihitung "
                f"(dari v{pending.get('versi_dasar')}, "
                f"cloud sekarang v{state['versi']}). "
                "Jalankan lagi aksinya supaya tidak ada progres yang tertimpa.",
                "gagal",
            )
        slot = pending["slot_akhir"]
        hasil_teks = str(pending.get("ringkasan", "Aksi cepat diterapkan"))
        hasil_teks += " (simpanan online v{versi}). Buka game → pilih simpanan cloud."
    elif pending["kind"] == "rollback":
        # Rollback Fase 5: arsip diunggah APA ADANYA sebagai versi baru.
        # Tidak ada cek versi terhadap arsip (arsip memang lebih lama) —
        # pengamannya adalah konfirmasi ganda di handler. Paket cloud
        # saat ini dicadangkan di bawah sebelum ditimpa.
        p_data_arsip = pending.get("p_data")
        if not p_data_arsip:
            return ("Tidak ada arsip yang bisa dipulihkan.", "gagal")
        try:
            paket_baru = save_mod.decode_package(p_data_arsip)
        except save_mod.PackageError as exc:
            return (f"Arsip rusak dan tidak bisa dipulihkan: {exc}", "gagal")
        p_data_baru = p_data_arsip
        hasil_teks = (
            f"Simpanan tanggal {pending.get('tanggal_arsip', '?')} "
            f"(v{pending.get('versi_arsip', '?')}) sudah dipulihkan "
            "(simpanan online v{versi}). Buka game → pilih simpanan cloud."
        )
    else:
        return (f"Aksi tertunda tidak dikenal: {pending.get('kind')}", "gagal")

    if p_data_baru is None:
        paket_baru = save_mod.build_package_with_slot(
            state["paket"], state["nomor_slot"], slot)
        p_data_baru = save_mod.encode_package(paket_baru)
    # Cadangkan paket cloud saat ini SEBELUM menimpa (rollback).
    store.save_backup(chat_id, state["versi"], state["p_data"])
    try:
        hasil, session = await cloud.upload_cloud(
            state["session"], p_data_baru, state["versi"],
            state["ringkasan"]["id_papan"], paksa=False,
        )
    except ConflictError as exc:
        if getattr(exc, "session", None):
            store.update_session(chat_id, exc.session)
        pending["p_data"] = p_data_baru
        pending["versi_dasar"] = state["versi"]
        return (
            conflict_text(state["versi"]),
            "bentrok",
        )
    except SessionExpired:
        store.delete_user(chat_id)
        return ("Sesi login habis. Kirim ulang akun.json dari game dengan /link.", "sesi_habis")
    except CloudError as exc:
        if getattr(exc, "session", None):
            store.update_session(chat_id, exc.session)
        return (f"Upload gagal: {exc}", "gagal")

    # Sukses: simpan versi + sidik baru seperti kirim() di akun_online.gd.
    session["versi"] = int(hasil["versi"])
    session["sidik"] = save_mod.compute_sidik(paket_baru)
    session["disimpan"] = int(time.time())
    if pending["kind"] == "rollback":
        # Kemajuan = slot terbaik paket arsip (bukan slot lama).
        _, slot = save_mod.best_slot(paket_baru)
    ringkasan_baru = save_mod.slot_summary(slot)
    session["kemajuan"] = {
        "level": ringkasan_baru["level"],
        "hari": ringkasan_baru["hari"],
        "nama": ringkasan_baru["nama_warung"],
        "uang": ringkasan_baru["uang"],
        "qris": ringkasan_baru["qris"],
        "disimpan": ringkasan_baru["disimpan"],
    }
    store.update_session(chat_id, session)
    return (hasil_teks.format(versi=hasil["versi"]), "ok")


async def execute_force_upload(context, chat_id: int, pending: dict) -> tuple[str, str]:
    """Kirim ulang paket edit yang ditolak bentrok, dengan p_paksa=true.

    Memakai p_data + p_versi_dasar yang TERSIMPAN saat penolakan (bukan
    ambil ulang) — supaya server tetap melihat ini sebagai penimpaan paksa.
    """
    store = context.bot_data["store"]
    cloud = context.bot_data["cloud"]
    p_data = pending.get("p_data")
    versi_dasar = pending.get("versi_dasar")
    id_papan = pending.get("id_papan") or ""
    if not p_data or versi_dasar is None or not id_papan:
        return ("Tidak ada upload tertunda yang bisa dipaksa.", "gagal")
    session = store.get_user(chat_id)
    if session is None:
        return ("Belum ada akun tertaut. Tautkan dulu dengan /link.", "gagal")
    try:
        hasil, session = await cloud.upload_cloud(
            session, p_data, int(versi_dasar), id_papan, paksa=True
        )
    except SessionExpired:
        store.delete_user(chat_id)
        return ("Sesi login habis. Kirim ulang akun.json dari game dengan /link.", "sesi_habis")
    except CloudError as exc:
        if getattr(exc, "session", None):
            store.update_session(chat_id, exc.session)
        return (f"Upload paksa gagal: {exc}", "gagal")
    paket_baru = save_mod.decode_package(p_data)
    session["versi"] = int(hasil["versi"])
    session["sidik"] = save_mod.compute_sidik(paket_baru)
    session["disimpan"] = int(time.time())
    _, slot = save_mod.best_slot(paket_baru)
    ringkasan_baru = save_mod.slot_summary(slot)
    session["kemajuan"] = {
        "level": ringkasan_baru["level"],
        "hari": ringkasan_baru["hari"],
        "nama": ringkasan_baru["nama_warung"],
        "uang": ringkasan_baru["uang"],
        "qris": ringkasan_baru["qris"],
        "disimpan": ringkasan_baru["disimpan"],
    }
    store.update_session(chat_id, session)
    return (
        f"Cloud sudah ditimpa dengan hasil edit bot (simpanan online v{hasil['versi']}). "
        "Buka game → pilih simpanan cloud.",
        "ok",
    )
