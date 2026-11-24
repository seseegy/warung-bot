"""Tes Fase 2 — perencana (bot/core/plan.py): kapan naik, ROI, what-if,
harga terbaik.
"""

from __future__ import annotations

import copy

import pytest

from bot.core import plan as plan_mod
from bot.core import sim as sim_mod
from bot.core.sim import SimError


# -- kapan_naik ---------------------------------------------------------------

def test_kapan_naik_progres_penuh_nol_hari(rich_slot, game_data):
    """Progres sudah memenuhi target Lv1 (15 pelanggan, 25 barang,
    omzet 100rb, khusus beruntun 5) -> 0 hari / sudah bisa naik."""
    slot = copy.deepcopy(rich_slot)
    slot["progres"] = {"pelanggan": 15, "barang": 25, "omzet": 100000,
                       "khusus": 5}
    hasil = plan_mod.kapan_naik(slot, game_data)
    assert hasil["naik"] is True
    assert hasil["hari"] == 0


def test_kapan_naik_level_terakhir(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 10
    hasil = plan_mod.kapan_naik(slot, game_data)
    assert hasil["naik"] is False
    assert hasil["alasan"] == "sudah level terakhir"


def test_kapan_naik_blocker_upgrade_dilaporkan(rich_slot, game_data):
    """Level 2 (tingkat=1) syarat upgrade ['kipas'] — tidak dimiliki ->
    blocker dilaporkan, naik False."""
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 1
    slot["upgrade"] = []
    hasil = plan_mod.kapan_naik(slot, game_data)
    assert hasil["naik"] is False
    assert any("kipas" in b for b in hasil["blocker"])


def test_kapan_naik_dengan_upgrade_bisa_naik(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 1
    slot["upgrade"] = ["kipas"]
    hasil = plan_mod.kapan_naik(slot, game_data)
    assert hasil["naik"] is True
    assert isinstance(hasil["hari"], int) and hasil["hari"] >= 0
    assert hasil["hari"] <= plan_mod.MAKS_HARI_KAPAN_NAIK


# -- roi_upgrade ---------------------------------------------------------------

def _slot_level_10(rich_slot):
    """Slot Level 10 (tingkat=9) — semua 12 upgrade memenuhi syarat level."""
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 9
    slot["upgrade"] = []
    slot["uang"] = 100_000_000
    return slot


def test_roi_upgrade_terurut_balik_modal(rich_slot, game_data):
    hasil = plan_mod.roi_upgrade(_slot_level_10(rich_slot), game_data)
    assert len(hasil) == 12, "semua upgrade harus dinilai di level 10"
    kunci = [h["hari_balik_modal"] if h["hari_balik_modal"] is not None
             else float("inf") for h in hasil]
    assert kunci == sorted(kunci), "tidak terurut dari tercepat balik modal"


def test_roi_upgrade_tanpa_efek_uang_ditandai(rich_slot, game_data):
    """cctv & genset: efek utamanya pencegahan (tidak disimulasikan) —
    harus ada catatan, dan kalaupun sim mengukur efek ramai kecilnya,
    balik modalnya harus absurd (> 1 tahun) atau None."""
    hasil = plan_mod.roi_upgrade(_slot_level_10(rich_slot), game_data)
    per_id = {h["id"]: h for h in hasil}
    for uid in ("cctv", "genset"):
        assert uid in per_id, f"{uid} tidak ada di hasil ROI"
        assert per_id[uid]["catatan"], f"{uid} tidak ditandai"
        balik = per_id[uid]["hari_balik_modal"]
        assert balik is None or balik > 365, f"{uid}: balik {balik} hari"


def test_roi_upgrade_yang_dimiliki_tidak_muncul(rich_slot, game_data):
    slot = _slot_level_10(rich_slot)
    slot["upgrade"] = ["etalase"]
    hasil = plan_mod.roi_upgrade(slot, game_data)
    assert all(h["id"] != "etalase" for h in hasil)


def test_roi_upgrade_harga_dan_biaya_hari_benar(rich_slot, game_data):
    hasil = plan_mod.roi_upgrade(_slot_level_10(rich_slot), game_data)
    per_id = {h["id"]: h for h in hasil}
    assert per_id["etalase"]["harga"] == 425000
    assert per_id["etalase"]["biaya_hari"] == 0
    assert per_id["kipas"]["harga"] == 520000
    assert per_id["kipas"]["biaya_hari"] == 1000


def test_roi_upgrade_level_rendah_hanya_yang_memenuhi_syarat(rich_slot, game_data):
    """Level 1 (tingkat=0) -> hanya etalase (level 1) yang dinilai."""
    hasil = plan_mod.roi_upgrade(rich_slot, game_data)
    assert [h["id"] for h in hasil] == ["etalase"]


# -- whatif -----------------------------------------------------------------------

def test_whatif_harga_di_bawah_lantai_ditolak(rich_slot, game_data):
    lantai = sim_mod.lantai_harga(game_data, "mi_goreng", rich_slot)
    with pytest.raises(SimError):
        plan_mod.whatif(rich_slot, game_data, {"mi_goreng": lantai - 100})


def test_whatif_harga_di_atas_batas_ditolak(rich_slot, game_data):
    batas = sim_mod.batas_harga_jual(game_data, "mi_goreng", rich_slot)
    with pytest.raises(SimError):
        plan_mod.whatif(rich_slot, game_data, {"mi_goreng": batas + 500})


def test_whatif_barang_tidak_dikenal_ditolak(rich_slot, game_data):
    with pytest.raises(SimError):
        plan_mod.whatif(rich_slot, game_data, {"tidak_ada": 5000})


def test_whatif_harga_lebih_murah_pelanggan_lebih_banyak(rich_slot, game_data):
    """Semua harga ke lantai (jauh di bawah normal) -> efek murah maks
    (+30% ramai) -> dilayani naik atau sama, tidak turun."""
    harga_murah = {}
    for item_id in ("beras", "gula", "mi_goreng", "sachet", "teh_botol",
                    "minyak_goreng", "telur", "kopi_susu"):
        harga_murah[item_id] = sim_mod.lantai_harga(game_data, item_id, rich_slot)
    hasil = plan_mod.whatif(rich_slot, game_data, harga_murah, jumlah_hari=3)
    assert hasil["usulan"]["dilayani"] >= hasil["sekarang"]["dilayani"]
    assert hasil["usulan"]["datang"] >= hasil["sekarang"]["datang"]


def test_whatif_harga_mahal_laba_per_unit_naik_tapi_pelanggan_turun(
        rich_slot, game_data):
    """Harga naik ke batas -> omzet per pelanggan naik, tapi keluhan mahal
    membuat sebagian batal. Arahnya harus konsisten dengan rumus."""
    batas = sim_mod.batas_harga_jual(game_data, "mi_goreng", rich_slot)
    hasil = plan_mod.whatif(rich_slot, game_data, {"mi_goreng": batas},
                            jumlah_hari=3)
    assert hasil["usulan"]["dilayani"] <= hasil["sekarang"]["dilayani"]


def test_whatif_seed_sama_deterministik(rich_slot, game_data):
    a = plan_mod.whatif(rich_slot, game_data, {"mi_goreng": 3000}, seed=77)
    b = plan_mod.whatif(rich_slot, game_data, {"mi_goreng": 3000}, seed=77)
    assert a == b


# -- harga_terbaik -------------------------------------------------------------------

def test_harga_terbaik_tidak_pernah_di_bawah_lantai(rich_slot, game_data):
    hasil = plan_mod.harga_terbaik(rich_slot, game_data)
    assert hasil, "seharusnya ada barang yang dinilai"
    for entri in hasil:
        lantai = sim_mod.lantai_harga(game_data, entri["id"], rich_slot)
        batas = sim_mod.batas_harga_jual(game_data, entri["id"], rich_slot)
        assert lantai <= entri["harga_terbaik"] <= batas, entri["id"]


def test_harga_terbaik_laba_tidak_lebih_buruk_dari_sekarang(rich_slot, game_data):
    """Harga terbaik dipilih dari kandidat yang TERMASUK harga sekarang,
    jadi laba_terbaik >= laba_sekarang (per seed yang sama)."""
    hasil = plan_mod.harga_terbaik(rich_slot, game_data)
    for entri in hasil:
        assert entri["laba_terbaik"] >= entri["laba_sekarang"], entri["id"]


def test_harga_terbaik_hanya_barang_ada_stok(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["stok"] = {"mi_goreng": 5}
    hasil = plan_mod.harga_terbaik(slot, game_data)
    assert [h["id"] for h in hasil] == ["mi_goreng"]


def test_harga_terbaik_stok_nol_kosong(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["stok"] = {k: 0 for k in slot["stok"]}
    assert plan_mod.harga_terbaik(slot, game_data) == []
