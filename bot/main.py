"""Entry point bot Telegram Warung Life Simulator — Fase 1 (MVP) + Fase 2
(Simulasi & perencana).

Jalankan:  BOT_TOKEN=... FERNET_KEY=... .venv/bin/python -m bot.main
Lihat README.md untuk cara menyiapkan .env.

Semua rahasia dari environment, tidak pernah di-hardcode:
- BOT_TOKEN: token bot dari @BotFather (wajib).
- FERNET_KEY: kunci enkripsi token akun (wajib; buat dengan
  ``.venv/bin/python -c "from cryptography.fernet import Fernet;
  print(Fernet.generate_key().decode())"``).
- SUPABASE_URL / SUPABASE_KEY: default = server + publishable key game
  (publik by design, ada di APK).
- ALLOWED_CHAT_IDS: daftar chat id dipisah koma; kosong = semua boleh
  (tidak disarankan untuk pemakaian nyata).
- DB_PATH: lokasi SQLite (default data/bot.db di folder proyek).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from .core import jobs as jobs_mod
from .core.cloud import SUPABASE_KEY, SUPABASE_URL, SupabaseClient
from .core.sim import GameData
from .core.store import Store
from .tg import handlers
from .tg import sim as sim_tg
from .tg import tiers as tiers_tg
from .tg import cepat as cepat_tg

log = logging.getLogger("warung-bot")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_dotenv(path: Path) -> None:
    """Muat file .env sederhana (KEY=VALUE, # komentar). Tanpa dependensi."""
    if not path.exists():
        return
    for baris in path.read_text(encoding="utf-8").splitlines():
        baris = baris.strip()
        if not baris or baris.startswith("#") or "=" not in baris:
            continue
        kunci, nilai = baris.split("=", 1)
        kunci = kunci.strip()
        nilai = nilai.strip().strip('"').strip("'")
        os.environ.setdefault(kunci, nilai)


def _parse_allowed(raw: str) -> set[int]:
    hasil: set[int] = set()
    for bagian in raw.split(","):
        bagian = bagian.strip()
        if not bagian:
            continue
        try:
            hasil.add(int(bagian))
        except ValueError:
            log.warning("ALLOWED_CHAT_IDS berisi nilai bukan angka: %r", bagian)
    return hasil


def _proxy_dari_env() -> str | None:
    """URL proxy egress eksplisit, bila ada.

    Dibaca dari HTTPS_PROXY/https_proxy/HTTP_PROXY/http_proxy/ALL_PROXY/
    all_proxy (.env atau environment). Dipakai eksplisit (bukan via
    trust_env) supaya httpx tidak mem-parse no_proxy host yang rusak
    ("[::1]") dan supaya systemd service — yang tidak mewarisi proxy
    shell — tetap bisa egress. None = koneksi langsung (VPS biasa).
    Nilai proxy TIDAK pernah di-log.
    """
    for kunci in (
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        nilai = os.environ.get(kunci, "").strip()
        if nilai:
            return nilai
    return None


def load_context() -> dict:
    """Muat konteks bersama bot polling + API Mini App (Fase 4).

    Membaca .env, memvalidasi BOT_TOKEN/FERNET_KEY, memuat tugas.json +
    GameData, membuka Store + SupabaseClient, mem-parse allowlist.
    Melempar SystemExit bila ada yang tidak bisa dimuat (perilaku lama
    build_application dipertahankan).
    """
    _load_dotenv(BASE_DIR / ".env")

    bot_token = os.environ.get("BOT_TOKEN", "")
    if not bot_token:
        raise SystemExit("BOT_TOKEN belum diisi (lihat .env.example)")
    fernet_key = os.environ.get("FERNET_KEY", "")
    if not fernet_key:
        raise SystemExit("FERNET_KEY belum diisi (lihat .env.example)")

    tugas_path = DATA_DIR / "tugas.json"
    try:
        tugas_data = json.loads(tugas_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"tidak bisa memuat {tugas_path}: {exc}") from exc
    if not isinstance(tugas_data, dict) or not tugas_data.get("tingkat"):
        raise SystemExit(f"{tugas_path} tidak berisi daftar 'tingkat'")
    try:
        game_data = GameData(DATA_DIR)
    except (OSError, KeyError) as exc:
        raise SystemExit(f"tidak bisa memuat data game (bot/data/): {exc}") from exc

    db_path = os.environ.get("DB_PATH", str(BASE_DIR / "data" / "bot.db"))
    store = Store(db_path, fernet_key)
    cloud = SupabaseClient(
        base_url=os.environ.get("SUPABASE_URL", SUPABASE_URL),
        api_key=os.environ.get("SUPABASE_KEY", SUPABASE_KEY),
        proxy=_proxy_dari_env(),
    )
    allowed = _parse_allowed(os.environ.get("ALLOWED_CHAT_IDS", ""))
    if not allowed:
        log.warning("ALLOWED_CHAT_IDS kosong — bot melayani semua chat")
    return {
        "bot_token": bot_token,
        "store": store,
        "cloud": cloud,
        "tugas": tugas_data,
        "data": game_data,
        "allowed": allowed,
    }


def build_application() -> Application:
    """Bangun Application (dipisah dari main() agar bisa diimpor/dites)."""
    ctx = load_context()
    store = ctx["store"]
    cloud = ctx["cloud"]
    tugas_data = ctx["tugas"]
    game_data = ctx["data"]
    allowed = ctx["allowed"]
    bot_token = ctx["bot_token"]

    # trust_env=False (lihat juga SupabaseClient): proxy env host tidak
    # dibaca — httpx gagal total saat konstruksi bila no_proxy berisi
    # entri IPv6 "[::1]" (teramati di VM). Proxy disampaikan eksplisit
    # lewat proxy_url dari _proxy_dari_env() bila ada (mis. sandbox ini);
    # None = langsung (VPS biasa). PTB membangun DUA request (bot +
    # get_updates), keduanya harus diatur.
    proxy = _proxy_dari_env()

    def _request() -> HTTPXRequest:
        return HTTPXRequest(
            connection_pool_size=8,
            proxy=proxy,
            httpx_kwargs={"trust_env": False},
        )

    app = (
        Application.builder()
        .token(bot_token)
        .request(_request())
        .get_updates_request(_request())
        .post_init(_startup)
        .post_shutdown(_shutdown)
        .build()
    )
    app.bot_data["store"] = store
    app.bot_data["cloud"] = cloud
    app.bot_data["tugas"] = tugas_data
    app.bot_data["data"] = game_data
    app.bot_data["allowed"] = allowed

    app.add_handler(CommandHandler("start", handlers.cmd_start))
    app.add_handler(CommandHandler("menu", handlers.cmd_menu))
    app.add_handler(CommandHandler("bantuan", handlers.cmd_bantuan))
    app.add_handler(CommandHandler("batal", handlers.cmd_batal))
    app.add_handler(CommandHandler("link", handlers.start_link))
    app.add_handler(CommandHandler("unlink", handlers.cmd_unlink))
    app.add_handler(CommandHandler("status", handlers.cmd_status))
    app.add_handler(CommandHandler("tugas", handlers.cmd_tugas))
    app.add_handler(CommandHandler("tugas_selesai", handlers.cmd_tugas_selesai))
    app.add_handler(CommandHandler("sync", handlers.cmd_sync))
    app.add_handler(CommandHandler("upload_paksa", handlers.cmd_upload_paksa))
    # Fase 2 — Simulasi & perencana.
    app.add_handler(CommandHandler("simulasi", sim_tg.cmd_simulasi))
    app.add_handler(CommandHandler("harga_terbaik", sim_tg.cmd_harga_terbaik))
    app.add_handler(CommandHandler("stok", sim_tg.cmd_stok))
    app.add_handler(CommandHandler("jadwal", sim_tg.cmd_jadwal))
    app.add_handler(CommandHandler("kapan_naik", sim_tg.cmd_kapan_naik))
    app.add_handler(CommandHandler("roi_upgrade", sim_tg.cmd_roi_upgrade))
    app.add_handler(CommandHandler("whatif", sim_tg.cmd_whatif))
    # Fase 3 — Kerja 24/7 (tiga tier).
    app.add_handler(CommandHandler("tier", tiers_tg.cmd_tier))
    app.add_handler(CommandHandler("otomatis", tiers_tg.cmd_otomatis))
    app.add_handler(CommandHandler("laporan", tiers_tg.cmd_laporan))
    app.add_handler(CommandHandler("bandingkan", tiers_tg.cmd_bandingkan))
    # Fase 5 — Pemantauan & jaga-jaga.
    app.add_handler(CommandHandler("jual", cepat_tg.cmd_jual))
    app.add_handler(CommandHandler("beli", cepat_tg.cmd_beli))
    app.add_handler(CommandHandler("ngopi", cepat_tg.cmd_ngopi))
    app.add_handler(CommandHandler("tutup", cepat_tg.cmd_tutup))
    app.add_handler(CommandHandler("slot", cepat_tg.cmd_slot))
    app.add_handler(CommandHandler("backup", cepat_tg.cmd_backup))
    app.add_handler(CommandHandler("rencana", cepat_tg.cmd_rencana))
    app.add_handler(CommandHandler("statistik", cepat_tg.cmd_statistik))
    app.add_handler(CallbackQueryHandler(handlers.on_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handlers.on_document))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_text)
    )
    app.add_error_handler(handlers.on_error)
    return app


async def _startup(app: Application) -> None:
    """Nyalakan scheduler laporan harian + muat jadwal tersimpan."""
    scheduler = jobs_mod.build_scheduler()
    app.bot_data["scheduler"] = scheduler
    jumlah = jobs_mod.muat_semua_jadwal(scheduler, app, app.bot_data["store"])
    log.info("jadwal laporan harian dimuat: %d job aktif", jumlah)
    jumlah_oto = jobs_mod.muat_semua_otomatis(
        scheduler, app, app.bot_data["store"])
    log.info("siklus otomatis dimuat: %d job aktif", jumlah_oto)
    # Fase 4: sinkronisasi berkala — perubahan pengaturan dari Mini App
    # (proses API terpisah) berlaku tanpa restart bot.
    jobs_mod.atur_sinkronisasi(scheduler, app)
    # Fase 5: pemantauan global (pasar Senin, cek versi, backup harian,
    # pengingat adu laris Jumat).
    jobs_mod.atur_pemantauan(scheduler, app)
    scheduler.start()


async def _shutdown(app: Application) -> None:
    """Tutup scheduler, klien HTTP + SQLite saat bot berhenti."""
    scheduler = app.bot_data.get("scheduler")
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    cloud = app.bot_data.get("cloud")
    if cloud is not None:
        await cloud.close()
    store = app.bot_data.get("store")
    if store is not None:
        store.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = build_application()
    log.info("bot mulai (long polling)")
    app.run_polling()


if __name__ == "__main__":
    main()
