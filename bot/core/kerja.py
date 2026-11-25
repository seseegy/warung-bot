"""Mode Kerja 24/7 — 1 hari game tiap interval, tanpa target, jalan terus.

Bedanya dengan Mode Target/Kejar:
- TANPA target level / peringkat -> tidak pernah berhenti karena
  "tercapai". Berhenti hanya bila bermasalah (bentrok, sesi habis,
  diusir, macet, maks siklus).
- Tujuannya murni mesin hari-game: absen harian + cuan + siklus ekonomi
  berjalan terus selama mode nyala.

INTERVAL_MENIT = 5 (1 hari game tiap 5 menit, seperti Mode Target/Kejar).
MAKS_SIKLUS = batas aman siklus sebelum mode berhenti sendiri.
"""

from __future__ import annotations

INTERVAL_MENIT = 5
MAKS_SIKLUS = 10_000  # 10.000 hari game ~= 35 hari nyata sebelum berhenti


def alasan_berhenti(slot: dict, siklus: int) -> str | None:
    """Alasan berhenti mode kerja (None = lanjut)."""
    if int(siklus) >= MAKS_SIKLUS:
        return "maks_siklus"
    if slot.get("diusir"):
        return "diusir"
    if int(slot.get("uang", 0)) <= 0 and total_stok(slot) <= 0:
        return "macet"
    return None


def total_stok(slot: dict) -> int:
    """Total unit stok barang fisik."""
    stok = slot.get("stok", {}) or {}
    return sum(int(v) for v in stok.values() if int(v) > 0)


TEKS_BERHENTI = {
    "maks_siklus": (
        f"Batas {MAKS_SIKLUS} siklus tercapai. Nyalakan lagi bila mau lanjut."
    ),
    "uang_minus": (
        "Uang save MINUS — mode berhenti supaya tidak makin berdarah."
    ),
    "diusir": "Warung diusir (sewa menunggak 3 minggu). Mode berhenti.",
    "macet": (
        "Uang habis dan rak kosong — bot tidak bisa jualan lagi."
    ),
    "bentrok": (
        "Simpanan di cloud berubah (kemungkinan game baru saja mengunggah). "
        "Mode berhenti supaya tidak ada yang tertimpa."
    ),
    "sesi_habis": (
        "Sesi login habis. Kirim ulang akun.json dengan /link, lalu "
        "nyalakan lagi."
    ),
}


def teks_berhenti(alasan: str) -> str:
    """Teks pengguna untuk satu alasan berhenti."""
    return TEKS_BERHENTI.get(alasan, f"Mode berhenti ({alasan}).")
