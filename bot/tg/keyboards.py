"""Inline keyboard — teks polos TANPA emoji (RANCANGAN §15.2).

Aturan Bot Guidelines yang dipakai: menu memakai INLINE keyboard, bukan
custom reply keyboard; label singkat dan jelas; callback_data < 64 byte.
"""

from __future__ import annotations

import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

# Awalan callback_data per layar/aksi.
CB_MENU = "menu"
CB_STATUS = "status"
CB_TUGAS = "tugas"
CB_UANG = "uang"
CB_SYNC = "sync"
CB_PENGATURAN = "pengaturan"
CB_KONFIRM = "konfirm"
CB_BENTROK = "bentrok"
CB_LINK = "link"
CB_BATAL = "batal"


def main_menu(miniapp_url: str | None = None) -> InlineKeyboardMarkup:
    """Menu utama (Fase 1 + Fase 2).

    Bila ``miniapp_url`` diisi (atau env MINIAPP_URL), baris pertama adalah
    tombol web_app "Buka Dashboard" (Mini App, Fase 4).
    """
    url = miniapp_url or os.environ.get("MINIAPP_URL") or None
    baris: list[list[InlineKeyboardButton]] = []
    if url:
        baris.append([
            InlineKeyboardButton(
                "Buka Dashboard",
                web_app=WebAppInfo(url=url),
            )
        ])
    baris += [
        [
            InlineKeyboardButton("Status", callback_data=f"{CB_MENU}:status"),
            InlineKeyboardButton("Tugas", callback_data=f"{CB_MENU}:tugas"),
        ],
        [
            InlineKeyboardButton("Ubah Uang", callback_data=f"{CB_MENU}:uang"),
            InlineKeyboardButton("Sinkron", callback_data=f"{CB_MENU}:sync"),
        ],
        [
            InlineKeyboardButton("Simulasi", callback_data="sim:menu"),
            InlineKeyboardButton("Stok", callback_data="sim:stok"),
        ],
        [
            InlineKeyboardButton("Kerja 24/7", callback_data="tier:menu"),
            InlineKeyboardButton("Laporan", callback_data="laporan:harian"),
        ],
        [
            InlineKeyboardButton("Aksi Cepat", callback_data="cepat:menu"),
            InlineKeyboardButton("Pengaturan", callback_data=f"{CB_MENU}:pengaturan"),
        ],
    ]
    return InlineKeyboardMarkup(baris)


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Kembali ke Menu", callback_data=f"{CB_MENU}:root")]]
    )


def status_keyboard(miniapp_url: str | None = None) -> InlineKeyboardMarkup:
    """Keyboard kartu status (+ tombol Buka Dashboard bila URL tersedia)."""
    url = miniapp_url or os.environ.get("MINIAPP_URL") or None
    baris: list[list[InlineKeyboardButton]] = []
    if url:
        baris.append([
            InlineKeyboardButton("Buka Dashboard", web_app=WebAppInfo(url=url))
        ])
    baris += [
        [
            InlineKeyboardButton("Perbarui", callback_data=f"{CB_STATUS}:refresh"),
            InlineKeyboardButton(
                "Selesaikan Tugas", callback_data=f"{CB_TUGAS}:isi"
            ),
        ],
        [
            InlineKeyboardButton("Ubah Uang", callback_data=f"{CB_UANG}:pilih"),
            InlineKeyboardButton("Sinkron", callback_data=f"{CB_SYNC}:ambil"),
        ],
        [
            InlineKeyboardButton(
                "Kembali ke Menu", callback_data=f"{CB_MENU}:root"
            ),
        ],
    ]
    return InlineKeyboardMarkup(baris)


def money_keyboard() -> InlineKeyboardMarkup:
    """Pilih nominal tambah (quick buttons = TAMBAH ke uang sekarang)."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("+100rb", callback_data=f"{CB_UANG}:tambah:100000"),
                InlineKeyboardButton("+500rb", callback_data=f"{CB_UANG}:tambah:500000"),
                InlineKeyboardButton("+1jt", callback_data=f"{CB_UANG}:tambah:1000000"),
            ],
            [
                InlineKeyboardButton(
                    "Ketik Jumlah Sendiri", callback_data=f"{CB_UANG}:ketik"
                ),
            ],
            [
                InlineKeyboardButton("Batal", callback_data=f"{CB_BATAL}:uang"),
            ],
        ]
    )


def confirm_keyboard(aksi: str) -> InlineKeyboardMarkup:
    """Konfirmasi sebelum aksi tulis. ``aksi`` = id aksi tertunda."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Ya, Upload", callback_data=f"{CB_KONFIRM}:ya:{aksi}"
                ),
                InlineKeyboardButton("Batal", callback_data=f"{CB_KONFIRM}:tidak:{aksi}"),
            ],
        ]
    )


def conflict_keyboard() -> InlineKeyboardMarkup:
    """Pilihan saat server menjawab bentrok."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Pakai Simpanan Online", callback_data=f"{CB_BENTROK}:pakai"
                ),
            ],
            [
                InlineKeyboardButton(
                    "Timpa dengan Punya Saya", callback_data=f"{CB_BENTROK}:timpa"
                ),
            ],
        ]
    )


def link_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Cara Mengambil akun.json", callback_data=f"{CB_LINK}:cara"
                ),
            ],
            [
                InlineKeyboardButton("Batal", callback_data=f"{CB_BATAL}:link"),
            ],
        ]
    )


def unlink_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Ya, Hapus Semua", callback_data=f"{CB_KONFIRM}:ya:unlink"
                ),
                InlineKeyboardButton(
                    "Batal", callback_data=f"{CB_KONFIRM}:tidak:unlink"
                ),
            ],
        ]
    )
