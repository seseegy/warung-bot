"""Tes jobs.sinkronkan_semua (Fase 4) — perubahan pengaturan lewat API
(proses terpisah, hanya menulis DB) harus diterapkan bot polling tanpa restart.
"""

from __future__ import annotations

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from bot.core import jobs as jobs_mod


@pytest.fixture()
async def scheduler():
    s = AsyncIOScheduler()
    s.start()
    yield s
    s.shutdown(wait=False)


def _dummy(app):
    async def _kerja():
        return None
    return _kerja


@pytest.mark.asyncio
async def test_sinkronkan_tambah_job_baru(store, scheduler):
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u1", "email": "a@b.c"})
    store.set_jadwal(123, 7, aktif=True)
    store.set_otomatis(123, True)
    store.set_jam_otomatis(123, 9)

    app = object()
    hasil = jobs_mod.sinkronkan_semua(scheduler, app, store)
    assert hasil["laporan"] == 1
    assert hasil["otomatis"] == 1
    assert hasil["dihapus"] == 0
    assert scheduler.get_job(jobs_mod.job_id(123)) is not None
    assert scheduler.get_job(jobs_mod.siklus_job_id(123)) is not None
    job = scheduler.get_job(jobs_mod.job_id(123))
    assert isinstance(job.trigger, CronTrigger)
    assert str(job.trigger) and "7" in str(job.trigger)


@pytest.mark.asyncio
async def test_sinkronkan_idempotent_tidak_duplikat(store, scheduler):
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u1", "email": "a@b.c"})
    store.set_jadwal(123, 7, aktif=True)
    app = object()
    jobs_mod.sinkronkan_semua(scheduler, app, store)
    job_pertama = scheduler.get_job(jobs_mod.job_id(123))
    hasil = jobs_mod.sinkronkan_semua(scheduler, app, store)
    # Job yang sudah benar dibiarkan (tidak dihapus-dibuat ulang) supaya
    # tidak ada jadwal yang terlewat — sinkronisasi kedua tidak mengubah
    # apa-apa. (get_job mengembalikan objek Job baru tiap panggilan, jadi
    # yang dibandingkan adalah id + trigger, bukan identitas objek.)
    assert hasil["laporan"] == 0
    assert hasil["otomatis"] == 0
    assert hasil["dihapus"] == 0
    job_kedua = scheduler.get_job(jobs_mod.job_id(123))
    assert job_kedua is not None
    assert job_kedua.id == job_pertama.id
    assert jobs_mod._jam_trigger(job_kedua) == 7


@pytest.mark.asyncio
async def test_sinkronkan_perbarui_jam_dan_hapus_yang_tidak_aktif(
        store, scheduler):
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u1", "email": "a@b.c"})
    store.set_jadwal(123, 7, aktif=True)
    store.set_otomatis(123, True)
    app = object()
    jobs_mod.sinkronkan_semua(scheduler, app, store)

    # Ubah jam laporan + matikan otomatis lewat DB (seperti API).
    store.set_jadwal(123, 21, aktif=True)
    store.set_otomatis(123, False)
    hasil = jobs_mod.sinkronkan_semua(scheduler, app, store)
    assert hasil["laporan"] == 1  # diperbarui
    assert hasil["otomatis"] == 0
    assert hasil["dihapus"] == 1  # job otomatis dihapus
    assert scheduler.get_job(jobs_mod.siklus_job_id(123)) is None
    job = scheduler.get_job(jobs_mod.job_id(123))
    assert "21" in str(job.trigger)


@pytest.mark.asyncio
async def test_sinkronkan_hapus_job_pengguna_unlink(store, scheduler):
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u1", "email": "a@b.c"})
    store.set_jadwal(123, 7, aktif=True)
    app = object()
    jobs_mod.sinkronkan_semua(scheduler, app, store)
    assert scheduler.get_job(jobs_mod.job_id(123)) is not None

    store.delete_user(123)
    hasil = jobs_mod.sinkronkan_semua(scheduler, app, store)
    assert hasil["dihapus"] == 1
    assert scheduler.get_job(jobs_mod.job_id(123)) is None


@pytest.mark.asyncio
async def test_atur_sinkronisasi_daftarkan_job_interval(scheduler):
    app = object()
    jobs_mod.atur_sinkronisasi(scheduler, app)
    job = scheduler.get_job("sinkronisasi")
    assert job is not None
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval.seconds == 600
