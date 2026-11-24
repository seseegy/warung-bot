"""Tes API Mini App (Fase 4) — validasi initData + endpoint, TANPA panggilan live.

Mock cloud memakai p_data contoh dari conftest (save Level 2 asli).
Tes memakai httpx.ASGITransport (in-process, satu thread) supaya koneksi
sqlite Store tidak pindah thread seperti pada TestClient.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import httpx
import pytest

from bot.api import (
    INITDATA_HEADER,
    create_app,
    validate_init_data,
)
from bot.core.cloud import SupabaseClient

BOT_TOKEN = "TOKEN-RAHASIA-TEST-12345"
CHAT_ID = 123456789
CHAT_LAIN = 999


def _hash_init_data(token: str, fields: dict) -> str:
    """Hash initData persis seperti spek Telegram (untuk membuat vektor tes)."""
    data_check_string = "\n".join(
        f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, data_check_string.encode(),
                    hashlib.sha256).hexdigest()


def buat_init_data(token: str = BOT_TOKEN, chat_id: int = CHAT_ID,
                   auth_date: int | None = None, **extra) -> str:
    fields = {
        "auth_date": str(auth_date if auth_date is not None
                         else int(time.time())),
        "user": json.dumps({"id": chat_id, "first_name": "Sir",
                            "username": "sir"}, ensure_ascii=False),
    }
    fields.update(extra)
    fields["hash"] = _hash_init_data(token, fields)
    return urlencode(fields)


def _mock_handler_factory(p_data: str):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        try:
            isi = json.loads(request.content.decode() or "{}")
        except json.JSONDecodeError:
            isi = {}
        if path == "/rest/v1/rpc/akun_ambil":
            return httpx.Response(
                200, json={"ok": True, "versi": 8, "data": p_data})
        if path == "/rest/v1/rpc/akun_simpan":
            if int(isi.get("p_versi_dasar", 0)) < 8:
                return httpx.Response(
                    200, json={"ok": False, "alasan": "bentrok"})
            return httpx.Response(200, json={"ok": True, "versi": 9})
        return httpx.Response(404, json={"error": "not found"})
    return handler


def _buat_app(store, game_data, tugas_data, p_data, allowed):
    cloud = SupabaseClient(
        transport=httpx.MockTransport(_mock_handler_factory(p_data)))
    ctx = {
        "store": store, "cloud": cloud,
        "tugas": tugas_data, "data": game_data,
        "allowed": allowed,
    }
    return create_app(ctx, BOT_TOKEN, miniapp_dist=None)


@pytest.fixture()
async def api_client(store, game_data, tugas_data, sample_package,
                     rich_slot, akun_json_valid):
    # Slot kaya (barang_terbuka + stok) supaya endpoint stok/harga-terbaik
    # punya data — sample_slot tidak punya barang_terbuka.
    from bot.core import save as save_mod

    slot = dict(rich_slot)
    slot.update(
        tingkat=1, hari=120, uang=4_500_000, saldo_digital=120_000,
        progres={"pelanggan": 10, "barang": 20, "omzet": 100_000,
                 "khusus": 2},
        stok={"beras": 0, "gula": 3, "mi_goreng": 5, "sachet": 20,
              "teh_botol": 20, "minyak_goreng": 10, "telur": 10,
              "kopi_susu": 10},
    )
    paket = dict(sample_package)
    paket["slot"] = {"1": save_mod.serialize_slot(slot)}
    p_data = save_mod.encode_package(paket)
    store.save_user(CHAT_ID, akun_json_valid)
    app = _buat_app(store, game_data, tugas_data, p_data, {CHAT_ID})
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test") as client:
        yield client


def _h(init_data: str) -> dict:
    return {INITDATA_HEADER: init_data}


# -- validasi initData ------------------------------------------------------

def test_validate_init_data_benar():
    user = validate_init_data(buat_init_data(), BOT_TOKEN)
    assert user["id"] == CHAT_ID


def test_validate_init_data_hash_salah():
    init = buat_init_data()
    # Ubah satu karakter hash.
    rusak = init[:-1] + ("0" if init[-1] != "0" else "1")
    with pytest.raises(Exception) as exc:
        validate_init_data(rusak, BOT_TOKEN)
    assert exc.value.code == "hash_salah"


def test_validate_init_data_token_salah():
    with pytest.raises(Exception) as exc:
        validate_init_data(buat_init_data(), "TOKEN-LAIN")
    assert exc.value.code == "hash_salah"


def test_validate_init_data_kedaluwarsa():
    lama = int(time.time()) - 25 * 3600
    with pytest.raises(Exception) as exc:
        validate_init_data(buat_init_data(auth_date=lama), BOT_TOKEN)
    assert exc.value.code == "auth_kedaluwarsa"


def test_validate_init_data_masa_depan():
    depan = int(time.time()) + 3600
    with pytest.raises(Exception) as exc:
        validate_init_data(buat_init_data(auth_date=depan), BOT_TOKEN)
    assert exc.value.code == "auth_kedaluwarsa"


def test_validate_init_data_kosong():
    with pytest.raises(Exception) as exc:
        validate_init_data("", BOT_TOKEN)
    assert exc.value.code == "init_data_hilang"


def test_validate_init_data_tanpa_hash():
    init = urlencode({"auth_date": str(int(time.time())),
                      "user": json.dumps({"id": CHAT_ID})})
    with pytest.raises(Exception) as exc:
        validate_init_data(init, BOT_TOKEN)
    assert exc.value.code == "init_data_rusak"


def test_validate_init_data_tanpa_user():
    fields = {"auth_date": str(int(time.time()))}
    fields["hash"] = _hash_init_data(BOT_TOKEN, fields)
    with pytest.raises(Exception) as exc:
        validate_init_data(urlencode(fields), BOT_TOKEN)
    assert exc.value.code == "init_data_rusak"


# -- autentikasi di endpoint ------------------------------------------------

async def test_health_tanpa_auth(api_client):
    r = await api_client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "fase": 4}


async def test_api_tidak_dikenal_404_json(api_client):
    # Path /api/* yang salah ketik harus JSON 404, bukan index.html.
    r = await api_client.get("/api/tidak-ada",
                             headers=_h(buat_init_data()))
    assert r.status_code == 404
    assert r.json()["code"] == "tidak_dikenal"


async def test_status_tanpa_header_ditolak(api_client):
    r = await api_client.get("/api/status")
    assert r.status_code == 401
    assert r.json()["code"] == "init_data_hilang"


async def test_status_hash_salah_ditolak(api_client):
    r = await api_client.get("/api/status",
                             headers=_h(buat_init_data()[:-1] + "0"))
    assert r.status_code == 401
    assert r.json()["code"] == "hash_salah"


async def test_status_kedaluwarsa_ditolak(api_client):
    lama = int(time.time()) - 25 * 3600
    r = await api_client.get("/api/status",
                             headers=_h(buat_init_data(auth_date=lama)))
    assert r.status_code == 401
    assert r.json()["code"] == "auth_kedaluwarsa"


async def test_status_tidak_di_allowlist_ditolak(api_client, store,
                                                akun_json_valid):
    store.save_user(CHAT_LAIN, akun_json_valid)
    r = await api_client.get("/api/status",
                             headers=_h(buat_init_data(chat_id=CHAT_LAIN)))
    assert r.status_code == 403
    assert r.json()["code"] == "tidak_diizinkan"


async def test_belum_tertaut_ditolak(store, game_data, tugas_data,
                                     sample_p_data):
    # Allowlist kosong = semua boleh -> yang belum tertaut kena 404.
    app = _buat_app(store, game_data, tugas_data, sample_p_data, set())
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test") as c:
        r = await c.get("/api/status", headers=_h(buat_init_data(chat_id=555)))
        assert r.status_code == 404
        assert r.json()["code"] == "belum_tertaut"


# -- endpoint baca ----------------------------------------------------------

async def test_status_ok(api_client):
    r = await api_client.get("/api/status", headers=_h(buat_init_data()))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["nama_warung"] == "Warung Barokah"
    assert d["level"] == 2
    assert d["hari"] == 120
    assert d["uang"] == 4_500_000
    assert d["versi"] == 8
    assert d["tugas"]["pelanggan"] == [10, 40]
    assert "Stok Beras 1 kg habis" in d["peringatan"]


async def test_tugas_ok_dan_blocker(api_client):
    r = await api_client.get("/api/tugas", headers=_h(buat_init_data()))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["level"] == 2
    assert d["target"][0] == {"kunci": "pelanggan", "label": "Pelanggan",
                              "saat_ini": 10, "target": 40}
    # Level 2 butuh upgrade kipas yang belum dimiliki -> blocker jujur.
    assert any("kipas" in b for b in d["blockers"])


async def test_stok_ok(api_client):
    r = await api_client.get("/api/stok", headers=_h(buat_init_data()))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["versi_dasar"] == 8
    beras = next(x for x in d["daftar"] if x["id"] == "beras")
    assert beras["stok"] == 0
    assert beras["harga_jual"] > 0
    assert beras["lantai"] <= beras["harga_jual"] <= beras["batas"]


async def test_harga_terbaik_ok(api_client):
    r = await api_client.get("/api/harga-terbaik", headers=_h(buat_init_data()))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["versi_dasar"] == 8
    assert len(d["daftar"]) > 0
    pertama = d["daftar"][0]
    assert "harga_terbaik" in pertama and "laba_terbaik" in pertama


# -- endpoint tulis ---------------------------------------------------------

async def test_simulasi_dan_terapkan(api_client):
    r = await api_client.post("/api/simulasi", json={"hari": 1},
                              headers=_h(buat_init_data()))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["jumlah_hari"] == 1
    assert "sim_id" in d and d["sim_id"]
    assert d["uang_akhir"] >= 0
    assert d["versi_dasar"] == 8
    sim_id = d["sim_id"]

    r2 = await api_client.post("/api/terapkan-simulasi", json={"sim_id": sim_id},
                               headers=_h(buat_init_data()))
    assert r2.status_code == 200, r2.text
    assert r2.json()["ok"] is True


async def test_terapkan_simulasi_id_salah_ditolak(api_client):
    await api_client.post("/api/simulasi", json={"hari": 1},
                          headers=_h(buat_init_data()))
    r = await api_client.post("/api/terapkan-simulasi",
                              json={"sim_id": "bukan-id"},
                              headers=_h(buat_init_data()))
    assert r.status_code == 410
    assert r.json()["code"] == "simulasi_kedaluwarsa"


async def test_terapkan_simulasi_tanpa_simulasi_ditolak(api_client):
    r = await api_client.post("/api/terapkan-simulasi", json={"sim_id": "x"},
                              headers=_h(buat_init_data()))
    assert r.status_code == 410


async def test_simulasi_hari_tidak_valid(api_client):
    r = await api_client.post("/api/simulasi", json={"hari": 99},
                              headers=_h(buat_init_data()))
    assert r.status_code == 422
    assert r.json()["code"] == "validasi"


async def test_uang_ok(api_client):
    r = await api_client.post("/api/uang", json={"jumlah": 5_000_000},
                              headers=_h(buat_init_data()))
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


async def test_uang_melebihi_maks_ditolak(api_client):
    r = await api_client.post("/api/uang", json={"jumlah": 10_000_000_000},
                              headers=_h(buat_init_data()))
    assert r.status_code == 422


async def test_tugas_selesai_ok(api_client):
    r = await api_client.post("/api/tugas-selesai", headers=_h(buat_init_data()))
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


async def test_terapkan_harga_ok(api_client):
    r = await api_client.get("/api/stok", headers=_h(buat_init_data()))
    beras = next(x for x in r.json()["daftar"] if x["id"] == "beras")
    r2 = await api_client.post(
        "/api/terapkan-harga",
        json={"versi_dasar": 8, "harga": {"beras": beras["harga_jual"]}},
        headers=_h(buat_init_data()))
    assert r2.status_code == 200, r2.text
    assert r2.json()["ok"] is True


async def test_terapkan_harga_di_bawah_lantai_ditolak(api_client):
    r = await api_client.post(
        "/api/terapkan-harga",
        json={"versi_dasar": 8, "harga": {"beras": 100}},
        headers=_h(buat_init_data()))
    assert r.status_code == 400
    assert r.json()["code"] == "harga_tidak_valid"


async def test_terapkan_harga_barang_tak_dikenal_ditolak(api_client):
    r = await api_client.post(
        "/api/terapkan-harga",
        json={"versi_dasar": 8, "harga": {"nasi_goreng_xyz": 5000}},
        headers=_h(buat_init_data()))
    assert r.status_code == 400


# -- pengaturan & baca saja --------------------------------------------------

async def test_pengaturan_get_dan_post(api_client):
    r = await api_client.get("/api/pengaturan", headers=_h(buat_init_data()))
    assert r.status_code == 200
    assert r.json()["tier"] == 1

    r2 = await api_client.post("/api/pengaturan",
                               json={"tier": 3, "otomatis": True,
                                     "batas_harian": 500_000,
                                     "jam_laporan": 8},
                               headers=_h(buat_init_data()))
    assert r2.status_code == 200, r2.text
    d = r2.json()
    assert d["tier"] == 3
    assert d["otomatis"] is True
    assert d["batas_harian"] == 500_000
    assert d["jam_laporan"] == 8


async def test_pengaturan_tier_tidak_valid(api_client):
    r = await api_client.post("/api/pengaturan", json={"tier": 9},
                              headers=_h(buat_init_data()))
    assert r.status_code == 422


async def test_baca_saja_blokir_tulis(api_client):
    await api_client.post("/api/pengaturan", json={"baca_saja": True},
                          headers=_h(buat_init_data()))
    r = await api_client.post("/api/uang", json={"jumlah": 5_000_000},
                              headers=_h(buat_init_data()))
    assert r.status_code == 403
    assert r.json()["code"] == "baca_saja"
    # Baca tetap jalan.
    r2 = await api_client.get("/api/status", headers=_h(buat_init_data()))
    assert r2.status_code == 200
    # Matikan lagi, tulis jalan.
    await api_client.post("/api/pengaturan", json={"baca_saja": False},
                          headers=_h(buat_init_data()))
    r3 = await api_client.post("/api/uang", json={"jumlah": 5_000_000},
                               headers=_h(buat_init_data()))
    assert r3.status_code == 200


async def test_unlink_hapus_semua(api_client, store):
    r = await api_client.post("/api/unlink", headers=_h(buat_init_data()))
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert store.get_user(CHAT_ID) is None
    r2 = await api_client.get("/api/status", headers=_h(buat_init_data()))
    assert r2.status_code == 404
    assert r2.json()["code"] == "belum_tertaut"
