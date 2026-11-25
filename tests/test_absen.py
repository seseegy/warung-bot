"""Tes fitur absen harian game (core/absen.py + integrasi siklus)."""

from __future__ import annotations

import copy

from bot.core import absen as absen_mod
from bot.core import auto as auto_mod
from bot.core import sim as sim_mod


def test_berikutnya_siklus():
    assert absen_mod.berikutnya(0) == 1
    assert absen_mod.berikutnya(1) == 2
    assert absen_mod.berikutnya(29) == 30
    assert absen_mod.berikutnya(30) == 1  # berulang
    assert absen_mod.berikutnya(31) == 2
    assert absen_mod.berikutnya(60) == 1


def test_jumlah_hadiah_bonus():
    # Hari biasa = nominal penuh.
    assert absen_mod.jumlah_hadiah(100_000, 1) == 100_000
    # Bonus 3/7/30.
    assert absen_mod.jumlah_hadiah(100_000, 3) == 200_000
    assert absen_mod.jumlah_hadiah(100_000, 7) == 300_000
    assert absen_mod.jumlah_hadiah(100_000, 30) == 1_000_000
    # Nominal 0 = tidak ada.
    assert absen_mod.jumlah_hadiah(0, 3) == 0


def test_terapkan_absen_murni():
    slot = {"uang": 1_000, "hari": 5}
    hasil = absen_mod.terapkan_absen(slot, 100_000, 0)
    assert hasil is not None
    assert hasil["ok"] is True
    assert hasil["hari_siklus"] == 1
    assert slot["uang"] == 101_000
    # Slot asli tidak berubah? terapkan_absen mengubah slot yang diberi
    # (bukan deepcopy) — pola sama dengan catat_transaksi. Cek isinya.
    assert absen_mod.terapkan_absen(slot, 0, 0) is None


def test_jalankan_siklus_dengan_absen(rich_slot, game_data, tugas_data):
    """Siklus harian menambahkan uang absen + aksi absen dicatat."""
    slot = copy.deepcopy(rich_slot)
    uang_awal = int(slot["uang"])
    hasil_tanpa = auto_mod.jalankan_siklus(slot, game_data, tugas_data,
                                           tier=1, batas_harian=0,
                                           seed=1)
    hasil_dengan = auto_mod.jalankan_siklus(
        copy.deepcopy(rich_slot), game_data, tugas_data,
        tier=1, batas_harian=0, seed=1,
        absen_nominal=100_000, absen_hari_ke=0)
    aksi_absen = [a for a in hasil_dengan["aksi"] if a.get("aksi") == "absen"]
    assert len(aksi_absen) == 1
    assert aksi_absen[0]["ok"] is True
    assert aksi_absen[0]["jumlah"] == 100_000
    # Uang akhir berbeda tepat sebesar hadiah absen (seed sama).
    selisih = (int(hasil_dengan["uang_akhir"])
               - int(hasil_tanpa["uang_akhir"]))
    assert selisih == 100_000
    assert uang_awal > 0  # sanity
