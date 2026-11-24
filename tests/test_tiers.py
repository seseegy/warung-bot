"""Tes Fase 3 — tier + Store Fase 3 (tier/otomatis/audit/login/peringkat)."""

from __future__ import annotations

import pytest

from bot.core import tiers as tiers_mod


# -- definisi tier ------------------------------------------------------------

def test_nama_dan_deskripsi_tiap_tier():
    assert tiers_mod.TIER_NAMA[1] == "Pemula"
    assert tiers_mod.TIER_NAMA[2] == "Standar"
    assert tiers_mod.TIER_NAMA[3] == "Profesional"
    assert tiers_mod.TIER_DESKRIPSI[1]
    assert tiers_mod.TIER_DESKRIPSI[2]
    assert tiers_mod.TIER_DESKRIPSI[3]
    assert tiers_mod.nama_tier(2) == "Standar"
    assert tiers_mod.nama_tier(99) == "Pemula"  # nilai tak dikenal -> Pemula
    assert tiers_mod.tier_valid("x") == 1


def test_fitur_minimum_naik_dengan_tier():
    assert tiers_mod.FITUR_MIN_TIER["login_inget"] == 1
    assert tiers_mod.FITUR_MIN_TIER["simulasi_harian"] == 2
    assert tiers_mod.FITUR_MIN_TIER["harga_dinamis"] == 3
    assert tiers_mod.FITUR_MIN_TIER["auto_bayar"] == 3
    assert tiers_mod.FITUR_MIN_TIER["peringkat"] == 3


def test_fitur_tidak_dikenal_default_profesional():
    # FITUR_MIN_TIER.get(fitur, TIER_PROFESIONAL) — fitur asing paling ketat.
    with pytest.raises(tiers_mod.TierError):
        tiers_mod.require_tier(1, "bukan_fitur")
    tiers_mod.require_tier(3, "bukan_fitur")  # Profesional lolos


# -- gating -------------------------------------------------------------------

def _user(store, tier=1):
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u", "versi": 1})
    store.set_tier(123, tier)


def test_require_tier_lolos_bila_cukup():
    tiers_mod.require_tier(2, "simulasi_harian")  # tidak melempar


def test_require_tier_ditolak_bila_kurang():
    with pytest.raises(tiers_mod.TierError) as info:
        tiers_mod.require_tier(1, "simulasi_harian")
    assert "Standar" in str(info.value)
    assert "Pemula" in str(info.value)
    assert "/tier" in str(info.value)


def test_require_tier_profesional_ditolak_di_standar():
    with pytest.raises(tiers_mod.TierError) as info:
        tiers_mod.require_tier(2, "harga_dinamis")
    assert "Profesional" in str(info.value)


def test_require_tier_tanpa_akun_default_pemula():
    # tier_valid(None) -> Pemula, jadi fitur Standar ditolak.
    with pytest.raises(tiers_mod.TierError):
        tiers_mod.require_tier(None, "simulasi_harian")


# -- Store: tier / otomatis / batas / jam -------------------------------------

def test_tier_default_pemula(store):
    _user(store)
    assert store.get_tier(123) == 1


def test_set_tier_dan_baca(store):
    _user(store)
    store.set_tier(123, 3)
    assert store.get_tier(123) == 3


def test_set_tier_tidak_valid_ditolak(store):
    _user(store)
    with pytest.raises(ValueError):
        store.set_tier(123, 0)
    with pytest.raises(ValueError):
        store.set_tier(123, 4)


def test_otomatis_default_mati_dan_toggle(store):
    _user(store)
    assert store.get_otomatis(123) is False
    store.set_otomatis(123, True)
    assert store.get_otomatis(123) is True
    store.set_otomatis(123, False)
    assert store.get_otomatis(123) is False


def test_batas_harian_default_satu_juta(store):
    _user(store)
    assert store.get_batas_harian(123) == 1_000_000


def test_set_batas_harian(store):
    _user(store)
    store.set_batas_harian(123, 500_000)
    assert store.get_batas_harian(123) == 500_000
    with pytest.raises(ValueError):
        store.set_batas_harian(123, -1)


def test_jam_otomatis_default_tujuh(store):
    _user(store)
    assert store.get_jam_otomatis(123) == 7


def test_set_jam_otomatis(store):
    _user(store)
    store.set_jam_otomatis(123, 20)
    assert store.get_jam_otomatis(123) == 20
    with pytest.raises(ValueError):
        store.set_jam_otomatis(123, 24)


def test_all_otomatis_hanya_yang_nyala(store):
    _user(store)
    store.save_user(456, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u2", "versi": 1})
    store.set_otomatis(123, True)
    store.set_otomatis(456, False)
    rows = store.all_otomatis()
    assert [r["chat_id"] for r in rows] == [123]


# -- audit --------------------------------------------------------------------

def test_log_audit_dan_baca(store):
    _user(store)
    store.log_audit(123, "beli_stok", "Beras x18", "Rp500.000", "Rp266.000")
    audit = store.get_audit(123, 0)
    assert len(audit) == 1
    assert audit[0]["aksi"] == "beli_stok"
    assert audit[0]["detail"] == "Beras x18"
    assert audit[0]["lama"] == "Rp500.000"
    assert audit[0]["baru"] == "Rp266.000"


def test_audit_dibatasi_waktu(store):
    _user(store)
    store.log_audit(123, "lama", "x")
    import time

    sekarang = int(time.time())
    assert store.get_audit(123, sekarang + 1000) == []
    assert len(store.get_audit(123, sekarang - 10)) == 1


# -- login lacak + peringkat ---------------------------------------------------

def test_login_lacak_default_dan_set(store):
    assert store.get_login_lacak(123) == {"hari_ke": 0, "tanggal": "",
                                          "siklus": 0}
    store.set_login_lacak(123, 4, "2026-11-24")
    assert store.get_login_lacak(123) == {"hari_ke": 4,
                                          "tanggal": "2026-11-24",
                                          "siklus": 0}
    store.set_login_lacak(123, 5, "2026-11-25")
    assert store.get_login_lacak(123)["hari_ke"] == 5


def test_peringkat_simpan_baca(store):
    assert store.get_peringkat(123, "semua") is None
    store.save_peringkat(123, "semua", 12, 500)
    row = store.get_peringkat(123, "semua")
    assert row["peringkat"] == 12
    assert row["jumlah_warung"] == 500
    store.save_peringkat(123, "semua", 9, 510)
    assert store.get_peringkat(123, "semua")["peringkat"] == 9


def test_delete_user_menghapus_semua_fase3(store):
    _user(store, tier=3)
    store.set_otomatis(123, True)
    store.set_jadwal(123, 7)
    store.log_audit(123, "beli_stok", "x")
    store.set_login_lacak(123, 4, "2026-11-24")
    store.save_peringkat(123, "semua", 12, 500)
    store.delete_user(123)
    assert store.get_user(123) is None
    assert store.get_jadwal(123) is None
    assert store.get_audit(123, 0) == []
    assert store.get_login_lacak(123)["hari_ke"] == 0
    assert store.get_peringkat(123, "semua") is None
    assert store.get_tier(123) == 1
    assert store.get_otomatis(123) is False
