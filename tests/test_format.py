"""Tes format tampilan + keyboard (tg/status.py, tg/keyboards.py, handlers)."""

from __future__ import annotations

import json

from bot.tg import keyboards as kb
from bot.tg.handlers import _parse_jumlah
from bot.tg.status import (
    format_rupiah,
    format_rupiah_compact,
    format_status_card,
    format_task_card,
    progress_bar,
)

# Rentang codepoint emoji yang umum (bukan blok grafis █/░, bukan tanda baca).
EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),
    (0x2600, 0x27BF),
    (0x2B00, 0x2BFF),
    (0xFE00, 0xFE0F),
    (0x1F1E6, 0x1F1FF),
)


def _ada_emoji(teks: str) -> bool:
    return any(
        any(lo <= ord(ch) <= hi for lo, hi in EMOJI_RANGES) for ch in teks
    )


def test_format_rupiah():
    assert format_rupiah(4500000) == "Rp4.500.000"
    assert format_rupiah(0) == "Rp0"
    assert format_rupiah(999) == "Rp999"


def test_format_rupiah_compact():
    assert format_rupiah_compact(2100000) == "Rp2,1jt"
    assert format_rupiah_compact(4500000) == "Rp4,5jt"
    assert format_rupiah_compact(1000000) == "Rp1jt"
    assert format_rupiah_compact(1500) == "Rp1,5rb"
    assert format_rupiah_compact(500) == "Rp500"


def test_progress_bar():
    assert progress_bar(210, 350) == "██████░░░░"
    assert progress_bar(0, 100) == "░░░░░░░░░░"
    assert progress_bar(100, 100) == "██████████"
    assert progress_bar(150, 100) == "██████████"  # melebihi target -> penuh
    assert progress_bar(0, 0) == "██████████"  # tanpa syarat -> penuh


def test_status_card(tugas_data, sample_slot):
    from bot.core.save import slot_summary

    ringkasan = slot_summary(sample_slot)
    teks = format_status_card(ringkasan, sample_slot, tugas_data, 8)
    assert "Warung Barokah" in teks
    assert "Level 2" in teks
    assert "Rp4.500.000" in teks
    assert "Mulai Dikenal" in teks  # nama tugas Lv 2
    assert "Simpanan online v8" in teks
    assert not _ada_emoji(teks)


def test_status_card_tampilkan_jam_sinkron(tugas_data, sample_slot):
    from bot.core.save import slot_summary

    ringkasan = slot_summary(sample_slot)
    teks = format_status_card(
        ringkasan, sample_slot, tugas_data, 8, "2026-11-24 15:24:10")
    assert "disimpan" in teks
    assert "disinkronkan 24 Nov 2026 15:24 WIB" in teks
    # Tanpa jam sinkron, baris tambahan tidak muncul (kompatibel lama).
    teks_tanpa = format_status_card(ringkasan, sample_slot, tugas_data, 8)
    assert "disinkronkan" not in teks_tanpa


def test_task_card_tampilkan_blocker_upgrade(tugas_data, sample_slot):
    teks = format_task_card(sample_slot, tugas_data)
    assert "Mulai Dikenal" in teks
    assert "kipas" in teks
    assert "belum dimiliki" in teks
    assert not _ada_emoji(teks)


def test_task_card_tanpa_blocker_bila_upgrade_dimiliki(tugas_data):
    slot = {
        "tingkat": 1,
        "progres": {"pelanggan": 40, "barang": 70, "omzet": 400000, "khusus": 8},
        "upgrade": ["kipas"],
        "misi_status": "lunas",
        "cerita_tamat": False,
    }
    teks = format_task_card(slot, tugas_data)
    assert "sudah dimiliki" in teks
    assert "belum dimiliki" not in teks


def test_semua_tombol_tanpa_emoji():
    markups = [
        kb.main_menu(),
        kb.back_to_menu(),
        kb.status_keyboard(),
        kb.money_keyboard(),
        kb.confirm_keyboard("uang"),
        kb.conflict_keyboard(),
        kb.link_keyboard(),
        kb.unlink_confirm_keyboard(),
    ]
    for markup in markups:
        for baris in markup.inline_keyboard:
            for tombol in baris:
                assert not _ada_emoji(tombol.text), tombol.text
                assert len(tombol.callback_data.encode()) < 64


def test_parse_jumlah():
    assert _parse_jumlah("5000000") == 5000000
    assert _parse_jumlah("5.000.000") == 5000000
    assert _parse_jumlah("Rp 5.000.000") == 5000000
    assert _parse_jumlah("500rb") == 500000
    assert _parse_jumlah("1,5jt") == 1500000
    assert _parse_jumlah("1jt") == 1000000
    assert _parse_jumlah("abc") is None
    assert _parse_jumlah("") is None
    assert _parse_jumlah("-100") is None
    assert _parse_jumlah("0") == 0


def test_parse_jumlah_titik_desimal_vs_ribuan():
    # "." desimal bila pecahan bukan 3 digit; ribuan bila 3 digit / >= 2x.
    assert _parse_jumlah("1.5jt") == 1500000
    assert _parse_jumlah("5.000") == 5000
    assert _parse_jumlah("1.000.000") == 1000000
    assert _parse_jumlah("2,5rb") == 2500
