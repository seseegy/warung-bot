"""Tes fitur /cuan (core/cuan.py)."""

from __future__ import annotations

import copy

from bot.core import cuan as cuan_mod
from bot.core import sim as sim_mod


def test_aktifkan_cuan_set_flag_dan_diskon(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["uang"] = 1_000_000
    # modal beras sebelum cuan
    modal_normal = sim_mod.harga_modal(game_data, "beras", slot)
    hasil = cuan_mod.aktifkan_cuan(slot, game_data)
    s = hasil["slot"]
    assert s["mode_cuan"] is True
    # diskon 80% -> modal kira-kira 20% dari normal
    modal_cuan = sim_mod.harga_modal(game_data, "beras", s)
    assert modal_cuan <= modal_normal
    assert modal_cuan <= int(modal_normal * 0.2) + 100  # pembulatan ratusan
    # slot asli tidak berubah
    assert slot.get("mode_cuan") is not True


def test_aktifkan_cuan_beli_stok_sampai_target(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["uang"] = 5_000_000
    hasil = cuan_mod.aktifkan_cuan(slot, game_data)
    s = hasil["slot"]
    stok = s.get("stok", {})
    dibeli = [a for a in hasil["aksi"] if a.get("ok")]
    for a in dibeli:
        assert stok.get(a["id"], 0) > 0
    # tidak boleh melebihi target 100
    for a in dibeli:
        assert int(a["jumlah"]) <= cuan_mod.CUAN_TARGET_STOK


def test_aktifkan_cuan_sisakan_30_persen(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["uang"] = 1_000_000
    hasil = cuan_mod.aktifkan_cuan(slot, game_data)
    s = hasil["slot"]
    # sisa uang >= 30% dari uang awal
    assert s["uang"] >= int(1_000_000 * sim_mod.CUAN_SISA_UANG) - 1


def test_matikan_cuan_hapus_flag(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    hasil = cuan_mod.aktifkan_cuan(slot, game_data)
    assert hasil["slot"]["mode_cuan"] is True
    s = cuan_mod.matikan_cuan(hasil["slot"])
    assert s.get("mode_cuan") is not True


def test_simulasi_cuan_lebih_ramai(rich_slot, game_data):
    """Mode cuan -> pelanggan datang jauh lebih banyak (interval x 0.1)."""
    slot = copy.deepcopy(rich_slot)
    slot["uang"] = 5_000_000
    hasil = cuan_mod.aktifkan_cuan(slot, game_data)
    s = hasil["slot"]
    normal = sim_mod.simulate(slot, game_data, 1, seed=1)
    cuan = sim_mod.simulate(s, game_data, 1, seed=1)
    # cuan harus mendatangkan jauh lebih banyak pelanggan
    assert cuan["datang"] > normal["datang"] * 3


def test_cuan_stok_tak_berkurang(rich_slot, game_data):
    """Mode cuan: stok fisik tidak berkurang saat terjual (unlimited)."""
    slot = copy.deepcopy(rich_slot)
    slot["uang"] = 5_000_000
    hasil = cuan_mod.aktifkan_cuan(slot, game_data)
    s = hasil["slot"]
    stok_sebelum = {k: int(v) for k, v in s.get("stok", {}).items()}
    sim = sim_mod.simulate(s, game_data, 3, seed=1)
    s_akhir = sim["slot_akhir"]
    # stok barang fisik yang terjual harus tetap (tidak berkurang)
    for item_id in stok_sebelum:
        assert int(s_akhir.get("stok", {}).get(item_id, 0)) == stok_sebelum[item_id]
    # tetap ada penjualan (tidak habis di hari 2/3)
    assert sim["omzet"] > 0
    assert sim["dilayani"] > 0
