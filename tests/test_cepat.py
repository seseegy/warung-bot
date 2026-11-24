"""Tes Fase 5 — aksi cepat (bot/core/cepat.py): parse, /jual, /beli, /ngopi,
/tutup, /slot. Semua rumus digrounding ke game_state.gd (lihat docstring
cepat.py) — tes memakai slot contoh berstruktur asli game.
"""

from __future__ import annotations

import copy

import pytest

from bot.core import cepat as cepat_mod
from bot.core import save as save_mod


# -- parse / cari barang ------------------------------------------------------

def test_parse_mi_goreng_5(game_data):
    assert cepat_mod.parse_perintah("mi goreng 5", game_data) == ("mi_goreng", 5)


def test_parse_sufiks_x_dan_sebutan(game_data):
    assert cepat_mod.parse_perintah("kopi sachet 2x", game_data) == ("sachet", 2)


def test_parse_tanpa_jumlah_ditolak(game_data):
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.parse_perintah("mi goreng", game_data)


def test_parse_jumlah_bukan_angka_ditolak(game_data):
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.parse_perintah("mi goreng lima", game_data)


def test_parse_jumlah_nol_ditolak(game_data):
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.parse_perintah("beras 0", game_data)


def test_cari_ambigu_ditolak(game_data):
    # "kopi" cocok dengan sachet (sebutan "kopi sachet") dan kopi susu.
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.cari_barang(game_data, "kopi")


def test_cari_tidak_ada_ditolak(game_data):
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.cari_barang(game_data, "barang hantu")


def test_cari_id_langsung(game_data):
    assert cepat_mod.cari_barang(game_data, "mi_goreng") == "mi_goreng"


# -- /jual --------------------------------------------------------------------

def test_jual_stok_uang_omzet_laba_benar(rich_slot, game_data):
    hasil = cepat_mod.jual_barang(rich_slot, game_data, "mi_goreng", 5)
    s = hasil["slot"]
    # mi_goreng: jual 3500, modal 2500.
    assert s["stok"]["mi_goreng"] == 15
    assert hasil["omzet"] == 5 * 3500
    assert hasil["laba"] == 5 * 1000
    assert hasil["uang_awal"] == 500000
    assert hasil["uang_akhir"] == 500000 + 5 * 3500
    assert s["penjualan_hari"]["mi_goreng"] == [5, 5 * 3500, 5 * 1000]
    assert s["progres"]["barang"] == 5
    assert s["progres"]["omzet"] == 5 * 3500
    assert s["omzet_minggu"] == 5 * 3500
    # Slot asli TIDAK diubah (normalisasi menyalin).
    assert rich_slot["stok"]["mi_goreng"] == 20
    assert rich_slot["uang"] == 500000


def test_jual_stok_kurang_ditolak(rich_slot, game_data):
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.jual_barang(rich_slot, game_data, "mi_goreng", 21)


def test_jual_barang_belum_terbuka_ditolak(rich_slot, game_data):
    # roti tidak ada di barang_terbuka slot contoh.
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.jual_barang(rich_slot, game_data, "roti", 1)


def test_jual_layanan_pakai_saldo_layanan(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["barang_terbuka"] = list(slot["barang_terbuka"]) + ["token_listrik"]
    slot["saldo_layanan"] = 100000
    item = game_data.katalog["token_listrik"]
    hasil = cepat_mod.jual_barang(slot, game_data, "token_listrik", 2)
    s = hasil["slot"]
    assert s["saldo_layanan"] == 100000 - 2 * int(item["modal"])
    assert hasil["uang_akhir"] == 500000 + 2 * int(item["jual"])
    assert hasil["saldo_layanan_akhir"] == 100000 - 2 * int(item["modal"])


def test_jual_layanan_saldo_kurang_ditolak(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["barang_terbuka"] = list(slot["barang_terbuka"]) + ["token_listrik"]
    slot["saldo_layanan"] = 100
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.jual_barang(slot, game_data, "token_listrik", 1)


def test_jual_memicu_naik_level(rich_slot, game_data, tugas_data):
    # Lv1: pelanggan 15, barang 25, omzet 100rb, khusus beruntun 5.
    slot = copy.deepcopy(rich_slot)
    slot["progres"] = {"pelanggan": 15, "barang": 24, "omzet": 99000,
                       "khusus": 5}
    target = save_mod.task_targets(tugas_data, 0)
    hasil = cepat_mod.jual_barang(slot, game_data, "mi_goreng", 1)
    assert hasil["naik_level"] is True
    assert hasil["tingkat_akhir"] == 1
    # Hadiah tugas masuk ke uang (di luar omzet penjualan).
    assert hasil["uang_akhir"] == 500000 + 3500 + int(target["hadiah"])


# -- /beli --------------------------------------------------------------------

def test_beli_biaya_kiriman_benar(rich_slot, game_data):
    hasil = cepat_mod.beli_barang(rich_slot, game_data, "beras", 10)
    s = hasil["slot"]
    # beras modal 13000 (level 1: agen belum aktif, tanpa upgrade supplier).
    assert hasil["harga_modal"] == 13000
    assert hasil["biaya"] == 130000
    assert hasil["uang_akhir"] == 500000 - 130000
    assert s["kiriman_stok"]["beras"] == 10
    # Stok TIDAK langsung bertambah (kurir saat game dibuka).
    assert s["stok"]["beras"] == 20
    assert any(t.get("teks") == "Belanja 10 beras 1 kg"
               and t.get("jumlah") == -130000
               for t in s.get("transaksi", []))
    assert s["catatan_hari"]["belanja"] == 130000


def test_beli_uang_tidak_cukup_ditolak(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["uang"] = 1000
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.beli_barang(slot, game_data, "beras", 1)


def test_beli_rak_penuh_ditolak(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["stok"]["beras"] = 100  # sisa_muat = max(100-100, 0) = 0
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.beli_barang(slot, game_data, "beras", 1)


def test_beli_titipan_sales_ditolak(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["barang_terbuka"] = list(slot["barang_terbuka"]) + ["roti"]
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.beli_barang(slot, game_data, "roti", 1)


def test_beli_wajib_etalase_ditolak(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["wajib_etalase"] = True
    slot["upgrade"] = []
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.beli_barang(slot, game_data, "beras", 1)


def test_beli_barang_bukan_fisik_ditolak(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["barang_terbuka"] = list(slot["barang_terbuka"]) + ["token_listrik"]
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.beli_barang(slot, game_data, "token_listrik", 1)


# -- /ngopi -------------------------------------------------------------------

def _slot_ngopi(rich_slot, **overrides):
    slot = copy.deepcopy(rich_slot)
    slot["energi"] = 50.0
    slot.update(overrides)
    return slot


def test_ngopi_energi_30_stok_berkurang(rich_slot, game_data):
    hasil = cepat_mod.ngopi(_slot_ngopi(rich_slot), game_data)
    s = hasil["slot"]
    assert hasil["minuman"] == "sachet"
    assert hasil["energi_awal"] == 50.0
    assert hasil["energi_akhir"] == 80.0
    assert s["stok"]["sachet"] == 19
    assert s["menit"] == 550.0  # +10 menit
    assert s["istirahat_hari"]["ngopi"] == 1


def test_ngopi_dibatasi_100(rich_slot, game_data):
    hasil = cepat_mod.ngopi(_slot_ngopi(rich_slot, energi=85.0), game_data)
    assert hasil["energi_akhir"] == 100.0


def test_ngopi_energi_penuh_ditolak(rich_slot, game_data):
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.ngopi(_slot_ngopi(rich_slot, energi=100.0), game_data)


def test_ngopi_dua_kali_sehari_ditolak(rich_slot, game_data):
    slot = _slot_ngopi(rich_slot)
    hasil = cepat_mod.ngopi(slot, game_data)
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.ngopi(hasil["slot"], game_data)


def test_ngopi_tanpa_stok_ditolak(rich_slot, game_data):
    slot = _slot_ngopi(rich_slot)
    for m in ("sachet", "kopi_susu", "minuman_energi"):
        slot["stok"][m] = 0
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.ngopi(slot, game_data)


def test_ngopi_ramadan_ditolak(rich_slot, game_data):
    # Ramadan hari 55-84 (game_state.gd:7714).
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.ngopi(_slot_ngopi(rich_slot, hari=60), game_data)


def test_ngopi_jeda_120_menit(rich_slot, game_data):
    slot = _slot_ngopi(rich_slot)
    slot["menit"] = 550
    slot["istirahat_hari"] = {"hari": 1, "ngopi": 0, "ngopi_menit": 540}
    with pytest.raises(cepat_mod.CepatError):
        cepat_mod.ngopi(slot, game_data)


# -- /tutup -------------------------------------------------------------------

def _slot_tutup(rich_slot, **overrides):
    slot = copy.deepcopy(rich_slot)
    slot["penjualan_hari"] = {"mi_goreng": [10, 35000, 10000]}
    slot["catatan_hari"] = {"omzet": 35000, "laba": 10000, "terjual": 10,
                            "belanja": 0, "dilayani": 12, "batal": 1,
                            "hadiah": 0}
    slot.update(overrides)
    return slot


def test_tutup_hari_bertambah_biaya_dipotong(rich_slot, game_data):
    hasil = cepat_mod.tutup_hari_bot(_slot_tutup(rich_slot), game_data)
    s = hasil["slot"]
    assert hasil["hari_lama"] == 1
    assert hasil["hari_baru"] == 2
    assert hasil["omzet"] == 35000
    assert hasil["laba"] == 10000
    assert hasil["biaya_harian"] > 0
    assert hasil["sewa"] == 0  # hari 1 bukan Minggu (hari % 7 != 0)
    assert hasil["uang_akhir"] == 500000 - hasil["biaya_harian"]
    assert s["energi"] == 100.0
    assert s["menit"] == 540  # jam buka 09.00
    assert s["riwayat"][-1]["hari"] == 1
    assert s["riwayat"][-1]["omzet"] == 35000
    assert s["riwayat"][-1]["dilayani"] == 12
    assert s["riwayat"][-1]["batal"] == 1


def test_tutup_minggu_bayar_sewa(rich_slot, game_data):
    hasil = cepat_mod.tutup_hari_bot(
        _slot_tutup(rich_slot, hari=7), game_data)
    assert hasil["sewa"] > 0
    assert hasil["hari_baru"] == 8
    assert hasil["uang_akhir"] == (
        500000 - hasil["biaya_harian"] - hasil["sewa"])


def test_tutup_tanpa_penjualan_tidak_ganda_hitung(rich_slot, game_data):
    # Save ditulis tepat setelah tutup_hari: catatan masih ringkasan
    # kemarin, penjualan_hari sudah kosong -> hari ini dihitung 0.
    slot = copy.deepcopy(rich_slot)
    slot["penjualan_hari"] = {}
    slot["catatan_hari"] = {"omzet": 50000, "laba": 20000, "terjual": 15,
                            "belanja": 0, "dilayani": 20, "batal": 2,
                            "hadiah": 0}
    hasil = cepat_mod.tutup_hari_bot(slot, game_data)
    assert hasil["omzet"] == 0
    assert hasil["dilayani"] == 0
    assert hasil["batal"] == 0
    assert hasil["slot"]["riwayat"][-1]["omzet"] == 0


def test_tutup_tunggakan_3_minggu_diusir(rich_slot, game_data):
    slot = _slot_tutup(rich_slot, hari=7, uang=0, saldo_digital=0,
                       minggu_tunggak=2, tunggakan_sewa=0)
    hasil = cepat_mod.tutup_hari_bot(slot, game_data)
    assert hasil["minggu_tunggak"] == 3
    assert hasil["diusir"] is True
    assert hasil["slot"]["diusir"] is True


# -- /slot --------------------------------------------------------------------

def test_daftar_slot_enam_slot(sample_package):
    daftar = cepat_mod.daftar_slot(sample_package)
    assert len(daftar) == 6
    assert daftar[0]["kosong"] is False
    assert daftar[0]["nama_warung"] == "Warung Barokah"
    assert daftar[0]["level"] == 2
    assert daftar[0]["hari"] == 120
    assert daftar[0]["uang"] == 4500000
    assert all(d["kosong"] is True for d in daftar[1:])


def test_daftar_slot_paket_kosong():
    daftar = cepat_mod.daftar_slot({"slot": {}})
    assert len(daftar) == 6
    assert all(d["kosong"] is True for d in daftar)
