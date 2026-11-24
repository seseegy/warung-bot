"""Penyimpanan lokal bot: SQLite + enkripsi Fernet.

Isi ``akun.json`` (game, ``akun_online.gd`` ``_pakai_jawaban_token`` /
``masuk()``): ``akses``, ``segar``, ``habis`` (unix, = waktu login +
``expires_in``), ``user_id``, ``email``, ``nama``, ``penyedia``, ``versi``,
``sidik``, ``kemajuan`` {disimpan, hari, level, nama, qris, uang},
``disimpan`` (unix), ``bonus_tertunda``.

Aturan keamanan (RANCANGAN §9):
- Token (``akses``/``segar``) TIDAK PERNAH disimpan polos — Fernet.
- Token tidak pernah ditulis ke log/chat (penangan hanya menampilkan
  4 karakter terakhir bila perlu).
- ``/unlink`` menghapus SEMUA data pengguna (akun + backup).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

# Field akun.json yang wajib ada agar tautan bisa dipakai.
AKUN_FIELDS_WAJIB = ("akses", "segar", "habis", "user_id")


def validate_akun_json(data: object) -> tuple[bool, list[str], list[str]]:
    """Validasi isi akun.json. Mengembalikan (valid, errors, warnings).

    - Bukan dict / field wajib hilang / kosong / ``habis`` bukan int
      -> tidak valid.
    - ``akses`` kedaluwarsa (``habis`` sudah lewat) -> WARNING saja:
      bot masih bisa menautkan karena refresh token (``segar``) akan
      dipakai otomatis saat pertama memanggil cloud. Yang menentukan
      apakah sesi benar-benar mati adalah jawaban server saat refresh.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return False, ["file bukan object JSON"], []
    for field in AKUN_FIELDS_WAJIB:
        nilai = data.get(field)
        if nilai is None or (isinstance(nilai, str) and nilai == ""):
            errors.append(f"field wajib hilang/kosong: {field}")
    habis = data.get("habis")
    if habis is not None and (isinstance(habis, bool) or not isinstance(habis, int)):
        errors.append("field 'habis' harus bilangan bulat (unix timestamp)")
    if not errors and isinstance(habis, int) and habis <= int(time.time()):
        warnings.append(
            "access token sudah kedaluwarsa — bot akan mencoba refresh "
            "saat pertama memakai akun ini"
        )
    return (not errors), errors, warnings


def is_access_expired(session: dict) -> bool:
    """True bila access token sudah lewat masa berlaku."""
    habis = session.get("habis", 0)
    return not isinstance(habis, int) or habis <= int(time.time())


class Store:
    """SQLite per pengguna + cadangan paket (terenkripsi)."""

    def __init__(self, path: str | Path, fernet_key: bytes | str) -> None:
        if isinstance(fernet_key, str):
            fernet_key = fernet_key.encode("ascii")
        # Fernet() melempar ValueError bila kunci bukan base64 32 byte —
        # sengaja dibiarkan: kunci salah harus gagal keras saat start.
        self._fernet = Fernet(fernet_key)
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                chat_id     INTEGER PRIMARY KEY,
                user_id     TEXT,
                email       TEXT,
                nama        TEXT,
                penyedia    TEXT,
                akses_enc   BLOB,
                segar_enc   BLOB,
                habis       INTEGER,
                versi       INTEGER DEFAULT 0,
                sidik       TEXT DEFAULT '',
                p_id_papan  TEXT DEFAULT '',
                kemajuan    TEXT DEFAULT '{}',
                disimpan    INTEGER DEFAULT 0,
                tier        INTEGER DEFAULT 1,
                otomatis    INTEGER DEFAULT 0,
                batas_harian INTEGER DEFAULT 1000000,
                jam_otomatis INTEGER DEFAULT 7,
                baca_saja   INTEGER DEFAULT 0,
                updated_at  INTEGER
            );
            CREATE TABLE IF NOT EXISTS backups (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     INTEGER NOT NULL,
                versi       INTEGER NOT NULL,
                p_data_enc  BLOB NOT NULL,
                created_at  INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jadwal (
                chat_id     INTEGER PRIMARY KEY,
                jam         INTEGER NOT NULL,
                aktif       INTEGER NOT NULL DEFAULT 1,
                updated_at  INTEGER
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     INTEGER NOT NULL,
                waktu       INTEGER NOT NULL,
                aksi        TEXT NOT NULL,
                detail      TEXT DEFAULT '',
                lama        TEXT DEFAULT '',
                baru        TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS login_lacak (
                chat_id     INTEGER PRIMARY KEY,
                hari_ke     INTEGER NOT NULL DEFAULT 0,
                tanggal     TEXT NOT NULL DEFAULT '',
                siklus      INTEGER NOT NULL DEFAULT 0,
                updated_at  INTEGER
            );
            CREATE TABLE IF NOT EXISTS peringkat (
                chat_id     INTEGER NOT NULL,
                tab         TEXT NOT NULL,
                peringkat   INTEGER,
                jumlah_warung INTEGER DEFAULT 0,
                waktu       INTEGER NOT NULL,
                PRIMARY KEY (chat_id, tab)
            );
            CREATE TABLE IF NOT EXISTS meta (
                chat_id     INTEGER NOT NULL,
                kunci       TEXT NOT NULL,
                nilai       TEXT NOT NULL DEFAULT '',
                updated_at  INTEGER,
                PRIMARY KEY (chat_id, kunci)
            );
            CREATE TABLE IF NOT EXISTS mode_target (
                chat_id     INTEGER PRIMARY KEY,
                target_tingkat INTEGER NOT NULL,
                siklus      INTEGER NOT NULL DEFAULT 0,
                dimulai     INTEGER NOT NULL,
                updated_at  INTEGER
            );
            """
        )
        self._conn.commit()
        # Migrasi DB lama (Fase 1-2): tambah kolom tier/otomatis bila belum ada.
        kolom = {r[1] for r in self._conn.execute("PRAGMA table_info(users)")}
        for nama, bawaan in (
            ("tier", "1"),
            ("otomatis", "0"),
            ("batas_harian", "1000000"),
            ("jam_otomatis", "7"),
            ("baca_saja", "0"),
            ("slot_aktif", "NULL"),
        ):
            if nama not in kolom:
                self._conn.execute(
                    f"ALTER TABLE users ADD COLUMN {nama} INTEGER DEFAULT {bawaan}"
                )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- enkripsi -------------------------------------------------------
    def _enc(self, teks: str) -> bytes:
        return self._fernet.encrypt(teks.encode("utf-8"))

    def _dec(self, blob: bytes) -> str:
        try:
            return self._fernet.decrypt(blob).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError(
                "gagal mendekripsi data tersimpan — FERNET_KEY berubah?"
            ) from exc

    # -- pengguna -------------------------------------------------------
    def save_user(self, chat_id: int, session: dict) -> None:
        """Simpan/perbarui sesi akun.json (token terenkripsi)."""
        kemajuan = session.get("kemajuan", {})
        self._conn.execute(
            """
            INSERT INTO users
                (chat_id, user_id, email, nama, penyedia, akses_enc, segar_enc,
                 habis, versi, sidik, p_id_papan, kemajuan, disimpan, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                user_id=excluded.user_id, email=excluded.email,
                nama=excluded.nama, penyedia=excluded.penyedia,
                akses_enc=excluded.akses_enc, segar_enc=excluded.segar_enc,
                habis=excluded.habis, versi=excluded.versi,
                sidik=excluded.sidik, p_id_papan=excluded.p_id_papan,
                kemajuan=excluded.kemajuan, disimpan=excluded.disimpan,
                updated_at=excluded.updated_at
            """,
            (
                chat_id,
                str(session.get("user_id", "")),
                str(session.get("email", "")),
                str(session.get("nama", "")),
                str(session.get("penyedia", "google")),
                self._enc(str(session.get("akses", ""))),
                self._enc(str(session.get("segar", ""))),
                int(session.get("habis", 0) or 0),
                int(session.get("versi", 0) or 0),
                str(session.get("sidik", "")),
                str(session.get("p_id_papan", "")),
                json.dumps(kemajuan, ensure_ascii=False),
                int(session.get("disimpan", 0) or 0),
                int(time.time()),
            ),
        )
        self._conn.commit()

    def get_user(self, chat_id: int) -> dict | None:
        """Ambil sesi (token terdekripsi). None bila belum tertaut."""
        row = self._conn.execute(
            "SELECT * FROM users WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        if row is None:
            return None
        kemajuan = json.loads(row["kemajuan"] or "{}")
        if not isinstance(kemajuan, dict):
            kemajuan = {}
        return {
            "chat_id": row["chat_id"],
            "user_id": row["user_id"],
            "email": row["email"],
            "nama": row["nama"],
            "penyedia": row["penyedia"],
            "akses": self._dec(row["akses_enc"]),
            "segar": self._dec(row["segar_enc"]),
            "habis": row["habis"],
            "versi": row["versi"],
            "sidik": row["sidik"],
            "p_id_papan": row["p_id_papan"],
            "kemajuan": kemajuan,
            "disimpan": row["disimpan"],
        }

    def update_session(self, chat_id: int, session: dict) -> None:
        """Perbarui token/versi/sidik setelah refresh atau upload."""
        self._conn.execute(
            """
            UPDATE users SET akses_enc=?, segar_enc=?, habis=?, versi=?,
                sidik=?, p_id_papan=?, kemajuan=?, disimpan=?, updated_at=?
            WHERE chat_id=?
            """,
            (
                self._enc(str(session.get("akses", ""))),
                self._enc(str(session.get("segar", ""))),
                int(session.get("habis", 0) or 0),
                int(session.get("versi", 0) or 0),
                str(session.get("sidik", "")),
                str(session.get("p_id_papan", "")),
                json.dumps(session.get("kemajuan", {}), ensure_ascii=False),
                int(session.get("disimpan", 0) or 0),
                int(time.time()),
                chat_id,
            ),
        )
        self._conn.commit()

    def delete_user(self, chat_id: int) -> None:
        """Hapus SEMUA data pengguna (akun + cadangan + jadwal + tier +
        audit + login + peringkat). Dipakai /unlink."""
        self._conn.execute("DELETE FROM backups WHERE chat_id=?", (chat_id,))
        self._conn.execute("DELETE FROM jadwal WHERE chat_id=?", (chat_id,))
        self._conn.execute("DELETE FROM audit_log WHERE chat_id=?", (chat_id,))
        self._conn.execute("DELETE FROM login_lacak WHERE chat_id=?", (chat_id,))
        self._conn.execute("DELETE FROM peringkat WHERE chat_id=?", (chat_id,))
        self._conn.execute("DELETE FROM mode_target WHERE chat_id=?", (chat_id,))
        self._conn.execute("DELETE FROM meta WHERE chat_id=?", (chat_id,))
        self._conn.execute("DELETE FROM users WHERE chat_id=?", (chat_id,))
        self._conn.commit()

    def all_chat_ids(self) -> list[int]:
        """Semua chat yang tertaut (untuk job pemantauan global Fase 5)."""
        rows = self._conn.execute("SELECT chat_id FROM users").fetchall()
        return [int(r["chat_id"]) for r in rows]

    # -- slot aktif (Fase 5: /slot) ----------------------------------------
    def get_slot_aktif(self, chat_id: int) -> int | None:
        """Nomor slot (1-6) yang dipilih pengguna, atau None (= slot
        terbaik seperti ``kemajuan_hp``)."""
        row = self._conn.execute(
            "SELECT slot_aktif FROM users WHERE chat_id=?", (chat_id,)
        ).fetchone()
        if row is None or row["slot_aktif"] is None:
            return None
        try:
            nomor = int(row["slot_aktif"])
        except (TypeError, ValueError):
            return None
        return nomor if 1 <= nomor <= 6 else None

    def set_slot_aktif(self, chat_id: int, nomor: int | None) -> None:
        """Pilih slot aktif (1-6); None = kembali ke slot terbaik."""
        if nomor is not None and not 1 <= int(nomor) <= 6:
            raise ValueError("nomor slot harus 1-6")
        self._conn.execute(
            "UPDATE users SET slot_aktif=?, updated_at=? WHERE chat_id=?",
            (None if nomor is None else int(nomor),
             int(time.time()), chat_id),
        )
        self._conn.commit()

    # -- meta generik (Fase 5: snapshot pasaran, versi diberitahu, dll) -----
    def meta_get(self, chat_id: int, kunci: str) -> str | None:
        row = self._conn.execute(
            "SELECT nilai FROM meta WHERE chat_id=? AND kunci=?",
            (chat_id, str(kunci)),
        ).fetchone()
        return None if row is None else str(row["nilai"])

    def meta_set(self, chat_id: int, kunci: str, nilai: str) -> None:
        self._conn.execute(
            """
            INSERT INTO meta (chat_id, kunci, nilai, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, kunci) DO UPDATE SET
                nilai=excluded.nilai, updated_at=excluded.updated_at
            """,
            (chat_id, str(kunci), str(nilai), int(time.time())),
        )
        self._conn.commit()

    # -- tier + otomatis (Fase 3) ---------------------------------------
    def get_tier(self, chat_id: int) -> int:
        row = self._conn.execute(
            "SELECT tier FROM users WHERE chat_id=?", (chat_id,)
        ).fetchone()
        if row is None or row["tier"] is None:
            return 1
        try:
            t = int(row["tier"])
        except (TypeError, ValueError):
            return 1
        return t if t in (1, 2, 3) else 1

    def set_tier(self, chat_id: int, tier: int) -> None:
        if int(tier) not in (1, 2, 3):
            raise ValueError("tier harus 1, 2, atau 3")
        self._conn.execute(
            "UPDATE users SET tier=?, updated_at=? WHERE chat_id=?",
            (int(tier), int(time.time()), chat_id),
        )
        self._conn.commit()

    def get_otomatis(self, chat_id: int) -> bool:
        row = self._conn.execute(
            "SELECT otomatis FROM users WHERE chat_id=?", (chat_id,)
        ).fetchone()
        return bool(row["otomatis"]) if row is not None else False

    def set_otomatis(self, chat_id: int, aktif: bool) -> None:
        self._conn.execute(
            "UPDATE users SET otomatis=?, updated_at=? WHERE chat_id=?",
            (1 if aktif else 0, int(time.time()), chat_id),
        )
        self._conn.commit()

    def get_batas_harian(self, chat_id: int) -> int:
        row = self._conn.execute(
            "SELECT batas_harian FROM users WHERE chat_id=?", (chat_id,)
        ).fetchone()
        if row is None or row["batas_harian"] is None:
            return 1_000_000
        try:
            return max(0, int(row["batas_harian"]))
        except (TypeError, ValueError):
            return 1_000_000

    def set_batas_harian(self, chat_id: int, batas: int) -> None:
        if int(batas) < 0:
            raise ValueError("batas harian tidak boleh negatif")
        self._conn.execute(
            "UPDATE users SET batas_harian=?, updated_at=? WHERE chat_id=?",
            (int(batas), int(time.time()), chat_id),
        )
        self._conn.commit()

    def get_jam_otomatis(self, chat_id: int) -> int:
        row = self._conn.execute(
            "SELECT jam_otomatis FROM users WHERE chat_id=?", (chat_id,)
        ).fetchone()
        if row is None or row["jam_otomatis"] is None:
            return 7
        try:
            jam = int(row["jam_otomatis"])
        except (TypeError, ValueError):
            return 7
        return jam if 0 <= jam <= 23 else 7

    def set_jam_otomatis(self, chat_id: int, jam: int) -> None:
        if not 0 <= int(jam) <= 23:
            raise ValueError("jam harus 0-23")
        self._conn.execute(
            "UPDATE users SET jam_otomatis=?, updated_at=? WHERE chat_id=?",
            (int(jam), int(time.time()), chat_id),
        )
        self._conn.commit()

    # -- mode baca saja (Fase 4: Mini App) ---------------------------------
    def get_baca_saja(self, chat_id: int) -> bool:
        row = self._conn.execute(
            "SELECT baca_saja FROM users WHERE chat_id=?", (chat_id,)
        ).fetchone()
        return bool(row["baca_saja"]) if row is not None else False

    def set_baca_saja(self, chat_id: int, aktif: bool) -> None:
        self._conn.execute(
            "UPDATE users SET baca_saja=?, updated_at=? WHERE chat_id=?",
            (1 if aktif else 0, int(time.time()), chat_id),
        )
        self._conn.commit()

    def all_otomatis(self) -> list[dict]:
        """Semua chat dengan otomatis=1 (untuk muat ulang job saat start)."""
        rows = self._conn.execute(
            "SELECT chat_id, tier, jam_otomatis FROM users WHERE otomatis=1"
        ).fetchall()
        return [{"chat_id": r["chat_id"], "tier": r["tier"],
                 "jam": r["jam_otomatis"]} for r in rows]

    # -- mode target level (Fase 3+) --------------------------------------
    def get_mode_target(self, chat_id: int) -> dict | None:
        """Mode Target aktif chat ini, atau None bila tidak aktif."""
        row = self._conn.execute(
            "SELECT target_tingkat, siklus, dimulai FROM mode_target "
            "WHERE chat_id=?", (chat_id,)
        ).fetchone()
        if row is None:
            return None
        return {"target_tingkat": int(row["target_tingkat"]),
                "siklus": int(row["siklus"]),
                "dimulai": int(row["dimulai"])}

    def set_mode_target(self, chat_id: int, target_tingkat: int) -> None:
        """Nyalakan Mode Target (siklus dihitung dari 0)."""
        kini = int(time.time())
        self._conn.execute(
            """
            INSERT INTO mode_target (chat_id, target_tingkat, siklus,
                                     dimulai, updated_at)
            VALUES (?, ?, 0, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                target_tingkat=excluded.target_tingkat, siklus=0,
                dimulai=excluded.dimulai, updated_at=excluded.updated_at
            """,
            (chat_id, int(target_tingkat), kini, kini),
        )
        self._conn.commit()

    def tambah_siklus_target(self, chat_id: int) -> int:
        """Naikkan hitungan siklus Mode Target; kembalikan jumlah baru."""
        self._conn.execute(
            "UPDATE mode_target SET siklus=siklus+1, updated_at=? "
            "WHERE chat_id=?", (int(time.time()), chat_id),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT siklus FROM mode_target WHERE chat_id=?", (chat_id,)
        ).fetchone()
        return int(row["siklus"]) if row is not None else 0

    def hapus_mode_target(self, chat_id: int) -> None:
        """Matikan Mode Target chat ini."""
        self._conn.execute(
            "DELETE FROM mode_target WHERE chat_id=?", (chat_id,))
        self._conn.commit()

    def all_mode_target(self) -> list[dict]:
        """Semua chat dengan Mode Target aktif (muat ulang job saat start)."""
        rows = self._conn.execute(
            "SELECT chat_id, target_tingkat, siklus, dimulai "
            "FROM mode_target"
        ).fetchall()
        return [{"chat_id": r["chat_id"],
                 "target_tingkat": int(r["target_tingkat"]),
                 "siklus": int(r["siklus"]),
                 "dimulai": int(r["dimulai"])} for r in rows]

    # -- log audit (Fase 3) ---------------------------------------------
    def log_audit(self, chat_id: int, aksi: str, detail: str = "",
                  lama: str = "", baru: str = "") -> None:
        """Catat satu aksi otomatis/manual: apa, kapan, lama -> baru."""
        self._conn.execute(
            "INSERT INTO audit_log (chat_id, waktu, aksi, detail, lama, baru)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, int(time.time()), str(aksi), str(detail),
             str(lama), str(baru)),
        )
        self._conn.commit()

    def get_audit(self, chat_id: int, sejak: int, limit: int = 200) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM audit_log WHERE chat_id=? AND waktu>=?"
            " ORDER BY waktu DESC, id DESC LIMIT ?",
            (chat_id, int(sejak), int(limit)),
        ).fetchall()
        return [{"waktu": r["waktu"], "aksi": r["aksi"],
                 "detail": r["detail"], "lama": r["lama"],
                 "baru": r["baru"]} for r in rows]

    # -- pelacak login harian (Fase 3) -----------------------------------
    # Bot hanya MENCATAT klaim yang dikonfirmasi pengguna (pengingat),
    # karena state login asli tinggal di pengaturan.cfg HP (bukan cloud).
    def get_login_lacak(self, chat_id: int) -> dict:
        row = self._conn.execute(
            "SELECT * FROM login_lacak WHERE chat_id=?", (chat_id,)
        ).fetchone()
        if row is None:
            return {"hari_ke": 0, "tanggal": "", "siklus": 0}
        return {"hari_ke": int(row["hari_ke"]), "tanggal": str(row["tanggal"]),
                "siklus": int(row["siklus"])}

    def set_login_lacak(self, chat_id: int, hari_ke: int, tanggal: str,
                        siklus: int = 0) -> None:
        self._conn.execute(
            """
            INSERT INTO login_lacak (chat_id, hari_ke, tanggal, siklus, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                hari_ke=excluded.hari_ke, tanggal=excluded.tanggal,
                siklus=excluded.siklus, updated_at=excluded.updated_at
            """,
            (chat_id, int(hari_ke), str(tanggal), int(siklus), int(time.time())),
        )
        self._conn.commit()

    # -- peringkat (Fase 3) ----------------------------------------------
    def save_peringkat(self, chat_id: int, tab: str,
                       peringkat: int | None, jumlah_warung: int = 0) -> None:
        self._conn.execute(
            """
            INSERT INTO peringkat (chat_id, tab, peringkat, jumlah_warung, waktu)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, tab) DO UPDATE SET
                peringkat=excluded.peringkat,
                jumlah_warung=excluded.jumlah_warung,
                waktu=excluded.waktu
            """,
            (chat_id, str(tab),
             None if peringkat is None else int(peringkat),
             int(jumlah_warung or 0), int(time.time())),
        )
        self._conn.commit()

    def get_peringkat(self, chat_id: int, tab: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM peringkat WHERE chat_id=? AND tab=?",
            (chat_id, str(tab)),
        ).fetchone()
        if row is None:
            return None
        return {"peringkat": row["peringkat"],
                "jumlah_warung": row["jumlah_warung"],
                "waktu": row["waktu"]}

    # -- jadwal laporan harian (Fase 2) ---------------------------------
    def set_jadwal(self, chat_id: int, jam: int, aktif: bool = True) -> None:
        """Simpan jam laporan harian (WIB, 0-23) + status aktif."""
        if not 0 <= int(jam) <= 23:
            raise ValueError("jam harus 0-23")
        self._conn.execute(
            """
            INSERT INTO jadwal (chat_id, jam, aktif, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                jam=excluded.jam, aktif=excluded.aktif,
                updated_at=excluded.updated_at
            """,
            (chat_id, int(jam), 1 if aktif else 0, int(time.time())),
        )
        self._conn.commit()

    def get_jadwal(self, chat_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM jadwal WHERE chat_id=?", (chat_id,)
        ).fetchone()
        if row is None:
            return None
        return {"chat_id": row["chat_id"], "jam": row["jam"],
                "aktif": bool(row["aktif"])}

    def delete_jadwal(self, chat_id: int) -> None:
        self._conn.execute("DELETE FROM jadwal WHERE chat_id=?", (chat_id,))
        self._conn.commit()

    def all_jadwal(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM jadwal").fetchall()
        return [{"chat_id": r["chat_id"], "jam": r["jam"],
                 "aktif": bool(r["aktif"])} for r in rows]

    # -- cadangan paket (rollback sebelum upload) -----------------------
    def save_backup(self, chat_id: int, versi: int, p_data: str) -> None:
        self._conn.execute(
            "INSERT INTO backups (chat_id, versi, p_data_enc, created_at)"
            " VALUES (?, ?, ?, ?)",
            (chat_id, int(versi), self._enc(p_data), int(time.time())),
        )
        self._conn.commit()

    def get_latest_backup(self, chat_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM backups WHERE chat_id=? ORDER BY id DESC LIMIT 1",
            (chat_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "versi": row["versi"],
            "p_data": self._dec(row["p_data_enc"]),
            "created_at": row["created_at"],
        }

    def list_backups(self, chat_id: int, limit: int = 30) -> list[dict]:
        """Semua arsip paket (terbaru dulu) — Fase 5 /backup."""
        rows = self._conn.execute(
            "SELECT id, versi, created_at FROM backups WHERE chat_id=?"
            " ORDER BY id DESC LIMIT ?",
            (chat_id, int(limit)),
        ).fetchall()
        return [{"id": r["id"], "versi": r["versi"],
                 "created_at": r["created_at"]} for r in rows]

    def get_backup(self, chat_id: int, backup_id: int) -> dict | None:
        """Satu arsip (dengan p_data terdekripsi). None bila tidak ada."""
        row = self._conn.execute(
            "SELECT * FROM backups WHERE chat_id=? AND id=?",
            (chat_id, int(backup_id)),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "versi": row["versi"],
            "p_data": self._dec(row["p_data_enc"]),
            "created_at": row["created_at"],
        }
