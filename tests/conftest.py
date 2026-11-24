"""Fixture bersama: save contoh berstruktur ASLI game.

Slot contoh meniru field yang ditulis ``simpan()`` di game_state.gd:
uang, tingkat (0-based), hari, saldo_digital, nama_warung, progres,
upgrade (array id), misi_status, cerita_tamat, energi, id_papan, disimpan.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.core import save as save_mod  # noqa: E402
from bot.core.sim import GameData  # noqa: E402
from bot.core.store import Store  # noqa: E402


@pytest.fixture(scope="session")
def game_data():
    """GameData dari bot/data/ (6 JSON, SHA-256 terverifikasi = asset pack)."""
    return GameData(ROOT / "bot" / "data")


def make_rich_slot(**overrides):
    """Slot kaya untuk simulasi: Level 1 (tingkat=0), hari Senin (hari 1),
    stok cukup untuk beberapa barang, harga pasar segar, saldo layanan
    cukup, energi penuh, tanpa upgrade — titik awal yang adil untuk sim."""
    slot = make_slot(
        tingkat=0,
        hari=1,
        menit=540,
        uang=500000,
        saldo_digital=0,
        saldo_layanan=200000,
        progres={"pelanggan": 0, "barang": 0, "omzet": 0, "khusus": 0},
        upgrade=[],
        misi_status="",
        cerita_tamat=False,
        energi=100.0,
        reputasi=0,
        ulasan=[],
        barang_terbuka=["beras", "gula", "mi_goreng", "sachet",
                        "teh_botol", "minyak_goreng", "telur", "kopi_susu"],
        stok={"beras": 20, "gula": 20, "mi_goreng": 20, "sachet": 20,
              "teh_botol": 20, "minyak_goreng": 10, "telur": 10,
              "kopi_susu": 10},
        harga_jual_khusus={},
        harga_pasaran={},
        agen_kenalan=[],
        promosi_mulai=0,
        riwayat_layan=[],
        riwayat=[],
        penjualan_hari={},
        kiriman_stok={},
        tas_grosir={},
        kurir_pilihan=0,
        kurir_hari=0,
        instan_mulai=0,
        tunggakan_sewa=0,
        sewa_cicil=0,
        sewa_selesai_hari=0,
        minggu_tunggak=0,
        diusir=False,
        rumah_renovasi=False,
        motor_baru=False,
        agus_bantu_sampai=0,
        kios_milik=False,
        total_pembeli=0,
        pembeli_minggu=0,
        pembeli_bulan=0,
        omzet_minggu=0,
        omzet_bulan=0,
        cerita_warga={},
        keakraban={},
        beruntun_sekarang=0,
        hari_inti_beres=0,
        hari_level_mulai=1,
    )
    slot.update(overrides)
    return slot


@pytest.fixture()
def rich_slot():
    return make_rich_slot()


@pytest.fixture()
def tugas_data():
    return json.loads((ROOT / "bot" / "data" / "tugas.json").read_text(encoding="utf-8"))


def make_slot(**overrides):
    """Slot Level 2 (tingkat=1) dengan progres sebagian — default.

    Level 2 punya syarat upgrade ['kipas'] (tugas.json) dan TIDAK dimiliki
    secara default -> fill_task_progress harus melaporkan blocker.
    """
    slot = {
        "versi": 1,
        "disimpan": "2026-11-24 10:39:21",
        "nama_warung": "Warung Barokah",
        "id_papan": "3a5dd8081fa92f174078ce3ca639fa07",
        "mode": "casual",
        "hari": 120,
        "uang": 4500000,
        "saldo_digital": 120000,
        "tingkat": 1,
        "progres": {"pelanggan": 10, "barang": 20, "omzet": 100000, "khusus": 2},
        "upgrade": [],
        "misi_status": "",
        "cerita_tamat": False,
        "energi": 94.36,
        "stok": {"mi_goreng": 5, "beras": 0, "gula": 3},
    }
    slot.update(overrides)
    return slot


@pytest.fixture()
def sample_slot():
    return make_slot()


@pytest.fixture()
def sample_package(sample_slot):
    """Paket cloud dengan 1 slot (string JSON indent TAB seperti game)."""
    return {
        "format": 1,
        "dari": "Android",
        "dibuat": "2026-11-24 10:39:21",
        "versi_game": "1.2",
        "slot": {"1": save_mod.serialize_slot(sample_slot)},
        "slot_terakhir": 1,
        "toko": {
            "tanpa_iklan": False,
            "pendukung": False,
            "kode_pendukung": "",
            "dukungan_iklan_dicek": False,
            "kode_iklan": "",
        },
        "lemari": [],
        "lemari_dipakai": "",
        "promo": [],
        "tutorial_selesai": True,
        "tip": [],
        "reset_rilis_dicek": False,
        "tester": False,
    }


@pytest.fixture()
def sample_p_data(sample_package):
    return save_mod.encode_package(sample_package)


@pytest.fixture()
def fernet_key():
    return Fernet.generate_key()


@pytest.fixture()
def store(tmp_path, fernet_key):
    s = Store(tmp_path / "test.db", fernet_key)
    yield s
    s.close()


@pytest.fixture()
def akun_json_valid():
    """akun.json valid: access token masih berlaku 1 jam."""
    import time

    return {
        "akses": "access-TOKEN-valid",
        "segar": "refresh-TOKEN-valid",
        "habis": int(time.time()) + 3600,
        "user_id": "acf8cc4f-9ae9-4d9e-8e2e-a90f7c8e159f",
        "email": "akunling427@gmail.com",
        "nama": "Akun Ling",
        "penyedia": "google",
        "versi": 8,
        "sidik": "",
        "kemajuan": {
            "level": 2, "hari": 120, "nama": "Warung Barokah",
            "uang": 4500000, "qris": 120000, "disimpan": "2026-11-24 10:39:21",
        },
        "disimpan": 0,
    }
