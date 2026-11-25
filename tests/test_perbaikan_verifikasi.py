"""Tes regresi perbaikan verifikasi seluruh bot (25 Nov 2026).

Setiap tes memaku satu bug yang ditemukan saat verifikasi baca kode
supaya tidak kambuh: bab hadiah, efek kios, catatan_hari, buka
barang level, pool saldo layanan, restock darurat Rp50.000, invarian
baca saja, delete_user mode_kerja, rollback versi, token konfirmasi,
eksklusi otomatisasi, dan parser jumlah.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.core import auto as auto_mod
from bot.core import sim as sim_mod
from bot.tg import handlers as handlers_tg
from bot.tg import tiers as tiers_tg
from bot.tg.confirm import build_pending_harga, execute_upload


def _slot_bab(rich_slot, bab, **kw):
    slot = copy.deepcopy(rich_slot)
    slot.update({
        "bab": bab, "misi_status": "aktif", "kiriman_bab": 0,
        "target_bab": 2000000, "cerita_tamat": False,
    })
    slot.update(kw)
    return slot


def test_bab_hadiah_menambah_uang_bukan_mengurangi(rich_slot, game_data):
    slot = _slot_bab(rich_slot, 7, uang=100000)
    slot_baru, aksi = auto_mod.bayar_misi(slot, game_data)
    assert aksi is not None and aksi["ok"]
    assert slot_baru["uang"] == 100000 + 2000000
    assert slot_baru["misi_status"] == "lunas"


def test_bab_kios_menerapkan_efek_kios(rich_slot, game_data):
    slot = _slot_bab(rich_slot, 9, target_bab=30000000, uang=40000000,
                     saldo_digital=5000000, tunggakan_sewa=2000000,
                     minggu_tunggak=2, sewa_cicil=300000)
    slot_baru, aksi = auto_mod.bayar_misi(slot, game_data)
    assert aksi is not None and aksi["ok"]
    assert slot_baru["kios_milik"] is True
    assert slot_baru["tunggakan_sewa"] == 0
    assert slot_baru["minggu_tunggak"] == 0
    assert slot_baru["sewa_cicil"] == 0
    # 40jt - 30jt misi - 2jt tunggakan + 300rb cicilan kembali.
    assert slot_baru["uang"] == 8300000


def test_catatan_hari_kosong_di_hari_baru(rich_slot, game_data):
    hasil = sim_mod.simulate(rich_slot, game_data, 1, seed=3)
    catatan = hasil["slot_akhir"]["catatan_hari"]
    assert catatan == {"omzet": 0, "laba": 0, "terjual": 0, "belanja": 0,
                       "dilayani": 0, "batal": 0, "hadiah": 0}


def test_buka_barang_level_tidak_terlambat(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["progres"] = {"pelanggan": 99999, "barang": 99999,
                       "omzet": 999999999, "khusus": 99999}
    slot["misi_status"] = ""
    assert sim_mod._cek_tugas(slot, game_data) is True
    assert int(slot["tingkat"]) == 1
    assert "kerupuk" in slot["barang_terbuka"]


def test_saldo_layanan_tidak_negatif(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["uang"] = 50000
    slot["saldo_layanan"] = 0
    slot["barang_terbuka"] = list(set(slot["barang_terbuka"])
                                 | {"pulsa_data_2gb", "pulsa_data_5gb"})
    hasil = sim_mod.simulate(slot, game_data, 3, seed=5)
    assert hasil["slot_akhir"]["saldo_layanan"] >= 0


def test_restock_darurat_saat_uang_50000_rak_kosong(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["uang"] = 50000
    slot["stok"] = {}
    slot_baru, aksi = auto_mod.auto_beli_stok(slot, game_data)
    assert any(a["aksi"] == "beli_stok" and a.get("ok") for a in aksi)
    assert sum(slot_baru["stok"].values()) > 0


@pytest.mark.asyncio
async def test_baca_saja_menahan_execute_upload(store):
    store.save_user(123, {"versi": 1})
    store.set_baca_saja(123, True)
    ctx = SimpleNamespace(bot_data={"store": store, "cloud": object(),
                                    "tugas": {}})
    teks, status = await execute_upload(
        ctx, 123, {"kind": "uang", "jumlah_baru": 1, "nomor_slot": 1})
    assert status == "gagal"
    assert "baca saja" in teks.lower()


def test_delete_user_menghapus_mode_kerja(store):
    store.save_user(123, {"versi": 1})
    store.set_mode_kerja(123)
    assert store.get_mode_kerja(123) is not None
    store.delete_user(123)
    assert store.get_mode_kerja(123) is None


def test_parse_jumlah_menolak_inf_nan():
    assert handlers_tg._parse_jumlah("inf") is None
    assert handlers_tg._parse_jumlah("nan") is None
    assert handlers_tg._parse_jumlah("5jt") == 5000000


def test_eksklusi_otomatisasi_memati_semua_mode_lain(store):
    store.save_user(123, {"versi": 1})
    store.set_mode_kerja(123)
    store.set_mode_target(123, 5)
    store.set_otomatis(123, True)
    tiers_tg._matikan_otomatisasi_lain(store, None, 123,
                                       "kejar", "tes")
    assert store.get_mode_kerja(123) is None
    assert store.get_mode_target(123) is None
    assert store.get_otomatis(123) is False


def test_teks_konfirmasi_harga_tidak_melewati_batas_telegram(rich_slot):
    hasil = [{"id": f"barang_{i}", "nama": f"Barang {i}",
              "harga_sekarang": 1000, "harga_terbaik": 2000,
              "laba_sekarang": 100, "laba_terbaik": 200}
             for i in range(37)]
    state = {"ringkasan": {"id_papan": "x"}, "versi": 1, "nomor_slot": 1}
    harga_baru = {e["id"]: 2000 for e in hasil}
    _pending, teks = build_pending_harga(state, harga_baru, hasil)
    assert len(teks) < 4096


@pytest.mark.asyncio
async def test_token_konfirmasi_lama_ditolak(store):
    query = SimpleNamespace(
        message=SimpleNamespace(chat_id=123),
        edit_message_text=AsyncMock(),
    )
    ctx = SimpleNamespace(
        bot_data={"store": store},
        user_data={"pending": {"kind": "uang", "token": "baru1234",
                               "dibuat": 9999999999}},
    )
    await handlers_tg._konfirm_callback(query, ctx, "konfirm:ya:uang:lama9999")
    teks = query.edit_message_text.call_args[0][0]
    assert "Tidak ada aksi tertunda" in teks
