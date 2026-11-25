"""Tes Fase 3 — job siklus otomatis harian (bot/core/jobs.py).

fetch_latest_state + execute_upload di-monkeypatch (tanpa Supabase live).
"""

from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.core import jobs as jobs_mod
from bot.core.cloud import SessionExpired
from bot.tg.confirm import execute_upload


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


def _tutup(scheduler):
    if scheduler.running:
        scheduler.shutdown(wait=False)


# -- atur/hapus/muat siklus ---------------------------------------------------

def test_atur_siklus_membuat_job():
    scheduler = jobs_mod.build_scheduler()
    app = SimpleNamespace(bot_data={})
    jobs_mod.atur_siklus(scheduler, app, 123, 7)
    job = scheduler.get_job(jobs_mod.siklus_job_id(123))
    assert job is not None
    jam = next(f for f in job.trigger.fields if f.name == "hour")
    assert str(jam) == "7"
    _tutup(scheduler)


def test_atur_siklus_jam_tidak_valid_ditolak():
    scheduler = jobs_mod.build_scheduler()
    with pytest.raises(ValueError):
        jobs_mod.atur_siklus(scheduler, SimpleNamespace(bot_data={}), 123, 24)
    _tutup(scheduler)


def test_atur_siklus_ganda_hanya_satu_job():
    scheduler = jobs_mod.build_scheduler()
    app = SimpleNamespace(bot_data={})
    jobs_mod.atur_siklus(scheduler, app, 123, 7)
    jobs_mod.atur_siklus(scheduler, app, 123, 20)
    assert len(scheduler.get_jobs()) == 1
    job = scheduler.get_job(jobs_mod.siklus_job_id(123))
    jam = next(f for f in job.trigger.fields if f.name == "hour")
    assert str(jam) == "20"
    _tutup(scheduler)


def test_hapus_siklus(store):
    scheduler = jobs_mod.build_scheduler()
    app = SimpleNamespace(bot_data={})
    jobs_mod.atur_siklus(scheduler, app, 123, 7)
    jobs_mod.hapus_siklus(scheduler, 123)
    assert scheduler.get_job(jobs_mod.siklus_job_id(123)) is None
    _tutup(scheduler)


def test_muat_semua_otomatis(store):
    _link_otomatis(store, tier=2)
    store.save_user(456, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u2", "versi": 1})
    store.set_otomatis(456, False)
    scheduler = jobs_mod.build_scheduler()
    app = SimpleNamespace(bot_data={})
    jumlah = jobs_mod.muat_semua_otomatis(scheduler, app, store)
    assert jumlah == 1
    assert scheduler.get_job(jobs_mod.siklus_job_id(123)) is not None
    assert scheduler.get_job(jobs_mod.siklus_job_id(456)) is None
    _tutup(scheduler)


# -- pengingat login ----------------------------------------------------------

async def test_pengingatan_login_dikirim_bila_belum_klaim(store):
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, {}, None, bot_mock)
    await jobs_mod._kirim_pengingatan_login(app, 123, {"toko": {}, "lemari": []})
    bot_mock.send_message.assert_awaited_once()
    kwargs = bot_mock.send_message.await_args.kwargs
    assert "hari ke-1" in kwargs["text"]
    assert "Rp15.000" in kwargs["text"]
    markup = kwargs["reply_markup"]
    data = [t.callback_data for baris in markup.inline_keyboard
            for t in baris]
    assert "login:klaim:1" in data
    assert "login:lewat" in data


async def test_pengingatan_login_diam_bila_sudah_klaim(store):
    from bot.core import auto as auto_mod

    store.set_login_lacak(123, 1, auto_mod.tanggal_wib())
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, {}, None, bot_mock)
    await jobs_mod._kirim_pengingatan_login(app, 123, {"toko": {}, "lemari": []})
    bot_mock.send_message.assert_not_awaited()


# -- siklus -------------------------------------------------------------------

async def test_siklus_berhasil_mengunggah_dan_melapor(
        store, tugas_data, game_data, monkeypatch, rich_slot):
    _link_otomatis(store, tier=2)
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, game_data, bot_mock)
    slot = copy.deepcopy(rich_slot)
    slot["stok"]["beras"] = 1
    state = {"slot": slot,
             "ringkasan": {"nama": "W", "level": 1, "hari": 1,
                           "uang": 500000, "id_papan": "id-x"},
             "versi": 1,
             "paket": {"toko": {}, "lemari": []}}

    async def _fetch(context, chat_id):
        return state

    async def _upload(context, chat_id, pending):
        assert pending["kind"] == "siklus"
        assert pending["versi_dasar"] == 1
        return "Siklus otomatis diunggah (simpanan online v2).", "ok"

    monkeypatch.setattr("bot.tg.status.fetch_latest_state", _fetch)
    monkeypatch.setattr("bot.tg.confirm.execute_upload", _upload)
    await jobs_mod.jalankan_siklus_otomatis(app, 123)
    # Laporan terkirim (pengingat login + laporan siklus).
    assert bot_mock.send_message.await_count >= 1
    teks = bot_mock.send_message.await_args.kwargs["text"]
    assert "Siklus otomatis selesai" in teks
    assert "Simulasi 1 hari" in teks
    assert "Cuan hari ini" in teks
    # Audit tercatat, otomatisasi tetap nyala.
    assert store.get_otomatis(123) is True
    assert any(e["aksi"] == "simulasi" for e in store.get_audit(123, 0))


async def test_siklus_bentrok_mematikan_otomatisasi(
        store, tugas_data, game_data, monkeypatch, rich_slot):
    _link_otomatis(store, tier=2)
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, game_data, bot_mock)
    state = {"slot": rich_slot,
             "ringkasan": {"nama": "W", "level": 1, "hari": 1,
                           "uang": 500000, "id_papan": "id-x"},
             "versi": 1,
             "paket": {"toko": {}, "lemari": []}}

    async def _fetch(context, chat_id):
        return state

    async def _upload(context, chat_id, pending):
        return "bentrok", "bentrok"

    monkeypatch.setattr("bot.tg.status.fetch_latest_state", _fetch)
    monkeypatch.setattr("bot.tg.confirm.execute_upload", _upload)
    await jobs_mod.jalankan_siklus_otomatis(app, 123)
    assert store.get_otomatis(123) is False
    teks = bot_mock.send_message.await_args.kwargs["text"]
    assert "BERHENTI" in teks


async def test_siklus_sesi_habis_mematikan_otomatisasi(
        store, tugas_data, game_data, monkeypatch):
    _link_otomatis(store, tier=2)
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, game_data, bot_mock)

    async def _fetch(context, chat_id):
        raise SessionExpired("sesi habis")

    monkeypatch.setattr("bot.tg.status.fetch_latest_state", _fetch)
    await jobs_mod.jalankan_siklus_otomatis(app, 123)
    assert store.get_otomatis(123) is False
    teks = bot_mock.send_message.await_args.kwargs["text"]
    assert "Sesi login habis" in teks


async def test_siklus_tanpa_akun_diam(store, tugas_data, game_data):
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, game_data, bot_mock)
    await jobs_mod.jalankan_siklus_otomatis(app, 123)
    bot_mock.send_message.assert_not_awaited()


async def test_siklus_otomatis_mati_diam(store, tugas_data, game_data):
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u", "versi": 1})
    store.set_otomatis(123, False)
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, game_data, bot_mock)
    await jobs_mod.jalankan_siklus_otomatis(app, 123)
    bot_mock.send_message.assert_not_awaited()


# -- guard versi di execute_upload (kind siklus) ------------------------------

async def test_execute_upload_siklus_tolak_bila_cloud_berubah(
        store, monkeypatch, rich_slot):
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u", "versi": 1})
    state_baru = {"slot": rich_slot,
                  "ringkasan": {"nama": "W", "level": 1, "hari": 1,
                                "uang": 500000, "id_papan": "id-x"},
                  "versi": 2,
                  "paket": {}}

    async def _fetch(context, chat_id):
        return state_baru

    monkeypatch.setattr("bot.tg.confirm.fetch_latest_state", _fetch)
    ctx = SimpleNamespace(bot_data={"store": store,
                                    "cloud": SimpleNamespace(),
                                    "tugas": {}})
    pending = {"kind": "siklus", "id_papan": "id-x", "p_data": None,
               "versi_dasar": 1, "slot_akhir": rich_slot,
               "ringkasan": "Siklus otomatis harian diterapkan"}
    teks, status = await execute_upload(ctx, 123, pending)
    assert status == "gagal"
    assert "berubah" in teks


async def test_execute_upload_siklus_ok_bila_versi_sama(
        store, monkeypatch, rich_slot, sample_package):
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u", "versi": 1})
    state = {"slot": rich_slot,
             "ringkasan": {"nama": "W", "level": 1, "hari": 1,
                           "uang": 500000, "id_papan": "id-x"},
             "versi": 1,
             "nomor_slot": 1,
             "p_data": "paket-lama",
             "session": {"akses": "x"},
             "paket": sample_package}

    async def _fetch(context, chat_id):
        return state

    class _Cloud:
        async def upload_cloud(self, session, p_data, versi_dasar,
                               id_papan, paksa=False):
            return {"versi": 2}, session

    monkeypatch.setattr("bot.tg.confirm.fetch_latest_state", _fetch)
    ctx = SimpleNamespace(bot_data={"store": store, "cloud": _Cloud(),
                                    "tugas": {}})
    pending = {"kind": "siklus", "id_papan": "id-x", "p_data": None,
               "versi_dasar": 1, "slot_akhir": rich_slot,
               "ringkasan": "Siklus otomatis harian diterapkan"}
    teks, status = await execute_upload(ctx, 123, pending)
    assert status == "ok"
    assert "Siklus otomatis harian diterapkan" in teks
