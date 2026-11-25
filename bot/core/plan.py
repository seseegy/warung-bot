"""Perencana Fase 2: kapan naik level, ROI upgrade, what-if, harga terbaik.

Semua memakai mesin simulasi (``core.sim``) dengan seed tetap supaya
hasil bisa dibandingkan apel-dengan-apel. Rumus yang dipakai:

- ``kapan_naik``: simulasikan hari demi hari (maks 90) sampai ``tingkat``
  naik. Blocker jujur: syarat upgrade tidak dimiliki atau misi cerita
  belum lunas -> tidak akan pernah naik apa pun progresnya.
- ``roi_upgrade``: bandingkan laba/hari 3 hari dengan vs tanpa upgrade
  (seed sama; biaya_hari upgrade ikut dihitung, harga TIDAK dipotong
  dari uang sim — balik modal sudah = harga / laba tambahan/hari).
  Balik modal = harga / laba_tambahan_bersih_per_hari.
  Upgrade yang efeknya tidak menambah laba terukur (cctv, genset —
  pencegahan) ditandai, bukan dipaksa angka.
- ``whatif``: simulasikan N hari dengan harga jual yang diubah pengguna,
  bandingkan dengan harga sekarang (seed sama).
- ``harga_terbaik``: untuk tiap barang fisik terbuka yang ada stoknya,
  coba semua harga dari lantai ke batas atas per langkah harga game
  (``langkah_harga`` dari harga katalog, ``game_state.gd:5723``) dan pilih
  yang laba hariannya tertinggi (rata-rata 2 seed, 1 hari). Harga di bawah
  lantai TIDAK PERNAH disarankan (``lantai_harga``, ``game_state.gd:5730``).
"""

from __future__ import annotations

import random

from . import sim as sim_mod
from .sim import GameData, SimError

MAKS_HARI_KAPAN_NAIK = 90
HARI_ROI = 3
ULANG_HARGA_TERBAIK = 2


def _rng(seed: int | None) -> random.Random:
    return random.Random(seed) if seed is not None else random.Random()


def kapan_naik(slot: dict, data: GameData, seed: int | None = 12345,
               maks_hari: int = MAKS_HARI_KAPAN_NAIK) -> dict:
    """Berapa hari lagi naik level pada laju simulasi.

    Mengembalikan: hari (int, 0 bila progres sudah memenuhi dan syarat
    lain beres), rata_omzet, rata_laba, blocker (list string), naik (bool),
    tingkat_akhir. Bila blocker ada dan tidak bisa diatasi sim -> naik False.
    """
    tingkat = int(slot.get("tingkat", 0))
    if tingkat >= len(data.tugas):
        return {"naik": False, "hari": None, "alasan": "sudah level terakhir",
                "rata_omzet": 0, "rata_laba": 0, "blocker": [], "tingkat_akhir": tingkat}
    t = data.tugas[tingkat]
    blocker: list[str] = []
    syarat_upgrade = t.get("upgrade", []) or []
    if syarat_upgrade and not any(u in (slot.get("upgrade", []) or [])
                                  for u in syarat_upgrade):
        blocker.append("upgrade belum dimiliki: " + ", ".join(syarat_upgrade))
    if (str(slot.get("misi_status", "")) not in ("", "lunas")
            and not slot.get("cerita_tamat")):
        blocker.append(f"misi cerita belum lunas (misi_status: {slot.get('misi_status')})")
    # Progres sudah memenuhi target saat ini?
    s0 = sim_mod._normalisasi_slot(slot, data)
    inti_ok = (
        int((s0.get("progres", {}) or {}).get("pelanggan", 0)) >= sim_mod.target_inti(data, s0, "pelanggan")
        and int((s0.get("progres", {}) or {}).get("barang", 0)) >= sim_mod.target_inti(data, s0, "barang")
        and int((s0.get("progres", {}) or {}).get("omzet", 0)) >= sim_mod.target_inti(data, s0, "omzet")
    )
    khusus_ok = int((s0.get("progres", {}) or {}).get("khusus", 0)) >= sim_mod.target_khusus(data, s0)
    if inti_ok and khusus_ok and not blocker:
        return {"naik": True, "hari": 0, "alasan": "progres sudah memenuhi target",
                "rata_omzet": 0, "rata_laba": 0, "blocker": [], "tingkat_akhir": tingkat}
    if blocker:
        # Tetap simulasikan untuk laju harian, tapi naik tidak akan terjadi.
        pass
    rng = _rng(seed)
    s = sim_mod._normalisasi_slot(slot, data)
    hari_jalan = 0
    for _ in range(maks_hari):
        sebelum = int(s.get("tingkat", 0))
        sim_mod.simulate_day(s, data, rng)
        hari_jalan += 1
        if int(s.get("tingkat", 0)) > sebelum:
            break
    naik = int(s.get("tingkat", 0)) > tingkat
    # Laju harian dihitung dari riwayat yang terbentuk selama simulasi.
    riwayat = s.get("riwayat", []) or []
    potong = riwayat[-hari_jalan:] if hari_jalan else []
    rata_omzet = sum(int(r.get("omzet", 0)) for r in potong) / max(len(potong), 1)
    rata_laba = sum(int(r.get("laba", 0)) for r in potong) / max(len(potong), 1)
    return {
        "naik": naik,
        "hari": hari_jalan if naik else None,
        "alasan": ("naik dalam simulasi" if naik else
                   ("tidak naik dalam 90 hari simulasi" if not blocker else
                    "tidak bisa naik: " + "; ".join(blocker))),
        "rata_omzet": int(rata_omzet),
        "rata_laba": int(rata_laba),
        "blocker": blocker,
        "tingkat_akhir": int(s.get("tingkat", 0)),
    }


def roi_upgrade(slot: dict, data: GameData, seed: int | None = 12345,
                hari: int = HARI_ROI) -> list:
    """Urutan upgrade dari yang paling cepat balik modal.

    Tiap entri: id, nama, harga, biaya_hari, laba_tambahan_per_hari,
    hari_balik_modal (None bila tidak terukur), catatan. Hanya upgrade
    yang levelnya sudah memenuhi syarat yang dinilai; yang uangnya tidak
    cukup ditandai (tetap dihitung — balik modal memakai harga penuh).
    """
    rng_baris = _rng(seed)
    dasar = sim_mod.simulate(slot, data, hari, seed=seed)
    laba_dasar = dasar["laba"] / max(hari, 1)
    tingkat = int(slot.get("tingkat", 0)) + 1
    dimiliki = set(slot.get("upgrade", []) or [])
    hasil = []
    for up in data.upgrade["upgrade"]:
        uid = str(up["id"])
        if uid in dimiliki:
            continue
        if int(up.get("level", 1)) > tingkat:
            continue
        harga = int(up.get("harga", 0))
        # biaya_hari bisa null di JSON (= 0).
        biaya_hari = int(up.get("biaya_hari") or 0)
        slot_uji = sim_mod._normalisasi_slot(slot, data)
        slot_uji["upgrade"] = list(dimiliki) + [uid]
        # Harga TIDAK dipotong dari uang sim: balik modal sudah dihitung
        # sebagai harga / tambahan laba harian. Memotongnya juga akan
        # mengacaukan sim (uang menipis -> top-up layanan terhambat ->
        # laba terukur jadi lebih kecil dari seharusnya).
        uji = sim_mod.simulate(slot_uji, data, hari, seed=seed)
        laba_uji = uji["laba"] / max(hari, 1)
        tambahan = laba_uji - laba_dasar - biaya_hari
        # Efek yang tidak bisa diuangkan langsung (pencegahan/perlindungan:
        # cctv, genset) — sim hanya mengukur efek ramai kecilnya, jadi
        # angka balik modalnya menyesatkan bila dibaca mentah-mentah.
        efek = up.get("efek", {}) or {}
        kunci_tidak_langsung = [k for k in efek if k not in (
            "ramai", "sabar", "malam", "maks_antre", "respon", "banyak",
            "minuman", "kurir", "ulasan_baik", "tip", "supplier",
            "sabar_antre")]
        if tambahan > 0:
            balik = harga / tambahan
            catatan = ("efek utama tidak langsung (pencegahan/perlindungan) "
                       "— angka di atas hanya dari efek ramai kecil"
                       if kunci_tidak_langsung else "")
        else:
            balik = None
            if kunci_tidak_langsung:
                catatan = "efek tidak langsung (pencegahan/perlindungan)"
            else:
                catatan = "tidak menambah laba terukur dalam 3 hari sim"
        hasil.append({
            "id": uid,
            "nama": str(up.get("nama", uid)),
            "harga": harga,
            "biaya_hari": biaya_hari,
            "laba_tambahan_per_hari": int(tambahan),
            "hari_balik_modal": (round(balik, 1) if balik is not None else None),
            "catatan": catatan,
            "uang_cukup": int(slot.get("uang", 0)) >= harga,
        })
    hasil.sort(key=lambda x: (x["hari_balik_modal"] is None,
                              x["hari_balik_modal"] or 0))
    return hasil


def whatif(slot: dict, data: GameData, harga_baru: dict,
           jumlah_hari: int = 1, seed: int | None = 12345) -> dict:
    """Bandingkan harga sekarang vs harga usulan (seed sama).

    ``harga_baru``: {id_barang: harga}. Harga divalidasi ke lantai/batas
    game dan di-snap ke kelipatan langkah (seperti tombol +/- game).
    Mengembalikan perbandingan sekarang vs usulan + harga yang dipakai.
    """
    harga_dipakai: dict = {}
    catatan: list[str] = []
    for item_id, harga in harga_baru.items():
        if item_id not in data.katalog:
            raise SimError(f"barang tidak dikenal: {item_id}")
        if data.katalog[item_id]["jenis"] != "fisik":
            raise SimError(f"harga hanya untuk barang fisik: {item_id}")
        lantai = sim_mod.lantai_harga(data, item_id, slot)
        batas = sim_mod.batas_harga_jual(data, item_id, slot)
        langkah = sim_mod.langkah_harga(data, item_id)
        h = int(harga)
        if h < lantai:
            raise SimError(
                f"{item_id}: {h} di bawah lantai {lantai} (modal+100 / pasar)")
        if h > batas:
            raise SimError(
                f"{item_id}: {h} di atas batas {batas} (1,3x normal / pasar)")
        # Snap ke kelipatan langkah seperti ubah_harga_jual().
        h_snap = (h // langkah) * langkah
        if h_snap < lantai:
            h_snap = ((lantai + langkah - 1) // langkah) * langkah
        h_snap = min(h_snap, batas)  # ceil lantai bisa melewati batas bila
        # rentang lantai..batas lebih sempit dari satu langkah.
        if h_snap != h:
            catatan.append(f"{item_id}: {h} di-snap ke {h_snap} (langkah {langkah})")
        harga_dipakai[item_id] = h_snap
    sekarang = sim_mod.simulate(slot, data, jumlah_hari, seed=seed)
    slot_uji = sim_mod._normalisasi_slot(slot, data)
    khusus = dict(slot_uji.get("harga_jual_khusus", {}) or {})
    khusus.update(harga_dipakai)
    slot_uji["harga_jual_khusus"] = khusus
    usulan = sim_mod.simulate(slot_uji, data, jumlah_hari, seed=seed)
    return {
        "jumlah_hari": jumlah_hari,
        "harga_dipakai": harga_dipakai,
        "catatan": catatan,
        "sekarang": {"omzet": sekarang["omzet"], "laba": sekarang["laba"],
                     "dilayani": sekarang["dilayani"], "batal": sekarang["batal"],
                     "datang": sekarang["datang"],
                     "uang_akhir": sekarang["uang_akhir"]},
        "usulan": {"omzet": usulan["omzet"], "laba": usulan["laba"],
                   "dilayani": usulan["dilayani"], "batal": usulan["batal"],
                   "datang": usulan["datang"],
                   "uang_akhir": usulan["uang_akhir"]},
    }


def harga_terbaik(slot: dict, data: GameData, seed: int | None = 12345,
                  ulang: int = ULANG_HARGA_TERBAIK) -> list:
    """Harga per barang yang memaksimalkan laba harian (brute force).

    Hanya barang fisik terbuka yang ADA stoknya. Tiap barang dinilai
    sendiri (barang lain di harga sekarang), 1 hari x N seed, lalu
    diambil harga dengan rata-rata laba tertinggi. Mengembalikan list
    per barang: id, nama, harga_sekarang, harga_terbaik, laba_sekarang,
    laba_terbaik (per hari), stok.
    """
    terbuka = set(slot.get("barang_terbuka", []) or [])
    stok = slot.get("stok", {}) or {}
    hasil = []
    for item_id in data.urutan_barang:
        item = data.katalog[item_id]
        if item["jenis"] != "fisik" or item_id not in terbuka:
            continue
        if int(stok.get(item_id, 0)) <= 0:
            continue
        lantai = sim_mod.lantai_harga(data, item_id, slot)
        batas = sim_mod.batas_harga_jual(data, item_id, slot)
        langkah = sim_mod.langkah_harga(data, item_id)
        harga_sekarang = sim_mod.harga_jual(data, item_id, slot)
        # Kandidat: lantai..batas per langkah (snap lantai ke atas).
        awal = ((lantai + langkah - 1) // langkah) * langkah
        kandidat = list(range(awal, batas + 1, langkah))
        if not kandidat:
            kandidat = [lantai]
        # Harga sekarang hanya kandidat bila tidak di bawah lantai (save
        # lama bisa menyimpan harga khusus di bawah lantai game).
        if harga_sekarang not in kandidat and harga_sekarang >= lantai:
            kandidat.append(harga_sekarang)
        terbaik = None
        laba_terbaik = None
        laba_sekarang = None
        # Harga sekarang SELALU dievaluasi sebagai baseline, walaupun
        # di bawah lantai (save lama bisa menyimpan harga khusus di
        # bawah lantai) — baseline tidak boleh dilaporkan nol. Harga
        # di bawah lantai hanya tidak boleh DIPILIH sebagai terbaik.
        evaluasi = list(kandidat)
        if harga_sekarang not in evaluasi:
            evaluasi.append(harga_sekarang)
        for harga in evaluasi:
            slot_uji = sim_mod._normalisasi_slot(slot, data)
            khusus = dict(slot_uji.get("harga_jual_khusus", {}) or {})
            khusus[item_id] = harga
            slot_uji["harga_jual_khusus"] = khusus
            total_laba = 0
            for rep in range(ulang):
                r = sim_mod.simulate(slot_uji, data, 1,
                                     seed=(seed + rep * 1000) if seed is not None else None,
                                     dt=1.0)
                total_laba += r["laba"]
            rata = total_laba / ulang
            if harga == harga_sekarang:
                laba_sekarang = rata
            if harga in kandidat and (laba_terbaik is None or rata > laba_terbaik):
                laba_terbaik = rata
                terbaik = harga
        hasil.append({
            "id": item_id,
            "nama": str(item.get("nama", item_id)),
            "stok": int(stok.get(item_id, 0)),
            "harga_sekarang": harga_sekarang,
            "harga_terbaik": terbaik,
            "laba_sekarang": int(laba_sekarang or 0),
            "laba_terbaik": int(laba_terbaik or 0),
        })
    hasil.sort(key=lambda x: x["laba_terbaik"] - x["laba_sekarang"], reverse=True)
    return hasil
