"""Kartu status + pengambilan state terbaru dari cloud.

Format tampilan mengikuti RANCANGAN §15.4 (teks polos, tanpa emoji).
Data digrounding ke kode game:

- ``info_slot()`` (game_state.gd): level = tingkat+1, qris = saldo_digital.
- ``teks_khusus()`` (game_state.gd ~l.3126): label tugas khusus per jenis.
- ``kemajuan_hp()`` (akun_online.gd): slot terbaik = level lalu hari.
"""

from __future__ import annotations

from datetime import datetime

from ..core import save as save_mod
from ..core.cloud import CloudError, NoCloudData, SessionExpired

BULAN_ID = [
    "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
    "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
]

# Label tugas khusus — sama dengan teks_khusus() di game_state.gd.
KHUSUS_LABEL = {
    "beruntun": "Layani {n}x beruntun",
    "multi": "{n} pesanan campuran",
    "laba_hari": "Laba {n} sehari",
    "minuman": "Jual {n} minuman",
    "hari_sempurna": "Sehari tanpa batal (min. {n})",
}


class NotLinked(Exception):
    """Pengguna belum menautkan akun (tidak ada sesi di store)."""


def format_rupiah(nilai: int | float) -> str:
    """Rp4.500.000 — pemisah ribuan titik (format Indonesia)."""
    return f"Rp{int(nilai):,}".replace(",", ".")


def format_rupiah_compact(nilai: int | float) -> str:
    """Rp2,1jt / Rp1,5rb / Rp500 — untuk bar progres yang sempit."""
    nilai = int(nilai)
    if nilai >= 1_000_000:
        angka = nilai / 1_000_000
        teks = f"{angka:.1f}".replace(".", ",").rstrip("0").rstrip(",")
        return f"Rp{teks}jt"
    if nilai >= 1_000:
        angka = nilai / 1_000
        teks = f"{angka:.1f}".replace(".", ",").rstrip("0").rstrip(",")
        return f"Rp{teks}rb"
    return f"Rp{nilai}"


def progress_bar(saat_ini: int, target: int, lebar: int = 10) -> str:
    """Bar █/░. Target 0 -> penuh (tidak ada syarat)."""
    if target <= 0:
        return "█" * lebar
    terisi = max(0, min(lebar, round(saat_ini / target * lebar)))
    return "█" * terisi + "░" * (lebar - terisi)


def format_disimpan(disimpan: str) -> str:
    """'2026-11-24 10:39:21' -> '24 Nov 2026 10:39'. Gagal parse -> mentah."""
    try:
        dt = datetime.strptime(disimpan, "%Y-%m-%d %H:%M:%S")
        return f"{dt.day} {BULAN_ID[dt.month - 1]} {dt.year} {dt.hour:02d}:{dt.minute:02d}"
    except (ValueError, TypeError):
        return disimpan or "-"


def format_status_card(
    ringkasan: dict, slot: dict, tugas_data: dict, versi_cloud: int
) -> str:
    """Kartu status (RANCANGAN §15.4)."""
    tingkat = int(slot.get("tingkat", 0))
    try:
        target = save_mod.task_targets(tugas_data, tingkat)
    except save_mod.TaskError:
        target = None
    progres = slot.get("progres", {})
    if not isinstance(progres, dict):
        progres = {}

    energi = slot.get("energi", "?")
    energi_teks = f"{float(energi):.0f}" if isinstance(energi, (int, float)) else "?"
    stok = slot.get("stok", {})
    stok_ada = sum(1 for v in stok.values() if isinstance(v, (int, float)) and v > 0) if isinstance(stok, dict) else 0

    baris = [
        f"Warung \"{ringkasan['nama_warung'] or '(belum bernama)'}\""
        f" — Level {ringkasan['level']} · Hari {ringkasan['hari']}",
        f"Uang {format_rupiah(ringkasan['uang'])} · QRIS {format_rupiah(ringkasan['qris'])}",
        f"Energi {energi_teks} · Stok {stok_ada} jenis barang ada stok",
        "",
    ]
    if target is not None:
        baris.append(f"Tugas Lv {ringkasan['level']} — {target.get('nama', '')}")
        for kunci, label in (
            ("pelanggan", "Pelanggan"),
            ("barang", "Barang"),
            ("omzet", "Omzet"),
        ):
            t = int(target.get(kunci, 0))
            p = int(progres.get(kunci, 0))
            nilai = (
                f"{format_rupiah_compact(p)} / {format_rupiah_compact(t)}"
                if kunci == "omzet"
                else f"{p}/{t}"
            )
            baris.append(f"{label:<10}{progress_bar(p, t)} {nilai}")
        khusus = target.get("khusus", {})
        if isinstance(khusus, dict) and khusus.get("target"):
            jenis = str(khusus.get("jenis", ""))
            t = int(khusus.get("target", 0))
            p = int(progres.get("khusus", 0))
            label = KHUSUS_LABEL.get(jenis, "{n}").format(n=t)
            if jenis == "laba_hari":
                label = KHUSUS_LABEL[jenis].format(n=format_rupiah(t))
            baris.append(f"Khusus    {progress_bar(p, t)} {p}/{t} — {label}")
    else:
        baris.append("Tugas: sudah level terakhir, tidak ada tugas lagi.")
    baris += [
        "",
        f"Simpanan online v{versi_cloud}"
        f" · disimpan {format_disimpan(ringkasan['disimpan'])}",
    ]
    return "\n".join(baris)


def format_task_card(slot: dict, tugas_data: dict) -> str:
    """Kartu tugas level berjalan (dipakai /tugas + tombol Tugas)."""
    tingkat = int(slot.get("tingkat", 0))
    try:
        target = save_mod.task_targets(tugas_data, tingkat)
    except save_mod.TaskError:
        return "Sudah di level terakhir (Level 11 'Coming Soon') — tidak ada tugas lagi."
    progres = slot.get("progres", {})
    if not isinstance(progres, dict):
        progres = {}
    baris = [
        f"Tugas Level {tingkat + 1} — {target.get('nama', '')}",
        f"Hadiah: {format_rupiah(int(target.get('hadiah', 0)))}",
        "",
    ]
    for kunci, label in (
        ("pelanggan", "Pelanggan"),
        ("barang", "Barang"),
        ("omzet", "Omzet"),
    ):
        t = int(target.get(kunci, 0))
        p = int(progres.get(kunci, 0))
        nilai = (
            f"{format_rupiah_compact(p)} / {format_rupiah_compact(t)}"
            if kunci == "omzet"
            else f"{p}/{t}"
        )
        baris.append(f"{label:<10}{progress_bar(p, t)} {nilai}")
    khusus = target.get("khusus", {})
    if isinstance(khusus, dict) and khusus.get("target"):
        jenis = str(khusus.get("jenis", ""))
        t = int(khusus.get("target", 0))
        p = int(progres.get("khusus", 0))
        label = KHUSUS_LABEL.get(jenis, "{n}").format(n=t)
        if jenis == "laba_hari":
            label = KHUSUS_LABEL[jenis].format(n=format_rupiah(t))
        baris.append(f"Khusus    {progress_bar(p, t)} {p}/{t} — {label}")
    # Syarat lain _cek_tugas() yang tidak terlihat dari progres saja.
    syarat: list[str] = []
    upgrade = target.get("upgrade", [])
    if upgrade:
        dimiliki = slot.get("upgrade", [])
        if not isinstance(dimiliki, list):
            dimiliki = []
        punya = [u for u in upgrade if u in dimiliki]
        if punya:
            syarat.append("Upgrade: sudah dimiliki (" + ", ".join(punya) + ")")
        else:
            syarat.append(
                "Upgrade: belum dimiliki ("
                + ", ".join(str(u) for u in upgrade)
                + ")"
            )
    misi = str(slot.get("misi_status", ""))
    if not bool(slot.get("cerita_tamat", False)):
        syarat.append(
            "Misi cerita: " + ("lunas" if misi in ("", "lunas") else f"belum lunas ({misi})")
        )
    if syarat:
        baris += ["", "Syarat lain: " + " · ".join(syarat)]
    return "\n".join(baris)


# -- pengambilan state -------------------------------------------------

async def fetch_latest_state(context, chat_id: int,
                             nomor_slot: int | None = None) -> dict:
    """Ambil save terbaru dari cloud + decode + pilih slot.

    Default (``nomor_slot=None``): slot terbaik seperti ``kemajuan_hp``
    (level lalu hari). Bila ``nomor_slot`` 1-6 diberikan (pilihan /slot
    Fase 5), slot itu yang dipakai — dan ``kemajuan`` sesi TIDAK
    diperbarui (kemajuan selalu menggambarkan slot terbaik, seperti
    ``akun.json`` game).

    Mengembalikan dict: versi, p_data, paket, nomor_slot, slot, ringkasan,
    session (sesi terbaru setelah kemungkinan refresh token).
    Sesi yang di-refresh langsung disimpan ke store oleh fungsi ini.

    Melempar: NotLinked, SessionExpired, NoCloudData, CloudError,
    PackageError, SlotError.
    """
    store = context.bot_data["store"]
    cloud = context.bot_data["cloud"]
    session = store.get_user(chat_id)
    if session is None:
        raise NotLinked("belum ada akun tertaut")
    try:
        cloud_data, session = await cloud.fetch_cloud(session)
    except SessionExpired:
        # Perilaku game saat refresh ditolak: sesi dihapus, wajib login ulang.
        store.delete_user(chat_id)
        raise
    except (NoCloudData, CloudError) as exc:
        # Refresh token mungkin sudah di-rotasi sebelum kegagalan ini;
        # simpan sesi terbaru agar token baru tidak hilang.
        if getattr(exc, "session", None):
            store.update_session(chat_id, exc.session)
        raise
    # Token mungkin di-refresh di dalam fetch_cloud -> simpan sesi baru.
    store.update_session(chat_id, session)
    paket = save_mod.decode_package(cloud_data["data"])
    if nomor_slot is None:
        nomor_slot, slot = save_mod.best_slot(paket)
    else:
        if not 1 <= int(nomor_slot) <= 6:
            raise save_mod.SlotError("nomor slot harus 1-6")
        slot_map = paket.get("slot", {})
        teks = slot_map.get(str(int(nomor_slot))) if isinstance(
            slot_map, dict) else None
        if not teks:
            raise save_mod.SlotError(f"slot {nomor_slot} kosong")
        slot = save_mod.parse_slot(teks)
    ringkasan = save_mod.slot_summary(slot)
    # Perbarui info versi/sidik/kemajuan di store dari data cloud terbaru.
    session["versi"] = int(cloud_data["versi"])
    try:
        session["sidik"] = save_mod.compute_sidik(paket)
    except save_mod.PackageError:
        session["sidik"] = session.get("sidik", "")
    session["p_id_papan"] = ringkasan["id_papan"] or session.get("p_id_papan", "")
    if nomor_slot is None:
        # Slot terbaik: kemajuan = slot itu.
        session["kemajuan"] = {
            "level": ringkasan["level"],
            "hari": ringkasan["hari"],
            "nama": ringkasan["nama_warung"],
            "uang": ringkasan["uang"],
            "qris": ringkasan["qris"],
            "disimpan": ringkasan["disimpan"],
        }
    else:
        # Slot eksplisit: kemajuan tetap dari slot terbaik.
        try:
            _, slot_terbaik = save_mod.best_slot(paket)
            ringkasan_terbaik = save_mod.slot_summary(slot_terbaik)
            session["kemajuan"] = {
                "level": ringkasan_terbaik["level"],
                "hari": ringkasan_terbaik["hari"],
                "nama": ringkasan_terbaik["nama_warung"],
                "uang": ringkasan_terbaik["uang"],
                "qris": ringkasan_terbaik["qris"],
                "disimpan": ringkasan_terbaik["disimpan"],
            }
        except save_mod.SlotError:
            pass
    store.update_session(chat_id, session)
    return {
        "versi": int(cloud_data["versi"]),
        "p_data": cloud_data["data"],
        "paket": paket,
        "nomor_slot": nomor_slot,
        "slot": slot,
        "ringkasan": ringkasan,
        "session": session,
    }


def kemajuan_terakhir(session: dict) -> str:
    """Satu baris ringkasan kemajuan tersimpan (dipakai pesan fallback)."""
    k = session.get("kemajuan", {})
    if not isinstance(k, dict) or not k:
        return ""
    return (
        f"Level {k.get('level', '?')} · Hari {k.get('hari', '?')} · "
        f"Uang {format_rupiah(int(k.get('uang', 0) or 0))}"
    )
