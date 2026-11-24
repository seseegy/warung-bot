"""Manipulasi save + paket cloud Warung Life Simulator 1.2.

Seluruh format di sini digrounding ke kode hasil decompile GDRE, BUKAN ditebak:

- ``_paket_pindah()`` / ``paket_cloud()`` / ``_buka_paket_pindah()``
  (``game_state.gd`` ~l.10034-10099):
  paket = JSON top-level -> gzip -> base64, diawali ``"1:"``.
  Isi slot adalah STRING JSON mentah file ``simpanan_N.json`` (bukan dict).
- ``_sidik()`` (``akun_online.gd``): SHA-256 dari bagian-bagian yang digabung
  ``"|"`` — hanya slot yang ADA, lalu string flag
  ``"%s%s%s%d" % [tanpa_iklan, pendukung, kode_pendukung, len(baju)]``
  (bool Godot dirender ``"true"``/``"false"``).
- ``simpan()`` (``game_state.gd`` ~l.3344-3420): slot disimpan sebagai JSON
  pretty-print indent TAB; field yang dipakai bot: ``uang``, ``tingkat``
  (0-based, level = tingkat+1), ``hari``, ``saldo_digital`` (QRIS),
  ``nama_warung``, ``progres`` {pelanggan, barang, omzet, khusus},
  ``upgrade`` (array id upgrade yang dimiliki), ``misi_status``,
  ``cerita_tamat``, ``energi``, ``id_papan``, ``disimpan``.
- ``_cek_tugas()`` (``game_state.gd`` ~l.3158): naik level butuh SEMUA:
  progres inti >= target, progres khusus >= target_khusus, bintang >=
  target_bintang (0 di tugas.json saat ini — tidak ada field "bintang"),
  misi cerita lunas (``misi_status`` "" atau "lunas", atau ``cerita_tamat``),
  DAN ``syarat_upgrade_beres`` (punya >=1 dari ``t["upgrade"]``).
  Mengisi ``progres`` saja TIDAK menjamin hadiah cair — lihat
  :func:`fill_task_progress`.

Modul ini murni (tanpa I/O jaringan / Telegram) supaya mudah dites.
"""

from __future__ import annotations

import base64
import binascii
import copy
import gzip
import hashlib
import json
import zlib
from datetime import datetime

# Batas dekompresi yang dipakai game: decompress_dynamic(20000000, GZIP).
MAX_PACKAGE_BYTES = 20_000_000

# game_state.gd: const JUMLAH_SLOT = 6
JUMLAH_SLOT = 6

# Format paket pindah (game_state.gd: const FORMAT_PINDAH = 1).
FORMAT_PINDAH = 1

# Versi game yang format save-nya dipahami bot ini.
VERSI_GAME_DIDUKUNG = "1.2"

# Batas uang yang wajar (RANCANGAN §9): tolak nilai di luar rentang ini.
UANG_MAKSIMAL = 999_999_999


class PackageError(ValueError):
    """Paket cloud tidak bisa di-decode / strukturnya tidak valid."""


class SlotError(ValueError):
    """Isi slot save tidak bisa di-parse / strukturnya tidak valid."""


class TaskError(ValueError):
    """Tugas level tidak bisa diisi (mis. sudah level terakhir)."""


def _godot_str(value: object) -> str:
    """Render nilai seperti operator ``%s`` Godot.

    bool -> "true"/"false", None -> "", str -> apa adanya.
    Dipakai agar sidik yang dihitung bot sama dengan sidik game.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _md5_hex(teks: str) -> str:
    # Game: FileAccess.get_md5(file) = MD5 dari BYTES file.
    # Slot di paket adalah string file itu sendiri, jadi MD5 dari UTF-8-nya.
    return hashlib.md5(teks.encode("utf-8")).hexdigest()


def encode_package(paket: dict) -> str:
    """Dict paket -> string ``"1:" + base64(gzip(JSON))``.

    JSON kompak tanpa spasi (``JSON.stringify(paket)`` Godot tanpa indent).
    """
    mentah = json.dumps(paket, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    padat = gzip.compress(mentah, compresslevel=9)
    return "1:" + base64.b64encode(padat).decode("ascii")


def decode_package(teks: str) -> dict:
    """String paket -> dict. Validasi ketat seperti ``_buka_paket_pindah``.

    Menolak: bukan str, tanpa awalan "1:", base64 rusak, gzip rusak,
    ukuran hasil > 20 MB, JSON bukan dict, atau dict tanpa key "slot".
    """
    if not isinstance(teks, str) or not teks.startswith("1:"):
        raise PackageError("paket harus diawali '1:'")
    try:
        padat = base64.b64decode(teks[2:], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PackageError(f"base64 paket rusak: {exc}") from exc
    if not padat:
        raise PackageError("isi paket kosong setelah base64-decode")
    try:
        # zlib wbits=31 = format gzip; max_length menegakkan batas game
        # (decompress_dynamic(20000000, GZIP)) dan mendeteksi data terpotong.
        dekompres = zlib.decompressobj(31)
        mentah = dekompres.decompress(padat, MAX_PACKAGE_BYTES)
        if dekompres.unconsumed_tail or not dekompres.eof:
            raise PackageError("paket melebihi batas 20 MB atau terpotong")
        mentah += dekompres.flush()
    except zlib.error as exc:
        raise PackageError(f"gzip paket rusak: {exc}") from exc
    try:
        data = json.loads(mentah.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"JSON paket rusak: {exc}") from exc
    if not isinstance(data, dict) or "slot" not in data:
        raise PackageError("paket bukan dict JSON atau tanpa key 'slot'")
    if not isinstance(data["slot"], dict):
        raise PackageError("key 'slot' paket bukan dict")
    return data


def parse_slot(slot_teks: str) -> dict:
    """String isi slot (JSON file simpanan_N.json) -> dict."""
    if not isinstance(slot_teks, str):
        raise SlotError("isi slot harus string JSON")
    try:
        data = json.loads(slot_teks)
    except json.JSONDecodeError as exc:
        raise SlotError(f"JSON slot rusak: {exc}") from exc
    if not isinstance(data, dict):
        raise SlotError("isi slot bukan object JSON")
    return data


def serialize_slot(slot: dict) -> str:
    """Dict slot -> string JSON seperti yang ditulis game.

    Game: ``JSON.stringify(data, "\\t")`` — pretty-print indent TAB.
    Bot memakai format yang sama agar byte slot hasil edit konsisten.
    """
    return json.dumps(slot, ensure_ascii=False, indent="\t")


def compute_sidik(paket: dict) -> str:
    """Hitung sidik paket, persis seperti ``_sidik()`` di akun_online.gd.

    Bagian: ``"<n>:<md5 slot n>"`` untuk tiap slot yang ADA saja,
    lalu ``"<tanpa_iklan><pendukung><kode_pendukung><jumlah baju>"``.
    Semua bagian digabung "|", lalu SHA-256 hex.
    """
    slot = paket.get("slot", {})
    if not isinstance(slot, dict):
        raise PackageError("key 'slot' paket bukan dict")
    bagian: list[str] = []
    for n in range(1, JUMLAH_SLOT + 1):
        isi = slot.get(str(n))
        if isi is None:
            continue
        if not isinstance(isi, str):
            raise PackageError(f"slot {n} bukan string")
        bagian.append(f"{n}:{_md5_hex(isi)}")
    toko = paket.get("toko", {})
    if not isinstance(toko, dict):
        raise PackageError("key 'toko' paket bukan dict")
    lemari = paket.get("lemari", [])
    if not isinstance(lemari, list):
        raise PackageError("key 'lemari' paket bukan list")
    flags = (
        _godot_str(toko.get("tanpa_iklan", False))
        + _godot_str(toko.get("pendukung", False))
        + _godot_str(toko.get("kode_pendukung", ""))
        + str(len(lemari))
    )
    bagian.append(flags)
    return hashlib.sha256("|".join(bagian).encode("utf-8")).hexdigest()


def slot_summary(slot: dict) -> dict:
    """Ringkasan slot seperti ``info_slot()`` (game_state.gd ~l.3272).

    level = tingkat + 1; qris = saldo_digital.
    """
    return {
        "nama_warung": str(slot.get("nama_warung", "")),
        "hari": int(slot.get("hari", 1)),
        "uang": int(slot.get("uang", 0)),
        "qris": int(slot.get("saldo_digital", 0)),
        "level": int(slot.get("tingkat", 0)) + 1,
        "tingkat": int(slot.get("tingkat", 0)),
        "disimpan": str(slot.get("disimpan", "")),
        "id_papan": str(slot.get("id_papan", "")),
    }


def best_slot(paket: dict) -> tuple[int, dict]:
    """Slot terbaik (level tertinggi, lalu hari terbanyak).

    Sama seperti ``kemajuan_hp()`` di akun_online.gd yang memilih slot
    "paling jauh" (level dulu, baru hari). Mengembalikan (nomor_slot, dict).
    """
    slot = paket.get("slot", {})
    terbaik_n: int | None = None
    terbaik: dict | None = None
    terbaik_kunci: tuple[int, int] | None = None
    for n in range(1, JUMLAH_SLOT + 1):
        isi = slot.get(str(n))
        if isi is None:
            continue
        data = parse_slot(isi)
        kunci = (int(data.get("tingkat", 0)), int(data.get("hari", 1)))
        if terbaik_kunci is None or kunci > terbaik_kunci:
            terbaik_n, terbaik, terbaik_kunci = n, data, kunci
    if terbaik_n is None or terbaik is None:
        raise PackageError("paket tidak berisi slot yang bisa dibaca")
    return terbaik_n, terbaik


def set_uang(slot: dict, jumlah: int) -> dict:
    """Set ``uang`` di slot. Validasi ketat; mengembalikan slot yang sama.

    Menolak: bukan int (bool ikut ditolak), negatif, nol TIDAK ditolak
    (uang 0 = bangkrut, keadaan yang sah di game), > 999.999.999.
    """
    if isinstance(jumlah, bool) or not isinstance(jumlah, int):
        raise ValueError("jumlah uang harus bilangan bulat")
    if jumlah < 0:
        raise ValueError("jumlah uang tidak boleh negatif")
    if jumlah > UANG_MAKSIMAL:
        raise ValueError(f"jumlah uang melebihi batas wajar Rp{UANG_MAKSIMAL:,}")
    slot["uang"] = jumlah
    return slot


def task_targets(tugas_data: dict, tingkat: int) -> dict:
    """Target level berjalan dari tugas.json (``daftar_tingkat[tingkat]``).

    ``tingkat`` 0-based. Melempar TaskError bila sudah melewati level terakhir.
    """
    daftar = tugas_data.get("tingkat", [])
    if not isinstance(daftar, list) or not daftar:
        raise TaskError("data tugas.json tidak berisi daftar 'tingkat'")
    if tingkat < 0 or tingkat >= len(daftar):
        raise TaskError(
            "sudah di level terakhir (Level 11 'Coming Soon' di tugas.json) — "
            "tidak ada tugas lagi yang bisa diisi"
        )
    target = daftar[tingkat]
    if not isinstance(target, dict):
        raise TaskError("entri tugas.json rusak")
    return target


def fill_task_progress(slot: dict, tugas_data: dict) -> dict:
    """Isi ``progres`` slot sampai target level berjalan (raw, tanpa keringanan).

    Target mentah dari tugas.json adalah batas ATAS yang aman: game boleh
    MERINGANKAN target (``faktor_macet``/``faktor_keringanan`` di mode casual,
    ``target_inti``/``target_khusus``), tidak pernah menaikkannya. Jadi
    mengisi sampai target mentah selalu memenuhi syarat progres.

    PENTING — mengisi progres saja belum tentu menaikkan level. ``_cek_tugas``
    juga mensyaratkan:
    - ``syarat_upgrade_beres``: punya >=1 dari ``t["upgrade"]``
      (Level 2-10 SEMUA punya syarat upgrade di tugas.json saat ini);
    - ``agus_beres``: ``misi_status`` "" atau "lunas", atau ``cerita_tamat``.
    Fungsi ini mengembalikan daftar ``blockers`` (string) agar bot bisa
    menyampaikannya dengan jujur, bukan mengklaim hadiah pasti cair.
    """
    tingkat = int(slot.get("tingkat", 0))
    target = task_targets(tugas_data, tingkat)
    khusus = target.get("khusus", {})
    target_khusus = int(khusus.get("target", 0)) if isinstance(khusus, dict) else 0
    slot["progres"] = {
        "pelanggan": int(target.get("pelanggan", 0)),
        "barang": int(target.get("barang", 0)),
        "omzet": int(target.get("omzet", 0)),
        "khusus": target_khusus,
    }

    blockers: list[str] = []
    syarat_upgrade = target.get("upgrade", [])
    if syarat_upgrade:
        dimiliki = slot.get("upgrade", [])
        if not isinstance(dimiliki, list):
            dimiliki = []
        if not any(u in dimiliki for u in syarat_upgrade):
            blockers.append(
                "upgrade belum dimiliki: " + ", ".join(str(u) for u in syarat_upgrade)
                + " (beli dulu salah satu di game)"
            )
    misi_status = str(slot.get("misi_status", ""))
    cerita_tamat = bool(slot.get("cerita_tamat", False))
    if misi_status not in ("", "lunas") and not cerita_tamat:
        blockers.append(
            f"misi cerita belum lunas (misi_status: {misi_status or '(kosong)'}) — "
            "selesaikan dulu misi Agus di game"
        )
    return {"target": target, "blockers": blockers}


def build_package_with_slot(paket: dict, nomor_slot: int, slot: dict) -> dict:
    """Salinan paket dengan SATU slot diganti hasil edit + "dibuat" diperbarui.

    Slot lain dan semua field lain (toko, lemari, promo, ...) dipertahankan
    APA ADANYA (byte-for-byte) agar sidik slot yang tidak disentuh tetap
    cocok dengan yang dihitung game setelah mengunduh.
    """
    if nomor_slot < 1 or nomor_slot > JUMLAH_SLOT:
        raise ValueError(f"nomor slot harus 1..{JUMLAH_SLOT}")
    baru = copy.deepcopy(paket)
    baru["slot"][str(nomor_slot)] = serialize_slot(slot)
    # Format game: Time.get_datetime_string_from_system(false, true) = waktu
    # lokal "YYYY-MM-DD HH:MM:SS".
    baru["dibuat"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return baru
