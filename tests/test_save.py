"""Tes core/save.py — format paket & sidik digrounding ke kode game."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json

import pytest

from bot.core import save as save_mod
from bot.core.save import (
    PackageError,
    SlotError,
    TaskError,
    best_slot,
    build_package_with_slot,
    compute_sidik,
    decode_package,
    encode_package,
    fill_task_progress,
    parse_slot,
    sekarang_wib_str,
    serialize_slot,
    set_uang,
    slot_summary,
    task_targets,
)


# -- encode / decode -----------------------------------------------------

def test_roundtrip_encode_decode(sample_package):
    p_data = encode_package(sample_package)
    assert p_data.startswith("1:")
    assert decode_package(p_data) == sample_package


def test_roundtrip_nyata_dari_format_api():
    """Paket kecil dengan slot string mentah (seperti request asli 10:39)."""
    paket = {
        "format": 1,
        "dari": "Android",
        "dibuat": "2026-11-24 10:39:21",
        "versi_game": "1.2",
        "slot": {"1": '{\n\t"uang": 1000,\n\t"tingkat": 0\n}'},
        "slot_terakhir": 1,
        "toko": {"tanpa_iklan": False, "pendukung": False, "kode_pendukung": ""},
        "lemari": [],
    }
    hasil = decode_package(encode_package(paket))
    assert hasil["slot"]["1"] == paket["slot"]["1"]
    # base64 hasil encode harus diawali magic gzip "H4sI" (1f 8b 08)
    assert encode_package(paket)[2:6] == "H4sI"


def test_decode_tolak_tanpa_prefix():
    with pytest.raises(PackageError):
        decode_package("H4sIAAAAAAAAA==")


def test_decode_tolak_base64_rusak():
    with pytest.raises(PackageError):
        decode_package("1:!!!bukan-base64!!!")


def test_decode_tolak_gzip_rusak():
    # base64 valid tapi isinya bukan gzip
    with pytest.raises(PackageError):
        decode_package("1:" + base64.b64encode(b"bukan gzip sama sekali").decode())


def test_decode_tolak_json_bukan_dict():
    mentah = gzip.compress(json.dumps([1, 2, 3]).encode())
    with pytest.raises(PackageError):
        decode_package("1:" + base64.b64encode(mentah).decode())


def test_decode_tolak_gzip_terpotong():
    mentah = gzip.compress(json.dumps({"slot": {}}).encode())
    potong = mentah[: len(mentah) // 2]
    with pytest.raises(PackageError):
        decode_package("1:" + base64.b64encode(potong).decode())


def test_decode_tolak_melebihi_batas_20mb():
    besar = gzip.compress(b"x" * (save_mod.MAX_PACKAGE_BYTES + 1))
    with pytest.raises(PackageError):
        decode_package("1:" + base64.b64encode(besar).decode())


def test_decode_tolak_tanpa_slot():
    mentah = gzip.compress(json.dumps({"format": 1}).encode())
    with pytest.raises(PackageError):
        decode_package("1:" + base64.b64encode(mentah).decode())


def test_parse_slot_tolak_rusak():
    with pytest.raises(SlotError):
        parse_slot("{bukan json")
    with pytest.raises(SlotError):
        parse_slot("[1,2]")


def test_serialize_slot_pakai_indent_tab(sample_slot):
    teks = serialize_slot(sample_slot)
    assert '\n\t"uang": 4500000' in teks
    assert parse_slot(teks) == sample_slot


# -- sidik ---------------------------------------------------------------

def test_sidik_stabil(sample_package):
    assert compute_sidik(sample_package) == compute_sidik(sample_package)


def test_sidik_cocok_hitungan_manual(sample_package):
    """Hitung ulang sidik secara independen (hashlib mentah).

    Meniru _sidik(): slot yang ada saja -> "n:md5(file)"; flag
    "falsefalse0" (tanpa_iklan=false, pendukung=false, kode="", 0 baju).
    """
    slot_teks = sample_package["slot"]["1"]
    md5 = hashlib.md5(slot_teks.encode("utf-8")).hexdigest()
    gabung = f"1:{md5}|falsefalse0"
    harap = hashlib.sha256(gabung.encode("utf-8")).hexdigest()
    assert compute_sidik(sample_package) == harap


def test_sidik_berubah_saat_isi_berubah(sample_package):
    sebelum = compute_sidik(sample_package)
    paket2 = dict(sample_package)
    paket2["slot"] = {"1": serialize_slot({"uang": 999, "tingkat": 0})}
    assert compute_sidik(paket2) != sebelum


def test_sidik_hanya_slot_yang_ada(sample_package):
    # Menambah slot "2" mengubah sidik; slot yang TIDAK ada tidak dihitung.
    paket2 = dict(sample_package)
    paket2["slot"] = dict(sample_package["slot"])
    paket2["slot"]["2"] = serialize_slot({"uang": 1, "tingkat": 0})
    assert compute_sidik(paket2) != compute_sidik(sample_package)
    # Flag tanpa_iklan=true mengubah sidik (bool Godot -> "true").
    paket3 = json.loads(json.dumps(sample_package))
    paket3["toko"]["tanpa_iklan"] = True
    assert compute_sidik(paket3) != compute_sidik(sample_package)


# -- ringkasan & slot terbaik --------------------------------------------

def test_slot_summary(sample_slot):
    ringkasan = slot_summary(sample_slot)
    assert ringkasan["level"] == 2  # tingkat 1 + 1
    assert ringkasan["qris"] == 120000  # saldo_digital
    assert ringkasan["uang"] == 4500000
    assert ringkasan["hari"] == 120
    assert ringkasan["id_papan"] == "3a5dd8081fa92f174078ce3ca639fa07"


def test_best_slot_pilih_level_lalu_hari(sample_package):
    slot2 = {
        "uang": 1, "tingkat": 2, "hari": 5,
        "nama_warung": "W2", "saldo_digital": 0, "id_papan": "x",
        "disimpan": "",
    }
    sample_package["slot"]["2"] = serialize_slot(slot2)
    nomor, data = best_slot(sample_package)
    assert nomor == 2
    assert data["tingkat"] == 2


def test_best_slot_tolak_paket_kosong():
    with pytest.raises(PackageError):
        best_slot({"slot": {}})


def test_best_slot_lewati_slot_rusak(sample_package):
    """Satu slot rusak tidak boleh membuat seluruh paket gagal dibaca:
    slot rusak dilewati, slot sehat tetap dipilih."""
    sample_package["slot"]["2"] = "{json rusak"
    nomor, data = best_slot(sample_package)
    assert nomor == 1
    assert data["nama_warung"] == "Warung Barokah"
    # Semua slot rusak -> tetap PackageError.
    with pytest.raises(PackageError):
        best_slot({"slot": {"1": "{rusak", "2": "bukan json"}})


# -- ubah uang -------------------------------------------------------------

def test_set_uang_ok(sample_slot):
    set_uang(sample_slot, 5000000)
    assert sample_slot["uang"] == 5000000


def test_set_uang_nol_diizinkan_core(sample_slot):
    # Uang 0 = bangkrut, keadaan sah di game. (Input chat menolak 0
    # sebagai kemungkinan salah ketik — itu keputusan lapis handler.)
    set_uang(sample_slot, 0)
    assert sample_slot["uang"] == 0


def test_set_uang_tolak_negatif(sample_slot):
    with pytest.raises(ValueError):
        set_uang(sample_slot, -1)


def test_set_uang_tolak_melebihi_batas(sample_slot):
    with pytest.raises(ValueError):
        set_uang(sample_slot, save_mod.UANG_MAKSIMAL + 1)


def test_set_uang_tolak_bool_dan_str(sample_slot):
    with pytest.raises(ValueError):
        set_uang(sample_slot, True)
    with pytest.raises(ValueError):
        set_uang(sample_slot, "5000000")


# -- isi progres tugas -----------------------------------------------------

def test_task_targets_level_1(tugas_data):
    t = task_targets(tugas_data, 0)
    assert t["nama"] == "Pemula"
    assert (t["pelanggan"], t["barang"], t["omzet"], t["hadiah"]) == (15, 25, 100000, 15000)


def test_task_targets_lewat_level_terakhir(tugas_data):
    with pytest.raises(TaskError):
        task_targets(tugas_data, 10)


def test_fill_tugas_level_1_tanpa_blocker(tugas_data):
    slot = {"tingkat": 0, "progres": {"pelanggan": 0, "barang": 0, "omzet": 0, "khusus": 0},
            "upgrade": [], "misi_status": "", "cerita_tamat": False}
    hasil = fill_task_progress(slot, tugas_data)
    assert slot["progres"] == {"pelanggan": 15, "barang": 25, "omzet": 100000, "khusus": 5}
    assert hasil["blockers"] == []  # Lv 1 tanpa syarat upgrade


def test_fill_tugas_level_2_blocker_upgrade(tugas_data):
    slot = {"tingkat": 1, "progres": {"pelanggan": 0, "barang": 0, "omzet": 0, "khusus": 0},
            "upgrade": [], "misi_status": "", "cerita_tamat": False}
    hasil = fill_task_progress(slot, tugas_data)
    assert slot["progres"]["pelanggan"] == 40
    assert any("kipas" in b for b in hasil["blockers"])


def test_fill_tugas_level_2_upgrade_dimiliki_tanpa_blocker(tugas_data):
    slot = {"tingkat": 1, "progres": {"pelanggan": 0, "barang": 0, "omzet": 0, "khusus": 0},
            "upgrade": ["kipas"], "misi_status": "", "cerita_tamat": False}
    hasil = fill_task_progress(slot, tugas_data)
    assert hasil["blockers"] == []


def test_fill_tugas_blocker_misi_belum_lunas(tugas_data):
    slot = {"tingkat": 1, "progres": {"pelanggan": 0, "barang": 0, "omzet": 0, "khusus": 0},
            "upgrade": ["kipas"], "misi_status": "aktif", "cerita_tamat": False}
    hasil = fill_task_progress(slot, tugas_data)
    assert any("misi" in b for b in hasil["blockers"])


def test_fill_tugas_level_terakhir_gagal(tugas_data):
    slot = {"tingkat": 10, "progres": {}, "upgrade": [], "misi_status": "", "cerita_tamat": True}
    with pytest.raises(TaskError):
        fill_task_progress(slot, tugas_data)


# -- bangun paket hasil edit ----------------------------------------------

def test_build_package_slot_lain_tidak_berubah(sample_package, sample_slot):
    slot2 = {"uang": 7, "tingkat": 0}
    sample_package["slot"]["2"] = serialize_slot(slot2)
    slot_baru = dict(sample_slot)
    set_uang(slot_baru, 5000000)
    paket_baru = build_package_with_slot(sample_package, 1, slot_baru)
    # Slot 2 byte-for-byte sama; slot 1 berubah; toko/lemari sama.
    assert paket_baru["slot"]["2"] == sample_package["slot"]["2"]
    assert parse_slot(paket_baru["slot"]["1"])["uang"] == 5000000
    assert paket_baru["toko"] == sample_package["toko"]
    assert paket_baru["lemari"] == sample_package["lemari"]
    # "dibuat" diperbarui (format game: YYYY-MM-DD HH:MM:SS).
    assert paket_baru["dibuat"] != sample_package["dibuat"]
    assert len(paket_baru["dibuat"]) == 19


def test_build_package_nomor_slot_tidak_valid(sample_package, sample_slot):
    with pytest.raises(ValueError):
        build_package_with_slot(sample_package, 0, sample_slot)
    with pytest.raises(ValueError):
        build_package_with_slot(sample_package, 7, sample_slot)


def test_sekarang_wib_str_format():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    teks = sekarang_wib_str()
    dt = datetime.strptime(teks, "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=ZoneInfo("Asia/Jakarta"))
    assert abs(
        (datetime.now(ZoneInfo("Asia/Jakarta")) - dt).total_seconds()) < 10


def test_build_package_stempel_wib(sample_package, sample_slot):
    """Stempel edit bot = WIB sekarang, bukan UTC sistem.

    Service systemd jalan dengan zona UTC (shell punya TZ=Asia/Jakarta,
    service tidak) — datetime.now() telanjang akan 7 jam ketinggalan.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    slot_baru = dict(sample_slot)
    dibuat_lama = sample_package["dibuat"]
    paket_baru = build_package_with_slot(sample_package, 1, slot_baru)
    sekarang = datetime.now(ZoneInfo("Asia/Jakarta"))
    dibuat = datetime.strptime(
        paket_baru["dibuat"], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=ZoneInfo("Asia/Jakarta"))
    assert abs((sekarang - dibuat).total_seconds()) < 10
    # Slot yang diedit ikut diperbarui stempelnya (seperti game saat save);
    # paket asli tidak berubah.
    assert parse_slot(paket_baru["slot"]["1"])["disimpan"] == paket_baru["dibuat"]
    assert sample_package["dibuat"] == dibuat_lama
