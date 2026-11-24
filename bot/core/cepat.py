"""Aksi cepat Fase 5: /jual, /beli, /ngopi, /tutup, /slot.

Semua fungsi di sini MURNI (mengubah salinan slot, tanpa I/O) dan
meniru fungsi game SATU-PERSATU. Yang diedit bot adalah save — bukan
replay permainan: /jual menerapkan akuntansi ``jual()`` seolah n unit
terjual, /beli menerapkan ``beli_stok()``, /ngopi menerapkan
``istirahat("ngopi")``, /tutup menerapkan ``tutup_hari()``.

Grounding (game_state.gd):
- ``jual(id)`` (:2356): stok -1 (fisik) atau saldo_layanan -= modal
  (layanan); uang += harga; omzet_hari/minggu/bulan += harga (kecuali
  mode latihan); laba_hari += harga - modal; barang_terjual_hari += 1;
  penjualan_hari[id] = [jumlah, omzet, laba]; progres barang/omzet/
  khusus; lalu ``_cek_tugas()``. ``alasan_tidak_bisa_jual`` (:2335):
  warung harus buka, barang terbuka, fisik stok > 0, layanan
  saldo_layanan >= modal. CATATAN: bot TIDAK mengecek ``status_hari``
  ("buka") — gate itu berlaku untuk main langsung saat warung buka;
  bot mengedit save saat game tertutup, jadi gate itu tidak bermakna
  di sini (dicatat di README).
- ``beli_stok(id, jumlah)`` (:2393): etalase wajib dulu, harus terbuka,
  bukan titipan sales (roti/jamu), jumlah <= sisa_muat_stok, biaya =
  harga_modal x jumlah, uang harus cukup; uang -= biaya; kiriman_stok
  += jumlah (kurir jalan saat game dibuka — BUKAN instan);
  belanja_hari += biaya; catat_transaksi.
- ``istirahat("ngopi")`` (:1547) + ``ISTIRAHAT`` (:939): minuman
  [sachet, kopi_susu, minuman_energi] (yang pertama ada stoknya),
  +30 energi (``ENERGI_KOPI = 30.0``), maks 1x/hari
  (``MAKS_ISTIRAHAT_HARIAN = 1``), jeda 120 menit antar istirahat
  (``JEDA_ISTIRAHAT``), tolak bila energi >= 99 ("masih segar"), tolak
  saat Ramadan sebelum Maghrib, majukan waktu 10 menit.
- ``tutup_hari()`` (:6715) + sim ``_tutup_hari``: biaya harian, sewa
  tiap Minggu (``hari % 7 == 0``), riwayat harian, hari + 1, energi 100,
  menit = jam buka. Diusir bila tunggakan mencapai 3 minggu
  (``MINGGU_DIUSIR = 3``, auto.py ``bayar_sewa``).
- ``simpan()`` (:3343): ``catatan_hari`` di save = penghitung hari
  BERJALAN (omzet/laba/terjual/belanja/dilayani/batal/hadiah); dan
  ``penjualan_hari`` = {id: [jumlah, omzet, laba]}. Bila save ditulis
  tepat setelah tutup_hari (sebelum simpan berikutnya), catatan_hari
  masih berisi ringkasan KEMARIN — terdeteksi karena penjualan_hari
  kosong tapi catatannya berisi angka (lihat ``_catatan_hari_ini``).
- ``kemajuan_hp()`` (akun_online.gd:623): slot terbaik = level
  tertinggi, seri -> hari terbanyak (``_lebih_jauh``).
"""

from __future__ import annotations

import re

from . import auto as auto_mod
from . import save as save_mod
from . import sim as sim_mod
from .sim import GameData

# Minuman ngopi — urutan pilihan game (ISTIRAHAT, game_state.gd:939).
MINUMAN_NGOPI = ("sachet", "kopi_susu", "minuman_energi")
ENERGI_KOPI = 30.0
MAKS_NGOPI_HARIAN = 1
JEDA_NGOPI_MENIT = 120.0
DURASI_NGOPI_MENIT = 10.0
ENERGI_SEGAR_MIN = 99.0
MINGGU_DIUSIR = 3


class CepatError(ValueError):
    """Input/aksi cepat tidak valid (pesan siap tampil ke pengguna)."""


# -- cari barang ------------------------------------------------------------

def _normalisasi_teks(teks: str) -> str:
    """Lowercase + rapikan spasi + samakan ejaan 'mie' -> 'mi' (nama game
    "Mie goreng" vs ketikan umum "mi goreng")."""
    teks = re.sub(r"\s+", " ", str(teks or "").strip().lower())
    return re.sub(r"\bmie\b", "mi", teks)


def cari_barang(data: GameData, teks: str) -> str:
    """Nama/sebutan/id barang -> id. Melempar CepatError bila tidak ada
    yang cocok, atau lebih dari satu yang cocok (minta lebih spesifik)."""
    cari = _normalisasi_teks(teks)
    if not cari:
        raise CepatError("nama barang kosong.")
    for item_id in data.urutan_barang:
        if cari == item_id:
            return item_id
    for item_id in data.urutan_barang:
        item = data.katalog[item_id]
        if cari == _normalisasi_teks(item.get("nama", "")):
            return item_id
        if cari == _normalisasi_teks(item.get("sebutan", "")):
            return item_id
    cocok = []
    for item_id in data.urutan_barang:
        item = data.katalog[item_id]
        nama = _normalisasi_teks(item.get("nama", ""))
        sebutan = _normalisasi_teks(item.get("sebutan", ""))
        if cari in nama or (sebutan and cari in sebutan):
            cocok.append(item_id)
    if len(cocok) == 1:
        return cocok[0]
    if len(cocok) > 1:
        nama_cocok = ", ".join(
            str(data.katalog[i].get("nama", i)) for i in cocok[:5])
        raise CepatError(
            f"'{teks}' cocok dengan beberapa barang: {nama_cocok}. "
            "Tulis nama lengkapnya.")
    raise CepatError(
        f"barang '{teks}' tidak ditemukan. Cek ejaan atau lihat /stok.")


def parse_perintah(teks: str, data: GameData) -> tuple[str, int]:
    """'mi goreng 5' / 'kopi sachet 2x' -> (item_id, jumlah).

    Jumlah = token terakhir (boleh bersufiks 'x'), 1..9999. Bila token
    terakhir bukan angka, minta format yang benar.
    """
    bagian = str(teks or "").strip().split()
    if not bagian:
        raise CepatError("tulis barang dan jumlah, contoh: mi goreng 5")
    token_jumlah = bagian[-1].lower().rstrip("x")
    if not token_jumlah.isdigit():
        raise CepatError(
            "jumlah harus angka di akhir, contoh: mi goreng 5 "
            "(atau kirim /batal)")
    jumlah = int(token_jumlah)
    if jumlah < 1:
        raise CepatError("jumlah minimal 1.")
    if jumlah > 9999:
        raise CepatError("jumlah maksimal 9999.")
    nama = " ".join(bagian[:-1])
    if not nama:
        raise CepatError("tulis nama barang dulu, contoh: mi goreng 5")
    return cari_barang(data, nama), jumlah


# -- pembantu save ----------------------------------------------------------

def _catatan_hari_ini(s: dict) -> dict:
    """``catatan_hari`` hari BERJALAN (lihat docstring modul).

    Bila ``penjualan_hari`` kosong tapi catatan berisi angka, itu
    ringkasan kemarin (save ditulis di antara tutup_hari dan simpan
    berikutnya) — reset ke penghitung kosong, persis seperti game saat
    hari baru (belanja/dilayani/batal direset 0).
    """
    penjualan = s.get("penjualan_hari") or {}
    catatan = s.get("catatan_hari")
    if not isinstance(catatan, dict):
        catatan = {}
        s["catatan_hari"] = catatan
    if penjualan:
        return catatan
    if any(int(catatan.get(k, 0) or 0) > 0
           for k in ("omzet", "laba", "terjual", "belanja", "dilayani",
                     "batal")):
        segar = {"omzet": 0, "laba": 0, "terjual": 0, "belanja": 0,
                 "dilayani": 0, "batal": 0, "hadiah": 0}
        s["catatan_hari"] = segar
        return segar
    return catatan


def _terbuka(slot: dict, item_id: str) -> bool:
    return item_id in (slot.get("barang_terbuka") or [])


def daftar_slot(paket: dict) -> list:
    """Ringkasan 6 slot (game_state.gd ``info_slot``): nomor, kosong,
    nama_warung, level, hari, uang, qris, disimpan. Slot rusak ditandai
    (tidak membuat /slot gagal total)."""
    hasil = []
    slot_map = paket.get("slot", {}) if isinstance(paket, dict) else {}
    if not isinstance(slot_map, dict):
        slot_map = {}
    for nomor in range(1, 7):
        teks = slot_map.get(str(nomor))
        if not teks:
            hasil.append({"nomor": nomor, "kosong": True})
            continue
        try:
            slot = save_mod.parse_slot(teks)
        except save_mod.SlotError as exc:
            hasil.append({"nomor": nomor, "kosong": False, "rusak": True,
                          "alasan": str(exc)})
            continue
        ringkasan = save_mod.slot_summary(slot)
        hasil.append({"nomor": nomor, "kosong": False,
                      "nama_warung": ringkasan["nama_warung"],
                      "level": ringkasan["level"],
                      "hari": ringkasan["hari"],
                      "uang": ringkasan["uang"],
                      "qris": ringkasan["qris"],
                      "disimpan": ringkasan["disimpan"]})
    return hasil


# -- /jual ------------------------------------------------------------------

def jual_barang(slot: dict, data: GameData, item_id: str,
                jumlah: int) -> dict:
    """Jual n unit — akuntansi ``jual()`` per unit (lihat docstring modul).

    Mengembalikan ringkasan + "slot" (salinan yang sudah diubah).
    TIDAK menambah progres pelanggan/total_pembeli: ``jual()`` tidak
    melakukannya (itu urusan alur layani pelanggan). Hadiah tugas yang
    jatuh tempo dibayar ``_cek_tugas()`` seperti di game.
    """
    if item_id not in data.katalog:
        raise CepatError(f"barang tidak dikenal: {item_id}")
    if jumlah < 1:
        raise CepatError("jumlah minimal 1.")
    s = sim_mod._normalisasi_slot(slot)
    item = data.katalog[item_id]
    nama = str(item.get("nama", item_id))
    if not _terbuka(s, item_id):
        raise CepatError(f"{nama} belum terbuka — belum bisa dijual.")
    jenis = item["jenis"]
    if jenis == "fisik":
        stok = s.setdefault("stok", {})
        punya = int(stok.get(item_id, 0) or 0)
        if punya < jumlah:
            raise CepatError(
                f"stok {nama} hanya {punya}, tidak cukup untuk "
                f"menjual {jumlah}.")
    elif jenis == "layanan":
        modal_satuan = int(item["modal"])
        saldo = int(s.get("saldo_layanan", 0) or 0)
        if saldo < modal_satuan * jumlah:
            raise CepatError(
                f"saldo layanan {saldo} tidak cukup untuk menjual "
                f"{jumlah}x {nama} (butuh {modal_satuan * jumlah}).")
    else:
        raise CepatError(f"jenis barang tidak dikenal: {jenis}")
    uang_awal = int(s.get("uang", 0))
    tingkat_awal = int(s.get("tingkat", 0))
    catatan = _catatan_hari_ini(s)
    penjualan = s.setdefault("penjualan_hari", {})
    progres = s.setdefault("progres", {})
    omzet = 0
    laba = 0
    for _ in range(jumlah):
        harga = sim_mod.harga_jual(data, item_id, s)
        if jenis == "fisik":
            stok[item_id] = int(stok.get(item_id, 0)) - 1
            modal = sim_mod.harga_modal(data, item_id, s)
        else:
            s["saldo_layanan"] = int(s.get("saldo_layanan", 0)) - int(
                item["modal"])
            modal = int(item["modal"])
        s["uang"] = int(s.get("uang", 0)) + harga
        if str(s.get("mode", "")) != "latihan":
            s["omzet_minggu"] = int(s.get("omzet_minggu", 0) or 0) + harga
            s["omzet_bulan"] = int(s.get("omzet_bulan", 0) or 0) + harga
        omzet += harga
        laba += harga - modal
        catatan["omzet"] = int(catatan.get("omzet", 0) or 0) + harga
        catatan["laba"] = int(catatan.get("laba", 0) or 0) + harga - modal
        catatan["terjual"] = int(catatan.get("terjual", 0) or 0) + 1
        r = penjualan.get(item_id, [0, 0, 0])
        try:
            r = [int(r[0]), int(r[1]), int(r[2])]
        except (TypeError, ValueError, IndexError):
            r = [0, 0, 0]
        penjualan[item_id] = [r[0] + 1, r[1] + harga, r[2] + harga - modal]
        progres["barang"] = int(progres.get("barang", 0) or 0) + 1
        progres["omzet"] = int(progres.get("omzet", 0) or 0) + harga
        khusus = sim_mod.jenis_khusus(data, s)
        if khusus == "minuman" and str(item.get("kategori", "")) == "minuman":
            progres["khusus"] = int(progres.get("khusus", 0) or 0) + 1
        elif khusus == "laba_hari":
            progres["khusus"] = max(
                int(progres.get("khusus", 0) or 0),
                int(catatan.get("laba", 0) or 0))
    naik = sim_mod._cek_tugas(s, data)
    return {
        "slot": s,
        "id": item_id,
        "nama": nama,
        "jumlah": jumlah,
        "harga_satuan": sim_mod.harga_jual(data, item_id, s),
        "omzet": omzet,
        "laba": laba,
        "uang_awal": uang_awal,
        "uang_akhir": int(s.get("uang", 0)),
        "stok_akhir": (int((s.get("stok", {}) or {}).get(item_id, 0))
                       if jenis == "fisik" else None),
        "saldo_layanan_akhir": (int(s.get("saldo_layanan", 0))
                                if jenis == "layanan" else None),
        "naik_level": bool(naik),
        "tingkat_awal": tingkat_awal,
        "tingkat_akhir": int(s.get("tingkat", 0)),
    }


# -- /beli ------------------------------------------------------------------

def beli_barang(slot: dict, data: GameData, item_id: str,
                jumlah: int) -> dict:
    """Beli stok — akuntansi ``beli_stok()`` (lihat docstring modul).

    Stok TIDAK langsung bertambah: masuk ``kiriman_stok`` dan diantar
    kurir saat game dibuka (``detik_kiriman``/``durasi_kirim()`` adalah
    runtime, tidak tersimpan di save).
    """
    if item_id not in data.katalog:
        raise CepatError(f"barang tidak dikenal: {item_id}")
    if jumlah < 1:
        raise CepatError("jumlah minimal 1.")
    s = sim_mod._normalisasi_slot(slot)
    item = data.katalog[item_id]
    nama = str(item.get("nama", item_id))
    if item["jenis"] != "fisik":
        raise CepatError(
            f"{nama} bukan barang fisik (jenis: {item['jenis']}) — "
            "tidak dibeli sebagai stok.")
    if bool(s.get("wajib_etalase")) and "etalase" not in (
            s.get("upgrade", []) or []):
        raise CepatError(
            "Beli etalase kaca dulu lewat tombol Upgrade warung di kiri "
            "atas (modal awal sudah termasuk Rp500.000 untuk etalase).")
    if not _terbuka(s, item_id):
        raise CepatError(f"{nama} belum terbuka — belum bisa dibeli.")
    if item_id in sim_mod.BARANG_TITIPAN:
        raise CepatError(f"{nama} titipan sales, tidak dibeli sendiri.")
    muat = auto_mod.sisa_muat_stok(s, item_id)
    if jumlah > muat:
        raise CepatError(
            f"rak {nama} hanya muat {muat} lagi (kapasitas penuh).")
    harga_modal = sim_mod.harga_modal(data, item_id, s)
    biaya = harga_modal * jumlah
    uang_awal = int(s.get("uang", 0))
    if uang_awal < biaya:
        raise CepatError(
            f"uang tidak cukup untuk membeli {jumlah} {nama.lower()} "
            f"({biaya}).")
    s["uang"] = uang_awal - biaya
    kiriman = s.setdefault("kiriman_stok", {})
    kiriman[item_id] = int(kiriman.get(item_id, 0) or 0) + jumlah
    catatan = _catatan_hari_ini(s)
    catatan["belanja"] = int(catatan.get("belanja", 0) or 0) + biaya
    auto_mod.catat_transaksi(
        s, f"Belanja {jumlah} {nama.lower()}", -biaya)
    return {
        "slot": s,
        "id": item_id,
        "nama": nama,
        "jumlah": jumlah,
        "harga_modal": harga_modal,
        "biaya": biaya,
        "uang_awal": uang_awal,
        "uang_akhir": int(s.get("uang", 0)),
        "kiriman_total": int(kiriman[item_id]),
        "stok_saat_ini": int((s.get("stok", {}) or {}).get(item_id, 0)),
        "muat_sisa": muat - jumlah,
    }


# -- /ngopi -----------------------------------------------------------------

def ngopi(slot: dict, data: GameData) -> dict:
    """Ngopi — ``istirahat("ngopi")`` (lihat docstring modul).

    Mengembalikan ringkasan + "slot". Menolak bila: Ramadan (sebelum
    Maghrib), sudah ngopi hari ini, masih dalam jeda 120 menit, tidak
    ada stok minuman, atau energi sudah >= 99.
    """
    s = sim_mod._normalisasi_slot(slot)
    hari = int(s.get("hari", 1))
    if sim_mod.ramadan(hari):
        raise CepatError(
            "Pak Misran sedang puasa. Sesudah adzan Maghrib (18.00) "
            "bisa buka puasa.")
    catatan = s.setdefault("istirahat_hari", {})
    if not isinstance(catatan, dict):
        catatan = {}
        s["istirahat_hari"] = catatan
    if int(catatan.get("hari", 0)) != hari:
        catatan = {"hari": hari}
        s["istirahat_hari"] = catatan
    if int(catatan.get("ngopi", 0) or 0) >= MAKS_NGOPI_HARIAN:
        raise CepatError("Hari ini sudah ngopi. Besok lagi, ya.")
    menit = float(s.get("menit", 540))
    if "ngopi_menit" in catatan:
        try:
            tunggu = float(catatan["ngopi_menit"]) + JEDA_NGOPI_MENIT - menit
        except (TypeError, ValueError):
            tunggu = 0.0
        if tunggu > 0:
            raise CepatError(
                f"Belum bisa ngopi lagi. Tunggu {tunggu:.0f} menit game.")
    stok = s.setdefault("stok", {})
    minuman = None
    for kandidat in MINUMAN_NGOPI:
        if (_terbuka(s, kandidat)
                and int(stok.get(kandidat, 0) or 0) > 0):
            minuman = kandidat
            break
    if minuman is None:
        raise CepatError(
            "Stok kopi habis (sachet / kopi susu / minuman energi). "
            "Beli dulu lewat /beli.")
    energi_awal = float(s.get("energi", 100.0))
    if energi_awal >= ENERGI_SEGAR_MIN:
        raise CepatError("Pak Misran masih segar, belum perlu istirahat.")
    stok[minuman] = int(stok.get(minuman, 0)) - 1
    energi_baru = min(energi_awal + ENERGI_KOPI, 100.0)
    s["energi"] = energi_baru
    catatan["ngopi"] = int(catatan.get("ngopi", 0) or 0) + 1
    menit_baru = menit + DURASI_NGOPI_MENIT
    s["menit"] = menit_baru
    catatan["ngopi_menit"] = menit_baru
    return {
        "slot": s,
        "minuman": minuman,
        "nama_minuman": str(data.katalog[minuman].get("nama", minuman)),
        "energi_awal": energi_awal,
        "energi_akhir": energi_baru,
        "menit_baru": menit_baru,
    }


# -- /tutup -----------------------------------------------------------------

def tutup_hari_bot(slot: dict, data: GameData) -> dict:
    """Tutup warung + tidur ke hari baru — ``tutup_hari()`` via
    ``sim._tutup_hari`` (lihat docstring modul).

    Angka hari ini diambil dari save: omzet/laba/terjual dari
    ``penjualan_hari`` (per barang, otoritatif); dilayani/batal/belanja
    dari ``catatan_hari`` — TAPI hanya bila hari ini ada penjualan
    (bila tidak ada, catatan bisa jadi ringkasan kemarin — lihat
    ``_catatan_hari_ini`` — maka dipakai 0).
    """
    s = sim_mod._normalisasi_slot(slot)
    penjualan = s.get("penjualan_hari") or {}
    omzet = 0
    laba = 0
    barang = 0
    for r in penjualan.values():
        try:
            barang += int(r[0])
            omzet += int(r[1])
            laba += int(r[2])
        except (TypeError, ValueError, IndexError):
            continue
    catatan = s.get("catatan_hari") or {}
    if penjualan and isinstance(catatan, dict):
        dilayani = int(catatan.get("dilayani", 0) or 0)
        batal = int(catatan.get("batal", 0) or 0)
        belanja = int(catatan.get("belanja", 0) or 0)
        hadiah = int(catatan.get("hadiah", 0) or 0)
    else:
        dilayani = batal = belanja = hadiah = 0
    hari_ini = {"omzet": omzet, "laba": laba, "barang": barang,
                "dilayani": dilayani, "batal": batal,
                "belanja": belanja, "hadiah": hadiah}
    hari_lama = int(s.get("hari", 1))
    uang_awal = int(s.get("uang", 0))
    sim_mod._tutup_hari(s, data, hari_ini)
    # Diusir bila tunggakan mencapai 3 minggu (auto.py bayar_sewa).
    diusir = False
    if int(s.get("minggu_tunggak", 0) or 0) >= MINGGU_DIUSIR:
        s["diusir"] = True
        diusir = True
    return {
        "slot": s,
        "hari_lama": hari_lama,
        "hari_baru": int(s.get("hari", 1)),
        "omzet": omzet,
        "laba": laba,
        "barang": barang,
        "dilayani": dilayani,
        "batal": batal,
        "belanja": belanja,
        "biaya_harian": int(hari_ini.get("biaya_harian", 0)),
        "sewa": int(hari_ini.get("sewa", 0)),
        "uang_awal": uang_awal,
        "uang_akhir": int(s.get("uang", 0)),
        "tunggakan_sewa": int(s.get("tunggakan_sewa", 0) or 0),
        "minggu_tunggak": int(s.get("minggu_tunggak", 0) or 0),
        "diusir": diusir,
    }
