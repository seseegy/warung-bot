"""Backend API Mini App (Fase 4) — FastAPI.

Autentikasi: header ``X-Telegram-Init-Data`` berisi initData mentah dari
``Telegram.WebApp.initData``. Divalidasi persis seperti dokumentasi resmi
``core.telegram.org/bots/webapps`` ("Validating data received via the
Mini App"):

- ``data_check_string`` = semua field KECUALI ``hash`` (dan ``signature``),
  diurutkan alfabet, format ``key=<value>``, pemisah LF (``\\n``).
- ``secret = HMAC-SHA256(key=b"WebAppData", msg=bot_token)``.
- Bandingkan ``hex(HMAC-SHA256(data_check_string, secret))`` dengan
  ``hash`` memakai ``hmac.compare_digest``.
- ``auth_date`` maksimal 24 jam (dan tidak di masa depan).

Semua logika bisnis memakai ulang modul core Fase 1-3 (cloud, save, sim,
plan, tiers, store) — file ini hanya validasi + HTTP + pemetaan respons.
Tidak ada token/rahasia game yang dikirim ke frontend.

Menjalankan (proses terpisah dari bot polling — alasannya di README):

    .venv/bin/python -m bot.api

Env: BOT_TOKEN, FERNET_KEY (wajib, seperti bot.main), API_HOST
(default 127.0.0.1), API_PORT (default 8000), MINIAPP_DIST
(default miniapp/dist — bila ada, file statis disajikan di /).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from .core import plan as plan_mod
from .core import save as save_mod
from .core import sim as sim_mod
from .core import tiers as tiers_mod
from .core.cloud import CloudError, NoCloudData, SessionExpired
from .main import BASE_DIR, DATA_DIR, load_context
from .tg.confirm import (
    build_pending_harga,
    build_pending_simulasi,
    build_pending_tugas,
    build_pending_uang,
    execute_upload,
)
from .tg.status import NotLinked, fetch_latest_state

log = logging.getLogger("warung-bot-api")

# Batas umur initData: 24 jam (dokumen resmi menyarankan cek auth_date).
INITDATA_MAX_AGE_SECONDS = 86_400
# Toleransi jam server yang sedikit lebih cepat dari jam Telegram.
INITDATA_FUTURE_SKEW_SECONDS = 300

# Header yang membawa initData mentah dari Mini App.
INITDATA_HEADER = "X-Telegram-Init-Data"


class InitDataError(ValueError):
    """initData tidak valid; ``code`` dipakai sebagai kode error API."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ApiError(Exception):
    """Error API yang dipetakan ke JSON {"ok": false, ...}."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def validate_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int = INITDATA_MAX_AGE_SECONDS,
    now: int | None = None,
) -> dict:
    """Validasi initData Telegram, kembalikan dict ``user``.

    Melempar InitDataError dengan code: ``init_data_hilang``,
    ``init_data_rusak`` (bukan query string / field hilang), ``hash_salah``,
    ``auth_kedaluwarsa``.
    """
    if not isinstance(init_data, str) or not init_data.strip():
        raise InitDataError("init_data_hilang", "header initData kosong")
    try:
        pasangan = parse_qsl(init_data, keep_blank_values=True)
    except ValueError as exc:
        raise InitDataError(
            "init_data_rusak", f"initData bukan query string: {exc}"
        ) from exc
    field: dict[str, str] = {}
    for kunci, nilai in pasangan:
        if kunci in field:
            raise InitDataError(
                "init_data_rusak", f"field initData ganda: {kunci}")
        field[kunci] = nilai
    hash_terima = field.get("hash", "")
    if not hash_terima:
        raise InitDataError("init_data_rusak", "field 'hash' hilang")
    # Data-check-string: semua field kecuali hash/signature, urut alfabet.
    periksa = {k: v for k, v in field.items() if k not in ("hash", "signature")}
    data_check_string = "\n".join(f"{k}={periksa[k]}" for k in sorted(periksa))
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"),
                      hashlib.sha256).digest()
    hitung = hmac.new(secret, data_check_string.encode("utf-8"),
                      hashlib.sha256).hexdigest()
    if not hmac.compare_digest(hitung, hash_terima.lower()):
        raise InitDataError("hash_salah", "hash initData tidak cocok")
    auth_raw = field.get("auth_date", "")
    try:
        auth_date = int(auth_raw)
    except (TypeError, ValueError):
        raise InitDataError(
            "init_data_rusak", "field 'auth_date' hilang/bukan angka") from None
    sekarang = int(time.time()) if now is None else int(now)
    if auth_date > sekarang + INITDATA_FUTURE_SKEW_SECONDS:
        raise InitDataError(
            "auth_kedaluwarsa", "auth_date di masa depan")
    if sekarang - auth_date > max_age_seconds:
        raise InitDataError(
            "auth_kedaluwarsa",
            "initData sudah lebih dari 24 jam — buka ulang Mini App")
    try:
        user = json.loads(field.get("user", ""))
    except (json.JSONDecodeError, TypeError) as exc:
        raise InitDataError(
            "init_data_rusak", "field 'user' bukan JSON") from exc
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        raise InitDataError(
            "init_data_rusak", "field 'user' tanpa id bilangan bulat")
    return user


# -- model body ------------------------------------------------------------

class SimulasiBody(BaseModel):
    hari: int = Field(default=1, ge=1, le=30)


class TerapkanSimulasiBody(BaseModel):
    sim_id: str = Field(min_length=1)


class UangBody(BaseModel):
    jumlah: int = Field(ge=0, le=save_mod.UANG_MAKSIMAL)


class TerapkanHargaBody(BaseModel):
    versi_dasar: int = Field(ge=0)
    harga: dict[str, int] = Field(min_length=1)


class PengaturanBody(BaseModel):
    tier: int | None = Field(default=None, ge=1, le=3)
    otomatis: bool | None = None
    batas_harian: int | None = Field(default=None, ge=0)
    jam_otomatis: int | None = Field(default=None, ge=0, le=23)
    jam_laporan: int | None = Field(default=None, ge=0, le=23)
    laporan_aktif: bool | None = None
    baca_saja: bool | None = None


# -- aplikasi --------------------------------------------------------------

def create_app(
    ctx: dict,
    bot_token: str,
    miniapp_dist: str | Path | None = None,
) -> FastAPI:
    """Bangun aplikasi FastAPI dari konteks bersama (lihat main.load_context)."""
    store = ctx["store"]
    cloud = ctx["cloud"]
    tugas_data = ctx["tugas"]
    game_data = ctx["data"]
    allowed: set[int] = ctx["allowed"]

    app = FastAPI(title="Warung Bot — Mini App API", version="4.0.0")
    # Pending simulasi per chat (di memori proses API saja): sim_id ->
    # pending hasil build_pending_simulasi (berisi slot_akhir + versi_dasar).
    app.state.sim_pending: dict[int, dict] = {}

    def _ctx() -> SimpleNamespace:
        # Adapter minimal agar fetch_latest_state/execute_upload (yang
        # menerima telegram.ext CallbackContext) bisa dipakai ulang.
        return SimpleNamespace(bot_data={
            "store": store, "cloud": cloud,
            "tugas": tugas_data, "data": game_data,
        })

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"ok": False, "code": exc.code, "message": exc.message},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "code": "validasi",
                     "message": "input tidak valid",
                     "detail": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "code": f"http_{exc.status_code}",
                     "message": str(exc.detail)},
        )

    # -- autentikasi -------------------------------------------------------
    async def _current_user(request: Request) -> dict:
        raw = request.headers.get(INITDATA_HEADER, "")
        try:
            return validate_init_data(raw, bot_token)
        except InitDataError as exc:
            raise ApiError(401, exc.code, str(exc)) from exc

    async def _linked(user: dict = Depends(_current_user)) -> tuple[dict, dict]:
        chat_id = int(user["id"])
        if allowed and chat_id not in allowed:
            raise ApiError(
                403, "tidak_diizinkan",
                "chat ini tidak ada di allowlist bot")
        session = store.get_user(chat_id)
        if session is None:
            raise ApiError(
                404, "belum_tertaut",
                "Belum ada akun tertaut. Tautkan dulu dengan /link di chat bot.")
        return user, session

    def _wajib_tulis(chat_id: int) -> None:
        if store.get_baca_saja(chat_id):
            raise ApiError(
                403, "baca_saja",
                "Mode baca saja aktif — matikan dulu di Pengaturan.")

    async def _state(chat_id: int) -> dict:
        """State terbaru dari cloud; petakan error cloud ke ApiError."""
        try:
            return await fetch_latest_state(_ctx(), chat_id)
        except NotLinked as exc:
            raise ApiError(404, "belum_tertaut", str(exc)) from exc
        except SessionExpired:
            raise ApiError(
                401, "sesi_habis",
                "Sesi login habis. Kirim ulang akun.json dari game "
                "dengan /link.") from None
        except NoCloudData as exc:
            raise ApiError(404, "cloud_kosong", str(exc)) from exc
        except (CloudError, save_mod.PackageError,
                save_mod.SlotError) as exc:
            raise ApiError(502, "cloud_gagal", str(exc)) from exc

    def _hasil_upload(teks: str, status: str) -> dict:
        if status == "ok":
            return {"ok": True, "teks": teks}
        if status == "bentrok":
            raise ApiError(409, "bentrok", teks)
        if status == "sesi_habis":
            raise ApiError(401, "sesi_habis", teks)
        raise ApiError(502, "upload_gagal", teks)

    # -- endpoint ----------------------------------------------------------
    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True, "fase": 4}

    @app.get("/api/status")
    async def status(
        pasang: tuple[dict, dict] = Depends(_linked),
    ) -> dict:
        _, session = pasang
        chat_id = int(session["chat_id"])
        state = await _state(chat_id)
        slot = state["slot"]
        ringkasan = state["ringkasan"]
        stok = slot.get("stok", {}) or {}
        terbuka = slot.get("barang_terbuka", []) or []
        peringatan: list[str] = []
        for item_id in terbuka:
            if int(stok.get(item_id, 0) or 0) <= 0:
                nama = game_data.katalog.get(item_id, {}).get("nama", item_id)
                peringatan.append(f"Stok {nama} habis")
        if float(slot.get("energi", 100.0)) < 30:
            peringatan.append("Energi rendah — istirahat (ngopi/makan) di game")
        if int(slot.get("tunggakan_sewa", 0) or 0) > 0:
            peringatan.append(
                f"Sewa menunggak {int(slot.get('minggu_tunggak', 0))} minggu "
                "— diusir bila mencapai 3 minggu")
        try:
            target = save_mod.task_targets(tugas_data, int(slot.get("tingkat", 0)))
            progres = slot.get("progres", {}) or {}
            tugas = {
                "nama": str(target.get("nama", "")),
                "hadiah": int(target.get("hadiah", 0)),
                "pelanggan": [int(progres.get("pelanggan", 0)),
                              int(target.get("pelanggan", 0))],
                "barang": [int(progres.get("barang", 0)),
                           int(target.get("barang", 0))],
                "omzet": [int(progres.get("omzet", 0)),
                          int(target.get("omzet", 0))],
            }
        except save_mod.TaskError:
            tugas = None
        return {
            "ok": True,
            "nama_warung": ringkasan["nama_warung"],
            "level": ringkasan["level"],
            "hari": ringkasan["hari"],
            "uang": ringkasan["uang"],
            "qris": ringkasan["qris"],
            "energi": float(slot.get("energi", 100.0)),
            "stok_terisi": sum(1 for i in terbuka
                               if int(stok.get(i, 0) or 0) > 0),
            "stok_total": len(terbuka),
            "versi": int(state["versi"]),
            "disimpan": ringkasan["disimpan"],
            "tugas": tugas,
            "peringatan": peringatan,
            "tier": tiers_mod.nama_tier(store.get_tier(chat_id)),
            "otomatis": store.get_otomatis(chat_id),
        }

    @app.get("/api/tugas")
    async def tugas(
        pasang: tuple[dict, dict] = Depends(_linked),
    ) -> dict:
        _, session = pasang
        chat_id = int(session["chat_id"])
        state = await _state(chat_id)
        slot = state["slot"]
        tingkat = int(slot.get("tingkat", 0))
        try:
            target = save_mod.task_targets(tugas_data, tingkat)
        except save_mod.TaskError:
            return {"ok": True, "level_terakhir": True,
                    "pesan": "Sudah di level terakhir — tidak ada tugas lagi."}
        # fill_task_progress pada SALINAN: dipakai untuk daftar blocker
        # yang jujur (upgrade/misi), tanpa mengubah slot asli.
        hasil = save_mod.fill_task_progress(dict(slot), tugas_data)
        progres = slot.get("progres", {}) or {}
        khusus = target.get("khusus", {}) or {}
        return {
            "ok": True,
            "level": tingkat + 1,
            "nama": str(target.get("nama", "")),
            "hadiah": int(target.get("hadiah", 0)),
            "target": [
                {"kunci": "pelanggan", "label": "Pelanggan",
                 "saat_ini": int(progres.get("pelanggan", 0)),
                 "target": int(target.get("pelanggan", 0))},
                {"kunci": "barang", "label": "Barang",
                 "saat_ini": int(progres.get("barang", 0)),
                 "target": int(target.get("barang", 0))},
                {"kunci": "omzet", "label": "Omzet",
                 "saat_ini": int(progres.get("omzet", 0)),
                 "target": int(target.get("omzet", 0))},
            ],
            "khusus": (
                {"jenis": str(khusus.get("jenis", "")),
                 "saat_ini": int(progres.get("khusus", 0)),
                 "target": int(khusus.get("target", 0))}
                if isinstance(khusus, dict) and khusus.get("target") else None
            ),
            "blockers": list(hasil["blockers"]),
        }

    @app.get("/api/stok")
    async def stok(
        pasang: tuple[dict, dict] = Depends(_linked),
    ) -> dict:
        _, session = pasang
        chat_id = int(session["chat_id"])
        state = await _state(chat_id)
        slot = state["slot"]
        stok_map = slot.get("stok", {}) or {}
        daftar = []
        for item_id in game_data.urutan_barang:
            item = game_data.katalog[item_id]
            if item.get("jenis") != "fisik":
                continue
            daftar.append({
                "id": item_id,
                "nama": str(item.get("nama", item_id)),
                "stok": int(stok_map.get(item_id, 0) or 0),
                "harga_jual": sim_mod.harga_jual(game_data, item_id, slot),
                "harga_pasar": sim_mod.harga_pasar(game_data, item_id, slot),
                "harga_modal": sim_mod.harga_modal(game_data, item_id, slot),
                "lantai": sim_mod.lantai_harga(game_data, item_id, slot),
                "batas": sim_mod.batas_harga_jual(game_data, item_id, slot),
            })
        return {"ok": True, "versi_dasar": int(state["versi"]),
                "uang": int(slot.get("uang", 0)), "daftar": daftar}

    @app.get("/api/harga-terbaik")
    async def harga_terbaik(
        pasang: tuple[dict, dict] = Depends(_linked),
    ) -> dict:
        import asyncio

        _, session = pasang
        chat_id = int(session["chat_id"])
        state = await _state(chat_id)
        # Brute force per barang bisa makan detik — jangan blokir loop.
        daftar = await asyncio.to_thread(
            plan_mod.harga_terbaik, state["slot"], game_data)
        return {"ok": True, "versi_dasar": int(state["versi"]),
                "daftar": daftar}

    @app.post("/api/simulasi")
    async def simulasi(
        body: SimulasiBody,
        pasang: tuple[dict, dict] = Depends(_linked),
    ) -> dict:
        import asyncio

        _, session = pasang
        chat_id = int(session["chat_id"])
        state = await _state(chat_id)
        try:
            hasil = await asyncio.to_thread(
                sim_mod.simulate, state["slot"], game_data, body.hari)
        except sim_mod.SimError as exc:
            raise ApiError(400, "simulasi_gagal", str(exc)) from exc
        sim_id = uuid.uuid4().hex[:12]
        pending, _teks = build_pending_simulasi(state, hasil)
        pending["sim_id"] = sim_id
        app.state.sim_pending[chat_id] = pending
        return {
            "ok": True, "sim_id": sim_id,
            "versi_dasar": int(state["versi"]),
            "jumlah_hari": len(hasil["hari"]),
            "omzet": int(hasil["omzet"]), "laba": int(hasil["laba"]),
            "uang_awal": int(hasil["uang_awal"]),
            "uang_akhir": int(hasil["uang_akhir"]),
            "qris_awal": int(hasil["qris_awal"]),
            "qris_akhir": int(hasil["qris_akhir"]),
            "dilayani": int(hasil["dilayani"]),
            "batal": int(hasil["batal"]),
            "datang": int(hasil["datang"]),
            "tingkat_awal": int(hasil["tingkat_awal"]),
            "tingkat_akhir": int(hasil["tingkat_akhir"]),
            "hari_akhir": int(hasil["hari_akhir"]),
            "diusir": bool(hasil["diusir"]),
            "tunggakan_sewa": int(hasil["tunggakan_sewa"]),
            "per_hari": [
                {"hari": int(h.get("hari", 0)), "omzet": int(h["omzet"]),
                 "laba": int(h["laba"]), "dilayani": int(h["dilayani"]),
                 "batal": int(h["batal"])}
                for h in hasil["hari"]
            ],
            "catatan": "Proyeksi simulasi, bukan hasil main sungguhan — "
                       "RNG, event acak, dan pilihan cerita tidak disimulasikan.",
        }

    @app.post("/api/terapkan-simulasi")
    async def terapkan_simulasi(
        body: TerapkanSimulasiBody,
        pasang: tuple[dict, dict] = Depends(_linked),
    ) -> dict:
        _, session = pasang
        chat_id = int(session["chat_id"])
        _wajib_tulis(chat_id)
        pending = app.state.sim_pending.get(chat_id)
        if pending is None or pending.get("sim_id") != body.sim_id:
            raise ApiError(
                410, "simulasi_kedaluwarsa",
                "Simulasi ini sudah tidak berlaku (diganti hasil yang lebih "
                "baru atau server dimulai ulang) — jalankan simulasi dulu.")
        teks, status = await execute_upload(_ctx(), chat_id, pending)
        if status == "ok":
            app.state.sim_pending.pop(chat_id, None)
        return _hasil_upload(teks, status)

    @app.post("/api/uang")
    async def uang(
        body: UangBody,
        pasang: tuple[dict, dict] = Depends(_linked),
    ) -> dict:
        _, session = pasang
        chat_id = int(session["chat_id"])
        _wajib_tulis(chat_id)
        state = await _state(chat_id)
        pending, _teks = build_pending_uang(state, int(body.jumlah))
        teks, status = await execute_upload(_ctx(), chat_id, pending)
        return _hasil_upload(teks, status)

    @app.post("/api/tugas-selesai")
    async def tugas_selesai(
        pasang: tuple[dict, dict] = Depends(_linked),
    ) -> dict:
        _, session = pasang
        chat_id = int(session["chat_id"])
        _wajib_tulis(chat_id)
        state = await _state(chat_id)
        pending, _teks = build_pending_tugas(state, tugas_data)
        teks, status = await execute_upload(_ctx(), chat_id, pending)
        return _hasil_upload(teks, status)

    @app.post("/api/terapkan-harga")
    async def terapkan_harga(
        body: TerapkanHargaBody,
        pasang: tuple[dict, dict] = Depends(_linked),
    ) -> dict:
        _, session = pasang
        chat_id = int(session["chat_id"])
        _wajib_tulis(chat_id)
        state = await _state(chat_id)
        slot = state["slot"]
        # Validasi ulang ke lantai/batas game + snap ke langkah harga
        # (sama seperti plan.whatif) — jangan percaya harga dari frontend.
        harga_baru: dict[str, int] = {}
        for item_id, harga in body.harga.items():
            if item_id not in game_data.katalog:
                raise ApiError(400, "harga_tidak_valid",
                               f"barang tidak dikenal: {item_id}")
            if game_data.katalog[item_id].get("jenis") != "fisik":
                raise ApiError(400, "harga_tidak_valid",
                               f"harga hanya untuk barang fisik: {item_id}")
            try:
                h = int(harga)
            except (TypeError, ValueError):
                raise ApiError(400, "harga_tidak_valid",
                               f"harga {item_id} bukan bilangan bulat") from None
            lantai = sim_mod.lantai_harga(game_data, item_id, slot)
            batas = sim_mod.batas_harga_jual(game_data, item_id, slot)
            langkah = sim_mod.langkah_harga(game_data, item_id)
            if h < lantai:
                raise ApiError(400, "harga_tidak_valid",
                               f"{item_id}: {h} di bawah lantai {lantai}")
            if h > batas:
                raise ApiError(400, "harga_tidak_valid",
                               f"{item_id}: {h} di atas batas {batas}")
            h_snap = (h // langkah) * langkah
            if h_snap < lantai:
                h_snap = ((lantai + langkah - 1) // langkah) * langkah
            harga_baru[item_id] = min(h_snap, batas)
        pending = {
            "kind": "harga",
            "id_papan": state["ringkasan"]["id_papan"],
            "p_data": None,
            "versi_dasar": int(body.versi_dasar),
            "harga_baru": harga_baru,
        }
        teks, status = await execute_upload(_ctx(), chat_id, pending)
        return _hasil_upload(teks, status)

    @app.get("/api/pengaturan")
    async def pengaturan(
        pasang: tuple[dict, dict] = Depends(_linked),
    ) -> dict:
        _, session = pasang
        chat_id = int(session["chat_id"])
        jadwal = store.get_jadwal(chat_id)
        return {
            "ok": True,
            "tier": store.get_tier(chat_id),
            "tier_nama": tiers_mod.nama_tier(store.get_tier(chat_id)),
            "otomatis": store.get_otomatis(chat_id),
            "batas_harian": store.get_batas_harian(chat_id),
            "jam_otomatis": store.get_jam_otomatis(chat_id),
            "jam_laporan": (int(jadwal["jam"]) if jadwal else None),
            "laporan_aktif": bool(jadwal["aktif"]) if jadwal else False,
            "baca_saja": store.get_baca_saja(chat_id),
        }

    @app.post("/api/pengaturan")
    async def ubah_pengaturan(
        body: PengaturanBody,
        pasang: tuple[dict, dict] = Depends(_linked),
    ) -> dict:
        _, session = pasang
        chat_id = int(session["chat_id"])
        if body.tier is not None:
            store.set_tier(chat_id, int(body.tier))
        if body.otomatis is not None:
            store.set_otomatis(chat_id, bool(body.otomatis))
        if body.batas_harian is not None:
            store.set_batas_harian(chat_id, int(body.batas_harian))
        if body.jam_otomatis is not None:
            store.set_jam_otomatis(chat_id, int(body.jam_otomatis))
        if body.jam_laporan is not None or body.laporan_aktif is not None:
            jadwal = store.get_jadwal(chat_id)
            jam = (int(body.jam_laporan) if body.jam_laporan is not None
                   else int(jadwal["jam"]) if jadwal else 7)
            aktif = (bool(body.laporan_aktif) if body.laporan_aktif is not None
                     else bool(jadwal["aktif"]) if jadwal else True)
            store.set_jadwal(chat_id, jam, aktif=aktif)
        if body.baca_saja is not None:
            store.set_baca_saja(chat_id, bool(body.baca_saja))
        # Perubahan jadwal/otomatis dibaca bot polling lewat job
        # sinkronisasi tiap 10 menit — berlaku tanpa restart.
        hasil = await pengaturan(pasang)
        hasil["catatan"] = ("Perubahan jadwal/otomatis berlaku paling lambat "
                            "10 menit (sinkronisasi bot).")
        return hasil

    @app.post("/api/unlink")
    async def unlink(
        pasang: tuple[dict, dict] = Depends(_linked),
    ) -> dict:
        _, session = pasang
        chat_id = int(session["chat_id"])
        store.delete_user(chat_id)
        app.state.sim_pending.pop(chat_id, None)
        return {"ok": True, "teks": "Semua data kamu sudah dihapus dari bot."}

    # -- file statis Mini App (bila sudah di-build) ------------------------
    # Catch-all /api/* HARUS sebelum mount statis: kalau tidak, path API
    # yang salah ketik akan mengembalikan index.html (200), bukan JSON 404.
    @app.api_route("/api/{path:path}",
                   methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def _api_tidak_dikenal() -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "code": "tidak_dikenal",
                     "message": "endpoint API tidak dikenal"},
        )

    if miniapp_dist is not None:
        dist = Path(miniapp_dist)
        if dist.is_dir():
            app.mount("/", StaticFiles(directory=str(dist), html=True),
                      name="miniapp")
            log.info("menyajikan Mini App dari %s", dist)
        else:
            log.warning("MINIAPP_DIST tidak ada (%s) — hanya API yang jalan",
                        dist)

    return app


def main() -> None:
    """Entry point proses API: ``.venv/bin/python -m bot.api``."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Hindari token bocor ke log (httpx mencatat URL lengkap di INFO).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    ctx = load_context()
    host = os.environ.get("API_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("API_PORT", "8000"))
    except ValueError:
        raise SystemExit("API_PORT bukan angka") from None
    dist_default = BASE_DIR / "miniapp" / "dist"
    dist = Path(os.environ.get("MINIAPP_DIST", str(dist_default)))
    app = create_app(ctx, ctx["bot_token"], miniapp_dist=dist)
    log.info("API Mini App jalan di %s:%d (dist: %s)", host, port, dist)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
