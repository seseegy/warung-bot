"""Tes Fase 5 — Store: slot aktif, meta generik, daftar arsip, all_chat_ids.
"""

from __future__ import annotations

import pytest


def test_slot_aktif_default_none(store):
    assert store.get_slot_aktif(123) is None


def test_slot_aktif_set_dan_hapus(store, akun_json_valid):
    store.save_user(123, akun_json_valid)
    store.set_slot_aktif(123, 3)
    assert store.get_slot_aktif(123) == 3
    store.set_slot_aktif(123, None)
    assert store.get_slot_aktif(123) is None


def test_slot_aktif_di_luar_1_6_ditolak(store, akun_json_valid):
    store.save_user(123, akun_json_valid)
    with pytest.raises(ValueError):
        store.set_slot_aktif(123, 7)
    with pytest.raises(ValueError):
        store.set_slot_aktif(123, 0)


def test_slot_aktif_rusak_di_db_dianggap_none(store, akun_json_valid):
    store.save_user(123, akun_json_valid)
    store._conn.execute("UPDATE users SET slot_aktif=99 WHERE chat_id=123")
    store._conn.commit()
    assert store.get_slot_aktif(123) is None


def test_meta_get_set(store):
    assert store.meta_get(123, "pasaran") is None
    store.meta_set(123, "pasaran", '{"a": 1}')
    assert store.meta_get(123, "pasaran") == '{"a": 1}'
    store.meta_set(123, "pasaran", '{"a": 2}')
    assert store.meta_get(123, "pasaran") == '{"a": 2}'
    assert store.meta_get(123, "lain") is None


def test_list_dan_get_backup(store, sample_p_data):
    assert store.list_backups(123) == []
    assert store.get_backup(123, 1) is None
    store.save_backup(123, 8, sample_p_data)
    store.save_backup(123, 9, sample_p_data)
    daftar = store.list_backups(123)
    assert len(daftar) == 2
    assert daftar[0]["versi"] == 9  # terbaru dulu
    assert daftar[1]["versi"] == 8
    satu = store.get_backup(123, daftar[1]["id"])
    assert satu["p_data"] == sample_p_data
    assert satu["versi"] == 8


def test_all_chat_ids(store, akun_json_valid):
    assert store.all_chat_ids() == []
    store.save_user(123, akun_json_valid)
    store.save_user(456, akun_json_valid)
    assert sorted(store.all_chat_ids()) == [123, 456]


def test_delete_user_menghapus_meta_dan_backup(store, akun_json_valid,
                                              sample_p_data):
    store.save_user(123, akun_json_valid)
    store.meta_set(123, "pasaran", "{}")
    store.save_backup(123, 8, sample_p_data)
    store.set_slot_aktif(123, 2)
    store.delete_user(123)
    assert store.get_user(123) is None
    assert store.meta_get(123, "pasaran") is None
    assert store.list_backups(123) == []
    assert store.get_slot_aktif(123) is None
