"""Fitur /unlimited — set nilai save ke angka besar / buka semua.

Semua fungsi MURNI (mengubah dict slot yang diberikan, tanpa I/O),
grounded ke kode game (game_state.gd):

- ``stok``: kapasitas etalase hanya dicek game saat MEMBELI; load
  tidak meng-clamp stok, jadi stok raksasa persisten dan bisa dijual.
- ``uang``: uang + saldo QRIS; game memakai int tanpa cap, bot
  membatasi wajar (sama seperti ``save.set_uang``).
- ``barang``: ``barang_terbuka`` = semua id katalog. Game hanya
  MENAMBAH saat load (perbaikan), tidak pernah menghapus.
- ``upgrade``: ``upgrade`` = semua id upgrade; kepemilikan dicek
  game lewat keanggotaan daftar.
- ``cerita``: cermin keadaan tamat game persis — bab terakhir,
  ``misi_status=""``, ``cerita_tamat=True`` (game_state.gd:3191).
  Saat load game membuka semua barang cerita untuk save tamat.
- ``level``: ``tingkat=10`` (Level 11 maksimum) + progres dikosongkan
  seperti ``_kosongkan_progres()`` saat naik level.
- ``pembeli``: ``total_pembeli`` — angka yang dikirim game sendiri
  ke papan peringkat (``kirim_skor5``) saat game dibuka.

Yang TIDAK ada di sini (game clamp/hitung ulang, sudah diverifikasi):
energi (clamp 0-100 tiap menit), harga di atas batas (di-clamp
``harga_jual()``), bintang (dihitung ulang dari riwayat).
"""

from __future__ import annotations

from . import save as save_mod
from . import sim as sim_mod

ANGKA_BESAR = 99_999_999

# Batas wajar bot per aksi numerik (game sendiri tidak punya cap).
BATAS_NILAI = {
    "stok": 999_999_999,
    "uang": save_mod.UANG_MAKSIMAL,
    "pembeli": 999_999_999_999,
}

AKSI_NUMERIK = ("stok", "uang", "pembeli")
AKSI_SEMUA = ("stok", "uang", "barang", "upgrade", "cerita", "level",
              "pembeli")

LABEL_AKSI = {
    "stok": "Stok semua barang",
    "uang": "Uang + QRIS",
    "barang": "Buka semua barang",
    "upgrade": "Semua upgrade",
    "cerita": "Cerita tamat",
    "level": "Level maksimum",
    "pembeli": "Total pembeli",
}


def validasi_nilai(aksi: str, nilai: int) -> int:
    """Validasi nilai aksi numerik. Melempar ValueError bila tidak sah."""
    if aksi not in BATAS_NILAI:
        raise ValueError(f"aksi {aksi!r} tidak memakai nilai angka")
    if isinstance(nilai, bool) or not isinstance(nilai, int):
        raise ValueError("nilai harus bilangan bulat")
    if nilai <= 0:
        raise ValueError("nilai harus lebih dari 0")
    if nilai > BATAS_NILAI[aksi]:
        raise ValueError(
            f"nilai melebihi batas wajar {BATAS_NILAI[aksi]:,}".replace(
                ",", "."))
    return nilai


def _fisik_katalog(data) -> list[str]:
    """Semua id barang fisik katalog (layanan tidak punya stok).

    Stok di-set untuk semua fisik, bukan hanya yang terbuka: entri
    stok barang terkunci tidak dihapus game dan langsung terpakai
    begitu barangnya terbuka, jadi sekali set cukup.
    """
    return [i for i, info in data.katalog.items()
            if info.get("jenis") == "fisik"]


def nilai_sekarang(slot: dict, data, aksi: str) -> str:
    """Satu baris nilai saat ini untuk menu/pratinjau."""
    if aksi == "stok":
        fisik = _fisik_katalog(data)
        stok = slot.get("stok", {}) or {}
        total = sum(int(stok.get(i, 0) or 0) for i in fisik)
        return f"{len(fisik)} barang fisik, total stok {total:,}".replace(",", ".")
    if aksi == "uang":
        return (f"Uang Rp{int(slot.get('uang', 0)):,}".replace(",", ".")
                + f" · QRIS Rp{int(slot.get('saldo_digital', 0)):,}".replace(",", "."))
    if aksi == "barang":
        terbuka = slot.get("barang_terbuka", []) or []
        return f"{len(terbuka)} dari {len(data.katalog)} barang terbuka"
    if aksi == "upgrade":
        dimiliki = slot.get("upgrade", []) or []
        return f"{len(dimiliki)} dari {len(data.upgrade_by_id)} upgrade dimiliki"
    if aksi == "cerita":
        if slot.get("cerita_tamat"):
            return "cerita sudah tamat"
        return (f"bab {int(slot.get('bab', 0)) + 1}, "
                f"misi {slot.get('misi_status') or '-'}")
    if aksi == "level":
        return f"Level {int(slot.get('tingkat', 0)) + 1}"
    if aksi == "pembeli":
        return f"{int(slot.get('total_pembeli', 0)):,}".replace(",", ".")
    return "-"


def pratinjau(slot: dict, data, aksi: str, nilai: int | None = None) -> str:
    """Teks lama -> baru untuk konfirmasi (tanpa mengubah slot)."""
    sekarang = nilai_sekarang(slot, data, aksi)
    if aksi == "stok":
        baru = f"stok tiap barang fisik jadi {nilai:,}".replace(",", ".")
    elif aksi == "uang":
        baru = f"uang + QRIS jadi Rp{nilai:,}".replace(",", ".")
    elif aksi == "barang":
        baru = f"semua {len(data.katalog)} barang terbuka"
    elif aksi == "upgrade":
        baru = f"semua {len(data.upgrade_by_id)} upgrade dimiliki"
    elif aksi == "cerita":
        baru = "cerita tamat, misi selesai, barang cerita terbuka"
    elif aksi == "level":
        baru = "Level 11 (maksimum)"
    elif aksi == "pembeli":
        baru = f"{nilai:,}".replace(",", ".")
    else:
        baru = "-"
    return f"{LABEL_AKSI[aksi]}: {sekarang} → {baru}"


def terapkan(slot: dict, data, aksi: str, nilai: int | None = None) -> None:
    """Terapkan aksi ke slot (mengubah dict yang diberikan).

    Aksi numerik wajib ``nilai`` valid (lihat ``validasi_nilai``).
    Melempar ValueError bila aksi/nilai tidak sah.
    """
    if aksi not in AKSI_SEMUA:
        raise ValueError(f"aksi unlimited tidak dikenal: {aksi!r}")
    if aksi in AKSI_NUMERIK:
        nilai = validasi_nilai(aksi, nilai)
    if aksi == "stok":
        stok_baru = dict(slot.get("stok", {}) or {})
        for item_id in _fisik_katalog(data):
            stok_baru[item_id] = nilai
        slot["stok"] = stok_baru
    elif aksi == "uang":
        save_mod.set_uang(slot, nilai)
        slot["saldo_digital"] = nilai
    elif aksi == "barang":
        slot["barang_terbuka"] = list(data.katalog.keys())
    elif aksi == "upgrade":
        slot["upgrade"] = list(data.upgrade_by_id.keys())
    elif aksi == "cerita":
        bab_terakhir = len(data.cerita.get("bab", [])) - 1
        if bab_terakhir < 0:
            raise ValueError("data cerita tidak berisi bab")
        slot["bab"] = bab_terakhir
        # Bab terakhir adalah bab kios: terapkan efek penyelesaian
        # game (kios_milik, tunggakan lunas, cicilan kembali) sebelum
        # menandai tamat, supaya bot tidak tetap mengenakan sewa.
        sim_mod.selesaikan_bab(slot, data)
        slot["misi_status"] = ""
        slot["cerita_tamat"] = True
    elif aksi == "level":
        slot["tingkat"] = 10
        slot["progres"] = {"pelanggan": 0, "barang": 0, "omzet": 0,
                           "khusus": 0}
    elif aksi == "pembeli":
        slot["total_pembeli"] = nilai
