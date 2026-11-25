"""Mode Target Level — kerja nonstop sampai level tujuan (Fase 3+).

Satu siklus target = 1 hari game: bayar misi cerita (bila uang cukup
sekali lunas DAN sisa uang >= Rp50.000) -> beli upgrade syarat level
(bila uang cukup) -> jalankan_siklus harian (1 hari simulasi + restock
+ isi tugas + auto-bayar). Job di jobs.py menjalankan satu siklus tiap
5 menit sampai berhenti.

Dua hal yang TIDAK dilakukan siklus harian biasa dan ditambahkan di sini
— keduanya membelanjakan uang game pengguna, jadi mode ini hanya jalan
atas perintah eksplisit pengguna (pilih level + konfirmasi di /otomatis)
dan hanya untuk tier Profesional:
- bayar misi cerita (``kirim_uang()``, game_state.gd:4384): misi Agus
  HARUS lunas sebelum naik level; tanpa ini mode macet di tiap level.
- beli upgrade syarat level (tugas.json ``upgrade``): cukup salah satu;
  yang termurah dibeli bila uang sesudah beli masih >= Rp50.000.

Berhenti otomatis (``alasan_berhenti``): target tercapai, diusir,
macet (uang habis + rak kosong — tidak bisa jualan lagi, jalan keluarnya
kerja sampingan manual yang tidak dimodelkan sim), atau maks siklus.
Bentrok/sesi habis ditangani job (otomatisasi dimatikan + pengguna
diberi tahu), seperti siklus harian.
"""

from __future__ import annotations

import copy

from . import save as save_mod
from . import sim as sim_mod
from .auto import CADANGAN_UANG_MIN, bayar_misi, jalankan_siklus

# bayar_misi tinggal di auto.py (dipakai juga siklus harian dan Mode
# Kejar lewat target_mod.bayar_misi); definisinya satu tempat.

# Satu siklus tiap 5 menit; tiap siklus = 1 hari game.
INTERVAL_MENIT = 5
# Pengaman: maks siklus per mode (300 x 5 menit = 25 jam; ~300 hari game).
MAKS_SIKLUS = 300
# Level tertinggi game (tugas.json punya 10 tingkat, Lv 11 "Coming Soon").
LEVEL_MAKSIMAL = 10


def syarat_upgrade(tingkat: int, data) -> list:
    """Daftar id upgrade syarat level ini (tugas.json); [] bila tak ada."""
    try:
        t = data.tugas[int(tingkat)]
    except (IndexError, TypeError, AttributeError):
        return []
    return list(t.get("upgrade", []) or [])


def harga_upgrade(data, upgrade_id: str) -> int:
    """Harga upgrade dari data game; -1 bila id tidak dikenal."""
    info = (getattr(data, "upgrade_by_id", {}) or {}).get(upgrade_id)
    if not isinstance(info, dict):
        return -1
    try:
        return int(info.get("harga", -1))
    except (TypeError, ValueError):
        return -1


def beli_upgrade_syarat(slot: dict, data) -> tuple[dict, dict | None]:
    """Beli upgrade syarat level ini (yang termurah) bila uang cukup.

    Syarat tugas.json cukup SALAH SATU upgrade. Dibeli hanya bila uang
    sesudah beli masih >= CADANGAN_UANG_MIN (Rp50.000) supaya toko
    tetap bisa restock. Mengembalikan (slot_baru, aksi|None).
    Slot awal TIDAK diubah.
    """
    s = copy.deepcopy(slot)
    tingkat = int(s.get("tingkat", 0))
    perlu = syarat_upgrade(tingkat, data)
    punya = s.get("upgrade", []) or []
    if not perlu or any(u in punya for u in perlu):
        return s, None
    termurah = None
    harga_termurah = None
    for uid in perlu:
        harga = harga_upgrade(data, uid)
        if harga < 0:
            continue
        if harga_termurah is None or harga < harga_termurah:
            termurah, harga_termurah = uid, harga
    if termurah is None or harga_termurah is None:
        return s, None
    if int(s.get("uang", 0)) - harga_termurah < CADANGAN_UANG_MIN:
        return s, None
    s["uang"] = int(s["uang"]) - harga_termurah
    s.setdefault("upgrade", []).append(termurah)
    return s, {"aksi": "beli_upgrade", "ok": True, "id": termurah,
               "jumlah": harga_termurah}


def total_stok(slot: dict) -> int:
    """Jumlah unit stok fisik di semua rak."""
    stok = slot.get("stok", {}) or {}
    return sum(int(v) for v in stok.values() if isinstance(v, (int, float)))


def alasan_berhenti(slot: dict, target_tingkat: int, siklus: int) -> str | None:
    """Alasan berhenti (None bila lanjut). Diperiksa job tiap siklus."""
    if int(slot.get("tingkat", 0)) + 1 >= int(target_tingkat):
        return "target_tercapai"
    # Uang minus: berhenti sebelum siklus berikutnya — sim memotong biaya
    # harian walau uang sudah habis (seperti game asli, tutup_hari()
    # game_state.gd:6723), dan 3 hari minus berturut-turut = bangkrut
    # (BATAS_HARI_MINUS, game_state.gd:136). Insiden 24 Nov 2026:
    # mode jalan terus sampai uang -Rp30.000.
    if int(slot.get("uang", 0)) < 0:
        return "uang_minus"
    if bool(slot.get("diusir")):
        return "diusir"
    if int(siklus) >= MAKS_SIKLUS:
        return "maks_siklus"
    # Macet: tidak ada uang dan tidak ada stok untuk dijual. Jalan keluar
    # (kerja sampingan, jual hasil jelajah) tidak dimodelkan sim.
    if int(slot.get("uang", 0)) <= 0 and total_stok(slot) <= 0:
        return "macet"
    return None


def satu_siklus_target(slot_awal: dict, data, tugas_data: dict,
                       tier: int, batas_harian: int,
                       seed: int | None = None,
                       absen_nominal: int = 0,
                       absen_hari_ke: int = 0) -> dict:
    """Satu siklus Mode Target (murni, tanpa I/O). Urutan:

    1. Bayar misi cerita (bila uang cukup) — supaya _cek_tugas di
       simulasi bisa menaikkan level pada siklus ini juga.
    2. Beli upgrade syarat level (bila uang cukup).
    3. jalankan_siklus harian (simulasi 1 hari + restock + isi tugas +
       auto-bayar sesuai tier).
    Mengembalikan {"slot", "aksi", "tingkat_awal", "tingkat_akhir",
    "naik", "macet", "diusir"}. Slot awal TIDAK diubah.
    """
    tingkat_awal = int(slot_awal.get("tingkat", 0))
    slot = copy.deepcopy(slot_awal)
    aksi: list[dict] = []

    slot, bayar = bayar_misi(slot, data)
    if bayar is not None:
        aksi.append(bayar)
    slot, beli = beli_upgrade_syarat(slot, data)
    if beli is not None:
        aksi.append(beli)

    hasil = jalankan_siklus(slot, data, tugas_data, tier, batas_harian,
                            seed=seed, absen_nominal=absen_nominal,
                            absen_hari_ke=absen_hari_ke)
    slot = hasil["slot"]
    aksi.extend(hasil.get("aksi", []))
    tingkat_akhir = int(slot.get("tingkat", 0))
    return {
        "slot": slot,
        "aksi": aksi,
        "tingkat_awal": tingkat_awal,
        "tingkat_akhir": tingkat_akhir,
        "naik": tingkat_akhir > tingkat_awal,
        "macet": int(slot.get("uang", 0)) <= 0 and total_stok(slot) <= 0,
        "diusir": bool(slot.get("diusir")),
        "uang_awal": int(hasil.get("uang_awal", slot_awal.get("uang", 0))),
        "uang_akhir": int(slot.get("uang", 0)),
        "absen": hasil.get("absen"),
    }


# -- teks alasan berhenti (dipakai pesan ke pengguna) -----------------------

TEKS_BERHENTI = {
    "target_tercapai": "Target tercapai.",
    "uang_minus": (
        "Uang save MINUS — mode berhenti supaya tidak makin berdarah. "
        "Cari uang dulu di game (kerja sampingan / jual hasil jelajah), "
        "lalu nyalakan lagi."
    ),
    "diusir": "Warung diusir (sewa menunggak 3 minggu). Mode berhenti.",
    "maks_siklus": (
        f"Batas {MAKS_SIKLUS} siklus tercapai. Nyalakan lagi bila mau lanjut."
    ),
    "macet": (
        "Uang habis dan rak kosong — bot tidak bisa jualan lagi. "
        "Cari uang dulu di game (kerja sampingan / jual hasil jelajah), "
        "lalu nyalakan lagi."
    ),
    "bentrok": (
        "Simpanan di cloud berubah (kemungkinan game baru saja mengunggah). "
        "Mode berhenti supaya tidak ada yang tertimpa."
    ),
    "sesi_habis": (
        "Sesi login habis. Kirim ulang akun.json dengan /link, lalu nyalakan lagi."
    ),
}


def teks_berhenti(alasan: str) -> str:
    """Teks pengguna untuk satu alasan berhenti."""
    return TEKS_BERHENTI.get(alasan, f"Mode berhenti ({alasan}).")
