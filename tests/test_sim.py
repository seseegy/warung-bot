"""Tes Fase 2 — mesin simulasi (bot/core/sim.py).

Rumus yang dites digrounding ke kode game (lihat docstring sim.py):
jendela 09:00-17:00, Jumat libur, interval detik nyata, harga_modal,
lantai/batas harga, tugas level, biaya harian, sewa Mingguan.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from bot.core import sim as sim_mod
from bot.core.sim import GameData, SimError, simulate, simulate_day

ASSETPACK = Path(__file__).resolve().parent.parent.parent / \
    "reverse-apk-analysis" / "warung-life-simulator" / "assetpack" / "assets" / "data"
ROOT = Path(__file__).resolve().parent.parent


# -- data -------------------------------------------------------------------

def test_data_json_identik_dengan_asset_pack(game_data):
    """bot/data/*.json harus identik (SHA-256) dengan asset pack game."""
    for nama in ("barang", "tugas", "pelanggan", "upgrade", "cerita", "event"):
        lokal = hashlib.sha256(
            (ROOT / "bot" / "data" / f"{nama}.json").read_bytes()).hexdigest()
        asli = hashlib.sha256((ASSETPACK / f"{nama}.json").read_bytes()).hexdigest()
        assert lokal == asli, f"{nama}.json berbeda dari asset pack"


def test_game_data_memuat_semua(game_data):
    assert len(game_data.katalog) > 0
    assert len(game_data.tugas) == 10
    assert len(game_data.upgrade["upgrade"]) == 12
    assert len(game_data.pelanggan) == 13


# -- determinisme ------------------------------------------------------------

def test_seed_sama_hasil_identik(rich_slot, game_data):
    a = simulate(rich_slot, game_data, 3, seed=42)
    b = simulate(rich_slot, game_data, 3, seed=42)
    assert a == b


def test_seed_beda_hasil_beda(rich_slot, game_data):
    a = simulate(rich_slot, game_data, 3, seed=1)
    b = simulate(rich_slot, game_data, 3, seed=2)
    assert a != b


def test_sim_tidak_mengubah_slot_asli(rich_slot, game_data):
    sebelum = copy.deepcopy(rich_slot)
    simulate(rich_slot, game_data, 2, seed=7)
    assert rich_slot == sebelum


# -- akuntansi ----------------------------------------------------------------

def test_rekonsiliasi_akuntansi_satu_hari(rich_slot, game_data):
    """Kas akhir = kas awal + omzet - modal layanan - biaya - sewa + hadiah.

    Modal FISIK tidak masuk: sudah dibayar saat beli stok (sebelum sim),
    jadi laba (omzet - modal) BUKAN perubahan kas. Top-up layanan dan
    QRIS net 0 (pindah antar kantong).
    """
    hasil = simulate(rich_slot, game_data, 1, seed=11)
    kas_awal = (hasil["uang_awal"] + hasil["qris_awal"]
                + hasil["saldo_layanan_awal"])
    kas_akhir = (hasil["uang_akhir"] + hasil["qris_akhir"]
                 + hasil["saldo_layanan_akhir"])
    assert kas_akhir == (kas_awal + hasil["omzet"] - hasil["modal_layanan"]
                         - hasil["biaya_harian"] - hasil["sewa"]
                         + hasil["hadiah"])


def test_rekonsiliasi_akuntansi_tujuh_hari(rich_slot, game_data):
    hasil = simulate(rich_slot, game_data, 7, seed=11)
    kas_awal = (hasil["uang_awal"] + hasil["qris_awal"]
                + hasil["saldo_layanan_awal"])
    kas_akhir = (hasil["uang_akhir"] + hasil["qris_akhir"]
                 + hasil["saldo_layanan_akhir"])
    assert kas_akhir == (kas_awal + hasil["omzet"] - hasil["modal_layanan"]
                         - hasil["biaya_harian"] - hasil["sewa"]
                         + hasil["hadiah"])


def test_laba_sama_dengan_omzet_minus_modal(rich_slot, game_data):
    hasil = simulate(rich_slot, game_data, 3, seed=5)
    assert hasil["laba"] == hasil["omzet"] - hasil["modal"]


# -- harga ----------------------------------------------------------------------

def test_harga_jual_tidak_di_bawah_lantai(rich_slot, game_data):
    for item_id in game_data.urutan_barang:
        item = game_data.katalog[item_id]
        if item["jenis"] != "fisik":
            continue
        lantai = sim_mod.lantai_harga(game_data, item_id, rich_slot)
        assert sim_mod.harga_jual(game_data, item_id, rich_slot) >= lantai


def test_lantai_harga_tidak_lebih_dari_pasar(rich_slot, game_data):
    """Lantai = min(modal+100, pasar) — boleh di bawah modal+100 bila
    pasar lebih rendah (game_state.gd:5730)."""
    for item_id in game_data.urutan_barang:
        item = game_data.katalog[item_id]
        if item["jenis"] != "fisik":
            continue
        lantai = sim_mod.lantai_harga(game_data, item_id, rich_slot)
        pasar = sim_mod.harga_pasar(game_data, item_id, rich_slot)
        assert lantai <= pasar


def test_batas_harga_minimal_pasar(rich_slot, game_data):
    for item_id in game_data.urutan_barang:
        item = game_data.katalog[item_id]
        if item["jenis"] != "fisik":
            continue
        batas = sim_mod.batas_harga_jual(game_data, item_id, rich_slot)
        pasar = sim_mod.harga_pasar(game_data, item_id, rich_slot)
        assert batas >= pasar


def test_harga_modal_lebih_dari_modal_katalog_tanpa_agen(rich_slot, game_data):
    """Tanpa agen/promo: harga_modal = bulat(modal x pengali/100) x 100,
    pengali = supplier (1,0) -> sama dengan modal katalog (dibulatkan)."""
    for item_id in ("beras", "gula", "mi_goreng"):
        modal = sim_mod.harga_modal(game_data, item_id, rich_slot)
        katalog = int(game_data.katalog[item_id]["modal"])
        assert modal == (katalog // 100) * 100 or modal == katalog


# -- hari & libur ---------------------------------------------------------------

def test_jumat_libur_tidak_ada_penjualan(rich_slot, game_data):
    """Hari 5 = Jumat (hari 1 = Senin). Tidak ada pelanggan, tapi biaya
    harian tetap jalan (tutup_hari)."""
    slot = copy.deepcopy(rich_slot)
    slot["hari"] = 5
    hasil = simulate(slot, game_data, 1, seed=3)
    assert hasil["hari"][0]["libur"] is True
    assert hasil["dilayani"] == 0
    assert hasil["omzet"] == 0
    assert hasil["biaya_harian"] > 0


def test_nama_hari_hari_1_senin(game_data):
    assert sim_mod.nama_hari(1) == "Senin"
    assert sim_mod.nama_hari(5) == "Jumat"
    assert sim_mod.nama_hari(8) == "Senin"


def test_ramadan_hari_55_sampai_84():
    assert sim_mod.ramadan(54) is False
    assert sim_mod.ramadan(55) is True
    assert sim_mod.ramadan(84) is True
    assert sim_mod.ramadan(85) is False


def test_jam_tutup_normal_17_00(rich_slot):
    assert sim_mod.jam_wajib_tutup(rich_slot) == 17 * 60


# -- edge case -------------------------------------------------------------------

def test_stok_nol_tidak_ada_yang_terjual(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["stok"] = {k: 0 for k in slot["stok"]}
    hasil = simulate(slot, game_data, 1, seed=9)
    assert hasil["omzet"] == 0
    assert hasil["dilayani"] == 0
    # Pelanggan tetap datang dan batal (barang habis).
    assert hasil["datang"] > 0
    assert hasil["batal"] > 0


def test_uang_nol_tidak_crash(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["uang"] = 0
    slot["saldo_layanan"] = 0
    hasil = simulate(slot, game_data, 1, seed=9)
    # Jualan fisik tetap menghasilkan uang; layanan tidak bisa (saldo 0).
    assert hasil["omzet"] >= 0
    assert isinstance(hasil["uang_akhir"], int)


def test_save_tanpa_progres_tidak_crash(game_data):
    slot = {"tingkat": 0, "hari": 1}
    hasil = simulate(slot, game_data, 1, seed=9)
    assert hasil["omzet"] >= 0


def test_level_terakhir_tidak_crash(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 10
    hasil = simulate(slot, game_data, 1, seed=9)
    assert hasil["tingkat_akhir"] == 10
    assert hasil["omzet"] >= 0


def test_maks_30_hari(rich_slot, game_data):
    with pytest.raises(SimError):
        simulate(rich_slot, game_data, 31, seed=1)
    with pytest.raises(SimError):
        simulate(rich_slot, game_data, 0, seed=1)


def test_harga_pasar_mingguan_belum_diperbarui_tidak_crash(rich_slot, game_data):
    """harga_pasaran kosong -> pakai harga katalog (fallback game)."""
    slot = copy.deepcopy(rich_slot)
    slot["harga_pasaran"] = {}
    hasil = simulate(slot, game_data, 1, seed=9)
    assert hasil["omzet"] >= 0


def test_upgrade_tanpa_biaya_hari_tidak_crash(rich_slot, game_data):
    """Regresi: biaya_hari null di upgrade.json (etalase, spanduk, bangku,
    kurir_cepat) tidak boleh membuat sim crash saat upgrade dimiliki."""
    slot = copy.deepcopy(rich_slot)
    slot["upgrade"] = ["etalase", "spanduk", "bangku", "kurir_cepat"]
    hasil = simulate(slot, game_data, 1, seed=9)
    assert hasil["omzet"] >= 0
    assert hasil["biaya_harian"] == 10000  # hanya biaya dasar casual


def test_sim_hari_pelanggan_dilayani_tidak_melebihi_datang(rich_slot, game_data):
    hasil = simulate(rich_slot, game_data, 7, seed=21)
    assert hasil["dilayani"] + hasil["batal"] <= hasil["datang"]


def test_efek_harga_murah_menaikkan_ramai(rich_slot, game_data):
    """Harga di lantai (murah vs pasar) -> efek > 0 -> interval kedatangan
    lebih pendek (lebih ramai). Harga normal -> efek 0."""
    slot_murah = copy.deepcopy(rich_slot)
    slot_mahal = copy.deepcopy(rich_slot)
    for item_id in ("beras", "gula", "mi_goreng"):
        lantai = sim_mod.lantai_harga(game_data, item_id, rich_slot)
        slot_murah.setdefault("harga_jual_khusus", {})[item_id] = lantai
    efek_murah = sim_mod.efek_harga_murah(game_data, slot_murah)
    efek_normal = sim_mod.efek_harga_murah(game_data, slot_mahal)
    assert efek_murah > efek_normal >= 0
    assert efek_murah <= 0.2  # dibatasi 0,3/1,5 (game_state.gd:7896)
    lo_murah, hi_murah = sim_mod.interval_datang(game_data, slot_murah, 600.0)
    lo_normal, hi_normal = sim_mod.interval_datang(game_data, slot_mahal, 600.0)
    assert (lo_murah, hi_murah) < (lo_normal, hi_normal)
