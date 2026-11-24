"""Tes core/store.py — validasi akun.json + enkripsi + hapus total."""

from __future__ import annotations

import time

import pytest
from cryptography.fernet import Fernet

from bot.core.store import Store, is_access_expired, validate_akun_json


# -- validasi akun.json --------------------------------------------------

def test_validate_akun_json_valid(akun_json_valid):
    valid, errors, warnings = validate_akun_json(akun_json_valid)
    assert valid and errors == [] and warnings == []


def test_validate_akun_json_bukan_dict():
    valid, errors, _ = validate_akun_json([1, 2])
    assert not valid and errors


def test_validate_akun_json_field_hilang(akun_json_valid):
    for field in ("akses", "segar", "habis", "user_id"):
        data = dict(akun_json_valid)
        del data[field]
        valid, errors, _ = validate_akun_json(data)
        assert not valid
        assert any(field in e for e in errors)


def test_validate_akun_json_field_kosong(akun_json_valid):
    data = dict(akun_json_valid, akses="")
    valid, errors, _ = validate_akun_json(data)
    assert not valid


def test_validate_akun_json_habis_bukan_int(akun_json_valid):
    data = dict(akun_json_valid, habis="besok")
    valid, errors, _ = validate_akun_json(data)
    assert not valid


def test_validate_akun_json_token_habis_hanya_warning(akun_json_valid):
    """Access token kedaluwarsa = warning, BUKAN error: refresh masih bisa."""
    data = dict(akun_json_valid, habis=int(time.time()) - 10)
    valid, errors, warnings = validate_akun_json(data)
    assert valid and errors == [] and warnings


def test_is_access_expired():
    assert is_access_expired({"habis": int(time.time()) - 1})
    assert not is_access_expired({"habis": int(time.time()) + 3600})
    assert is_access_expired({})


# -- simpan / ambil ------------------------------------------------------

def test_save_get_user_roundtrip(store, akun_json_valid):
    store.save_user(123, akun_json_valid)
    hasil = store.get_user(123)
    assert hasil is not None
    assert hasil["akses"] == akun_json_valid["akses"]
    assert hasil["segar"] == akun_json_valid["segar"]
    assert hasil["habis"] == akun_json_valid["habis"]
    assert hasil["user_id"] == akun_json_valid["user_id"]
    assert hasil["email"] == akun_json_valid["email"]
    assert hasil["versi"] == 8


def test_token_tidak_tersimpan_polos(store, akun_json_valid, tmp_path):
    store.save_user(123, akun_json_valid)
    store.close()
    raw = (tmp_path / "test.db").read_bytes()
    assert b"access-TOKEN-valid" not in raw
    assert b"refresh-TOKEN-valid" not in raw


def test_get_user_belum_tertaut(store):
    assert store.get_user(999) is None


def test_update_session(store, akun_json_valid):
    store.save_user(123, akun_json_valid)
    baru = dict(akun_json_valid, akses="access-TOKEN-baru", versi=9)
    store.update_session(123, baru)
    hasil = store.get_user(123)
    assert hasil["akses"] == "access-TOKEN-baru"
    assert hasil["versi"] == 9


def test_kunci_fernet_salah_gagal_dekripsi(store, akun_json_valid, tmp_path):
    store.save_user(123, akun_json_valid)
    store.close()
    store2 = Store(tmp_path / "test.db", Fernet.generate_key())
    with pytest.raises(ValueError):
        store2.get_user(123)
    store2.close()


def test_delete_user_hapus_semua(store, akun_json_valid):
    store.save_user(123, akun_json_valid)
    store.save_backup(123, 8, "1:xxx")
    assert store.get_latest_backup(123) is not None
    store.delete_user(123)
    assert store.get_user(123) is None
    assert store.get_latest_backup(123) is None


def test_backup_simpan_ambil(store):
    assert store.get_latest_backup(123) is None
    store.save_backup(123, 8, "1:paket-lama")
    store.save_backup(123, 9, "1:paket-baru")
    terbaru = store.get_latest_backup(123)
    assert terbaru["versi"] == 9
    assert terbaru["p_data"] == "1:paket-baru"
