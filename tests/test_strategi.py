"""Tes Fase 5 — strategi 7 hari (bot/core/strategi.py) + statistik
(bot/core/statistik.py).
"""

from __future__ import annotations

import copy

import pytest

from bot.core import statistik as statistik_mod
from bot.core import strategi as strategi_mod


# -- /rencana -----------------------------------------------------------------

def test_rencana_uang_akhir_konsisten(rich_slot, game_data, tugas_data):
    """Identitas akuntansi simulasi (diverifikasi dari kode sim):
    uang_akhir = uang_awal + omzet - qris_masuk - isi_layanan_bersih
    - biaya_harian - sewa + hadiah, dengan isi_layanan_bersih =
    (saldo_layanan_akhir - saldo_layanan_awal) + modal_layanan."""
    rencana = strategi_mod.rencana_7_hari(rich_slot, game_data, tugas_data)
    assert rencana["jumlah_hari"] == 7
    assert len(rencana["per_hari"]) == 7
    isi_bersih = ((rencana["saldo_layanan_akhir"]
                   - rencana["saldo_layanan_awal"])
                  + rencana["modal_layanan"])
    qris_masuk = rencana["qris_akhir"] - rencana["qris_awal"]
    hitung = (rencana["uang_awal"] + rencana["omzet"] - qris_masuk
              - isi_bersih - rencana["biaya_harian"] - rencana["sewa"]
              + rencana["hadiah"])
    assert rencana["uang_akhir"] == hitung
    # Jumlah per hari sama dengan total.
    assert sum(h["omzet"] for h in rencana["per_hari"]) == rencana["omzet"]
    assert sum(h["laba"] for h in rencana["per_hari"]) == rencana["laba"]
    assert sum(h["sewa"] for h in rencana["per_hari"]) == rencana["sewa"]


def test_rencana_restock_barang_habis(rich_slot, game_data, tugas_data):
    # Stok kecil supaya habis dalam 7 hari simulasi.
    slot = copy.deepcopy(rich_slot)
    slot["stok"]["mi_goreng"] = 2
    rencana = strategi_mod.rencana_7_hari(slot, game_data, tugas_data)
    ids = [r["id"] for r in rencana["restock"]]
    assert "mi_goreng" in ids
    entri = next(r for r in rencana["restock"] if r["id"] == "mi_goreng")
    assert entri["terjual"] == 2
    assert entri["stok_akhir"] == 0
    assert entri["saran_beli"] >= entri["terjual"]
    assert entri["biaya"] == entri["saran_beli"] * 2500


def test_rencana_stok_nol_sejak_awal_tidak_ditebak(rich_slot, game_data,
                                                  tugas_data):
    slot = copy.deepcopy(rich_slot)
    slot["stok"]["telur"] = 0
    rencana = strategi_mod.rencana_7_hari(slot, game_data, tugas_data)
    assert any(r["id"] == "telur" for r in rencana["sudah_habis"])
    assert all(r["id"] != "telur" for r in rencana["restock"])


def test_rencana_upgrade_dan_naik_level(rich_slot, game_data, tugas_data):
    rencana = strategi_mod.rencana_7_hari(rich_slot, game_data, tugas_data)
    # Slot contoh naik level dalam simulasi 7 hari (hadiah masuk).
    assert rencana["tingkat_akhir"] >= rencana["tingkat_awal"]
    assert isinstance(rencana["upgrade"], list)
    for u in rencana["upgrade"]:
        assert u["hari_balik_modal"] is not None
        assert u["hari_balik_modal"] > 0
    assert "hari" in rencana["kapan_naik"]


# -- /statistik ---------------------------------------------------------------

def _slot_statistik(rich_slot):
    slot = copy.deepcopy(rich_slot)
    slot["penjualan_hari"] = {
        "mi_goreng": [10, 35000, 10000],
        "beras": [3, 45000, 6000],
        "gula": [0, 0, 0],
    }
    slot["catatan_hari"] = {"omzet": 80000, "laba": 16000, "terjual": 13,
                            "belanja": 0, "dilayani": 14, "batal": 1,
                            "hadiah": 0}
    slot["riwayat"] = [
        {"hari": 1, "omzet": 80000, "laba": 16000, "bersih": 15000,
         "belanja": 0, "barang": 13, "dilayani": 14, "batal": 1},
        {"hari": 2, "omzet": 120000, "laba": 25000, "bersih": 24000,
         "belanja": 50000, "barang": 20, "dilayani": 22, "batal": 0},
        {"hari": 3, "omzet": 0, "laba": 0, "bersih": -1000,
         "belanja": 0, "barang": 0, "dilayani": 0, "batal": 0},
    ]
    return slot


def test_statistik_terlaris_dari_penjualan_hari(rich_slot, game_data):
    stat = statistik_mod.statistik_slot(_slot_statistik(rich_slot), game_data)
    assert stat["terlaris_hari_ini"]["id"] == "mi_goreng"
    assert stat["terlaris_hari_ini"]["jumlah"] == 10
    assert stat["hari_ini"]["omzet"] == 80000
    assert stat["hari_ini"]["dilayani"] == 14


def test_statistik_riwayat_total_dan_terbaik(rich_slot, game_data):
    stat = statistik_mod.statistik_slot(_slot_statistik(rich_slot), game_data)
    assert stat["jumlah_hari_riwayat"] == 3
    assert stat["total_omzet"] == 200000
    assert stat["total_laba"] == 41000
    assert stat["total_barang"] == 33
    assert stat["total_dilayani"] == 36
    assert stat["total_batal"] == 1
    assert stat["rata_omzet_hari"] == 200000 // 3
    assert stat["hari_terbaik"]["hari"] == 2
    assert stat["hari_terburuk"]["hari"] == 1  # hari 3 omzet 0 tidak dihitung


def test_statistik_pelanggan_tersering_tidak_ditebak(rich_slot, game_data):
    stat = statistik_mod.statistik_slot(_slot_statistik(rich_slot), game_data)
    assert stat["pelanggan_tersering"] is None
    assert "riwayat_layan" in stat["alasan_tanpa_pelanggan"]


def test_statistik_save_kosong_tidak_crash(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["penjualan_hari"] = {}
    slot["riwayat"] = []
    slot.pop("catatan_hari", None)
    stat = statistik_mod.statistik_slot(slot, game_data)
    assert stat["terlaris_hari_ini"] is None
    assert stat["total_omzet"] == 0
    assert stat["hari_terbaik"] is None
    assert stat["pelanggan_tersering"] is None
