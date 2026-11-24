"""Tes Fase 2 — jadwal laporan harian (bot/core/jobs.py + Store.jadwal)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.core import jobs as jobs_mod


# -- Store.jadwal ---------------------------------------------------------------

def test_jadwal_simpan_baca(store):
    assert store.get_jadwal(123) is None
    store.set_jadwal(123, 7)
    assert store.get_jadwal(123) == {"chat_id": 123, "jam": 7, "aktif": True}


def test_jadwal_ubah_jam(store):
    store.set_jadwal(123, 7)
    store.set_jadwal(123, 20)
    assert store.get_jadwal(123)["jam"] == 20
    assert store.get_jadwal(123)["aktif"] is True


def test_jadwal_jam_di_luar_0_23_ditolak(store):
    with pytest.raises(ValueError):
        store.set_jadwal(123, 24)
    with pytest.raises(ValueError):
        store.set_jadwal(123, -1)


def test_jadwal_nonaktif_dan_hapus(store):
    store.set_jadwal(123, 7, aktif=False)
    assert store.get_jadwal(123)["aktif"] is False
    store.delete_jadwal(123)
    assert store.get_jadwal(123) is None


def test_jadwal_per_chat_terpisah(store):
    store.set_jadwal(111, 7)
    store.set_jadwal(222, 20)
    assert store.get_jadwal(111)["jam"] == 7
    assert store.get_jadwal(222)["jam"] == 20
    assert len(store.all_jadwal()) == 2


def test_jadwal_ikut_terhapus_saat_unlink(store, fernet_key):
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u", "versi": 1})
    store.set_jadwal(123, 7)
    store.delete_user(123)
    assert store.get_jadwal(123) is None


# -- scheduler --------------------------------------------------------------------

def _tutup(scheduler):
    """Shutdown hanya bila jalan (APScheduler 3.11 melempar
    SchedulerNotRunningError bila shutdown saat berhenti)."""
    if scheduler.running:
        scheduler.shutdown(wait=False)


def test_atur_laporan_membuat_job():
    scheduler = jobs_mod.build_scheduler()
    app = SimpleNamespace(bot_data={})
    jobs_mod.atur_laporan(scheduler, app, 123, 7)
    job = scheduler.get_job(jobs_mod.job_id(123))
    assert job is not None
    jam = next(f for f in job.trigger.fields if f.name == "hour")
    assert str(jam) == "7"
    _tutup(scheduler)


def test_atur_laporan_jam_tidak_valid_ditolak():
    scheduler = jobs_mod.build_scheduler()
    app = SimpleNamespace(bot_data={})
    with pytest.raises(ValueError):
        jobs_mod.atur_laporan(scheduler, app, 123, 25)
    assert scheduler.get_job(jobs_mod.job_id(123)) is None
    _tutup(scheduler)


def test_atur_laporan_mengganti_jam_lama():
    scheduler = jobs_mod.build_scheduler()
    app = SimpleNamespace(bot_data={})
    jobs_mod.atur_laporan(scheduler, app, 123, 7)
    jobs_mod.atur_laporan(scheduler, app, 123, 20)
    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    jam = next(f for f in jobs[0].trigger.fields if f.name == "hour")
    assert str(jam) == "20"
    _tutup(scheduler)


def test_hapus_laporan():
    scheduler = jobs_mod.build_scheduler()
    app = SimpleNamespace(bot_data={})
    jobs_mod.atur_laporan(scheduler, app, 123, 7)
    jobs_mod.hapus_laporan(scheduler, 123)
    assert scheduler.get_job(jobs_mod.job_id(123)) is None
    jobs_mod.hapus_laporan(scheduler, 999)  # tidak ada -> tidak crash
    _tutup(scheduler)


def test_muat_semua_jadwal_melewati_yang_nonaktif(store):
    scheduler = jobs_mod.build_scheduler()
    app = SimpleNamespace(bot_data={})
    store.set_jadwal(111, 7, aktif=True)
    store.set_jadwal(222, 8, aktif=False)
    jumlah = jobs_mod.muat_semua_jadwal(scheduler, app, store)
    assert jumlah == 1
    assert scheduler.get_job(jobs_mod.job_id(111)) is not None
    assert scheduler.get_job(jobs_mod.job_id(222)) is None
    _tutup(scheduler)


# -- kirim_laporan_harian -----------------------------------------------------------

def _fake_app(store, tugas_data, bot_mock):
    return SimpleNamespace(
        bot_data={"store": store, "cloud": SimpleNamespace(),
                  "tugas": tugas_data, "scheduler": None},
        bot=bot_mock,
    )


def test_laporan_harian_mengirim_ringkasan(store, tugas_data, monkeypatch,
                                          sample_slot):
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, bot_mock)
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u", "versi": 1})
    state = {"slot": sample_slot,
             "ringkasan": {"uang": 100000, "qris": 5000, "level": 2,
                           "hari": 120, "id_papan": "x"},
             "versi": 1}

    async def _fetch(ctx, chat_id):
        return state

    monkeypatch.setattr("bot.tg.status.fetch_latest_state", _fetch)
    asyncio.run(jobs_mod.kirim_laporan_harian(app, 123))
    bot_mock.send_message.assert_awaited_once()
    teks = bot_mock.send_message.await_args.kwargs["text"]
    assert "Rp100.000" in teks
    assert "Level 2" in teks
    assert bot_mock.send_message.await_args.kwargs["chat_id"] == 123


def test_laporan_harian_tanpa_akun_tidak_mengirim(store, tugas_data):
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, bot_mock)
    asyncio.run(jobs_mod.kirim_laporan_harian(app, 123))
    bot_mock.send_message.assert_not_awaited()
