"""Tes wiring main.py — aplikasi terbangun tanpa polling."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from bot.main import build_application, load_context
from bot.tg import keyboards as kb


async def test_load_context_isi_lengkap(monkeypatch, tmp_path):
    monkeypatch.setenv("BOT_TOKEN", TOKEN_PALSU_VALID)
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DB_PATH", str(tmp_path / "bot.db"))
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "123, 456")
    ctx = load_context()
    try:
        assert ctx["bot_token"] == TOKEN_PALSU_VALID
        assert ctx["allowed"] == {123, 456}
        assert "store" in ctx and "cloud" in ctx
        assert "tugas" in ctx and "data" in ctx
        assert len(ctx["tugas"]["tingkat"]) == 10
    finally:
        ctx["store"].close()
        await ctx["cloud"].close()


def test_main_menu_tanpa_url_tidak_ada_web_app(monkeypatch):
    monkeypatch.delenv("MINIAPP_URL", raising=False)
    menu = kb.main_menu()
    assert all(
        b.web_app is None
        for baris in menu.inline_keyboard for b in baris
    )


def test_main_menu_dengan_url_ada_web_app(monkeypatch):
    monkeypatch.setenv("MINIAPP_URL", "https://contoh.test/miniapp/")
    menu = kb.main_menu()
    tombol = menu.inline_keyboard[0][0]
    assert tombol.text == "Buka Dashboard"
    assert tombol.web_app is not None
    assert tombol.web_app.url == "https://contoh.test/miniapp/"


def test_status_keyboard_dengan_url_ada_web_app(monkeypatch):
    monkeypatch.setenv("MINIAPP_URL", "https://contoh.test/miniapp/")
    menu = kb.status_keyboard()
    tombol = menu.inline_keyboard[0][0]
    assert tombol.text == "Buka Dashboard"
    assert tombol.web_app is not None


def test_load_context_gagal_tanpa_bot_token(monkeypatch):
    # .env asli di repo (saat live-run) ikut dimuat load_context via
    # setdefault — matikan pemuat .env supaya tes ini menguji ketiadaan
    # token, bukan isi .env.
    monkeypatch.setattr("bot.main._load_dotenv", lambda path: None)
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    with pytest.raises(SystemExit):
        load_context()

TOKEN_PALSU_VALID = "123456789:" + "A" * 35


def test_build_gagal_tanpa_bot_token(monkeypatch):
    monkeypatch.setattr("bot.main._load_dotenv", lambda path: None)
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    with pytest.raises(SystemExit):
        build_application()


def test_build_gagal_tanpa_fernet_key(monkeypatch):
    monkeypatch.setattr("bot.main._load_dotenv", lambda path: None)
    monkeypatch.setenv("BOT_TOKEN", TOKEN_PALSU_VALID)
    monkeypatch.delenv("FERNET_KEY", raising=False)
    with pytest.raises(SystemExit):
        build_application()


async def test_build_ok_dan_handler_terdaftar(monkeypatch, tmp_path):
    monkeypatch.setenv("BOT_TOKEN", TOKEN_PALSU_VALID)
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DB_PATH", str(tmp_path / "bot.db"))
    app = build_application()
    try:
        assert "store" in app.bot_data
        assert "cloud" in app.bot_data
        assert "tugas" in app.bot_data
        assert "data" in app.bot_data  # Fase 2: GameData (6 JSON)
        assert len(app.bot_data["tugas"]["tingkat"]) == 10
        perintah = set()
        for grup in app.handlers.values():
            for h in grup:
                if hasattr(h, "commands"):
                    perintah.update(h.commands)
        for wajib in (
            "start", "menu", "bantuan", "batal", "link", "unlink",
            "status", "tugas", "tugas_selesai", "sync", "upload_paksa",
            # Fase 2 — Simulasi & perencana.
            "simulasi", "harga_terbaik", "stok", "jadwal", "kapan_naik",
            "roi_upgrade", "whatif",
        ):
            assert wajib in perintah, f"perintah /{wajib} belum terdaftar"
    finally:
        app.bot_data["store"].close()
        await app.bot_data["cloud"].close()
