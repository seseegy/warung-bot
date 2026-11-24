"""Tes Penjaga Saldo (bot/core/auto.py::jaga_saldo + hook di siklus).

Penjaga Saldo (24 Nov 2026, atas perintah sir): bot tidak boleh pernah
minus dan tidak boleh pernah bangkrut — bila uang < Rp50.000, bot
menambah otomatis sampai Rp50.000. Uang ditambahkan dari ketiadaan
(BUKAN dari permainan), jadi tiap top-up harus tercatat di audit log.

Grounding rumus bangkrut (game_state.gd:6723-6738): tutup_hari potong
biaya harian, lalu bila uang < 0 hari_minus += 1 (kecuali
lindungi_hari_minus), bila tidak minus hari_minus = 0; bangkrut =
hari_minus >= BATAS_HARI_MINUS (casual 3, hard 1) atau diusir. Sim
bot meniru game persis (potong biaya walau uang habis) dan TIDAK diubah
— penjaga ini lapisan automasi, bukan perubahan sim.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.core import auto as auto_mod
from bot.core import jobs as jobs_mod


# -- jaga_saldo murni ---------------------------------------------------------

def test_jaga_saldo_minus_jadi_minimum():
    # Insiden 24 Nov 2026: -Rp30.000 -> tepat Rp50.000 (+Rp80.000).
    slot = {"uang": -30000, "hari": 11, "tingkat": 1}
    baru, tambah = auto_mod.jaga_saldo(slot)
    assert tambah == 80000
    assert baru["uang"] == 50000
    assert slot["uang"] == -30000  # slot awal tidak diubah


def test_jaga_saldo_nol_jadi_minimum():
    baru, tambah = auto_mod.jaga_saldo({"uang": 0})
    assert (baru["uang"], tambah) == (50000, 50000)


def test_jaga_saldo_di_bawah_minimum_ditambah_seluruh_kekurangan():
    baru, tambah = auto_mod.jaga_saldo({"uang": 20000})
    assert (baru["uang"], tambah) == (50000, 30000)


def test_jaga_saldo_tepat_minimum_tidak_berubah():
    slot = {"uang": 50000}
    baru, tambah = auto_mod.jaga_saldo(slot)
    assert (baru["uang"], tambah) == (50000, 0)
    assert baru == slot


def test_jaga_saldo_di_atas_minimum_tidak_berubah():
    slot = {"uang": 500000, "hari_minus": 2}
    baru, tambah = auto_mod.jaga_saldo(slot)
    assert (baru["uang"], tambah) == (500000, 0)
    # Tidak menyentuh apa pun bila tidak perlu — termasuk hari_minus.
    assert baru["hari_minus"] == 2


def test_jaga_saldo_minimum_kustom():
    baru, tambah = auto_mod.jaga_saldo({"uang": 60000}, minimum=100000)
    assert (baru["uang"], tambah) == (100000, 40000)


def test_jaga_saldo_reset_hari_minus_dan_bangkrut():
    slot = {"uang": -1000, "hari_minus": 2, "bangkrut": True, "diusir": False}
    baru, tambah = auto_mod.jaga_saldo(slot)
    assert tambah == 51000
    assert baru["uang"] == 50000
    assert baru["hari_minus"] == 0
    assert baru["bangkrut"] is False


def test_jaga_saldo_bangkrut_dibersihkan_bila_belum_diusir():
    # hari_minus 3 = ambang bangkrut casual, tapi belum diusir.
    slot = {"uang": -5000, "hari_minus": 3, "bangkrut": True, "diusir": False}
    baru, _ = auto_mod.jaga_saldo(slot)
    assert baru["hari_minus"] == 0
    assert baru["bangkrut"] is False


def test_jaga_saldo_tidak_menyentuh_jejak_minus_bila_diusir():
    # Sudah diusir: warung hilang, penjaga tidak bisa mengembalikannya —
    # uang tetap ditambah (tidak pernah minus), tapi jejak minus dibiarkan.
    slot = {"uang": -5000, "hari_minus": 3, "bangkrut": True, "diusir": True}
    baru, tambah = auto_mod.jaga_saldo(slot)
    assert (baru["uang"], tambah) == (50000, 55000)
    assert baru["hari_minus"] == 3
    assert baru["bangkrut"] is True
    assert baru["diusir"] is True


def test_jaga_saldo_slot_minimal_tidak_crash():
    # Field hari_minus/bangkrut tidak ada — tidak dibuat-buat.
    baru, tambah = auto_mod.jaga_saldo({"uang": -100})
    assert (baru["uang"], tambah) == (50000, 50100)
    assert "hari_minus" not in baru
    assert "bangkrut" not in baru


def test_jaga_saldo_tidak_menyentuh_field_lain():
    slot = {"uang": -1000, "stok": {"beras": 5}, "tingkat": 2,
            "total_pembeli": 123}
    baru, _ = auto_mod.jaga_saldo(slot)
    assert baru["stok"] == {"beras": 5}
    assert baru["tingkat"] == 2
    assert baru["total_pembeli"] == 123


# -- hook di jalankan_siklus ---------------------------------------------------

def test_siklus_awal_minus_diperbaiki_sebelum_sim(
        rich_slot, game_data, tugas_data):
    slot = copy.deepcopy(rich_slot)
    slot["uang"] = -30000
    hasil = auto_mod.jalankan_siklus(slot, game_data, tugas_data,
                                     tier=2, batas_harian=1_000_000,
                                     seed=12345)
    jaga = [a for a in hasil["aksi"] if a["aksi"] == "jaga_saldo"]
    assert jaga, "harus ada top-up Penjaga Saldo"
    # Top-up awal adalah aksi PERTAMA — sebelum harga/simulasi yang
    # membaca uang.
    assert hasil["aksi"][0]["aksi"] == "jaga_saldo"
    assert jaga[0]["jumlah"] == 80000
    assert jaga[0]["dari"] == -30000
    assert jaga[0]["ke"] == 50000
    assert hasil["slot"]["uang"] >= 50000
    assert hasil["uang_akhir"] >= 50000


def test_siklus_akhir_minus_diperbaiki_sebelum_upload(
        rich_slot, game_data, tugas_data):
    # Uang tepat Rp50.000, stok 0 (tidak ada penjualan), Lv2 (kipas
    # jadi blocker naik level, jadi tidak ada hadiah level): sim hanya
    # memotong biaya harian Rp10.000 -> uang 40.000 -> penjaga akhir
    # menambah Rp10.000. Angka dipatok dari BIAYA_HARIAN casual sim.
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 1
    slot["uang"] = 50000
    slot["stok"] = {k: 0 for k in slot["stok"]}
    hasil = auto_mod.jalankan_siklus(slot, game_data, tugas_data,
                                     tier=2, batas_harian=1_000_000,
                                     seed=12345)
    assert hasil["sim"] is not None
    assert hasil["sim"]["uang_akhir"] == 40000
    jaga = [a for a in hasil["aksi"] if a["aksi"] == "jaga_saldo"]
    assert len(jaga) == 1
    assert jaga[0]["jumlah"] == 10000
    assert jaga[0]["dari"] == 40000
    assert jaga[0]["ke"] == 50000
    assert hasil["slot"]["uang"] == 50000
    assert hasil["uang_akhir"] == 50000


def test_siklus_tidak_ada_topup_bila_uang_cukup(
        rich_slot, game_data, tugas_data):
    hasil = auto_mod.jalankan_siklus(rich_slot, game_data, tugas_data,
                                     tier=3, batas_harian=1_000_000,
                                     seed=12345)
    assert not any(a["aksi"] == "jaga_saldo" for a in hasil["aksi"])
    assert hasil["slot"]["uang"] >= 50000


# -- job siklus harian: audit + laporan ---------------------------------------

def _fake_app(store, tugas_data, game_data, bot_mock):
    return SimpleNamespace(
        bot_data={"store": store, "cloud": SimpleNamespace(),
                  "tugas": tugas_data, "data": game_data, "scheduler": None},
        bot=bot_mock,
    )


def _link_otomatis(store, tier=2):
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u", "versi": 1})
    store.set_tier(123, tier)
    store.set_otomatis(123, True)


async def test_job_siklus_harian_minus_diaudit_dan_dilaporkan(
        store, tugas_data, game_data, monkeypatch, rich_slot):
    _link_otomatis(store, tier=2)
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, game_data, bot_mock)
    slot = copy.deepcopy(rich_slot)
    slot["uang"] = -30000
    state = {"slot": slot,
             "ringkasan": {"nama": "W", "level": 1, "hari": 1,
                           "uang": -30000, "id_papan": "id-x"},
             "versi": 1, "paket": {"toko": {}, "lemari": []}}
    diunggah = {}

    async def _fetch(context, chat_id):
        return state

    async def _upload(context, chat_id, pending):
        diunggah.update(pending["slot_akhir"])
        return "Siklus otomatis diunggah (simpanan online v2).", "ok"

    monkeypatch.setattr("bot.tg.status.fetch_latest_state", _fetch)
    monkeypatch.setattr("bot.tg.confirm.execute_upload", _upload)
    await jobs_mod.jalankan_siklus_otomatis(app, 123)
    # Save yang di-upload tidak pernah minus.
    assert diunggah["uang"] >= 50000
    # Top-up tercatat di audit log dengan jumlahnya.
    audit = [e for e in store.get_audit(123, 0)
             if e["aksi"] == "jaga_saldo"]
    assert audit, "top-up harus dicatat di audit log"
    assert "+Rp80.000" in audit[0]["detail"]
    # Laporan siklus menyebut Penjaga Saldo.
    teks = bot_mock.send_message.await_args.kwargs["text"]
    assert "Penjaga Saldo" in teks
    assert "Rp80.000" in teks
