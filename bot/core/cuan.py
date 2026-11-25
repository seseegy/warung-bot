"""Fitur /cuan — beli stok murah, jual mahal, pelanggan ramai.

Mode "cuan" adalah aturan ekonomi lokal yang SADAR diubah atas permintaan
pengguna (bukan perilaku default game). Aktif lewat flag ``mode_cuan``
di slot; efeknya diterapkan di ``sim.py``:

- ``harga_modal``: beli stok 80% lebih murah (``CUAN_DISKON_MODAL``).
- ``harga_jual``: tetap mengikuti batas atas game (1,3x normal) — jual
  mahal tanpa melewati batas; keluhan "mahal" dinonaktifkan di
  ``_layani_pelanggan`` sehingga pelanggan tetap membeli.
- ``interval_datang``: kedatangan 90% lebih ramai (``CUAN_PENGALI_RAMAI``).

Modul ini berisi fungsi MURNI (mengubah salinan slot, tanpa I/O):

- ``aktifkan_cuan``: set ``mode_cuan`` + harga jual maksimal + beli stok
  sampai ``CUAN_TARGET_STOK`` unit tiap jenis, sisakan ``CUAN_SISA_UANG``.
- ``matikan_cuan``: hapus ``mode_cuan`` (kembali ke perilaku default).

Semua belanja memakai ``harga_modal`` (yang sudah kena diskon saat
``mode_cuan`` aktif), jadi stok otomatis murah.
"""

from __future__ import annotations

from . import auto as auto_mod
from . import sim as sim_mod
from .sim import GameData

CUAN_TARGET_STOK = 100   # beli sampai 100 unit per jenis


def aktifkan_cuan(slot: dict, data: GameData) -> dict:
    """Aktifkan mode cuan pada salinan slot (murni).

    1. Set ``mode_cuan = True`` (diskonya otomatis berlaku di harga_modal).
    2. Set harga jual tiap barang fisik terbuka ke batas atas (1,3x normal).
    3. Beli stok tiap barang fisik terbuka sampai ``CUAN_TARGET_STOK`` unit,
       sisakan ``CUAN_SISA_UANG`` (30%) dari uang.
    Mengembalikan {"slot", "aksi", "uang_awal", "uang_akhir"}.
    """
    s = sim_mod._normalisasi_slot(slot)
    s["mode_cuan"] = True
    uang_awal = int(s.get("uang", 0))
    aksi: list[dict] = []

    terbuka = set(s.get("barang_terbuka", []) or [])
    stok = s.setdefault("stok", {})
    harga_khusus = dict(s.get("harga_jual_khusus", {}) or {})
    # Batas uang terendah yang boleh tersisa (30% dari uang awal).
    batas_uang = int(uang_awal * sim_mod.CUAN_SISA_UANG)

    # 1) Harga jual maksimal.
    for item_id in data.urutan_barang:
        item = data.katalog[item_id]
        if item.get("jenis") != "fisik" or item_id not in terbuka:
            continue
        maks = sim_mod.batas_harga_jual(data, item_id, s)
        harga_khusus[item_id] = maks
    s["harga_jual_khusus"] = harga_khusus

    # 2) Beli stok sampai target, sisakan 30%.
    for item_id in data.urutan_barang:
        item = data.katalog[item_id]
        if item.get("jenis") != "fisik" or item_id not in terbuka:
            continue
        if item_id in sim_mod.BARANG_TITIPAN:
            continue
        punya = int(stok.get(item_id, 0) or 0)
        kiriman = int((s.get("kiriman_stok", {}) or {}).get(item_id, 0) or 0)
        grosir = int((s.get("tas_grosir", {}) or {}).get(item_id, 0) or 0)
        total = punya + kiriman + grosir
        muat = auto_mod.sisa_muat_stok(s, item_id)
        jumlah = min(CUAN_TARGET_STOK - total, muat)
        if jumlah <= 0:
            continue
        biaya = sim_mod.harga_modal(data, item_id, s) * jumlah
        # Berhenti total bila uang sudah tipis (jaga sisa 30%).
        if int(s.get("uang", 0)) - biaya < batas_uang:
            aksi.append({"aksi": "beli_stok", "ok": False, "id": item_id,
                         "alasan": "sisa uang 30% tercapai", "biaya": biaya})
            continue
        s["uang"] = int(s.get("uang", 0)) - biaya
        # Langsung masuk stok (konsisten dgn auto_beli_stok perbaikan).
        stok[item_id] = punya + jumlah
        auto_mod.catat_transaksi(
            s, f"Belanja cuan {jumlah} {str(item.get('nama', item_id)).lower()}",
            -biaya)
        aksi.append({"aksi": "beli_stok", "ok": True, "id": item_id,
                     "nama": str(item.get("nama", item_id)),
                     "jumlah": jumlah, "biaya": biaya})

    return {
        "slot": s,
        "aksi": aksi,
        "uang_awal": uang_awal,
        "uang_akhir": int(s.get("uang", 0)),
    }


def matikan_cuan(slot: dict) -> dict:
    """Nonaktifkan mode cuan (kembali ke perilaku default)."""
    s = sim_mod._normalisasi_slot(slot)
    s.pop("mode_cuan", None)
    return s


def ringkasan_cuan(hasil: dict) -> str:
    """Ringkasan teks hasil /cuan untuk ditampilkan."""
    dibeli = [a for a in hasil["aksi"] if a.get("ok")]
    gagal = [a for a in hasil["aksi"] if not a.get("ok")]
    jenis = len({a["id"] for a in dibeli})
    total_unit = sum(int(a["jumlah"]) for a in dibeli)
    baris = [
        "Mode Cuan AKTIF — beli stok murah, jual mahal, pelanggan ramai.",
        f"Membeli {total_unit} unit ({jenis} jenis) barang terbuka "
        f"sampai {CUAN_TARGET_STOK} unit/jenis.",
        f"Uang {hasil['uang_awal']} → {hasil['uang_akhir']} "
        f"(sisa {sim_mod.CUAN_SISA_UANG * 100:.0f}% dijaga).",
    ]
    if gagal:
        baris.append(
            f"{len(gagal)} jenis tidak kebeli (uang sudah menyentuh sisa 30%).")
    return "\n".join(baris)
