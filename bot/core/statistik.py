"""Statistik Fase 5: barang laku & omzet dari riwayat save — /statistik.

Sumber data (semua dari save, ``simpan()`` game_state.gd:3343):
- ``penjualan_hari``: {id: [jumlah, omzet, laba]} — penjualan HARI INI
  per barang (ditulis tiap ``jual()``). Inilah satu-satunya rincian
  per barang di save.
- ``riwayat``: [{hari, omzet, laba, bersih, belanja, barang, dilayani,
  batal}] — ringkasan per hari (ditulis ``_tutup_hari`` /
  ``catat_riwayat_hari``). Tidak ada rincian per barang di sini.
- ``catatan_hari``: penghitung hari berjalan (omzet/laba/terjual/
  belanja/dilayani/batal/hadiah).

BATASAN JUJUR (dicatat juga di README): "pelanggan tersering" TIDAK
BISA dihitung dari save. ``riwayat_layan`` hanya berisi boolean
berhasil/gagal 20 layanan terakhir (game_state.gd:2887-2960) — tanpa
jenis pelanggan, tanpa barang yang dibeli. Bot TIDAK menebaknya:
field ``pelanggan_tersering`` selalu None dengan alasan yang jelas.
Begitu pula barang terlaris SEPANJANG WAKTU: save hanya menyimpan
rincian per barang untuk hari ini; yang dilaporkan adalah terlaris
hari ini + total per hari dari riwayat.
"""

from __future__ import annotations

from .sim import GameData


def statistik_slot(slot: dict, data: GameData) -> dict:
    """Statistik dari save. Tidak pernah melempar untuk save yang
    field-nya hilang/rusak bentuknya — bagian yang tidak bisa dibaca
    dilaporkan kosong, bukan ditebak."""
    # -- hari ini: penjualan per barang -----------------------------------
    penjualan = slot.get("penjualan_hari") or {}
    if not isinstance(penjualan, dict):
        penjualan = {}
    per_barang = []
    for item_id, r in penjualan.items():
        if item_id not in data.katalog:
            continue
        try:
            jumlah, omzet, laba = int(r[0]), int(r[1]), int(r[2])
        except (TypeError, ValueError, IndexError):
            continue
        if jumlah <= 0 and omzet <= 0:
            continue
        per_barang.append({
            "id": item_id,
            "nama": str(data.katalog[item_id].get("nama", item_id)),
            "jumlah": jumlah,
            "omzet": omzet,
            "laba": laba,
        })
    per_barang.sort(key=lambda x: (x["jumlah"], x["omzet"]), reverse=True)
    terlaris = per_barang[0] if per_barang else None

    # -- riwayat harian ----------------------------------------------------
    riwayat = slot.get("riwayat") or []
    if not isinstance(riwayat, list):
        riwayat = []
    bersih_riwayat = []
    for entri in riwayat:
        if not isinstance(entri, dict):
            continue
        try:
            bersih_riwayat.append({
                "hari": int(entri.get("hari", 0)),
                "omzet": int(entri.get("omzet", 0) or 0),
                "laba": int(entri.get("laba", 0) or 0),
                "bersih": int(entri.get("bersih", 0) or 0),
                "belanja": int(entri.get("belanja", 0) or 0),
                "barang": int(entri.get("barang", 0) or 0),
                "dilayani": int(entri.get("dilayani", 0) or 0),
                "batal": int(entri.get("batal", 0) or 0),
            })
        except (TypeError, ValueError):
            continue
    total_omzet = sum(e["omzet"] for e in bersih_riwayat)
    total_laba = sum(e["laba"] for e in bersih_riwayat)
    total_barang = sum(e["barang"] for e in bersih_riwayat)
    total_dilayani = sum(e["dilayani"] for e in bersih_riwayat)
    total_batal = sum(e["batal"] for e in bersih_riwayat)
    hari_beromzet = [e for e in bersih_riwayat if e["omzet"] > 0]
    terbaik = max(hari_beromzet, key=lambda e: e["omzet"]) if hari_beromzet else None
    terburuk = min(hari_beromzet, key=lambda e: e["omzet"]) if hari_beromzet else None

    # -- hari ini: penghitung dari catatan_hari ----------------------------
    catatan = slot.get("catatan_hari") or {}
    if not isinstance(catatan, dict):
        catatan = {}

    def _int(kunci: str) -> int:
        try:
            return int(catatan.get(kunci, 0) or 0)
        except (TypeError, ValueError):
            return 0

    return {
        "hari": int(slot.get("hari", 1) or 1),
        "hari_ini": {
            "omzet": _int("omzet"), "laba": _int("laba"),
            "terjual": _int("terjual"), "dilayani": _int("dilayani"),
            "batal": _int("batal"), "belanja": _int("belanja"),
        },
        "per_barang_hari_ini": per_barang,
        "terlaris_hari_ini": terlaris,
        "riwayat": bersih_riwayat,
        "jumlah_hari_riwayat": len(bersih_riwayat),
        "total_omzet": total_omzet,
        "total_laba": total_laba,
        "total_barang": total_barang,
        "total_dilayani": total_dilayani,
        "total_batal": total_batal,
        "rata_omzet_hari": (total_omzet // len(bersih_riwayat)
                            if bersih_riwayat else 0),
        "hari_terbaik": terbaik,
        "hari_terburuk": terburuk,
        # TIDAK ADA di save (riwayat_layan hanya boolean) — jangan ditebak.
        "pelanggan_tersering": None,
        "alasan_tanpa_pelanggan": (
            "Save tidak mencatat jenis pelanggan per layanan — "
            "riwayat_layan hanya berisi berhasil/gagal. Jadi pelanggan "
            "tersering tidak bisa dihitung."),
    }
