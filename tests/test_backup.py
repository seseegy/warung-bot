"""Tes Fase 5 — backup paket harian + rollback (bot/core/backup.py).

Memakai tabel ``backups`` Store yang sudah ada (p_data terenkripsi).
Tidak ada panggilan live.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from bot.core import backup as backup_mod
from bot.core import save as save_mod


def test_arsipkan_satu_per_hari(store, sample_p_data):
    # Tanggal dinamis (WIB): param `tanggal` arsipkan_harian HANYA untuk
    # dedup, sedangkan tanggal tampilan berasal dari created_at nyata —
    # jadi ekspektasi harus memakai hari ini / besok, bukan tanggal
    # kalender hardcode.
    hari_ini = backup_mod.tanggal_hari_ini()
    besok = backup_mod.tanggal_hari_ini(
        datetime.now(backup_mod.WIB) + timedelta(days=1))
    r1 = backup_mod.arsipkan_harian(store, 123, 8, sample_p_data,
                                    tanggal=hari_ini)
    assert r1["disimpan"] is True
    r2 = backup_mod.arsipkan_harian(store, 123, 9, sample_p_data,
                                    tanggal=hari_ini)
    assert r2["disimpan"] is False  # hari yang sama: tidak menimpa
    r3 = backup_mod.arsipkan_harian(store, 123, 9, sample_p_data,
                                    tanggal=besok)
    assert r3["disimpan"] is True
    assert len(backup_mod.daftar_arsip(store, 123)) == 2


def test_arsipkan_p_data_kosong_ditolak(store):
    with pytest.raises(backup_mod.BackupError):
        backup_mod.arsipkan_harian(store, 123, 8, "")


def test_daftar_arsip_terbaru_dulu(store, sample_p_data):
    # Tanggal arsip berasal dari created_at nyata (bukan param dedup):
    # simulasikan arsip kemarin dengan mengubah created_at langsung.
    import time

    backup_mod.arsipkan_harian(store, 123, 8, sample_p_data,
                               tanggal="2026-11-24")
    kemarin = int(time.time()) - 86400
    store._conn.execute(
        "UPDATE backups SET created_at=? WHERE chat_id=?", (kemarin, 123))
    store._conn.commit()
    backup_mod.arsipkan_harian(store, 123, 9, sample_p_data)
    daftar = backup_mod.daftar_arsip(store, 123)
    assert len(daftar) == 2
    assert daftar[0]["versi"] == 9  # terbaru dulu
    assert daftar[1]["versi"] == 8
    assert daftar[0]["tanggal"] != daftar[1]["tanggal"]


def test_muat_arsip_identik_dengan_asli(store, sample_p_data, sample_package):
    backup_mod.arsipkan_harian(store, 123, 8, sample_p_data,
                               tanggal="2026-11-24")
    arsip_id = backup_mod.daftar_arsip(store, 123)[0]["id"]
    arsip = backup_mod.muat_arsip(store, 123, arsip_id)
    assert arsip["p_data"] == sample_p_data
    assert arsip["paket"]["format"] == sample_package["format"]
    assert arsip["paket"]["slot"]["1"] == sample_package["slot"]["1"]
    assert arsip["versi"] == 8


def test_muat_arsip_tidak_ada_ditolak(store):
    with pytest.raises(backup_mod.BackupError):
        backup_mod.muat_arsip(store, 123, 999)


def test_muat_arsip_rusak_ditolak(store, sample_p_data):
    store.save_backup(123, 8, "H4sI_BUKAN-BASE64-VALID!!!")
    arsip_id = backup_mod.daftar_arsip(store, 123)[0]["id"]
    with pytest.raises(backup_mod.BackupError):
        backup_mod.muat_arsip(store, 123, arsip_id)


def test_muat_arsip_slot_rusak_ditolak(store):
    paket_rusak = {"format": 1, "slot": {"1": "{bukan json"}}
    p_data = save_mod.encode_package(paket_rusak)
    store.save_backup(123, 8, p_data)
    arsip_id = backup_mod.daftar_arsip(store, 123)[0]["id"]
    with pytest.raises(backup_mod.BackupError):
        backup_mod.muat_arsip(store, 123, arsip_id)


def test_ringkasan_arsip_slot_terbaik(store, sample_p_data):
    backup_mod.arsipkan_harian(store, 123, 8, sample_p_data,
                               tanggal="2026-11-24")
    arsip_id = backup_mod.daftar_arsip(store, 123)[0]["id"]
    arsip = backup_mod.muat_arsip(store, 123, arsip_id)
    ringkasan = backup_mod.ringkasan_arsip(arsip["paket"])
    assert ringkasan["nama_warung"] == "Warung Barokah"
    assert ringkasan["level"] == 2
    assert ringkasan["uang"] == 4500000
