"""Tes Fase 5 — pemantauan (bot/core/monitor.py): pasaran Senin, peringatan
harga, cek versi game, pengingat adu laris.

Murni (tanpa I/O) kecuali fetch_versi_json yang memakai client palsu.
"""

from __future__ import annotations

import copy

import pytest

from bot.core import monitor as monitor_mod


def _slot_level2(rich_slot):
    """Slot Level 2 (tingkat=1) supaya agen aktif (LEVEL_AGEN=2) dan
    harga_pasar memakai faktor pasaran."""
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 1
    return slot


# -- bandingkan_pasaran -------------------------------------------------------

def test_pasaran_naik_terdeteksi_dan_saran_benar(rich_slot, game_data):
    slot = _slot_level2(rich_slot)
    lama = {"mi_goreng": 1.0}
    baru = {"mi_goreng": 1.15}
    hasil = monitor_mod.bandingkan_pasaran(lama, baru, game_data, slot)
    assert len(hasil) == 1
    assert hasil[0]["arah"] == "naik"
    assert hasil[0]["harga_baru"] > hasil[0]["harga_lama"]
    assert "naikkan" in hasil[0]["saran"]
    # mi_goreng jual 3500 x 1.15 -> 4000 (dibulatkan ke 100).
    assert hasil[0]["harga_baru"] == 4000
    assert hasil[0]["harga_lama"] == 3500


def test_pasaran_turun_terdeteksi(rich_slot, game_data):
    slot = _slot_level2(rich_slot)
    hasil = monitor_mod.bandingkan_pasaran(
        {"mi_goreng": 1.2}, {"mi_goreng": 1.0}, game_data, slot)
    assert len(hasil) == 1
    assert hasil[0]["arah"] == "turun"
    assert "turunkan" in hasil[0]["saran"]


def test_pasaran_baru_dan_hilang(rich_slot, game_data):
    slot = _slot_level2(rich_slot)
    hasil = monitor_mod.bandingkan_pasaran(
        {"mi_goreng": 1.1}, {"beras": 0.9}, game_data, slot)
    arah = {h["id"]: h["arah"] for h in hasil}
    assert arah == {"mi_goreng": "hilang", "beras": "baru"}


def test_pasaran_sama_tidak_ada_notifikasi(rich_slot, game_data):
    slot = _slot_level2(rich_slot)
    assert monitor_mod.bandingkan_pasaran(
        {"mi_goreng": 1.15}, {"mi_goreng": 1.15}, game_data, slot) == []
    assert monitor_mod.bandingkan_pasaran({}, {}, game_data, slot) == []


def test_pasaran_barang_tidak_dikenal_diabaikan(rich_slot, game_data):
    slot = _slot_level2(rich_slot)
    hasil = monitor_mod.bandingkan_pasaran(
        {}, {"barang_hantu": 1.5}, game_data, slot)
    assert hasil == []


# -- peringatan_harga ---------------------------------------------------------

def test_harga_terlalu_mahal_memicu_peringatan(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["harga_jual_khusus"] = {"mi_goreng": 5000}  # pasar 3500
    hasil = monitor_mod.peringatan_harga(game_data, slot)
    assert any(h["id"] == "mi_goreng" and h["arah"] == "mahal"
               for h in hasil)


def test_harga_terlalu_murah_memicu_peringatan(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["harga_jual_khusus"] = {"mi_goreng": 2000}  # pasar 3500
    hasil = monitor_mod.peringatan_harga(game_data, slot)
    entri = next(h for h in hasil if h["id"] == "mi_goreng")
    assert entri["arah"] == "murah"
    assert entri["di_lantai"] is True  # 2000 < lantai 2600


def test_harga_wajar_tidak_memicu(rich_slot, game_data):
    assert monitor_mod.peringatan_harga(game_data, rich_slot) == []


def test_harga_tanpa_stok_tidak_diperingatkan(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["harga_jual_khusus"] = {"mi_goreng": 9000}
    slot["stok"]["mi_goreng"] = 0
    assert all(h["id"] != "mi_goreng"
               for h in monitor_mod.peringatan_harga(game_data, slot))


# -- cek_versi ---------------------------------------------------------------

def test_versi_baru_terdeteksi():
    hasil = monitor_mod.cek_versi(
        {"kode_terbaru": 50, "versi_terbaru": "1.3"})
    assert hasil["diketahui"] is True
    assert hasil["ada_update"] is True
    assert hasil["kode_server"] == 50


def test_versi_sama_tidak_ada_update():
    hasil = monitor_mod.cek_versi(
        {"kode_terbaru": 49, "versi_terbaru": "1.2"})
    assert hasil["ada_update"] is False


def test_versi_server_kadaluarsa_bukan_update():
    # Fakta live 24 Nov 2026: file server (47/1.1) lebih lama dari game.
    hasil = monitor_mod.cek_versi(
        {"kode_terbaru": 47, "versi_terbaru": "1.1"})
    assert hasil["ada_update"] is False
    assert "lebih lama" in hasil["catatan"]


def test_versi_1_10_lebih_baru_dari_1_2():
    hasil = monitor_mod.cek_versi({"versi_terbaru": "1.10"})
    assert hasil["ada_update"] is True


def test_versi_format_tak_terduga_tidak_crash():
    for data in ({}, {"kode_terbaru": "lima puluh"},
                 {"kode_terbaru": None, "versi_terbaru": None},
                 {"versi_terbaru": "beta"}, ["1.3"], "1.3", None, 42):
        hasil = monitor_mod.cek_versi(data)
        assert hasil["diketahui"] is False
        assert hasil["ada_update"] is False


# -- fetch_versi_json (client palsu) ------------------------------------------

class _Resp:
    def __init__(self, status=200, data=None, rusak=False):
        self.status_code = status
        self._data = data
        self._rusak = rusak

    def json(self):
        if self._rusak:
            raise ValueError("bukan JSON")
        return self._data


class _Client:
    def __init__(self, resp=None, error=None):
        self._resp = resp
        self._error = error

    async def get(self, url):
        if self._error is not None:
            raise self._error
        return self._resp


async def test_fetch_versi_ok():
    data = await monitor_mod.fetch_versi_json(
        _Client(_Resp(200, {"kode_terbaru": 47})))
    assert data["kode_terbaru"] == 47


async def test_fetch_versi_http_gagal():
    with pytest.raises(monitor_mod.VersionCheckError):
        await monitor_mod.fetch_versi_json(_Client(_Resp(500, {})))


async def test_fetch_versi_bukan_json():
    with pytest.raises(monitor_mod.VersionCheckError):
        await monitor_mod.fetch_versi_json(_Client(_Resp(200, rusak=True)))


async def test_fetch_versi_bukan_object():
    with pytest.raises(monitor_mod.VersionCheckError):
        await monitor_mod.fetch_versi_json(_Client(_Resp(200, [1, 2])))


async def test_fetch_versi_jaringan_gagal():
    with pytest.raises(monitor_mod.VersionCheckError):
        await monitor_mod.fetch_versi_json(
            _Client(error=ConnectionError("putus")))


# -- pengingat adu laris -------------------------------------------------------

def test_adu_laris_baru_naik_turun_tetap():
    assert "peringkat #3" in (
        monitor_mod.teks_pengingat_adu_laris(None, 3, 100) or "")
    assert "naik #5 → #3" in (
        monitor_mod.teks_pengingat_adu_laris(5, 3, 100) or "")
    assert "turun #2 → #4" in (
        monitor_mod.teks_pengingat_adu_laris(2, 4, 100) or "")
    assert "tetap di peringkat #3" in (
        monitor_mod.teks_pengingat_adu_laris(3, 3, 100) or "")


def test_adu_laris_tanpa_peringkat_tidak_ada_teks():
    assert monitor_mod.teks_pengingat_adu_laris(3, None) is None
    assert monitor_mod.teks_pengingat_adu_laris(None, None) is None
