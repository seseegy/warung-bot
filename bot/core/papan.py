"""Pelacak papan peringkat — Fase 3 (hanya BACA, tanpa kirim skor).

Grounding (``papan_online.gd`` + ``papan_peringkat.gd``):
- Ambil papan: ``ambil_papan2 {p_jenis: "semua"|"minggu"|"bulan",
  p_id, p_hp}`` — ANONIM (tanpa Bearer, hanya apikey), timeout 12 dtk.
  Respons: {"daftar": [...], "peringkat": int?, "jumlah_warung": int,
  "diperbarui": str, "jempol_saya": int?}.
- Baris daftar: [nama, pembeli_total, kode, bintang, level, omzet,
  jempol, jempol_saya] (``papan_peringkat.gd:94``). Kode warung =
  ``md5(id_papan)[:12]`` (``papan_online.gd: kode()``). Daftar terurut
  menurun menurut pembeli; peringkat sendiri dihitung seperti game:
  posisi penyisipan menurut jumlah pembeli (``papan_peringkat.gd:41``),
  atau pakai field server "peringkat" bila ada.
- p_hp = id perangkat analitik (16 byte hex acak, tersimpan lokal di HP
  — bot TIDAK memilikinya). Bot mengirim "" — server tetap menjawab
  daftar (p_hp hanya dipakai untuk jempol). Bila server menolak,
  pelacakan dilaporkan "tidak tersedia", bukan ditebak.

KEPUTUSAN (dicatat juga di README): bot TIDAK MENGIRIM skor.
``kirim_skor5`` memakai HMAC ``RAHASIA`` dan angka kumulatif permainan
nyata; ``kirim_adu_laris`` butuh p_hp + "hasil" + "rekaman" harian dari
permainan nyata mingguan — tidak satu pun bisa direpresentasikan dengan
setia dari simulasi. RANCANGAN §9 juga melarang menyimpan RAHASIA di
repo bot. Yang bot lakukan: menaikkan angka save lewat simulasi yang
setia; game di HP-lah yang mengirim skor saat dimainkan.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")


def kode_papan(id_papan: str) -> str:
    """Kode warung di papan: md5(id_papan) 12 karakter pertama."""
    return hashlib.md5(str(id_papan).encode("utf-8")).hexdigest()[:12]


def minggu_wib(saat: datetime | None = None) -> str:
    """Senin minggu berjalan (WIB) 'YYYY-MM-DD' — seperti
    ``minggu_wib()`` (papan_online.gd)."""
    saat = (saat or datetime.now(WIB)).astimezone(WIB)
    senin = saat - timedelta(days=(saat.weekday()))
    return senin.strftime("%Y-%m-%d")


def _baris(daftar: list, i: int) -> dict | None:
    """Satu baris daftar -> dict. Kolom di luar jangkauan -> None/-1."""
    if i < 0 or i >= len(daftar):
        return None
    b = daftar[i]
    if not isinstance(b, (list, tuple)):
        return None

    def _int(idx: int, bawaan: int = -1) -> int:
        try:
            return int(b[idx]) if len(b) > idx and b[idx] is not None else bawaan
        except (TypeError, ValueError):
            return bawaan

    return {
        "nama": str(b[0]) if len(b) > 0 else "?",
        "pembeli": _int(1, 0),
        "kode": str(b[2]) if len(b) > 2 else "",
        "bintang": _int(3),
        "level": _int(4),
        "omzet": _int(5),
        "jempol": _int(6, 0),
    }


def parse_papan(data: dict, kode_saya: str, pembeli_saya: int | None) -> dict:
    """Hitung peringkat sendiri dari respons ``ambil_papan2``.

    ``pembeli_saya`` = ``total_pembeli`` dari save (game_state.gd:98,
    dikirim sebagai p_total oleh kirim_skor5). Bila None (field tidak
    ada di save lama), peringkat hanya dihitung bila baris sendiri ada
    atau server mengirim field "peringkat" — tidak ditebak.
    """
    daftar = data.get("daftar", [])
    if not isinstance(daftar, list):
        daftar = []
    try:
        jumlah_warung = int(data.get("jumlah_warung", 0) or 0)
    except (TypeError, ValueError):
        jumlah_warung = 0
    idx_saya: int | None = None
    for i, b in enumerate(daftar):
        if isinstance(b, (list, tuple)) and len(b) > 2 and str(b[2]) == kode_saya:
            idx_saya = i
            break
    if idx_saya is not None:
        peringkat = idx_saya + 1
        kamu = _baris(daftar, idx_saya)
        atas = _baris(daftar, idx_saya - 1)
        bawah = _baris(daftar, idx_saya + 1)
    else:
        # Tidak ada di daftar (di luar 50 besar / belum terkirim):
        # hitung posisi penyisipan seperti papan_peringkat.gd — hanya
        # bila jumlah pembeli sendiri diketahui.
        peringkat = None
        kamu = None
        atas = None
        bawah = None
        if pembeli_saya is not None:
            posisi = len(daftar)
            for i, b in enumerate(daftar):
                try:
                    if pembeli_saya >= int(b[1]):
                        posisi = i
                        break
                except (TypeError, ValueError, IndexError):
                    continue
            if daftar:
                peringkat = posisi + 1
                # Baris di atas posisi sisipan = indeks posisi-1,
                # di bawah = indeks posisi.
                atas = _baris(daftar, posisi - 1)
                bawah = _baris(daftar, posisi)
        if peringkat is None and data.get("peringkat") is not None:
            try:
                peringkat = int(data["peringkat"])
            except (TypeError, ValueError):
                peringkat = None
    if data.get("peringkat") is not None and idx_saya is not None:
        try:
            peringkat = int(data["peringkat"])
        except (TypeError, ValueError):
            pass
    return {
        "ditemukan": idx_saya is not None,
        "peringkat": peringkat,
        "jumlah_warung": jumlah_warung,
        "kamu": kamu,
        "atas": atas,
        "bawah": bawah,
        "total_baris": len(daftar),
    }


def bandingkan_peringkat(lama: int | None, baru: int | None) -> str:
    """'naik'/'turun'/'tetap'/'baru' — None = belum diketahui."""
    if baru is None:
        return "tidak_diketahui"
    if lama is None:
        return "baru"
    if baru < lama:
        return "naik"
    if baru > lama:
        return "turun"
    return "tetap"
