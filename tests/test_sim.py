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


# -- perbaikan 25 Nov 2026: cerita tamat / load / misi / bangkrut ------------
#
# Grounding: _semua_barang_cerita() (game_state.gd:8002-8021), perbaikan
# load (:3883-3896 + :8034/:8041/:7782), kirim_uang() (:4384),
# _siapkan_misi_level() (:4469), tutup_hari() (:6715-6745).


def _slot_siap_naik(rich_slot, game_data, tingkat, misi_status="aktif",
                    target_bab=150000, kiriman_bab=0, uang=500000, bab=0,
                    upgrade=None):
    """Slot yang progresnya sudah memenuhi target level ``tingkat``.

    Khusus diset sangat besar supaya jenis khusus apa pun terpenuhi;
    upgrade syarat level diisi otomatis bila tidak disebut.
    """
    slot = copy.deepcopy(rich_slot)
    t = game_data.tugas[tingkat]
    slot["tingkat"] = tingkat
    slot["bab"] = bab
    slot["misi_status"] = misi_status
    slot["target_bab"] = target_bab
    slot["kiriman_bab"] = kiriman_bab
    slot["uang"] = uang
    slot["cerita_tamat"] = False
    slot["progres"] = {"pelanggan": int(t["pelanggan"]),
                       "barang": int(t["barang"]),
                       "omzet": int(t["omzet"]), "khusus": 10 ** 9}
    if upgrade is None:
        upgrade = list(t.get("upgrade", []) or [])
    slot["upgrade"] = list(upgrade)
    return slot


# -- Tugas 2: perbaiki_barang_terbuka ----------------------------------------

def test_perbaiki_barang_terbuka_screenshot_bab_tertinggal(rich_slot, game_data):
    """Kasus screenshot: bab=1, tingkat=10 — cerita tertinggal dari level.
    Game TIDAK membuka kopi_susu/danda (bab 2+ belum dilewati); ini
    perilaku game (load :3883-3896), bukan bug."""
    slot = copy.deepcopy(rich_slot)
    slot["bab"] = 1
    slot["tingkat"] = 10
    slot["barang_terbuka"] = list(game_data.cerita["terbuka_awal"])
    hasil = sim_mod.perbaiki_barang_terbuka(slot, game_data)
    assert "teh_botol" in hasil          # bab 0 sudah lunas
    assert "kerupuk" in hasil            # tugas Lv2
    assert "minuman_energi" in hasil     # tugas Lv3
    assert "kopi_susu" not in hasil      # bab 1 belum lunas
    assert "danda" not in hasil          # bab 3 belum lunas
    assert "data_2gb" not in hasil
    assert "minyak_goreng" not in hasil  # bab 4 belum lunas


def test_perbaiki_barang_terbuka_bab9_buka_semua_yang_berhak(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["bab"] = 9
    slot["tingkat"] = 10
    slot["barang_terbuka"] = list(game_data.cerita["terbuka_awal"])
    hasil = sim_mod.perbaiki_barang_terbuka(slot, game_data)
    for item_id in ("teh_botol", "kopi_susu", "danda", "data_2gb",
                    "data_5gb", "data_10gb", "minyak_goreng",
                    "kerupuk", "minuman_energi"):
        assert item_id in hasil
    # Event/titipan tetap terkunci (bukan hak dari bab/level).
    assert "sayur" not in hasil
    assert "roti" not in hasil


def test_perbaiki_barang_terbuka_event_tolak_buka_agen(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["bab"] = 0
    slot["tingkat"] = 0
    slot["barang_terbuka"] = list(game_data.cerita["terbuka_awal"])
    slot["cerita_warga"] = {"ucup_sekolah": "tolak"}
    hasil = sim_mod.perbaiki_barang_terbuka(slot, game_data)
    assert "buku_tulis" in hasil   # agen Pak Misran (tolak ucup_sekolah)
    assert "beras" not in hasil    # event lain tidak ditolak -> tidak dibuka


def test_perbaiki_barang_terbuka_tidak_tambah_event_tolong(rich_slot, game_data):
    """Game tidak memperbaiki item event 'tolong' saat load — hanya saat
    event diselesaikan. Jangan tambahkan."""
    slot = copy.deepcopy(rich_slot)
    slot["bab"] = 9
    slot["tingkat"] = 10
    slot["barang_terbuka"] = list(game_data.cerita["terbuka_awal"])
    slot["cerita_warga"] = {}
    hasil = sim_mod.perbaiki_barang_terbuka(slot, game_data)
    for item_id in ("beras", "sayur", "obat", "galon", "lpg"):
        assert item_id not in hasil


def test_perbaiki_barang_terbuka_ramadan(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["bab"] = 0
    slot["tingkat"] = 0
    slot["barang_terbuka"] = list(game_data.cerita["terbuka_awal"])
    slot["hari"] = 54
    assert "kurma" not in sim_mod.perbaiki_barang_terbuka(slot, game_data)
    slot["hari"] = 55  # RAMADAN_MULAI = HARI_LEBARAN(85) - 30
    hasil = sim_mod.perbaiki_barang_terbuka(slot, game_data)
    assert "kurma" in hasil and "sirup" in hasil


def test_perbaiki_barang_terbuka_cerita_tamat(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["cerita_tamat"] = True
    slot["tingkat"] = 10
    slot["barang_terbuka"] = list(game_data.cerita["terbuka_awal"])
    hasil = sim_mod.perbaiki_barang_terbuka(slot, game_data)
    assert "kurma" in hasil and "sirup" in hasil
    assert "kopi_susu" in hasil and "minyak_goreng" in hasil
    assert "sayur" not in hasil and "roti" not in hasil and "jamu" not in hasil


# -- Tugas 1: buka barang saat cerita tamat ----------------------------------

def test_buka_semua_cerita_bab_tertinggal_buka_cerita_yang_terlewat(
        rich_slot, game_data):
    """Fungsi murni: slot bab=1 tingkat=10 yang cerita_tamat — buka semua
    barang cerita (termasuk dari bab yang terlewat), kecuali event/titipan
    yang belum terbuka."""
    slot = copy.deepcopy(rich_slot)
    slot["bab"] = 1
    slot["tingkat"] = 10
    slot["cerita_tamat"] = True
    slot["barang_terbuka"] = list(game_data.cerita["terbuka_awal"])
    hasil = sim_mod.buka_semua_cerita(slot, game_data)
    for item_id in ("kopi_susu", "danda", "data_2gb", "minyak_goreng",
                    "teh_botol", "kurma", "sirup"):
        assert item_id in hasil
    for item_id in ("sayur", "obat", "galon", "lpg", "roti", "jamu"):
        assert item_id not in hasil
    # Item event/titipan yang SUDAH terbuka dipertahankan.
    slot["barang_terbuka"] = list(game_data.cerita["terbuka_awal"]) + [
        "galon", "roti"]
    hasil2 = sim_mod.buka_semua_cerita(slot, game_data)
    assert "galon" in hasil2 and "roti" in hasil2


def test_cek_tugas_cerita_tamat_buka_semua(rich_slot, game_data):
    """Naik ke Lv10 dengan bab terakhir lunas -> cerita tamat + semua
    barang cerita terbuka; event/titipan yang belum terbuka tetap kunci."""
    slot = _slot_siap_naik(rich_slot, game_data, tingkat=9, bab=9,
                           target_bab=100000, uang=500000)
    slot["barang_terbuka"] = list(game_data.cerita["terbuka_awal"]) + [
        "beras", "galon", "lpg"]  # sudah ditolong warga -> dipertahankan
    slot["hari"] = 1  # sebelum Ramadan: kurma/sirup hanya lewat tamat
    s = sim_mod._normalisasi_slot(slot, game_data)
    assert sim_mod._cek_tugas(s, game_data) is True
    assert int(s["tingkat"]) == 10
    assert s["cerita_tamat"] is True
    terbuka = s["barang_terbuka"]
    for item_id in ("beras", "galon", "lpg", "minyak_goreng", "kopi_susu",
                    "teh_botol", "danda", "kurma", "sirup"):
        assert item_id in terbuka
    for item_id in ("sayur", "obat", "roti", "jamu"):
        assert item_id not in terbuka


def test_simulate_cerita_tamat_dan_bayar_misi(rich_slot, game_data):
    """End-to-end: sim 1 hari mencapai Lv10 -> tamat, misi terbayar,
    kurma/sirup terbuka (hari < 55), event yang belum ditolong terkunci."""
    slot = _slot_siap_naik(rich_slot, game_data, tingkat=9, bab=9,
                           target_bab=100000, uang=500000)
    slot["barang_terbuka"] = list(game_data.cerita["terbuka_awal"]) + ["beras"]
    slot["hari"] = 1
    hasil = simulate(slot, game_data, 1, seed=12345)
    assert hasil["tingkat_akhir"] == 10
    assert hasil["slot_akhir"]["cerita_tamat"] is True
    assert hasil["bayar_misi"] == 100000
    assert "kurma" in hasil["slot_akhir"]["barang_terbuka"]
    assert "sayur" not in hasil["slot_akhir"]["barang_terbuka"]


# -- Tugas 3a: bayar misi di sim --------------------------------------------

def test_cek_tugas_bayar_misi_bila_satu_satunya_penghalang(rich_slot, game_data):
    slot = _slot_siap_naik(rich_slot, game_data, tingkat=0, bab=0,
                           target_bab=150000, uang=500000)
    s = sim_mod._normalisasi_slot(slot, game_data)
    assert sim_mod._cek_tugas(s, game_data) is True
    assert int(s["tingkat"]) == 1
    assert int(s["_bayar_misi"]) == 150000
    # 500000 - 150000 (misi) + 15000 (hadiah Lv1) = 365000.
    assert int(s["uang"]) == 365000
    # Misi bab 0 lunas (terbukti dari _bayar_misi + naik level); misi bab
    # berikutnya langsung disiapkan (bab 1, target 350000, aktif).
    assert int(s["bab"]) == 1
    assert s["misi_status"] == "aktif"
    assert int(s["target_bab"]) == 350000


def test_cek_tugas_tidak_bayar_misi_bila_sisa_di_bawah_cadangan(
        rich_slot, game_data):
    slot = _slot_siap_naik(rich_slot, game_data, tingkat=1, bab=0,
                           target_bab=150000, uang=180000)
    s = sim_mod._normalisasi_slot(slot, game_data)
    assert sim_mod._cek_tugas(s, game_data) is False
    assert int(s["tingkat"]) == 1
    assert s["misi_status"] == "aktif"
    assert int(s["uang"]) == 180000  # tidak dibayar: sisa 30000 < 50000


def test_cek_tugas_bayar_misi_bila_sisa_pas_cadangan(rich_slot, game_data):
    slot = _slot_siap_naik(rich_slot, game_data, tingkat=1, bab=0,
                           target_bab=150000, uang=200000)
    s = sim_mod._normalisasi_slot(slot, game_data)
    assert sim_mod._cek_tugas(s, game_data) is True
    # 200000 - 150000 (misi) + 50000 (hadiah) = 100000.
    assert int(s["uang"]) == 100000


def test_cek_tugas_tidak_bayar_misi_bila_progres_belum_penuh(
        rich_slot, game_data):
    slot = _slot_siap_naik(rich_slot, game_data, tingkat=1, bab=0,
                           target_bab=150000, uang=500000)
    slot["progres"] = {"pelanggan": 0, "barang": 0, "omzet": 0, "khusus": 0}
    s = sim_mod._normalisasi_slot(slot, game_data)
    assert sim_mod._cek_tugas(s, game_data) is False
    assert s["misi_status"] == "aktif"
    assert int(s["uang"]) == 500000  # tidak dibayar: misi bukan satu-satunya
    # penghalang (progres belum penuh).


def test_cek_tugas_tidak_bayar_misi_menunggu(rich_slot, game_data):
    """Misi 'menunggu' (Agus belum menghubungi, JEDA_AGUS 2 hari) tidak
    dibayar sim — game mengaktifkannya belakangan."""
    slot = _slot_siap_naik(rich_slot, game_data, tingkat=1, bab=0,
                           misi_status="menunggu", target_bab=150000,
                           uang=500000)
    s = sim_mod._normalisasi_slot(slot, game_data)
    assert sim_mod._cek_tugas(s, game_data) is False
    assert s["misi_status"] == "menunggu"
    assert int(s["uang"]) == 500000


def test_cek_tugas_lewati_bab_yang_levelnya_tertinggal(rich_slot, game_data):
    """_siapkan_misi_level (:4469): bab yang levelnya < level saat itu
    dilewati — tidak pernah memberi misi lagi."""
    slot = _slot_siap_naik(rich_slot, game_data, tingkat=5, bab=1,
                           misi_status="lunas", target_bab=0, uang=500000)
    s = sim_mod._normalisasi_slot(slot, game_data)
    assert sim_mod._cek_tugas(s, game_data) is True
    # Naik ke tingkat 6 (Lv7): bab 2..5 terlewat (level 3..6 < 7),
    # bab 6 (level 7) langsung aktif.
    assert int(s["bab"]) == 6
    assert s["misi_status"] == "aktif"
    assert int(s["target_bab"]) == 1500000


# -- Tugas 4: hari_minus / bangkrut ------------------------------------------

def test_tutup_hari_minus_tambah_dan_bangkrut_casual(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["mode"] = "casual"
    slot["uang"] = -5000
    slot["hari"] = 2
    slot["hari_minus"] = 0
    slot["bangkrut"] = False
    s = sim_mod._normalisasi_slot(slot, game_data)
    sim_mod._tutup_hari(s, game_data, sim_mod._hari_baru())
    assert int(s["hari_minus"]) == 1
    assert s["bangkrut"] is False
    sim_mod._tutup_hari(s, game_data, sim_mod._hari_baru())
    sim_mod._tutup_hari(s, game_data, sim_mod._hari_baru())
    assert int(s["hari_minus"]) == 3
    assert s["bangkrut"] is True  # BATAS_HARI_MINUS casual = 3


def test_tutup_hari_minus_bangkrut_hard_sekali(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["mode"] = "hard"
    slot["uang"] = -5000
    slot["hari"] = 2
    slot["hari_minus"] = 0
    slot["bangkrut"] = False
    s = sim_mod._normalisasi_slot(slot, game_data)
    sim_mod._tutup_hari(s, game_data, sim_mod._hari_baru())
    assert int(s["hari_minus"]) == 1
    assert s["bangkrut"] is True  # BATAS_HARI_MINUS hard = 1


def test_tutup_hari_tidak_minus_reset_hari_minus(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["mode"] = "casual"
    slot["uang"] = 100000
    slot["hari"] = 2
    slot["hari_minus"] = 2
    slot["bangkrut"] = False
    s = sim_mod._normalisasi_slot(slot, game_data)
    sim_mod._tutup_hari(s, game_data, sim_mod._hari_baru())
    assert int(s["hari_minus"]) == 0
    assert s["bangkrut"] is False


def test_tutup_hari_lindungi_tidak_tambah_hari_minus(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["mode"] = "casual"
    slot["uang"] = -5000
    slot["hari"] = 2
    slot["hari_minus"] = 0
    slot["lindungi_hari_minus"] = True  # rangkaian sakit "tertabrak"
    s = sim_mod._normalisasi_slot(slot, game_data)
    sim_mod._tutup_hari(s, game_data, sim_mod._hari_baru())
    assert int(s["hari_minus"]) == 0
    assert s["bangkrut"] is False


def _slot_tanpa_penjualan():
    """Slot yang tidak bisa berjualan: rak kosong, tanpa layanan terbuka."""
    return {"mode": "casual", "hari": 1, "uang": 0, "tingkat": 0,
            "barang_terbuka": ["mi_goreng"], "stok": {},
            "misi_status": "", "cerita_tamat": False}


def test_simulate_bangkrut_tetap_kembalikan_hasil(game_data):
    hasil = simulate(_slot_tanpa_penjualan(), game_data, 3, seed=7)
    assert hasil["bangkrut"] is True
    assert hasil["hari_minus"] == 3
    assert hasil["uang_akhir"] < 0
    assert hasil["slot_akhir"]["bangkrut"] is True


def test_simulate_berhenti_saat_bangkrut(game_data):
    """Bangkrut mengakhiri permainan di game — sim berhenti di hari itu,
    tidak lanjut sampai diusir berminggu-minggu kemudian."""
    slot = _slot_tanpa_penjualan()
    slot["uang"] = 250000
    hasil = simulate(slot, game_data, 30, seed=7)
    assert hasil["bangkrut"] is True
    assert len(hasil["hari"]) < 30
