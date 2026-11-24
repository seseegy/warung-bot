"""Tes Mode Kejar Papan (Fase 3+) — core, store, job, UI.

Tanpa panggilan Supabase live: fetch_latest_state + execute_upload +
fetch_papan di-monkeypatch/di-mock seperti tes Fase 3. Bot TIDAK
pernah mengirim skor — tidak ada kirim_skor5/kirim_adu_laris di sini.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.core import jobs as jobs_mod
from bot.core import kejar as kejar_mod
from bot.core.cloud import CloudError
from bot.tg import tiers as tiers_tg


def _papan_100():
    """Respons ambil_papan2 palsu: 100 baris, peringkat 1 = 24.900
    pembeli, peringkat 100 = 15.000 pembeli (turun 100 per peringkat)."""
    daftar = []
    for i in range(1, 101):
        daftar.append([f"Warung {i:03d}", 15000 + (100 - i) * 100,
                       f"kode{i:09d}", 5, 11, 1000000 + i, 10, False])
    return {"daftar": daftar, "jumlah_warung": 614095}


def _slot_misi(uang=500000, target=150000, kiriman=0):
    from tests.conftest import make_rich_slot

    return make_rich_slot(
        uang=uang, misi_status="aktif", target_bab=target,
        kiriman_bab=kiriman, total_pembeli=100,
        progres={"pelanggan": 15, "barang": 25,
                 "omzet": 100000, "khusus": 5})


# -- core murni ---------------------------------------------------------------

def test_target_pembeli_dari_papan():
    papan = _papan_100()
    assert kejar_mod.target_pembeli_dari_papan(papan, 100) == 15000
    assert kejar_mod.target_pembeli_dari_papan(papan, 50) == 20000
    assert kejar_mod.target_pembeli_dari_papan(papan, 25) == 22500
    assert kejar_mod.target_pembeli_dari_papan(papan, 1) == 24900
    assert kejar_mod.target_pembeli_dari_papan(papan, 101) is None
    assert kejar_mod.target_pembeli_dari_papan(papan, 0) is None
    assert kejar_mod.target_pembeli_dari_papan({}, 100) is None
    assert kejar_mod.target_pembeli_dari_papan(
        {"daftar": [["X", "bukan-angka", "k", 5, 1, 0, 0, False]]}, 1) is None


def test_alasan_berhenti():
    from tests.conftest import make_rich_slot

    slot = make_rich_slot(total_pembeli=100)
    assert kejar_mod.alasan_berhenti(slot, 15000, 0) is None
    # Target tercapai.
    slot = make_rich_slot(total_pembeli=15000)
    assert kejar_mod.alasan_berhenti(slot, 15000, 0) == "target_tercapai"
    # Uang minus: berhenti (pelajaran insiden -Rp30.000, 24 Nov 2026).
    slot = make_rich_slot(uang=-30000, total_pembeli=100)
    assert kejar_mod.alasan_berhenti(slot, 15000, 0) == "uang_minus"
    # Uang minus mengalahkan "macet" (uang <= 0 + rak kosong).
    slot = make_rich_slot(uang=-1, stok={}, total_pembeli=100)
    assert kejar_mod.alasan_berhenti(slot, 15000, 0) == "uang_minus"
    slot = make_rich_slot(diusir=True, total_pembeli=100)
    assert kejar_mod.alasan_berhenti(slot, 15000, 0) == "diusir"
    slot = make_rich_slot(uang=0, stok={}, total_pembeli=100)
    assert kejar_mod.alasan_berhenti(slot, 15000, 0) == "macet"
    slot = make_rich_slot(total_pembeli=100)
    assert kejar_mod.alasan_berhenti(slot, 15000, 300) == "maks_siklus"
    # Target belum diketahui (papan gagal dibaca) -> tidak bisa
    # dinyatakan tercapai, lanjut.
    slot = make_rich_slot(total_pembeli=999999)
    assert kejar_mod.alasan_berhenti(slot, None, 0) is None


def test_satu_siklus_kejar_naik_level_dan_tambah_pembeli(game_data,
                                                        tugas_data):
    # Tugas Lv1 lengkap + misi bisa dibayar -> naik ke Lv2 dalam 1 siklus,
    # dan total pembeli bertambah dari simulasi jualan.
    slot = _slot_misi()
    hasil = kejar_mod.satu_siklus_kejar(slot, game_data, tugas_data,
                                        tier=3, batas_harian=1000000,
                                        seed=12345)
    assert hasil["naik"] is True
    assert hasil["tingkat_awal"] == 0
    assert hasil["tingkat_akhir"] == 1
    assert any(a.get("aksi") == "bayar_misi" for a in hasil["aksi"])
    assert hasil["total_pembeli_awal"] == 100
    assert hasil["total_pembeli_akhir"] > 100
    assert slot["tingkat"] == 0  # slot awal tidak diubah
    assert slot["total_pembeli"] == 100


# -- store --------------------------------------------------------------------

def test_store_mode_kejar(store):
    assert store.get_mode_kejar(123) is None
    store.set_mode_kejar(123, 100, 15000)
    mode = store.get_mode_kejar(123)
    assert mode["target_peringkat"] == 100
    assert mode["target_pembeli"] == 15000
    assert mode["siklus"] == 0
    assert store.tambah_siklus_kejar(123) == 1
    assert store.tambah_siklus_kejar(123) == 2
    assert len(store.all_mode_kejar()) == 1
    store.hapus_mode_kejar(123)
    assert store.get_mode_kejar(123) is None
    assert store.all_mode_kejar() == []


def test_store_mode_kejar_hilang_saat_unlink(store):
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u", "versi": 1})
    store.set_mode_kejar(123, 100, 15000)
    store.delete_user(123)
    assert store.get_mode_kejar(123) is None


# -- job ----------------------------------------------------------------------

def _fake_app(store, tugas_data, game_data, bot_mock, papan=None):
    cloud = SimpleNamespace(fetch_papan=AsyncMock(return_value=papan))
    return SimpleNamespace(
        bot_data={"store": store, "cloud": cloud,
                  "tugas": tugas_data, "data": game_data, "scheduler": None},
        bot=bot_mock,
    )


def _link_kejar(store, tier=3, peringkat=100, target_pembeli=15000):
    store.save_user(123, {"akses": "x", "segar": "y", "habis": 9999999999,
                          "user_id": "u", "versi": 1})
    store.set_tier(123, tier)
    store.set_mode_kejar(123, peringkat, target_pembeli)


def test_atur_mode_kejar_job_5_menit():
    scheduler = jobs_mod.build_scheduler()
    app = SimpleNamespace(bot_data={})
    jobs_mod.atur_mode_kejar(scheduler, app, 123)
    job = scheduler.get_job(jobs_mod.kejar_job_id(123))
    assert job is not None
    from apscheduler.triggers.interval import IntervalTrigger

    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval.total_seconds() == 5 * 60
    jobs_mod.hapus_mode_kejar(scheduler, 123)
    assert scheduler.get_job(jobs_mod.kejar_job_id(123)) is None
    if scheduler.running:
        scheduler.shutdown(wait=False)


def test_muat_semua_mode_kejar(store):
    _link_kejar(store)
    scheduler = jobs_mod.build_scheduler()
    app = SimpleNamespace(bot_data={})
    jumlah = jobs_mod.muat_semua_mode_kejar(scheduler, app, store)
    assert jumlah == 1
    assert scheduler.get_job(jobs_mod.kejar_job_id(123)) is not None
    if scheduler.running:
        scheduler.shutdown(wait=False)


def test_sinkronkan_semua_mode_kejar(store):
    _link_kejar(store)
    scheduler = jobs_mod.build_scheduler()
    app = SimpleNamespace(bot_data={})
    try:
        hasil = jobs_mod.sinkronkan_semua(scheduler, app, store)
        assert hasil["kejar"] == 1
        assert scheduler.get_job(jobs_mod.kejar_job_id(123)) is not None
        # Sinkron ulang: sudah benar, tidak dihitung sebagai perubahan.
        hasil = jobs_mod.sinkronkan_semua(scheduler, app, store)
        assert hasil["kejar"] == 0
        store.hapus_mode_kejar(123)
        hasil = jobs_mod.sinkronkan_semua(scheduler, app, store)
        assert hasil["dihapus"] == 1
        assert scheduler.get_job(jobs_mod.kejar_job_id(123)) is None
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


async def test_job_mode_kejar_siklus_biasa_diam(
        store, tugas_data, game_data, monkeypatch, rich_slot):
    _link_kejar(store)
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, game_data, bot_mock,
                    papan=_papan_100())
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 1
    slot["upgrade"] = []
    slot["misi_status"] = ""
    slot["total_pembeli"] = 100
    slot["progres"] = {"pelanggan": 0, "barang": 0, "omzet": 0, "khusus": 0}
    state = {"slot": slot,
             "ringkasan": {"nama": "W", "level": 2, "hari": 1,
                           "uang": 500000, "id_papan": "id-x"},
             "versi": 1, "paket": {"toko": {}, "lemari": []}}

    async def _fetch(context, chat_id):
        return state

    async def _upload(context, chat_id, pending):
        assert pending["kind"] == "siklus"
        return "Mode Kejar diunggah (simpanan online v2).", "ok"

    monkeypatch.setattr("bot.tg.status.fetch_latest_state", _fetch)
    monkeypatch.setattr("bot.tg.confirm.execute_upload", _upload)
    await jobs_mod.jalankan_mode_kejar(app, 123)
    # Siklus biasa: tidak ada pesan, mode tetap nyala, siklus terhitung.
    bot_mock.send_message.assert_not_awaited()
    mode = store.get_mode_kejar(123)
    assert mode is not None and mode["siklus"] == 1


async def test_job_mode_kejar_berhenti_saat_target_tercapai(
        store, tugas_data, game_data, monkeypatch, rich_slot):
    _link_kejar(store, peringkat=100, target_pembeli=15000)
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, game_data, bot_mock,
                    papan=_papan_100())
    slot = copy.deepcopy(rich_slot)
    slot["total_pembeli"] = 16000  # sudah di atas batas peringkat 100
    state = {"slot": slot,
             "ringkasan": {"nama": "W", "level": 2, "hari": 1,
                           "uang": 500000, "id_papan": "id-x"},
             "versi": 1, "paket": {"toko": {}, "lemari": []}}

    async def _fetch(context, chat_id):
        return state

    monkeypatch.setattr("bot.tg.status.fetch_latest_state", _fetch)
    await jobs_mod.jalankan_mode_kejar(app, 123)
    assert store.get_mode_kejar(123) is None
    teks = bot_mock.send_message.await_args.kwargs["text"]
    assert "MASUK 100 BESAR" in teks
    assert "16000" in teks


async def test_job_mode_kejar_uang_minus_diperbaiki_penjaga_saldo(
        store, tugas_data, game_data, monkeypatch, rich_slot):
    """Penjaga Saldo (24 Nov 2026): save minus TIDAK lagi menghentikan
    mode sebelum siklus pertama — penjaga menambah ke Rp50.000, siklus
    jalan, mode tetap nyala. Alasan berhenti ``uang_minus`` tetap ada
    sebagai jaring pengaman, tapi tidak terpicu di sini."""
    _link_kejar(store)
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, game_data, bot_mock,
                    papan=_papan_100())
    slot = copy.deepcopy(rich_slot)
    slot["uang"] = -30000
    slot["total_pembeli"] = 100
    state = {"slot": slot,
             "ringkasan": {"nama": "W", "level": 2, "hari": 1,
                           "uang": -30000, "id_papan": "id-x"},
             "versi": 1, "paket": {"toko": {}, "lemari": []}}
    diunggah = {}

    async def _fetch(context, chat_id):
        return state

    async def _upload(context, chat_id, pending):
        diunggah.update(pending["slot_akhir"])
        return "Mode Kejar diunggah (simpanan online v2).", "ok"

    monkeypatch.setattr("bot.tg.status.fetch_latest_state", _fetch)
    monkeypatch.setattr("bot.tg.confirm.execute_upload", _upload)
    await jobs_mod.jalankan_mode_kejar(app, 123)
    # Mode tetap nyala, siklus terhitung, tidak ada pesan berhenti.
    mode = store.get_mode_kejar(123)
    assert mode is not None and mode["siklus"] == 1
    bot_mock.send_message.assert_not_awaited()
    # Save yang di-upload sudah diperbaiki penjaga.
    assert diunggah["uang"] >= 50000
    audit = [e for e in store.get_audit(123, 0)
             if e["aksi"] == "jaga_saldo"]
    assert audit, "top-up harus dicatat di audit log"
    assert "+Rp80.000" in audit[0]["detail"]


async def test_job_mode_kejar_upload_gagal_tidak_hitung_siklus(
        store, tugas_data, game_data, monkeypatch, rich_slot):
    """Siklus hanya dihitung bila upload sukses: bila upload gagal, hari
    sim dibuang dan siklus tidak bertambah (regresi hitungan siklus)."""
    _link_kejar(store)
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, game_data, bot_mock,
                    papan=_papan_100())
    slot = copy.deepcopy(rich_slot)
    slot["total_pembeli"] = 100
    state = {"slot": slot,
             "ringkasan": {"nama": "W", "level": 1, "hari": 1,
                           "uang": 500000, "id_papan": "id-x"},
             "versi": 1, "paket": {"toko": {}, "lemari": []}}

    async def _fetch(context, chat_id):
        return state

    async def _upload(context, chat_id, pending):
        return "gagal upload", "gagal"

    monkeypatch.setattr("bot.tg.status.fetch_latest_state", _fetch)
    monkeypatch.setattr("bot.tg.confirm.execute_upload", _upload)
    await jobs_mod.jalankan_mode_kejar(app, 123)
    mode = store.get_mode_kejar(123)
    assert mode is not None and mode["siklus"] == 0
    bot_mock.send_message.assert_not_awaited()


async def test_job_mode_kejar_bentrok_mematikan(
        store, tugas_data, game_data, monkeypatch, rich_slot):
    _link_kejar(store)
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, game_data, bot_mock,
                    papan=_papan_100())
    slot = copy.deepcopy(rich_slot)
    slot["total_pembeli"] = 100
    state = {"slot": slot,
             "ringkasan": {"nama": "W", "level": 1, "hari": 1,
                           "uang": 500000, "id_papan": "id-x"},
             "versi": 1, "paket": {"toko": {}, "lemari": []}}

    async def _fetch(context, chat_id):
        return state

    async def _upload(context, chat_id, pending):
        return "bentrok", "bentrok"

    monkeypatch.setattr("bot.tg.status.fetch_latest_state", _fetch)
    monkeypatch.setattr("bot.tg.confirm.execute_upload", _upload)
    await jobs_mod.jalankan_mode_kejar(app, 123)
    assert store.get_mode_kejar(123) is None
    teks = bot_mock.send_message.await_args.kwargs["text"]
    assert "berhenti" in teks.lower()


async def test_job_mode_kejar_papan_gagal_lewati_siklus(
        store, tugas_data, game_data, monkeypatch, rich_slot):
    _link_kejar(store)
    bot_mock = SimpleNamespace(send_message=AsyncMock())
    app = _fake_app(store, tugas_data, game_data, bot_mock,
                    papan=_papan_100())
    app.bot_data["cloud"].fetch_papan = AsyncMock(
        side_effect=CloudError("papan mati"))
    slot = copy.deepcopy(rich_slot)
    slot["total_pembeli"] = 100
    state = {"slot": slot,
             "ringkasan": {"nama": "W", "level": 1, "hari": 1,
                           "uang": 500000, "id_papan": "id-x"},
             "versi": 1, "paket": {"toko": {}, "lemari": []}}

    async def _fetch(context, chat_id):
        return state

    async def _upload(context, chat_id, pending):
        raise AssertionError("upload tidak boleh jalan bila papan gagal")

    monkeypatch.setattr("bot.tg.status.fetch_latest_state", _fetch)
    monkeypatch.setattr("bot.tg.confirm.execute_upload", _upload)
    await jobs_mod.jalankan_mode_kejar(app, 123)
    # Mode tetap nyala, siklus tidak terhitung, tidak ada pesan.
    mode = store.get_mode_kejar(123)
    assert mode is not None and mode["siklus"] == 0
    bot_mock.send_message.assert_not_awaited()


# -- UI -----------------------------------------------------------------------

def _fake_context(game_data, store=None, scheduler=None, cloud=None):
    return SimpleNamespace(
        bot_data={"data": game_data, "store": store,
                  "scheduler": scheduler, "application": None,
                  "cloud": cloud},
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


def _cloud_papan():
    return SimpleNamespace(fetch_papan=AsyncMock(
        return_value=_papan_100()))


async def test_kejar_pilih_butuh_profesional(game_data, store):
    _link(store, tier=1)
    query = _fake_query("kejar:pilih")
    assert await tiers_tg.on_callback_tier(
        None, _fake_context(game_data, store), query, "kejar:pilih") is True
    assert "Profesional" in query.edit_message_text.await_args.args[0]


async def test_kejar_pilih_menampilkan_peringkat(game_data, store):
    _link(store, tier=3)
    query = _fake_query("kejar:pilih")
    await tiers_tg.on_callback_tier(
        None, _fake_context(game_data, store), query, "kejar:pilih")
    markup = query.edit_message_text.await_args.kwargs["reply_markup"]
    data = [t.callback_data for baris in markup.inline_keyboard
            for t in baris]
    assert "kejar:konfirmasi:25" in data
    assert "kejar:konfirmasi:50" in data
    assert "kejar:konfirmasi:100" in data


async def test_kejar_konfirmasi_uang_minus_ditampilkan_penjaga_saldo(
        game_data, store, monkeypatch, rich_slot):
    """Penjaga Saldo (24 Nov 2026): konfirmasi TIDAK lagi menolak uang
    minus — pesan menyebut top-up yang akan ditambahkan siklus pertama,
    dan tombol mulai tetap ada."""
    _link(store, tier=3)
    slot = copy.deepcopy(rich_slot)
    slot["uang"] = -50000
    slot["total_pembeli"] = 100

    async def _fetch(context, chat_id):
        return {"slot": slot,
                "ringkasan": {"nama": "W", "level": 2, "hari": 1,
                              "uang": -50000, "id_papan": "id-x"},
                "versi": 1, "paket": {}}

    monkeypatch.setattr("bot.tg.tiers.fetch_latest_state", _fetch)
    query = _fake_query("kejar:konfirmasi:100")
    await tiers_tg.on_callback_tier(
        None, _fake_context(game_data, store, cloud=_cloud_papan()),
        query, "kejar:konfirmasi:100")
    teks = query.edit_message_text.await_args.args[0]
    assert "Penjaga Saldo" in teks
    assert "Rp100.000" in teks  # -50.000 -> 50.000 = +100.000
    markup = query.edit_message_text.await_args.kwargs["reply_markup"]
    data = [t.callback_data for baris in markup.inline_keyboard
            for t in baris]
    assert "kejar:mulai:100" in data


async def test_kejar_konfirmasi_tampilkan_batas(
        game_data, store, monkeypatch, rich_slot):
    _link(store, tier=3)
    slot = copy.deepcopy(rich_slot)
    slot["total_pembeli"] = 100

    async def _fetch(context, chat_id):
        return {"slot": slot,
                "ringkasan": {"nama": "W", "level": 2, "hari": 1,
                              "uang": 500000, "id_papan": "id-x"},
                "versi": 1, "paket": {}}

    monkeypatch.setattr("bot.tg.tiers.fetch_latest_state", _fetch)
    query = _fake_query("kejar:konfirmasi:100")
    await tiers_tg.on_callback_tier(
        None, _fake_context(game_data, store, cloud=_cloud_papan()),
        query, "kejar:konfirmasi:100")
    teks = query.edit_message_text.await_args.args[0]
    assert "15000" in teks  # batas peringkat 100 dari papan
    assert "14900" in teks  # kurang 14900 pembeli lagi
    markup = query.edit_message_text.await_args.kwargs["reply_markup"]
    data = [t.callback_data for baris in markup.inline_keyboard
            for t in baris]
    assert "kejar:mulai:100" in data


async def test_kejar_mulai_menyalakan(
        game_data, store, monkeypatch, rich_slot):
    _link(store, tier=3)
    store.set_otomatis(123, True)
    store.set_mode_target(123, 6)
    scheduler = jobs_mod.build_scheduler()
    try:
        slot = copy.deepcopy(rich_slot)
        slot["total_pembeli"] = 100

        async def _fetch(context, chat_id):
            return {"slot": slot,
                    "ringkasan": {"nama": "W", "level": 1, "hari": 1,
                                  "uang": 500000, "id_papan": "id-x"},
                    "versi": 1, "paket": {}}

        monkeypatch.setattr("bot.tg.tiers.fetch_latest_state", _fetch)
        query = _fake_query("kejar:mulai:100")
        ctx = _fake_context(game_data, store, scheduler=scheduler,
                            cloud=_cloud_papan())
        await tiers_tg.on_callback_tier(None, ctx, query, "kejar:mulai:100")
        assert "DINYALAKAN" in query.edit_message_text.await_args.args[0]
        mode = store.get_mode_kejar(123)
        assert mode is not None
        assert mode["target_peringkat"] == 100
        assert mode["target_pembeli"] == 15000
        assert scheduler.get_job(jobs_mod.kejar_job_id(123)) is not None
        # Satu otomatisasi saja: Mode Target + siklus harian dimatikan.
        assert store.get_mode_target(123) is None
        assert store.get_otomatis(123) is False
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


async def test_kejar_mulai_uang_minus_diperbaiki_penjaga_saldo(
        game_data, store, monkeypatch, rich_slot):
    """Penjaga Saldo (24 Nov 2026): mulai TIDAK lagi ditolak bila uang
    minus — mode menyala, pesan menyebut top-up siklus pertama, dan
    rencana top-up tercatat di audit."""
    _link(store, tier=3)
    scheduler = jobs_mod.build_scheduler()
    try:
        slot = copy.deepcopy(rich_slot)
        slot["uang"] = -30000
        slot["total_pembeli"] = 100

        async def _fetch(context, chat_id):
            return {"slot": slot,
                    "ringkasan": {"nama": "W", "level": 1, "hari": 1,
                                  "uang": -30000, "id_papan": "id-x"},
                    "versi": 1, "paket": {}}

        monkeypatch.setattr("bot.tg.tiers.fetch_latest_state", _fetch)
        query = _fake_query("kejar:mulai:100")
        ctx = _fake_context(game_data, store, scheduler=scheduler,
                            cloud=_cloud_papan())
        await tiers_tg.on_callback_tier(None, ctx, query, "kejar:mulai:100")
        teks = query.edit_message_text.await_args.args[0]
        assert "DINYALAKAN" in teks
        assert "Penjaga Saldo" in teks
        assert "Rp80.000" in teks  # -30.000 -> 50.000
        assert store.get_mode_kejar(123) is not None
        audit = [e for e in store.get_audit(123, 0)
                 if e["aksi"] == "jaga_saldo"]
        assert audit, "rencana top-up harus dicatat di audit"
        assert "+Rp80.000" in audit[0]["detail"]
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


async def test_kejar_berhenti(game_data, store):
    _link(store, tier=3)
    store.set_mode_kejar(123, 100, 15000)
    query = _fake_query("kejar:berhenti")
    await tiers_tg.on_callback_tier(
        None, _fake_context(game_data, store), query, "kejar:berhenti")
    assert "DIMATIKAN" in query.edit_message_text.await_args.args[0]
    assert store.get_mode_kejar(123) is None


async def test_otomatis_nyala_mematikan_mode_kejar(game_data, store):
    _link(store, tier=3)
    store.set_mode_kejar(123, 100, 15000)
    query = _fake_query("otomatis:nyala")
    await tiers_tg.on_callback_tier(
        None, _fake_context(game_data, store), query, "otomatis:nyala")
    assert store.get_mode_kejar(123) is None
    assert store.get_otomatis(123) is True


async def test_target_mulai_mematikan_mode_kejar(
        game_data, store, monkeypatch, rich_slot):
    _link(store, tier=3)
    store.set_mode_kejar(123, 100, 15000)
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
        assert store.get_mode_kejar(123) is None
        assert store.get_mode_target(123) is not None
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


async def test_on_callback_mengarahkan_kejar_ke_tiers(monkeypatch):
    """Regresi: tombol Kejar Papan harus diteruskan ke on_callback_tier
    (pola bug yang sama seperti "target:" pada 24 Nov 2026)."""
    from bot.tg import handlers as handlers_tg

    dipanggil = {}

    async def _palsu(update, context, query, data):
        dipanggil["data"] = data
        return True

    monkeypatch.setattr("bot.tg.handlers.tiers_tg.on_callback_tier", _palsu)
    query = SimpleNamespace(
        data="kejar:pilih",
        message=SimpleNamespace(chat_id=123),
        answer=AsyncMock(), edit_message_text=AsyncMock())
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(bot_data={}, user_data={})
    await handlers_tg.on_callback(update, context)
    assert dipanggil.get("data") == "kejar:pilih"
    # Tidak jatuh ke "Tombol tidak dikenal."
    query.edit_message_text.assert_not_awaited()
