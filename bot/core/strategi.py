"""Strategi multi-hari Fase 5: rencana 7 hari — /rencana.

Memakai mesin simulasi (``core.sim``) + perencana (``core.plan``) yang
sudah ada — TIDAK ada rumus baru di sini, hanya gabungan:

- ``simulate(7 hari)``: proyeksi omzet/laba/uang akhir (seed tetap,
  bisa dibandingkan apel-dengan-apel).
- Restock: bandingkan stok awal vs stok akhir simulasi — barang yang
  habis/menipis selama 7 hari sim perlu dibeli lagi. Barang yang stoknya
  SUDAH 0 sejak awal tidak terukur (sim tidak bisa menjualnya) —
  dilaporkan sebagai catatan, bukan ditebak angkanya.
- Upgrade: 3 teratas ``plan.roi_upgrade`` yang balik modalnya terukur.
- Naik level: ``plan.kapan_naik``.

Semua angka adalah PROYEKSI simulasi (RNG, event acak, pilihan cerita
tidak disimulasikan) — bukan janji. Konsistensi akuntansi yang
dipertahankan: uang_akhir = uang_awal + laba - biaya_harian - sewa +
hadiah (belanja stok = 0 dalam simulasi — sim tidak membeli stok).
"""

from __future__ import annotations

import logging

from . import plan as plan_mod
from . import sim as sim_mod
from .sim import GameData

log = logging.getLogger(__name__)

HARI_RENCANA = 7
SEED_RENCANA = 12345


def rencana_7_hari(slot: dict, data: GameData, tugas_data: dict,
                   seed: int | None = SEED_RENCANA,
                   hari: int = HARI_RENCANA) -> dict:
    """Rencana N hari (default 7) dari slot saat ini."""
    hasil = sim_mod.simulate(slot, data, hari, seed=seed)
    slot_awal = sim_mod._normalisasi_slot(slot, data)
    slot_akhir = hasil["slot_akhir"]
    stok_awal = slot_awal.get("stok", {}) or {}
    stok_akhir = slot_akhir.get("stok", {}) or {}
    restock = []
    sudah_habis = []
    for item_id in data.urutan_barang:
        item = data.katalog[item_id]
        if item["jenis"] != "fisik":
            continue
        if item_id not in (slot_awal.get("barang_terbuka", []) or []):
            continue
        if item_id in sim_mod.BARANG_TITIPAN:
            continue
        awal = int(stok_awal.get(item_id, 0) or 0)
        akhir = int(stok_akhir.get(item_id, 0) or 0)
        terjual = awal - akhir
        if awal == 0:
            # Tidak terukur: sim tidak bisa menjual barang tanpa stok.
            sudah_habis.append({
                "id": item_id, "nama": str(item.get("nama", item_id)),
                "stok_awal": 0, "stok_akhir": akhir})
            continue
        if terjual > 0 and akhir <= 2:
            # Saran beli: cukup untuk 7 hari lagi, dibulatkan ke atas
            # kelipatan 5 (stok sim memakai kelipatan kecil).
            saran = max(terjual, 5)
            restock.append({
                "id": item_id, "nama": str(item.get("nama", item_id)),
                "stok_awal": awal, "stok_akhir": akhir,
                "terjual": terjual, "saran_beli": saran,
                "biaya": saran * sim_mod.harga_modal(data, item_id, slot_awal),
            })
    restock.sort(key=lambda x: x["terjual"], reverse=True)
    try:
        roi = plan_mod.roi_upgrade(slot_awal, data, seed=seed)
    except Exception as exc:
        # Rencana tetap ditampilkan tanpa rekomendasi upgrade — tapi
        # kegagalan DICATAT di log, tidak disembunyikan.
        log.warning("rencana: roi_upgrade gagal: %s", exc)
        roi = []
    upgrade = [
        {"id": r["id"], "nama": r["nama"], "harga": r["harga"],
         "hari_balik_modal": r["hari_balik_modal"],
         "laba_tambahan_per_hari": r["laba_tambahan_per_hari"],
         "uang_cukup_akhir": int(hasil["uang_akhir"]) >= int(r["harga"]),
         "catatan": r["catatan"]}
        for r in roi if r["hari_balik_modal"] is not None
    ][:3]
    try:
        naik = plan_mod.kapan_naik(slot_awal, data, seed=seed)
    except Exception as exc:
        log.warning("rencana: kapan_naik gagal: %s", exc)
        naik = {"naik": False, "hari": None, "alasan": "tidak bisa dihitung",
                "blocker": []}
    per_hari = [{
        "hari": int(h.get("hari", 0)),
        "omzet": int(h.get("omzet", 0)),
        "laba": int(h.get("laba", 0)),
        "biaya_harian": int(h.get("biaya_harian", 0)),
        "sewa": int(h.get("sewa", 0)),
        "dilayani": int(h.get("dilayani", 0)),
        "batal": int(h.get("batal", 0)),
        "libur": bool(h.get("libur", False)),
    } for h in hasil["hari"]]
    return {
        "jumlah_hari": hari,
        "uang_awal": int(hasil["uang_awal"]),
        "uang_akhir": int(hasil["uang_akhir"]),
        "omzet": int(hasil["omzet"]),
        "laba": int(hasil["laba"]),
        "modal": int(hasil["modal"]),
        "modal_layanan": int(hasil["modal_layanan"]),
        "biaya_harian": int(hasil["biaya_harian"]),
        "sewa": int(hasil["sewa"]),
        "hadiah": int(hasil["hadiah"]),
        "qris_awal": int(hasil["qris_awal"]),
        "qris_akhir": int(hasil["qris_akhir"]),
        "saldo_layanan_awal": int(hasil["saldo_layanan_awal"]),
        "saldo_layanan_akhir": int(hasil["saldo_layanan_akhir"]),
        "dilayani": int(hasil["dilayani"]),
        "batal": int(hasil["batal"]),
        "tingkat_awal": int(hasil["tingkat_awal"]),
        "tingkat_akhir": int(hasil["tingkat_akhir"]),
        "hari_awal": int(hasil["hari_awal"]),
        "hari_akhir": int(hasil["hari_akhir"]),
        "diusir": bool(hasil["diusir"]),
        "tunggakan_sewa": int(hasil["tunggakan_sewa"]),
        "per_hari": per_hari,
        "restock": restock,
        "sudah_habis": sudah_habis,
        "upgrade": upgrade,
        "kapan_naik": naik,
        "slot_akhir": slot_akhir,
    }
