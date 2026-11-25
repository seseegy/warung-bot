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


def _baris_tugas(progres: dict, target: dict) -> list[str]:
    """Baris tugas (monospace) untuk kartu status dan kartu tugas.

    Mengembalikan satu blok teks preformatted agar progress bar sejajar
    di font monospace Telegram. Omzet ditulis ringkas (100rb/100rb) supaya
    muat satu baris di layar HP.
    """
    baris: list[str] = []
    for kunci, label in (
        ("pelanggan", "Pelanggan"),
        ("barang", "Barang"),
        ("omzet", "Omzet"),
    ):
        t = int(target.get(kunci, 0))
        p = int(progres.get(kunci, 0))
        nilai = (
            f"{format_rupiah_compact(p)}/{format_rupiah_compact(t)}"
            if kunci == "omzet"
            else f"{p}/{t}"
        )
        baris.append(f"{label:<9} {progress_bar(p, t, lebar=8)} {nilai}")
    khusus = target.get("khusus", {})
    if isinstance(khusus, dict) and khusus.get("target"):
        jenis = str(khusus.get("jenis", ""))
        t = int(khusus.get("target", 0))
        p = int(progres.get("khusus", 0))
        label = KHUSUS_LABEL.get(jenis, "{n}").format(n=t)
        if jenis == "laba_hari":
            label = KHUSUS_LABEL[jenis].format(n=format_rupiah(t))
        baris.append(f"Khusus    {progress_bar(p, t, lebar=8)} {p}/{t} — {label}")
    return baris


def _blocker_naik_level(slot: dict, target: dict, data=None) -> list[str]:
    """Sebab-sebab progres penuh tapi level belum naik (jujur, seperti
    ``fill_task_progress``/``format_task_card``).

    ``data`` (opsional) = GameData untuk nama + harga upgrade. Bila None,
    jatuh ke id mentah. Mengembalikan daftar pesan pendek.
    """
    blockers: list[str] = []
    syarat_upgrade = target.get("upgrade", [])
    if syarat_upgrade:
        dimiliki = slot.get("upgrade", [])
        if not isinstance(dimiliki, list):
            dimiliki = []
        if not any(u in dimiliki for u in syarat_upgrade):
            nama_teks: list[str] = []
            for uid in syarat_upgrade:
                info = None
                if data is not None:
                    info = data.upgrade_by_id.get(str(uid))
                if info and info.get("nama"):
                    nama = str(info["nama"])
                    harga = int(info.get("harga", 0))
                    if harga:
                        nama += f" ({format_rupiah_compact(harga)})"
                    nama_teks.append(nama)
                else:
                    nama_teks.append(str(uid))
            blockers.append("beli upgrade " + "/".join(nama_teks))
    misi_status = str(slot.get("misi_status", ""))
    cerita_tamat = bool(slot.get("cerita_tamat", False))
    if misi_status not in ("", "lunas") and not cerita_tamat:
        blockers.append("selesaikan misi Agus")
    return blockers


def format_status_card(
    ringkasan: dict, slot: dict, tugas_data: dict, versi_cloud: int,
    disinkronkan: str | None = None,
    otomatis: bool | None = None,
    tier: int | None = None,
    jam_otomatis: int | None = None,
    data=None,
    nomor_slot: int | None = None,
) -> str:
    """Kartu status (RANCANGAN §15.4).

    ``disinkronkan`` (opsional, "YYYY-MM-DD HH:MM:SS" WIB) = jam bot
    mengambil save ini dari cloud. Ditampilkan bersama "disimpan"
    (jam game menyimpan slot di HP) supaya keduanya tidak tertukar.

    ``otomatis``/``tier``/``jam_otomatis`` (opsional) = ringkasan status
    otomatisasi di bawah kartu. ``otomatis=None`` (default) = tidak
    ditampilkan (dipakai jalur yang belum punya akses store).

    ``data`` (opsional) = GameData untuk nama + harga upgrade syarat.

    ``nomor_slot`` (opsional) = nomor slot yang sedang ditampilkan,
    ditulis di baris simpanan supaya jelas kartu ini slot yang mana
    (bot bisa memakai slot pilihan /slot, bukan selalu slot terbaik).
    """
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
        baris.append("```")
        baris.extend(_baris_tugas(progres, target))
        baris.append("```")
        # Bila semua progres sudah penuh, jelaskan kenapa belum naik level.
        semua_penuh = all(
            int(progres.get(k, 0)) >= int(target.get(k, 0))
            for k in ("pelanggan", "barang", "omzet")
            if int(target.get(k, 0)) > 0
        )
        khusus = target.get("khusus", {})
        if isinstance(khusus, dict) and khusus.get("target"):
            semua_penuh = semua_penuh and int(progres.get("khusus", 0)) >= int(khusus.get("target", 0))
        if semua_penuh:
            blok = _blocker_naik_level(slot, target, data)
            if blok:
                baris.append("Semua tugas beres — tinggal: " + " · ".join(blok))
    else:
        baris.append("Tugas: sudah level terakhir, tidak ada tugas lagi.")
    baris_disimpan = f"Simpanan online v{versi_cloud}"
    if nomor_slot is not None:
        baris_disimpan += f" · Slot {int(nomor_slot)}"
    baris_disimpan += f" · disimpan {format_disimpan(ringkasan['disimpan'])}"
    if disinkronkan:
        baris_disimpan += f" · disinkronkan {format_disimpan(disinkronkan)} WIB"
    if otomatis is not None:
        from ..core.tiers import nama_tier
        status_oto = "NYALA" if otomatis else "MATI"
        jam = int(jam_otomatis or 7)
        baris_disimpan += (
            f"\nOtomatis: {status_oto} · {nama_tier(tier)}"
            f" · siklus tiap {jam:02d}.00 WIB"
        )
    baris += [
        "",
        baris_disimpan,
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
        "```",
    ]
    baris.extend(_baris_tugas(progres, target))
    baris.append("```")
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

    Pemilihan slot (SATU titik resolusi untuk semua pemanggil):

    - ``nomor_slot`` eksplisit (1-6, mis. dari pending konfirmasi):
      slot itu yang dipakai, KETAT — kosong/rusak -> ``SlotError``.
      Pending harus mendarat di slot asal state-nya, bukan slot lain.
    - ``nomor_slot=None`` (default semua fitur): hormati pilihan
      pengguna di ``/slot`` (``store.get_slot_aktif``). Bila pilihan
      itu kosong/rusak di cloud, pilihan dibersihkan dan bot jatuh
      ke slot terbaik — bot tidak boleh terkunci oleh pilihan lama.
      Tanpa pilihan: slot terbaik seperti ``kemajuan_hp`` (level
      lalu hari).

    ``kemajuan`` sesi SELALU menggambarkan slot terbaik, seperti
    ``akun.json`` game, apa pun slot yang sedang dipakai bot.

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
    slot_map = paket.get("slot", {})
    if not isinstance(slot_map, dict):
        slot_map = {}
    if nomor_slot is not None:
        # Eksplisit: ketat, slot harus ada dan bisa dibaca.
        if not 1 <= int(nomor_slot) <= 6:
            raise save_mod.SlotError("nomor slot harus 1-6")
        teks = slot_map.get(str(int(nomor_slot)))
        if not teks:
            raise save_mod.SlotError(f"slot {nomor_slot} kosong")
        slot = save_mod.parse_slot(teks)
        nomor_slot = int(nomor_slot)
    else:
        # Implisit: pilihan /slot dulu, lalu slot terbaik.
        slot = None
        pilihan = store.get_slot_aktif(chat_id)
        if pilihan is not None:
            teks = slot_map.get(str(pilihan))
            if teks:
                try:
                    slot = save_mod.parse_slot(teks)
                    nomor_slot = pilihan
                except save_mod.SlotError:
                    slot = None
            if slot is None:
                # Pilihan lama sudah kosong/rusak di cloud: bersihkan
                # supaya bot kembali ke slot terbaik, bukan gagal terus.
                store.set_slot_aktif(chat_id, None)
        if slot is None:
            nomor_slot, slot = save_mod.best_slot(paket)
    ringkasan = save_mod.slot_summary(slot)
    # Perbarui info versi/sidik/kemajuan di store dari data cloud terbaru.
    session["versi"] = int(cloud_data["versi"])
    try:
        session["sidik"] = save_mod.compute_sidik(paket)
    except save_mod.PackageError:
        session["sidik"] = session.get("sidik", "")
    session["p_id_papan"] = ringkasan["id_papan"] or session.get("p_id_papan", "")
    # Kemajuan selalu slot terbaik (seperti akun.json game), apa pun
    # slot yang sedang dipakai bot.
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
    except (save_mod.SlotError, save_mod.PackageError):
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
        # Jam bot mengambil save ini (WIB) — ditampilkan di kartu status
        # supaya tidak tertukar dengan "disimpan" (jam game menyimpan
        # slot ini di HP, yang bisa jauh lebih lama).
        "disinkronkan": save_mod.sekarang_wib_str(),
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
