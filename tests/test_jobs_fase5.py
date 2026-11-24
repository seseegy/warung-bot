"""Tes Fase 5 — job pemantauan global (bot/core/jobs.py).

Tidak ada panggilan live: fetch_latest_state + fetch_versi_json +
cloud.fetch_papan di-monkeypatch. Menguji: 4 job terdaftar, notifikasi
pasar (snapshot pertama diam, perubahan dikabari, tanpa perubahan
diam), cek versi (sekali per kode baru), backup harian (satu arsip
per hari), pengingat adu laris (sekali per minggu, tier Profesional).
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.core import jobs as jobs_mod
from bot.core import monitor as monitor_mod
from bot.core import papan as papan_mod
from bot.tg import status as status_mod


def _fake_app(store, game_data, tugas_data, cloud=None):
    return SimpleNamespace(
        bot_data={"store": store, "cloud": cloud, "data": game_data,
                  "tugas": tugas_data},
        bot=SimpleNamespace(send_message=AsyncMock()),
    )


def _fake_state(slot, p_data="p_data-contoh", versi=8):
    return {
        "versi": versi,
        "p_data": p_data,
        "paket": {"slot": {"1": "{}"}},
        "nomor_slot": 1,
        "slot": slot,
        "ringkasan": {"id_papan": "3a5dd8081fa92f174078ce3ca639fa07",
                      "nama_warung": "Warung Barokah", "level": 2,
                      "hari": 120, "uang": 4500000, "qris": 120000,
                      "disimpan": "2026-11-24 10:39:21"},
        "session": {},
    }


def _mock_fetch(monkeypatch, state):
    async def _fetch(context, chat_id, nomor_slot=None):
        return copy.deepcopy(state)
    monkeypatch.setattr(status_mod, "fetch_latest_state", _fetch)


def test_atur_pemantauan_mendaftarkan_empat_job(store, game_data, tugas_data):
    app = _fake_app(store, game_data, tugas_data)
    scheduler = jobs_mod.build_scheduler()
    jobs_mod.atur_pemantauan(scheduler, app)
    assert scheduler.get_job("pasar_senin") is not None
    assert scheduler.get_job("cek_versi") is not None
    assert scheduler.get_job("backup_harian") is not None
    assert scheduler.get_job("adu_laris_jumat") is not None
    # Idempotent: panggil lagi, tidak ada duplikat.
    jobs_mod.atur_pemantauan(scheduler, app)
    assert len(scheduler.get_jobs()) == 4


async def test_notifikasi_pasar_snapshot_pertama_diam(
        monkeypatch, rich_slot, game_data, tugas_data, store,
        akun_json_valid):
    store.save_user(123, akun_json_valid)
    slot = copy.deepcopy(rich_slot)
    slot["harga_pasaran"] = {}
    _mock_fetch(monkeypatch, _fake_state(slot))
    app = _fake_app(store, game_data, tugas_data)
    await jobs_mod.notifikasi_pasar_senin(app)
    app.bot.send_message.assert_not_called()
    assert store.meta_get(123, "pasaran") == "{}"


async def test_notifikasi_pasar_perubahan_dikabari(
        monkeypatch, rich_slot, game_data, tugas_data, store,
        akun_json_valid):
    store.save_user(123, akun_json_valid)
    slot = copy.deepcopy(rich_slot)
    slot["harga_pasaran"] = {}
    state = _fake_state(slot)
    _mock_fetch(monkeypatch, state)
    app = _fake_app(store, game_data, tugas_data)
    await jobs_mod.notifikasi_pasar_senin(app)  # snapshot awal
    app.bot.send_message.assert_not_called()
    # Minggu berikutnya pasaran berubah.
    slot["harga_pasaran"] = {"mi_goreng": 1.15}
    await jobs_mod.notifikasi_pasar_senin(app)
    assert app.bot.send_message.call_count == 1
    teks = app.bot.send_message.call_args[1]["text"]
    assert "Harga pasar minggu ini berubah" in teks
    assert "Mie goreng" in teks
    # Tanpa perubahan lagi: diam.
    await jobs_mod.notifikasi_pasar_senin(app)
    assert app.bot.send_message.call_count == 1


async def test_notifikasi_pasar_tanpa_perubahan_diam(
        monkeypatch, rich_slot, game_data, tugas_data, store,
        akun_json_valid):
    store.save_user(123, akun_json_valid)
    slot = copy.deepcopy(rich_slot)
    slot["harga_pasaran"] = {"mi_goreng": 1.15}
    _mock_fetch(monkeypatch, _fake_state(slot))
    app = _fake_app(store, game_data, tugas_data)
    await jobs_mod.notifikasi_pasar_senin(app)
    await jobs_mod.notifikasi_pasar_senin(app)
    app.bot.send_message.assert_not_called()


async def test_cek_versi_update_dikabari_sekali(
        monkeypatch, store, game_data, tugas_data, akun_json_valid):
    store.save_user(123, akun_json_valid)

    async def _fetch(client=None):
        return {"kode_terbaru": 50, "versi_terbaru": "1.3"}
    monkeypatch.setattr(monitor_mod, "fetch_versi_json", _fetch)
    app = _fake_app(store, game_data, tugas_data)
    await jobs_mod.cek_versi_game_job(app)
    assert app.bot.send_message.call_count == 1
    assert "1.3" in app.bot.send_message.call_args[1]["text"]
    assert store.meta_get(123, "versi_diberitahu") == "50"
    await jobs_mod.cek_versi_game_job(app)
    assert app.bot.send_message.call_count == 1  # tidak duplikat


async def test_cek_versi_tidak_ada_update_diam(
        monkeypatch, store, game_data, tugas_data, akun_json_valid):
    store.save_user(123, akun_json_valid)

    async def _fetch(client=None):
        return {"kode_terbaru": 47, "versi_terbaru": "1.1"}
    monkeypatch.setattr(monitor_mod, "fetch_versi_json", _fetch)
    app = _fake_app(store, game_data, tugas_data)
    await jobs_mod.cek_versi_game_job(app)
    app.bot.send_message.assert_not_called()


async def test_cek_versi_gagal_fetch_diam(
        monkeypatch, store, game_data, tugas_data, akun_json_valid):
    store.save_user(123, akun_json_valid)

    async def _fetch(client=None):
        raise monitor_mod.VersionCheckError("putus")
    monkeypatch.setattr(monitor_mod, "fetch_versi_json", _fetch)
    app = _fake_app(store, game_data, tugas_data)
    await jobs_mod.cek_versi_game_job(app)  # tidak crash, tidak kirim
    app.bot.send_message.assert_not_called()


async def test_backup_harian_satu_arsip_per_hari(
        monkeypatch, rich_slot, game_data, tugas_data, store,
        akun_json_valid, sample_p_data):
    store.save_user(123, akun_json_valid)
    _mock_fetch(monkeypatch, _fake_state(copy.deepcopy(rich_slot),
                                        p_data=sample_p_data, versi=8))
    app = _fake_app(store, game_data, tugas_data)
    await jobs_mod.backup_harian_job(app)
    await jobs_mod.backup_harian_job(app)
    from bot.core import backup as backup_mod
    assert len(backup_mod.daftar_arsip(store, 123)) == 1


async def test_pengingat_adu_laris_sekali_seminggu(
        monkeypatch, rich_slot, game_data, tugas_data, store,
        akun_json_valid):
    store.save_user(123, akun_json_valid)
    store.set_tier(123, 3)
    id_papan = "3a5dd8081fa92f174078ce3ca639fa07"
    slot = copy.deepcopy(rich_slot)
    slot["total_pembeli"] = 500
    _mock_fetch(monkeypatch, _fake_state(slot))
    kode = papan_mod.kode_papan(id_papan)
    cloud = SimpleNamespace(
        fetch_papan=AsyncMock(return_value={
            "daftar": [["Warung Barokah", 500, kode, 5, 2, 100000, 0]],
            "jumlah_warung": 1}))
    app = _fake_app(store, game_data, tugas_data, cloud=cloud)
    await jobs_mod.pengingat_adu_laris_job(app)
    assert app.bot.send_message.call_count == 1
    assert "Adu laris minggu ini" in app.bot.send_message.call_args[1]["text"]
    assert store.meta_get(123, "adu_laris_minggu") == papan_mod.minggu_wib()
    await jobs_mod.pengingat_adu_laris_job(app)
    assert app.bot.send_message.call_count == 1  # minggu yang sama: diam


async def test_pengingat_adu_laris_tier_rendah_dilewati(
        monkeypatch, rich_slot, game_data, tugas_data, store,
        akun_json_valid):
    store.save_user(123, akun_json_valid)  # tier default 1
    _mock_fetch(monkeypatch, _fake_state(copy.deepcopy(rich_slot)))
    cloud = SimpleNamespace(fetch_papan=AsyncMock())
    app = _fake_app(store, game_data, tugas_data, cloud=cloud)
    await jobs_mod.pengingat_adu_laris_job(app)
    app.bot.send_message.assert_not_called()
    cloud.fetch_papan.assert_not_called()
