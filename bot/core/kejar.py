"""Mode Kejar Papan — kerja nonstop sampai masuk peringkat target (Fase 3+).

Bedakan dari Mode Target Level: yang dikejar di sini BUKAN level, tapi
``total_pembeli`` save sampai mencapai batas peringkat N di papan
peringkat "semua". Batas itu dibaca LIVE dari papan tiap siklus
(``ambil_papan2``, anonim, hanya baca) — bukan angka yang ditebak.

Satu siklus kejar = 1 hari game: bayar misi cerita (bila uang cukup) ->
beli upgrade syarat level (bila uang cukup) -> jalankan_siklus harian
(1 hari simulasi + restock + isi tugas + auto-bayar). Job di jobs.py
menjalankan satu siklus tiap 5 menit sampai berhenti.

Yang TIDAK PERNAH dilakukan mode ini (keputusan final, dicatat di
README + RANCANGAN §9/§13): mengirim skor ke leaderboard.
``kirim_skor5`` butuh HMAC ``RAHASIA`` dan angka permainan nyata;
``kirim_adu_laris`` butuh id perangkat + hasil mingguan nyata — tidak
satu pun bisa direpresentasikan dengan setia dari simulasi. Bot hanya
MENAIKKAN angka save lewat simulasi; game di HP-lah yang mengirim skor
saat dimainkan (tiap 10 menit). Mode ini hanya membaca papan untuk tahu
kapan berhenti.

Pelajaran dari insiden 24 Nov 2026 (Mode Target membuat uang save jadi
-Rp30.000 karena sim memotong biaya harian walau uang sudah habis):
sejak Penjaga Saldo (24 Nov 2026), uang TIDAK PERNAH minus — tiap
siklus diawali dan diakhiri penjaga yang menambah uang otomatis ke
Rp50.000 bila kurang (``jaga_saldo``, auto.py). Alasan berhenti
``uang_minus`` dipertahankan sebagai jaring pengaman di
``alasan_berhenti``, tapi seharusnya tidak pernah terpicu lagi; mulai
tidak lagi ditolak bila uang minus, karena siklus pertama yang
memperbaikinya.
"""

from __future__ import annotations

import copy

from . import target as target_mod
from .auto import jalankan_siklus

# Satu siklus tiap 5 menit; tiap siklus = 1 hari game.
INTERVAL_MENIT = 5
# Pengaman: maks siklus per mode (300 x 5 menit = 25 jam; ~300 hari game).
MAKS_SIKLUS = 300
# Peringkat default bila pengguna tidak memilih (100 besar).
PERINGKAT_DEFAULT = 100
# Pilihan peringkat target di tombol (tanpa parameter perintah, §15).
PERINGKAT_PILIHAN = (25, 50, 100)


def target_pembeli_dari_papan(data_papan: dict,
                              peringkat_target: int) -> int | None:
    """Total pembeli baris peringkat N (1-based) dari respons ambil_papan2.

    Baris daftar: [nama, pembeli, kode, bintang, level, omzet, jempol,
    foto] (``papan_peringkat.gd:94``). Kembalikan None bila peringkat di
    luar daftar atau data rusak — pemanggil harus melewati siklus, bukan
    menebak target.
    """
    try:
        n = int(peringkat_target)
    except (TypeError, ValueError):
        return None
    if not isinstance(data_papan, dict):
        return None
    daftar = data_papan.get("daftar", [])
    if not isinstance(daftar, list) or not 1 <= n <= len(daftar):
        return None
    baris = daftar[n - 1]
    if not isinstance(baris, (list, tuple)) or len(baris) < 2:
        return None
    try:
        return int(baris[1])
    except (TypeError, ValueError):
        return None


def alasan_berhenti(slot: dict, target_pembeli: int | None,
                    siklus: int) -> str | None:
    """Alasan berhenti (None bila lanjut). Diperiksa job tiap siklus.

    Urutan penting: ``uang_minus`` diperiksa SEBELUM macet/diusir —
    uang minus adalah tanda sim sudah memotong biaya harian melewati
    nol (insiden 24 Nov 2026: -Rp30.000), dan siklus berikutnya hanya
    akan memperburuk. ``target_pembeli`` None berarti target belum
    diketahui (papan gagal dibaca) — tidak bisa dinyatakan tercapai.
    """
    if target_pembeli is not None:
        try:
            if int(slot.get("total_pembeli", 0)) >= int(target_pembeli):
                return "target_tercapai"
        except (TypeError, ValueError):
            pass
    if int(slot.get("uang", 0)) < 0:
        return "uang_minus"
    if bool(slot.get("diusir")):
        return "diusir"
    if int(siklus) >= MAKS_SIKLUS:
        return "maks_siklus"
    # Macet: tidak ada uang dan tidak ada stok untuk dijual. Jalan keluar
    # (kerja sampingan, jual hasil jelajah) tidak dimodelkan sim.
    if (int(slot.get("uang", 0)) <= 0
            and target_mod.total_stok(slot) <= 0):
        return "macet"
    return None


def satu_siklus_kejar(slot_awal: dict, data, tugas_data: dict,
                      tier: int, batas_harian: int,
                      seed: int | None = None) -> dict:
    """Satu siklus Mode Kejar Papan (murni, tanpa I/O). Urutan:

    1. Bayar misi cerita (bila uang cukup) — supaya _cek_tugas di
       simulasi bisa menaikkan level pada siklus ini juga.
    2. Beli upgrade syarat level (bila uang cukup).
    3. jalankan_siklus harian (simulasi 1 hari + restock + isi tugas +
       auto-bayar sesuai tier).
    Mengembalikan {"slot", "aksi", "tingkat_awal", "tingkat_akhir",
    "naik", "macet", "diusir", "uang_awal", "uang_akhir",
    "total_pembeli_awal", "total_pembeli_akhir"}. Slot awal TIDAK diubah.
    """
    tingkat_awal = int(slot_awal.get("tingkat", 0))
    total_awal = int(slot_awal.get("total_pembeli", 0))
    slot = copy.deepcopy(slot_awal)
    aksi: list[dict] = []

    slot, bayar = target_mod.bayar_misi(slot, data)
    if bayar is not None:
        aksi.append(bayar)
    slot, beli = target_mod.beli_upgrade_syarat(slot, data)
    if beli is not None:
        aksi.append(beli)

    hasil = jalankan_siklus(slot, data, tugas_data, tier, batas_harian,
                            seed=seed)
    slot = hasil["slot"]
    aksi.extend(hasil.get("aksi", []))
    tingkat_akhir = int(slot.get("tingkat", 0))
    return {
        "slot": slot,
        "aksi": aksi,
        "tingkat_awal": tingkat_awal,
        "tingkat_akhir": tingkat_akhir,
        "naik": tingkat_akhir > tingkat_awal,
        "macet": (int(slot.get("uang", 0)) <= 0
                  and target_mod.total_stok(slot) <= 0),
        "diusir": bool(slot.get("diusir")),
        "uang_awal": int(hasil.get("uang_awal", slot_awal.get("uang", 0))),
        "uang_akhir": int(slot.get("uang", 0)),
        "total_pembeli_awal": total_awal,
        "total_pembeli_akhir": int(slot.get("total_pembeli", 0)),
    }


# -- teks alasan berhenti (dipakai pesan ke pengguna) -----------------------

TEKS_BERHENTI = {
    "target_tercapai": "Target tercapai — total pembeli sudah mencapai batas peringkat target.",
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
