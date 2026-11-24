"""Tes Mode Target Level (Fase 3+) — core, store, job, UI.

Tanpa panggilan Supabase live: fetch_latest_state + execute_upload
di-monkeypatch seperti tes Fase 3.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.core import jobs as jobs_mod
from bot.core import target as target_mod
from bot.tg import tiers as tiers_tg


def _slot_misi(uang=500000, target=150000, kiriman=0):
    from tests.conftest import make_rich_slot

    return make_rich_slot(
        uang=uang, misi_status="aktif", target_bab=target,
        kiriman_bab=kiriman, progres={"pelanggan": 15, "barang": 25,
                                      "omzet": 100000, "khusus": 5})


# -- core murni ---------------------------------------------------------------

def test_bayar_misi_bayar_bila_cukup(game_data):
    slot = _slot_misi()
    baru, aksi = target_mod.bayar_misi(slot, game_data)
    assert aksi == {"aksi": "bayar_misi", "ok": True, "jumlah": 150000}
    assert baru["uang"] == 350000
    assert baru["misi_status"] == "lunas"
    assert baru["kiriman_bab"] == 150000
    assert slot["uang"] == 500000  # slot awal tidak diubah


def test_bayar_misi_tidak_bayar_bila_kurang(game_data):
    slot = _slot_misi(uang=100000)
    baru, aksi = target_mod.bayar_misi(slot, game_data)
    assert aksi is None
    assert baru["uang"] == 100000
    assert baru["misi_status"] == "aktif"


def test_bayar_misi_diam_bila_tidak_aktif(game_data, rich_slot):
    _, aksi = target_mod.bayar_misi(rich_slot, game_data)
    assert aksi is None


def test_beli_upgrade_termurah(game_data, sample_slot):
    # sample_slot tingkat=1 (Lv2) syarat ['kipas']; tingkat 2 pilih
    # yang termurah dari ['spanduk' 830rb, 'bangku' 940rb].
    slot = copy.deepcopy(sample_slot)
    slot["tingkat"] = 2
    slot["uang"] = 4500000
    baru, aksi = target_mod.beli_upgrade_syarat(slot, game_data)
    assert aksi == {"aksi": "beli_upgrade", "ok": True, "id": "spanduk",
                    "jumlah": 830000}
    assert baru["uang"] == 4500000 - 830000
    assert "spanduk" in baru["upgrade"]


def test_beli_upgrade_tidak_beli_bila_sudah_punya(game_data, sample_slot):
    slot = copy.deepcopy(sample_slot)
    slot["upgrade"] = ["kipas"]
    _, aksi = target_mod.beli_upgrade_syarat(slot, game_data)
    assert aksi is None


def test_beli_upgrade_tidak_beli_bila_uang_pas(game_data, sample_slot):
    # Kipas 520rb; sisa 30rb < cadangan 50rb -> jangan beli.
    slot = copy.deepcopy(sample_slot)
    slot["uang"] = 550000
    _, aksi = target_mod.beli_upgrade_syarat(slot, game_data)
    assert aksi is None


def test_beli_upgrade_tidak_ada_syarat(game_data, rich_slot):
    _, aksi = target_mod.beli_upgrade_syarat(rich_slot, game_data)
    assert aksi is None


def test_harga_upgrade_tidak_dikenal(game_data):
    assert target_mod.harga_upgrade(game_data, "tidak_ada") == -1
    assert target_mod.syarat_upgrade(99, game_data) == []


def test_satu_siklus_target_naik_level(game_data, tugas_data):
    # Tugas Lv1 lengkap + misi bisa dibayar -> naik ke Lv2 dalam 1 siklus.
    slot = _slot_misi()
    hasil = target_mod.satu_siklus_target(slot, game_data, tugas_data,
                                          tier=3, batas_harian=1000000,
                                          seed=12345)
    assert hasil["naik"] is True
    assert hasil["tingkat_awal"] == 0
    assert hasil["tingkat_akhir"] == 1
    assert any(a.get("aksi") == "bayar_misi" for a in hasil["aksi"])
    assert slot["tingkat"] == 0  # slot awal tidak diubah


def test_alasan_berhenti(game_data):
    from tests.conftest import make_rich_slot

    slot = make_rich_slot()
    assert target_mod.alasan_berhenti(slot, 6, 0) is None
    slot["tingkat"] = 5
    assert target_mod.alasan_berhenti(slot, 6, 0) == "target_tercapai"
    slot = make_rich_slot(diusir=True)
    assert target_mod.alasan_berhenti(slot, 6, 0) == "diusir"
    slot = make_rich_slot(uang=0, stok={})
    assert target_mod.alasan_berhenti(slot, 6, 0) == "macet"
    slot = make_rich_slot()
    assert target_mod.alasan_berhenti(slot, 6, 300) == "maks_siklus"
    # Uang minus: berhenti (pelajaran insiden -Rp30.000, 24 Nov 2026) —
    # mengalahkan "macet" bila rak juga kosong.
    slot = make_rich_slot(uang=-30000)
    assert target_mod.alasan_berhenti(slot, 6, 0) == "uang_minus"
    slot = make_rich_slot(uang=-1, stok={})
    assert target_mod.alasan_berhenti(slot, 6, 0) == "uang_minus"


# -- store --------------------------------------------------------------------

def test_store_mode_target(store):
    assert store.get_mode_target(123) is None
    store.set_mode_target(123, 6)
    mode = store.get_mode_target(123)
    assert mode["target_tingkat"] == 6
    assert mode["siklus"] == 0
    assert store.tambah_siklus_target(123) == 1
    assert store.tambah_siklus_target(123) == 2
    assert len(store.all_mode_target()) == 1
    store.hapus_mode_target(123)
    assert store.get_mode_target(123) is None
    assert store.all_mode_target() == []


def test_store_mode_target_hilang_saat_unlink(store):
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u", "versi": 1})
    store.set_mode_target(123, 6)
    store.delete_user(123)
    assert store.get_mode_target(123) is None


# -- job ----------------------------------------------------------------------

def _fake_app(store, tugas_data, game_data, bot_mock):
    return SimpleNamespace(
        bot_data={"store": store, "cloud": SimpleNamespace(),
                  "tugas": tugas_data, "data": game_data, "scheduler": None},
        bot=bot_mock,
    )


def _link_target(store, tier=3, target=6):
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u", "versi": 1})
    store.set_tier(123, tier)
    store.set_mode_target(123, target)


def test_atur_mode_target_job_5_menit():
    scheduler = jobs_mod.build_scheduler()
    app = SimpleNamespace(bot_data={})
    jobs_mod.atur_mode_target(scheduler, app, 123)
    job = scheduler.get_job(jobs_mod.target_job_id(123))
    assert job is not None
    from apscheduler.triggers.interval import IntervalTrigger

    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval.total_seconds() == 5 * 60
    jobs_mod.hapus_mode_target(scheduler, 123)
    assert scheduler.get_job(jobs_mod.target_job_id(123)) is None
    if scheduler.running:
        scheduler.shutdown(wait=False)


def test_muat_semua_mode_target(store):
    _link_target(store)
    scheduler = jobs_mod.build_scheduler()
    app = SimpleNamespace(bot_data={})
    jumlah = jobs_mod.muat_semua_mode_target(scheduler, app, store)
    assert jumlah == 1
    assert scheduler.get_job(jobs_mod.target_job_id(123)) is not None
    if scheduler.running:
        scheduler.shutdown(wait=False)


async def test_job_mode_target_siklus_biasa_diam(
        store, tugas_data, game_data, monkeypatch, rich_slot):
    _link_target(store)
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, game_data, bot_mock)
    # Level 2 (tingkat=1) dengan syarat upgrade "kipas" yang BELUM dimiliki:
    # progres bisa penuh, tapi level TIDAK naik -> siklus biasa harus diam.
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 1
    slot["upgrade"] = []
    slot["misi_status"] = ""
    slot["progres"] = {"pelanggan": 0, "barang": 0, "omzet": 0, "khusus": 0}
    state = {"slot": slot,
             "ringkasan": {"nama": "W", "level": 2, "hari": 1,
                           "uang": 500000, "id_papan": "id-x"},
             "versi": 1, "paket": {"toko": {}, "lemari": []}}

    async def _fetch(context, chat_id):
        return state

    async def _upload(context, chat_id, pending):
        assert pending["kind"] == "siklus"
        return "Mode Target diunggah (simpanan online v2).", "ok"

    monkeypatch.setattr("bot.tg.status.fetch_latest_state", _fetch)
    monkeypatch.setattr("bot.tg.confirm.execute_upload", _upload)
    await jobs_mod.jalankan_mode_target(app, 123)
    # Siklus biasa: tidak ada pesan, mode tetap nyala, siklus terhitung.
    bot_mock.send_message.assert_not_awaited()
    mode = store.get_mode_target(123)
    assert mode is not None and mode["siklus"] == 1


async def test_job_mode_target_berhenti_saat_target_tercapai(
        store, tugas_data, game_data, monkeypatch, rich_slot):
    _link_target(store, target=6)
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, game_data, bot_mock)
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 5  # sudah Level 6
    state = {"slot": slot,
             "ringkasan": {"nama": "W", "level": 6, "hari": 1,
                           "uang": 500000, "id_papan": "id-x"},
             "versi": 1, "paket": {"toko": {}, "lemari": []}}

    async def _fetch(context, chat_id):
        return state

    monkeypatch.setattr("bot.tg.status.fetch_latest_state", _fetch)
    await jobs_mod.jalankan_mode_target(app, 123)
    assert store.get_mode_target(123) is None
    teks = bot_mock.send_message.await_args.kwargs["text"]
    assert "Target tercapai" in teks


async def test_job_mode_target_uang_minus_diperbaiki_penjaga_saldo(
        store, tugas_data, game_data, monkeypatch, rich_slot):
    """Penjaga Saldo (24 Nov 2026): save minus TIDAK lagi menghentikan
    Mode Target sebelum siklus pertama — penjaga menambah ke Rp50.000,
    siklus jalan, mode tetap nyala. Alasan berhenti ``uang_minus`` tetap
    ada sebagai jaring pengaman, tapi tidak terpicu di sini."""
    _link_target(store)
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, game_data, bot_mock)
    slot = copy.deepcopy(rich_slot)
    slot["uang"] = -30000
    slot["tingkat"] = 1
    slot["upgrade"] = []
    slot["misi_status"] = ""
    slot["progres"] = {"pelanggan": 0, "barang": 0, "omzet": 0, "khusus": 0}
    state = {"slot": slot,
             "ringkasan": {"nama": "W", "level": 2, "hari": 1,
                           "uang": -30000, "id_papan": "id-x"},
             "versi": 1, "paket": {"toko": {}, "lemari": []}}
    diunggah = {}

    async def _fetch(context, chat_id):
        return state

    async def _upload(context, chat_id, pending):
        diunggah.update(pending["slot_akhir"])
        return "Mode Target diunggah (simpanan online v2).", "ok"

    monkeypatch.setattr("bot.tg.status.fetch_latest_state", _fetch)
    monkeypatch.setattr("bot.tg.confirm.execute_upload", _upload)
    await jobs_mod.jalankan_mode_target(app, 123)
    # Mode tetap nyala, siklus terhitung, tidak ada pesan berhenti.
    mode = store.get_mode_target(123)
    assert mode is not None and mode["siklus"] == 1
    bot_mock.send_message.assert_not_awaited()
    # Save yang di-upload sudah diperbaiki penjaga.
    assert diunggah["uang"] >= 50000
    audit = [e for e in store.get_audit(123, 0)
             if e["aksi"] == "jaga_saldo"]
    assert audit, "top-up harus dicatat di audit log"
    assert "+Rp80.000" in audit[0]["detail"]


async def test_job_mode_target_bentrok_mematikan(
        store, tugas_data, game_data, monkeypatch, rich_slot):
    _link_target(store)
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, game_data, bot_mock)
    state = {"slot": copy.deepcopy(rich_slot),
             "ringkasan": {"nama": "W", "level": 1, "hari": 1,
                           "uang": 500000, "id_papan": "id-x"},
             "versi": 1, "paket": {"toko": {}, "lemari": []}}

    async def _fetch(context, chat_id):
        return state

    async def _upload(context, chat_id, pending):
        return "bentrok", "bentrok"

    monkeypatch.setattr("bot.tg.status.fetch_latest_state", _fetch)
    monkeypatch.setattr("bot.tg.confirm.execute_upload", _upload)
    await jobs_mod.jalankan_mode_target(app, 123)
    assert store.get_mode_target(123) is None
    teks = bot_mock.send_message.await_args.kwargs["text"]
    assert "berhenti" in teks.lower()


# -- UI -----------------------------------------------------------------------

def _fake_context(game_data, store=None, scheduler=None):
    return SimpleNamespace(
        bot_data={"data": game_data, "store": store,
                  "scheduler": scheduler, "application": None},
        application=None,
        user_data={},
    )


def _fake_query(data, chat_id=123):
    return SimpleNamespace(
        data=data,
        message=SimpleNamespace(chat_id=chat_id),
        edit_message_text=AsyncMock(),
        answer=AsyncMock(),
    )


def _link(store, tier=3):
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u", "versi": 1})
    store.set_tier(123, tier)


async def test_target_pilih_butuh_profesional(game_data, store):
    _link(store, tier=1)
    query = _fake_query("target:pilih")
    assert await tiers_tg.on_callback_tier(
        None, _fake_context(game_data, store), query, "target:pilih") is True
    assert "Profesional" in query.edit_message_text.await_args.args[0]


async def test_target_pilih_menampilkan_level(game_data, store):
    _link(store, tier=3)
    query = _fake_query("target:pilih")
    await tiers_tg.on_callback_tier(
        None, _fake_context(game_data, store), query, "target:pilih")
    markup = query.edit_message_text.await_args.kwargs["reply_markup"]
    data = [t.callback_data for baris in markup.inline_keyboard
            for t in baris]
    assert "target:konfirmasi:6" in data
    assert "target:konfirmasi:10" in data


async def test_target_konfirmasi_tolak_target_lewat(
        game_data, store, monkeypatch, rich_slot):
    _link(store, tier=3)

    async def _fetch(context, chat_id):
        return {"slot": rich_slot,
                "ringkasan": {"nama": "W", "level": 3, "hari": 1,
                              "uang": 500000, "id_papan": "id-x"},
                "versi": 1, "paket": {}}

    monkeypatch.setattr("bot.tg.tiers.fetch_latest_state", _fetch)
    query = _fake_query("target:konfirmasi:2")
    await tiers_tg.on_callback_tier(
        None, _fake_context(game_data, store), query, "target:konfirmasi:2")
    assert "Sudah Level 3" in query.edit_message_text.await_args.args[0]


async def test_target_mulai_menyalakan(
        game_data, store, monkeypatch, rich_slot):
    _link(store, tier=3)
    scheduler = jobs_mod.build_scheduler()
    try:
        async def _fetch(context, chat_id):
            return {"slot": rich_slot,
                    "ringkasan": {"nama": "W", "level": 1, "hari": 1,
                                  "uang": 500000, "id_papan": "id-x"},
                    "versi": 1, "paket": {}}

        monkeypatch.setattr("bot.tg.tiers.fetch_latest_state", _fetch)
        query = _fake_query("target:mulai:6")
        ctx = _fake_context(game_data, store, scheduler=scheduler)
        await tiers_tg.on_callback_tier(None, ctx, query, "target:mulai:6")
        assert "DINYALAKAN" in query.edit_message_text.await_args.args[0]
        mode = store.get_mode_target(123)
        assert mode is not None and mode["target_tingkat"] == 6
        assert scheduler.get_job(jobs_mod.target_job_id(123)) is not None
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


async def test_target_mulai_uang_minus_diperbaiki_penjaga_saldo(
        game_data, store, monkeypatch, rich_slot):
    """Penjaga Saldo (24 Nov 2026): mulai TIDAK ditolak bila uang minus
    — mode menyala, pesan menyebut top-up siklus pertama, dan rencana
    top-up tercatat di audit."""
    _link(store, tier=3)
    scheduler = jobs_mod.build_scheduler()
    try:
        slot = copy.deepcopy(rich_slot)
        slot["uang"] = -30000

        async def _fetch(context, chat_id):
            return {"slot": slot,
                    "ringkasan": {"nama": "W", "level": 1, "hari": 1,
                                  "uang": -30000, "id_papan": "id-x"},
                    "versi": 1, "paket": {}}

        monkeypatch.setattr("bot.tg.tiers.fetch_latest_state", _fetch)
        query = _fake_query("target:mulai:6")
        ctx = _fake_context(game_data, store, scheduler=scheduler)
        await tiers_tg.on_callback_tier(None, ctx, query, "target:mulai:6")
        teks = query.edit_message_text.await_args.args[0]
        assert "DINYALAKAN" in teks
        assert "Penjaga Saldo" in teks
        assert "Rp80.000" in teks  # -30.000 -> 50.000
        assert store.get_mode_target(123) is not None
        audit = [e for e in store.get_audit(123, 0)
                 if e["aksi"] == "jaga_saldo"]
        assert audit, "rencana top-up harus dicatat di audit"
        assert "+Rp80.000" in audit[0]["detail"]
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


async def test_target_konfirmasi_tampilkan_penjaga_saldo(
        game_data, store, monkeypatch, rich_slot):
    """Penjaga Saldo (24 Nov 2026): konfirmasi Mode Target menyebut
    top-up bila uang di bawah minimum."""
    _link(store, tier=3)
    slot = copy.deepcopy(rich_slot)
    slot["uang"] = -30000

    async def _fetch(context, chat_id):
        return {"slot": slot,
                "ringkasan": {"nama": "W", "level": 1, "hari": 1,
                              "uang": -30000, "id_papan": "id-x"},
                "versi": 1, "paket": {}}

    monkeypatch.setattr("bot.tg.tiers.fetch_latest_state", _fetch)
    query = _fake_query("target:konfirmasi:6")
    await tiers_tg.on_callback_tier(
        None, _fake_context(game_data, store), query, "target:konfirmasi:6")
    teks = query.edit_message_text.await_args.args[0]
    assert "Penjaga Saldo" in teks
    assert "Rp80.000" in teks
    markup = query.edit_message_text.await_args.kwargs["reply_markup"]
    data = [t.callback_data for baris in markup.inline_keyboard
            for t in baris]
    assert "target:mulai:6" in data


async def test_target_berhenti(game_data, store):
    _link(store, tier=3)
    store.set_mode_target(123, 6)
    query = _fake_query("target:berhenti")
    await tiers_tg.on_callback_tier(
        None, _fake_context(game_data, store), query, "target:berhenti")
    assert "DIMATIKAN" in query.edit_message_text.await_args.args[0]
    assert store.get_mode_target(123) is None


async def test_otomatis_nyala_mematikan_mode_target(game_data, store):
    _link(store, tier=3)
    store.set_mode_target(123, 6)
    query = _fake_query("otomatis:nyala")
    await tiers_tg.on_callback_tier(
        None, _fake_context(game_data, store), query, "otomatis:nyala")
    assert store.get_mode_target(123) is None
    assert store.get_otomatis(123) is True


async def test_on_callback_mengarahkan_target_ke_tiers(monkeypatch):
    """Regresi: tombol Mode Target sempat tidak dikenal karena handlers.py
    tidak meneruskan prefix "target:" ke on_callback_tier (24 Nov 2026)."""
    from bot.tg import handlers as handlers_tg

    dipanggil = {}

    async def _palsu(update, context, query, data):
        dipanggil["data"] = data
        return True

    monkeypatch.setattr("bot.tg.handlers.tiers_tg.on_callback_tier", _palsu)
    query = SimpleNamespace(
        data="target:pilih",
        message=SimpleNamespace(chat_id=123),
        answer=AsyncMock(), edit_message_text=AsyncMock())
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(bot_data={}, user_data={})
    await handlers_tg.on_callback(update, context)
    assert dipanggil.get("data") == "target:pilih"
    # Tidak jatuh ke "Tombol tidak dikenal."
    query.edit_message_text.assert_not_awaited()
