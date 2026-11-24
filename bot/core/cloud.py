"""Klien HTTP Supabase untuk akun cloud Warung Life Simulator 1.2.

Digrounding ke ``akun_online.gd`` (GDRE) dan ``FORMAT_API.md``:

- Base URL + publishable key: konstanta di ``akun_online.gd``.
- ``_pastikan_token()``: pakai ``akses`` bila ``habis - 90 > sekarang``,
  kalau tidak refresh via ``POST /auth/v1/token?grant_type=refresh_token``
  body ``{"refresh_token": <segar>}``. Respons memutar KEDUA token;
  ``habis = sekarang + expires_in`` (default 3600). 400/401 -> sesi mati.
- ``_rpc(fungsi, isi, batas=20)``: ``POST /rest/v1/rpc/<fungsi>`` header
  ``apikey`` + ``Content-Type: application/json`` + ``Authorization: Bearer``.
  Timeout akun_simpan/ambil = 40 dtk.
- ``kirim()``: ``akun_simpan {p_data, p_versi_dasar, p_id_papan, p_paksa}``.
  Sukses ``{"ok": true, "versi": N}``; bentrok
  ``{"ok": false, "alasan": "bentrok"}``.
- ``pakai_cloud()``: ``akun_ambil {}`` -> ``{"ok": true, "versi", "data"}``
  atau ``{"ok": false, "alasan": ...}`` bila belum ada simpanan.

Perbedaan dari kode game (sengaja, didokumentasikan): game mengembalikan
``{}`` untuk SEMUA kegagalan RPC sehingga tidak bisa membedakan 401 vs
gangguan jaringan. Bot ini membedakan status HTTP agar bisa memberi pesan
yang tepat ("sesi habis, tautkan ulang" vs "server/jaringan bermasalah").

Tidak ada panggilan live di sini — semua dites dengan mock transport.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

SUPABASE_URL = "https://vfeihrxdwynivqcksxwl.supabase.co"
# Publishable key — publik by design (ada di APK). Bukan secret.
SUPABASE_KEY = "sb_publishable_bGjm_-NNAqleprvQoE3dLA_IVYxzKmr"

# Jeda pengaman refresh seperti _pastikan_token(): refresh bila sisa < 90 dtk.
REFRESH_MARGIN_SECONDS = 90

# Timeout (detik) seperti _rpc default 20 / akun_simpan-ambil 40.
TIMEOUT_RPC = 20.0
TIMEOUT_CLOUD = 40.0


class CloudError(Exception):
    """Kegagalan cloud umum (jaringan, server, respons tak terduga).

    ``session`` (bila ada) adalah sesi terbaru SETELAH kemungkinan refresh
    token. Pemanggil WAJIB menyimpannya bila ada: refresh token di-rotasi
    server, jadi token lama bisa sudah tidak berlaku setelah refresh —
    membuang sesi baru berarti kehilangan akses sampai /link ulang.
    """

    def __init__(self, message: str, session: dict | None = None) -> None:
        super().__init__(message)
        self.session = session


class SessionExpired(CloudError):
    """Sesi mati: refresh ditolak (400/401) atau RPC dijawab 401.

    Pengguna harus /link ulang dengan akun.json baru dari game.
    """


class ConflictError(CloudError):
    """Server menolak upload karena cloud lebih baru (``alasan: bentrok``)."""


class NoCloudData(CloudError):
    """``akun_ambil`` menjawab ok=false — belum ada simpanan di cloud."""


class SupabaseClient:
    """Klien tipis di atas httpx. Token TIDAK disimpan di sini.

    ``session`` adalah dict akun.json (akses, segar, habis, ...).
    :meth:`ensure_token` mengembalikan session yang sudah diperbarui
    (dict baru) bila refresh terjadi; pemanggil wajib menyimpannya.
    """

    def __init__(
        self,
        base_url: str = SUPABASE_URL,
        api_key: str = SUPABASE_KEY,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        # trust_env=False: bot server terhubung langsung ke Supabase.
        # Proxy env host (mis. no_proxy berisi IPv6 "[::1]") TIDAK boleh
        # memengaruhi klien — httpx bisa gagal total saat konstruksi
        # karena tidak bisa mem-parse entri no_proxy seperti itu
        # (teramati di VM ini). Bila VPS butuh proxy, atur eksplisit.
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            transport=transport,
            timeout=TIMEOUT_RPC,
            trust_env=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "SupabaseClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # -- header ---------------------------------------------------------
    def _anon_headers(self) -> dict[str, str]:
        return {"apikey": self.api_key, "Content-Type": "application/json"}

    def _auth_headers(self, access_token: str) -> dict[str, str]:
        headers = self._anon_headers()
        headers["Authorization"] = f"Bearer {access_token}"
        return headers

    # -- token ----------------------------------------------------------
    async def refresh_tokens(self, refresh_token: str) -> dict:
        """Tukar refresh token -> token baru. 400/401 -> SessionExpired."""
        if not refresh_token:
            raise SessionExpired("tidak ada refresh token (field 'segar' kosong)")
        try:
            resp = await self._client.post(
                "/auth/v1/token?grant_type=refresh_token",
                headers=self._anon_headers(),
                json={"refresh_token": refresh_token},
                timeout=TIMEOUT_RPC,
            )
        except httpx.HTTPError as exc:
            raise CloudError(f"gagal menghubungi server auth: {exc}") from exc
        if resp.status_code in (400, 401):
            raise SessionExpired(
                "server menolak refresh token (400/401) — sesi sudah mati"
            )
        if resp.status_code != 200:
            raise CloudError(f"refresh token gagal: HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise CloudError("respons refresh bukan JSON") from exc
        if not isinstance(data, dict) or "access_token" not in data:
            raise CloudError("respons refresh tanpa access_token")
        return data

    async def ensure_token(self, session: dict) -> dict:
        """Pastikan access token masih berlaku; refresh bila sisa < 90 dtk.

        Mengembalikan session (dict baru bila di-refresh, dict yang sama
        bila masih berlaku). Melempar SessionExpired bila refresh gagal.
        """
        akses = str(session.get("akses", ""))
        habis = int(session.get("habis", 0) or 0)
        sekarang = int(time.time())
        if akses and habis - REFRESH_MARGIN_SECONDS > sekarang:
            return session
        try:
            data = await self.refresh_tokens(str(session.get("segar", "")))
        except SessionExpired as exc:
            exc.session = session
            raise
        baru = dict(session)
        baru["akses"] = str(data.get("access_token", ""))
        baru["segar"] = str(data.get("refresh_token", session.get("segar", "")))
        baru["habis"] = sekarang + int(data.get("expires_in", 3600) or 3600)
        user = data.get("user", {})
        if isinstance(user, dict):
            if user.get("id"):
                baru["user_id"] = str(user["id"])
            if user.get("email"):
                baru["email"] = str(user["email"])
        return baru

    # -- RPC ------------------------------------------------------------
    async def _rpc(
        self, session: dict, fungsi: str, isi: dict, timeout: float = TIMEOUT_RPC
    ) -> tuple[dict, dict]:
        """Panggil RPC akun. Mengembalikan (hasil_json, session_terbaru).

        401 dari server -> SessionExpired. Status lain != 200 -> CloudError.
        Respons 200 yang bukan dict -> CloudError.
        """
        session = await self.ensure_token(session)
        try:
            resp = await self._client.post(
                f"/rest/v1/rpc/{fungsi}",
                headers=self._auth_headers(str(session.get("akses", ""))),
                json=isi,
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            raise CloudError(f"gagal menghubungi {fungsi}: {exc}", session=session) from exc
        if resp.status_code == 401:
            raise SessionExpired(
                f"server menolak token untuk {fungsi} (401) — sesi sudah mati",
                session=session,
            )
        if resp.status_code != 200:
            raise CloudError(f"{fungsi} gagal: HTTP {resp.status_code}", session=session)
        try:
            data = resp.json()
        except ValueError as exc:
            raise CloudError(f"respons {fungsi} bukan JSON", session=session) from exc
        if not isinstance(data, dict):
            raise CloudError(f"respons {fungsi} bukan object JSON", session=session)
        return data, session

    async def fetch_papan(
        self, tab: str, id_papan: str, p_hp: str = ""
    ) -> dict:
        """``ambil_papan2`` — ANONIM (tanpa Bearer, hanya apikey),
        timeout 12 dtk seperti ``_rpc`` papan (papan_online.gd).

        ``p_hp`` = id perangkat analitik; bot tidak memilikinya jadi
        dikirim "" (hanya dipakai server untuk jempol). Respons 200 yang
        bukan dict atau tanpa "daftar" -> CloudError.
        """
        try:
            resp = await self._client.post(
                "/rest/v1/rpc/ambil_papan2",
                headers=self._anon_headers(),
                json={"p_jenis": tab, "p_id": id_papan, "p_hp": p_hp},
                timeout=12.0,
            )
        except httpx.HTTPError as exc:
            raise CloudError(f"gagal menghubungi ambil_papan2: {exc}") from exc
        if resp.status_code != 200:
            raise CloudError(f"ambil_papan2 gagal: HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise CloudError("respons ambil_papan2 bukan JSON") from exc
        if not isinstance(data, dict) or "daftar" not in data:
            raise CloudError("respons ambil_papan2 tanpa 'daftar'")
        return data

    async def fetch_papan_adu(self, id_papan: str) -> dict:
        """``ambil_papan_adu_laris`` — anonim, timeout 12 dtk."""
        try:
            resp = await self._client.post(
                "/rest/v1/rpc/ambil_papan_adu_laris",
                headers=self._anon_headers(),
                json={"p_id": id_papan},
                timeout=12.0,
            )
        except httpx.HTTPError as exc:
            raise CloudError(
                f"gagal menghubungi ambil_papan_adu_laris: {exc}") from exc
        if resp.status_code != 200:
            raise CloudError(
                f"ambil_papan_adu_laris gagal: HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise CloudError("respons ambil_papan_adu_laris bukan JSON") from exc
        if not isinstance(data, dict) or "daftar" not in data:
            raise CloudError("respons ambil_papan_adu_laris tanpa 'daftar'")
        return data

    async def fetch_cloud(self, session: dict) -> tuple[dict, dict]:
        """``akun_ambil``. Mengembalikan ({"versi": int, "data": str}, session).

        Belum ada simpanan -> NoCloudData. ``ok: false`` lain -> CloudError.
        """
        data, session = await self._rpc(session, "akun_ambil", {}, TIMEOUT_CLOUD)
        if not data.get("ok", False):
            raise NoCloudData(
                f"belum ada simpanan di cloud (alasan: {data.get('alasan', '-')})",
                session=session,
            )
        if "data" not in data:
            raise CloudError("akun_ambil ok tapi tanpa field 'data'", session=session)
        return {"versi": int(data.get("versi", 0)), "data": str(data["data"])}, session

    async def upload_cloud(
        self,
        session: dict,
        p_data: str,
        versi_dasar: int,
        id_papan: str,
        paksa: bool = False,
    ) -> tuple[dict, dict]:
        """``akun_simpan``. Mengembalikan ({"versi": int}, session).

        Bentrok -> ConflictError. ``ok: false`` lain -> CloudError.
        """
        if not id_papan:
            raise CloudError("id_papan kosong — save tidak berisi id_papan")
        data, session = await self._rpc(
            session,
            "akun_simpan",
            {
                "p_data": p_data,
                "p_versi_dasar": int(versi_dasar),
                "p_id_papan": id_papan,
                "p_paksa": bool(paksa),
            },
            TIMEOUT_CLOUD,
        )
        if data.get("ok", False):
            return {"versi": int(data.get("versi", int(versi_dasar) + 1))}, session
        alasan = str(data.get("alasan", "gagal"))
        if alasan == "bentrok":
            raise ConflictError(
                "cloud lebih baru dari versi dasar yang dikirim (bentrok)",
                session=session,
            )
        raise CloudError(f"akun_simpan ditolak server (alasan: {alasan})", session=session)
