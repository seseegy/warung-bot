"""Tier Kerja 24/7 — Fase 3.

Tiga tier (RANCANGAN §13). Tier disimpan per chat di Store (kolom
``tier`` pada tabel users, default Pemula) dan DITEGAKKAN DI KODE —
bukan hanya di UI: tiap aksi otomatis memeriksa tier sebelum jalan.

Perubahan jujur terhadap rancangan (diverifikasi dari kode game):
- "Auto-klaim login harian" TIDAK BISA dilakukan bot lewat cloud:
  state login (hari_ke/tanggal/siklus) tinggal di ``pengaturan.cfg``
  lokal HP, bukan di paket cloud, dan divalidasi HMAC ``tanda``
  (``game_state.gd:4257-4263``). Bot hanya bisa MENGINGATKAN + mencatat
  klaim yang dikonfirmasi pengguna (lihat ``core/auto.py``).
- "Auto-bayar hutang" TIDAK ADA: hutang di game adalah uang yang
  DIPINJAMKAN pemain ke warga (``kasih_hutang()``,
  ``game_state.gd:5375``) — pemain adalah kreditur, bukan debitur.
  Yang bisa dibayar otomatis: tunggakan/sewa, zakat, cicilan motor.
  Hutang aktif hanya DILAPORKAN di /laporan.
- "Sebelum denda": denda sewa efektif 0 (``MAKS_DENDA_SEWA = 0``,
  ``game_state.gd:6330``). Risiko nyata menunggak adalah DIUSIR setelah
  3 minggu (``MINGGU_DIUSIR = 3``) — itu yang dicegah auto-bayar.
"""

from __future__ import annotations

TIER_PEMULA = 1
TIER_STANDAR = 2
TIER_PROFESIONAL = 3

TIER_NAMA = {
    TIER_PEMULA: "Pemula",
    TIER_STANDAR: "Standar",
    TIER_PROFESIONAL: "Profesional",
}

TIER_DESKRIPSI = {
    TIER_PEMULA: (
        "Dijaga bot, tanpa ubah progres. Pengingat klaim login harian, "
        "laporan pagi, pengingat stok menipis dan sewa jatuh tempo."
    ),
    TIER_STANDAR: (
        "Semua Pemula, ditambah: simulasi 1 hari otomatis tiap hari, "
        "auto-beli stok saat menipis, harga ikut harga pasar Senin, "
        "auto-isi progres tugas saat target tercapai."
    ),
    TIER_PROFESIONAL: (
        "Semua Standar, ditambah: harga dinamis per barang (pilih hasil "
        "terbaik dari 3 simulasi), rencana naik level, auto-bayar "
        "sewa/zakat/cicilan motor, lacak posisi peringkat, Mode Target "
        "Level (kerja nonstop sampai level tujuan)."
    ),
}

# Fitur -> tier minimum. Dipakai require_tier().
FITUR_MIN_TIER = {
    "login_inget": TIER_PEMULA,
    "laporan": TIER_PEMULA,
    "pengingat": TIER_PEMULA,
    "simulasi_harian": TIER_STANDAR,
    "auto_beli": TIER_STANDAR,
    "auto_harga_pasar": TIER_STANDAR,
    "auto_tugas": TIER_STANDAR,
    "harga_dinamis": TIER_PROFESIONAL,
    "rencana_level": TIER_PROFESIONAL,
    "auto_bayar": TIER_PROFESIONAL,
    "peringkat": TIER_PROFESIONAL,
    # Mode Target Level: jalan tiap 5 menit sampai level tujuan (butuh
    # harga dinamis + auto-bayar + bayar misi + beli upgrade syarat).
    "mode_target": TIER_PROFESIONAL,
    # Fase 5: aksi cepat mengubah save langsung (jual/beli/ngopi/tutup).
    "aksi_cepat": TIER_STANDAR,
}

FITUR_NAMA = {
    "login_inget": "pengingat login harian",
    "laporan": "laporan harian",
    "pengingat": "pengingat stok/sewa",
    "simulasi_harian": "simulasi harian otomatis",
    "auto_beli": "auto-beli stok",
    "auto_harga_pasar": "harga ikut pasar",
    "auto_tugas": "auto-isi progres tugas",
    "harga_dinamis": "harga dinamis",
    "rencana_level": "rencana naik level",
    "auto_bayar": "auto-bayar sewa/zakat/cicilan",
    "peringkat": "lacak peringkat",
    "mode_target": "mode target level",
    "aksi_cepat": "aksi cepat (jual/beli/ngopi/tutup)",
}

# Batas harian default: maks kenaikan bersih uang (Rp) yang boleh
# dihasilkan satu siklus otomatis. BUKAN aturan game — pilihan bot
# (RANCANGAN §14 tidak memberi angka) supaya progres terlihat natural.
# Bila terlampaui, simulasi hari itu tidak diterapkan.
BATAS_PERUBAHAN_UANG_HARIAN_DEFAULT = 1_000_000

# Jam default siklus otomatis (WIB).
JAM_OTOMATIS_DEFAULT = 7

# Profesional: berapa simulasi dijalankan per hari, diambil laba terbaik.
SIMULASI_PRO_ULANG = 3


class TierError(ValueError):
    """Fitur membutuhkan tier lebih tinggi dari tier pengguna."""


def nama_tier(tier: int) -> str:
    return TIER_NAMA.get(tier_valid(tier), "Pemula")


def tier_valid(tier: object) -> int:
    """Kembalikan tier yang valid (1-3); nilai lain -> Pemula."""
    try:
        t = int(tier)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return TIER_PEMULA
    return t if t in TIER_NAMA else TIER_PEMULA


def require_tier(tier: int, fitur: str) -> None:
    """Lolos bila tier pengguna >= tier minimum fitur; kalau tidak,
    lempar TierError dengan pesan yang menyebut tier yang dibutuhkan."""
    minimum = FITUR_MIN_TIER.get(fitur, TIER_PROFESIONAL)
    if tier_valid(tier) < minimum:
        raise TierError(
            f"Fitur {FITUR_NAMA.get(fitur, fitur)} butuh tier "
            f"{TIER_NAMA[minimum]} (tier kamu: {nama_tier(tier)}). "
            f"Pilih tier di /tier."
        )
