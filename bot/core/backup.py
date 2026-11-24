"""Backup paket cloud harian + rollback — Fase 5.

Memakai tabel ``backups`` Store yang SUDAH ADA (dipakai Fase 1-4 untuk
mencadangkan paket cloud sebelum tiap upload): satu baris per arsip,
``p_data`` terenkripsi Fernet. Job harian menyimpan satu arsip per hari
(WIB); /backup menampilkan daftar; rollback memulihkan arsip sebagai
versi baru (dengan konfirmasi ganda di handler).

Aturan keamanan (RANCANGAN §9): arsip berisi paket save LENGKAP
(termasuk id_papan) — disimpan terenkripsi seperti token, TIDAK PERNAH
ditampilkan di chat, dan ikut terhapus saat /unlink (``delete_user``).
"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from . import save as save_mod

WIB = ZoneInfo("Asia/Jakarta")


class BackupError(ValueError):
    """Arsip tidak bisa dipakai (rusak / tidak bisa di-decode)."""


def tanggal_hari_ini(saat: datetime | None = None) -> str:
    """Tanggal WIB 'YYYY-MM-DD'."""
    saat = (saat or datetime.now(WIB)).astimezone(WIB)
    return saat.strftime("%Y-%m-%d")


def _tanggal_dari_unix(ts: int) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=WIB).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def arsipkan_harian(store, chat_id: int, versi: int, p_data: str,
                    tanggal: str | None = None) -> dict:
    """Simpan arsip paket hari ini. Bila arsip tanggal yang sama sudah
    ada, TIDAK menimpa (satu arsip per hari; yang pertama menang).

    Mengembalikan {"disimpan": bool, "tanggal": str, "alasan": str}.
    ``p_data`` yang kosong/bukan string ditolak mentah-mentah.
    """
    if not isinstance(p_data, str) or not p_data:
        raise BackupError("p_data kosong — tidak ada yang diarsipkan")
    tanggal = tanggal or tanggal_hari_ini()
    for arsip in daftar_arsip(store, chat_id):
        if arsip["tanggal"] == tanggal:
            return {"disimpan": False, "tanggal": tanggal,
                    "alasan": "arsip hari ini sudah ada"}
    store.save_backup(chat_id, int(versi), p_data)
    return {"disimpan": True, "tanggal": tanggal, "alasan": ""}


def daftar_arsip(store, chat_id: int, limit: int = 30) -> list:
    """Daftar arsip terbaru dulu: id, tanggal (WIB), versi."""
    hasil = []
    for row in store.list_backups(chat_id, limit=limit):
        hasil.append({
            "id": int(row["id"]),
            "tanggal": _tanggal_dari_unix(row["created_at"]),
            "versi": int(row["versi"]),
            "created_at": int(row["created_at"]),
        })
    return hasil


def muat_arsip(store, chat_id: int, backup_id: int) -> dict:
    """Muat + validasi arsip. Melempar BackupError bila:

    - arsip tidak ada,
    - p_data tidak bisa di-decode (``decode_package`` gagal),
    - struktur paket bukan dict / tidak punya slot,
    - ada slot yang tidak bisa di-parse (save rusak).
    """
    try:
        row = store.get_backup(chat_id, int(backup_id))
    except (TypeError, ValueError) as exc:
        raise BackupError(f"id arsip tidak valid: {backup_id}") from exc
    if row is None:
        raise BackupError(f"arsip #{backup_id} tidak ditemukan")
    try:
        paket = save_mod.decode_package(row["p_data"])
    except save_mod.PackageError as exc:
        raise BackupError(
            f"arsip #{backup_id} rusak (tidak bisa di-decode): {exc}"
        ) from exc
    if not isinstance(paket, dict) or not isinstance(
            paket.get("slot"), dict):
        raise BackupError(f"arsip #{backup_id} rusak (tidak ada slot)")
    for nomor, teks in paket["slot"].items():
        try:
            save_mod.parse_slot(teks)
        except save_mod.SlotError as exc:
            raise BackupError(
                f"arsip #{backup_id} rusak (slot {nomor}: {exc})"
            ) from exc
    return {
        "paket": paket,
        "p_data": row["p_data"],
        "versi": int(row["versi"]),
        "tanggal": _tanggal_dari_unix(row["created_at"]),
        "created_at": int(row["created_at"]),
    }


def ringkasan_arsip(paket: dict) -> dict:
    """Slot terbaik arsip (seperti ``kemajuan_hp``: level lalu hari)
    untuk layar konfirmasi rollback."""
    try:
        _, slot = save_mod.best_slot(paket)
    except save_mod.SlotError:
        return {"nama_warung": "(kosong)", "level": 0, "hari": 0,
                "uang": 0, "qris": 0, "disimpan": ""}
    ringkasan = save_mod.slot_summary(slot)
    return {
        "nama_warung": ringkasan["nama_warung"],
        "level": ringkasan["level"],
        "hari": ringkasan["hari"],
        "uang": ringkasan["uang"],
        "qris": ringkasan["qris"],
        "disimpan": ringkasan["disimpan"],
    }


def paket_ke_json(paket: dict) -> str:
    """Paket -> JSON ringkas (untuk log audit, tanpa p_data mentah)."""
    try:
        nomor, slot = save_mod.best_slot(paket)
        ringkasan = save_mod.slot_summary(slot)
        return json.dumps(
            {"slot": nomor, "nama": ringkasan["nama_warung"],
             "level": ringkasan["level"], "hari": ringkasan["hari"]},
            ensure_ascii=False)
    except save_mod.SlotError:
        return "{}"
