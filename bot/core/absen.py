"""Fitur absen harian game (logika lokal, seperti /cuan).

Setiap satu hari game yang disimulasikan bot, bot "absen" dan
menambahkan uang ke save: hadiah harian + bonus di hari ke-3, ke-7,
dan ke-30 dari siklus. Setelah hari ke-30, siklus kembali ke hari ke-1.

- Nominal harian diatur pengguna lewat /absen_set (0 = absen mati).
- Bonus: hari ke-3 = 2x, hari ke-7 = 3x, hari ke-30 = 10x.
- Pelacakan hari siklus disimpan di Store (tabel meta), BUKAN di save —
  supaya tidak menyentuh struktur save yang dibaca game.

Fungsi di sini MURNI (mengubah salinan slot, tanpa I/O).
"""

from __future__ import annotations

BONUS_SIKLUS = {3: 2, 7: 3, 30: 10}  # hari siklus -> pengali hadiah
SIKLUS_PANJANG = 30  # setelah hari ke-30, kembali ke hari ke-1


def berikutnya(hari_terakhir: int) -> int:
    """Nomor hari siklus absen berikutnya (1-30, berulang).

    ``hari_terakhir`` = hari siklus yang SUDAH dipakai terakhir kali
    (0 = belum pernah absen). Berikutnya = +1, wrap di 30 -> 1.
    """
    h = int(hari_terakhir)
    if h < 0:
        h = 0
    return (h % SIKLUS_PANJANG) + 1


def jumlah_hadiah(nominal: int, hari_siklus: int) -> int:
    """Total uang absen untuk hari siklus tertentu (hadiah + bonus)."""
    if nominal <= 0:
        return 0
    pengali = int(BONUS_SIKLUS.get(int(hari_siklus), 1))
    return int(nominal) * pengali


def terapkan_absen(slot: dict, nominal: int, hari_terakhir: int) -> dict | None:
    """Tambah uang absen ke salinan slot (murni).

    Mengembalikan dict hasil {ok, hari_siklus, jumlah, bonus} bila uang
    ditambahkan, atau None bila nominal 0 / tidak ada yang ditambahkan.
    """
    if nominal <= 0:
        return None
    n = berikutnya(hari_terakhir)
    total = jumlah_hadiah(int(nominal), n)
    bonus = total - int(nominal)
    slot["uang"] = int(slot.get("uang", 0)) + total
    return {"ok": True, "hari_siklus": n, "jumlah": total, "bonus": bonus}


def teks_hadiah(n: int, nominal: int) -> str:
    """Teks ringkas hadiah hari siklus ke-n (dipakai laporan)."""
    total = jumlah_hadiah(nominal, n)
    bonus = int(BONUS_SIKLUS.get(n, 1))
    if bonus > 1:
        return (f"Absen hari siklus ke-{n}: "
                f"{total} (bonus {bonus}x)")
    return f"Absen hari siklus ke-{n}: {total}"
