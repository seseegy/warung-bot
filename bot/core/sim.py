"""Mesin simulasi satu hari game Warung Life Simulator 1.2.

Seluruh rumus digrounding ke kode hasil decompile GDRE (BUKAN ditebak):

- Jam buka/tutup: ``JAM_BUKA = 9*60``, ``JAM_WAJIB_TUTUP = 17*60``,
  ``JAM_TUTUP_RAMADAN = 19*60``, kios milik 24:00 (``game_state.gd:17,1972,
  7724``). Jumat libur (``HARI_LIBUR = ["Jumat"]``, ``game_state.gd:714``).
  RANCANGAN §6 yang menulis hari 07.00-26.00 (1.140 menit) SALAH untuk
  jendela jualan: jualan normal 09.00-17.00 = 480 menit game.
- Timer kedatangan jalan dalam DETIK NYATA (``layanan.gd`` ``_process(delta)``),
  sedangkan jam game maju ``delta * kecepatan_waktu`` (1,52 normal,
  ``warung.gd:447``). Satu hari jualan = 480/1,52 = ~316 detik nyata.
- Interval kedatangan (``layanan.gd:136-175``):
  ``randf_range(jeda)`` dengan ``jeda = jeda_datang * pengali_jam * datang
  * keramaian * ramai_upgrade * jeda_kejadian * pengajian * ramai_murah
  * ramai_cerita * ramai_promosi * 1,4``.
- ``pengali_jam`` (``layanan.gd:2321``): non-Ramadan <10: 0,55, <11: 0,9,
  <13: 0,8, <15.5: 1,3, <17: 0,55, <19: 1,3, <21: 2,4, else 3,5. (Dokumen
  UX menulis batas 15.30/16.30 — kode yang menang: 15.5/17.0.)
- ``pengali_keramaian = 1 / clamp(0,4 + 0,06*(hari-1), 0,4, 1,0)``
  (``game_state.gd:7359``). ``pengali_ramai_upgrade = 1 / (1 + ramai +
  malam bila >= 15.00)`` (``game_state.gd:7661``).
- ``efek_harga_murah`` memakai rasio harga_jual/harga_PASAR (``rasio_harga``,
  ``game_state.gd:5758``) — dokumen UX §4.10 menulis "harga normal", SALAH.
  ``pengali_ramai_murah = 1 / (1 + efek*1,5)``, efek dibatasi 0,2
  (``game_state.gd:7896``).
- Reputasi: HANYA "datang" berubah (3: 0,95, 4: 0,9, 5: 0,85),
  ``efek_reputasi_bintang`` (``game_state.gd:5606``).
- Harga: ``harga_modal`` (``game_state.gd:5716``), ``langkah_harga`` dari
  harga KATALOG (bukan harga jual saat ini), ``batas_harga_jual``,
  ``harga_pasar`` (``game_state.gd:8837``), lantai
  ``min(max(modal, harga_modal)+100, pasar)`` (``ubah_harga_jual``,
  ``game_state.gd:5730``) — lantai BOLEH di bawah modal+100 bila pasar
  lebih rendah. ``TAMBAHAN_AGEN = 0,1`` hanya untuk item agen
  (``lewat_agen``, ``game_state.gd:8025``).
- ``jual()`` (``game_state.gd:2356``): per unit — stok -1 (fisik) atau
  saldo_layanan - modal (layanan), uang += harga, omzet/laba, progres.
- Keluhan harga (``layanan.gd:27-30, 505-540, 2318``): peluang mengeluh
  ``clamp((rasio-1)/0,3, 0, 1) * 0,9`` dengan rasio = harga_jual/harga_pasar
  tertinggi di pesanan; bila mengeluh dan ``rand >= 0,25`` -> batal.
- Kesabaran (``layanan.gd:165-177, 338, 481-484``): antre
  ``sabar_antre_dasar * pengali_sabar(true)``; di depan
  ``batas_respon(n_jenis) * pengali_sabar(false)`` dengan ``waktu`` di-reset
  0 saat naik ke depan; antre diperlambat ``1/(1+0,25*max(n_antre-1,0))``.
- Layani sebagian (``layanan.gd:1878``): pesanan dipotong ke stok yang ada;
  bila semuanya habis -> pelanggan pulang "habis" setelah 1,4 detik.
- QRIS per pelanggan (``layanan.gd:627``): upgrade qris + ``rand < 0,35``,
  bukan tipe anak -> seluruh total pindah ke saldo_digital.
- Energi (``game_state.gd:940-983, 953``): 0,039/menit siang, 0,099/menit
  malam (>= 21.00), x0,85 bila rumah renovasi. Lelah < 30 -> batas respon
  x0,85. Istirahat +30 (ngopi/makan, 1x/hari tiap jenis).
- Biaya harian (``game_state.gd:6491, 6722``): 10rb casual / 20rb hard +
  jumlah ``biaya_hari`` upgrade, dipotong saat tutup hari.
- Sewa (``game_state.gd:6284, 6421-6470``): tiap Minggu (``hari % 7 == 0``),
  ``sewa_per_minggu(tingkat) + tunggakan - cicilan``; bayar dari saldo
  digital dulu lalu uang; kurang -> ``minggu_tunggak += 1``; denda efektif 0
  (``MAKS_DENDA_SEWA = 0``); diusir bila ``minggu_tunggak >= 3``.
- Tugas (``game_state.gd:3054-3205``): ``faktor_macet`` (casual, setelah 45
  hari di level, -2%/hari, min 0,5), ``faktor_keringanan`` (setelah inti
  beres +5 hari, -10%/hari, min 0,4), target omzet dibulatkan ke ribuan.
  Naik level: hadiah, tingkat+1, progres direset, buka barang level baru.
- ``tingkat_bantuan`` dari ``riwayat_layan`` 20 terakhir (butuh >= 8 entri)
  (``game_state.gd:2965``). ``pengali_barang_ramadan`` /
  ``borong_takjil`` (``game_state.gd:7753-7769``).

Yang TIDAK disimulasikan (dinyatakan jujur di hasil): ulasan/reputasi
dinamis (bintang ditahan dari save), cuaca & event acak, hutang pelanggan,
minigame tip/QRIS, titipan sales, grosir, jelajah, kerja sampingan,
cerita/misi (uang misi tidak dibayar di sim), harga pasar Senin
(``harga_pasaran`` ditahan dari save), sakit, palak/pencurian. Hasil
simulasi adalah PROYEKSI, bukan replay persis game.
"""

from __future__ import annotations

import copy
import json
import math
import random
from pathlib import Path

# -- konstanta waktu & hari (game_state.gd) ------------------------------
JAM_BUKA = 9 * 60
JAM_WAJIB_TUTUP = 17 * 60
JAM_TUTUP_RAMADAN = 19 * 60
JAM_TUTUP_KIOS_MILIK = 24 * 60
JAM_TUTUP_KIOS_MILIK_RONDA = 22 * 60
JAM_BATAS = 26 * 60
KECEPATAN_WAKTU = 1.52  # "normal" (game_state.gd:48,75)
NAMA_HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
HARI_LIBUR = {"Jumat"}
RAMADAN_MULAI = 55  # HARI_LEBARAN - 30
HARI_LEBARAN = 85

# -- energi (game_state.gd:940-983) --------------------------------------
ENERGI_PER_MENIT_SIANG = 0.039
ENERGI_PER_MENIT_MALAM = 0.099
JAM_MALAM_LELAH = 21 * 60
BATAS_LELAH = 30.0
ENERGI_MIN_BUKA = 20.0
ENERGI_ISTIRAHAT = 30.0
PENGALI_ENERGI_RUMAH_BARU = 0.85

# -- pelanggan & kedatangan ----------------------------------------------
PENGALI_JEDA_PEMBELI = 1.4
JEDA_PERTAMA = (1.5, 3.5)
PENGALI_RAMAI_MURAH = 1.5
BATAS_RAMAI_MURAH = 0.3
PENGALI_SABAR_MURAH = 1.0
PERLAMBAT_SABAR_RAMAI = 0.25
KERINGANAN_AWAL = {1: (4.0, 2.0), 2: (4.0, 2.0), 3: (2.0, 1.0)}
BATAS_BINTANG = [0, 25, 50, 75, 90]
MAHAL_MULAI = 1.0
MAHAL_PENUH = 1.3
PELUANG_KELUH_MAKS = 0.9
PELUANG_TETAP_BELI = 0.25
PELUANG_BAYAR_QRIS = 0.35
BANTUAN_JENDELA = 20
BANTUAN_SABAR = 0.3
AGUS_BONUS_SABAR = 0.25
BARANG_RAMADAN = ["kurma", "sirup"]
BARANG_TAKJIL = ["kurma", "sirup", "teh_botol", "air_mineral", "kerupuk",
                 "soda", "susu_kotak", "es_krim", "biskuit"]
BARANG_MASAK = ["sayur", "gula", "minyak_goreng", "telur", "beras",
                "kopi_bubuk", "mi_rebus"]
BARANG_JAJAN_SIANG = ["ciki", "permen", "es_krim", "air_mineral", "teh_botol",
                      "kopi_susu", "soda", "minuman_energi", "susu_kotak",
                      "mi_goreng", "biskuit", "kerupuk", "sachet"]
PROMOSI_RAMAI = 0.2
LAMA_PROMOSI = 2

# -- ekonomi --------------------------------------------------------------
TAMBAHAN_AGEN = 0.1
HARGA_JUAL_MAKS = 1.3
MAKS_STOK_BARANG = 100
BIAYA_HARIAN = {"casual": 10000, "hard": 20000}
JUMLAH_ISI_OTOMATIS = 50000
LEVEL_AGEN = 2
BARANG_TITIPAN = {"roti", "jamu"}  # SALES_TITIPAN (game_state.gd:10705)
KURIR = {
    "reguler": {"detik": 30.0, "ongkir": 10000},
    "cepat": {"detik": 20.0, "ongkir": 20000},
    "instan": {"detik": 1.0, "ongkir": 0},
}
ONGKIR_REGULER_GRATIS_SAMPAI_LEVEL = 2
LAMA_KURIR_INSTAN = 2

# -- tugas -----------------------------------------------------------------
KERINGANAN_MULAI_HARI = 5
MACET_MULAI_HARI = 45

# -- sim -------------------------------------------------------------------
DT_DEFAULT = 0.5       # langkah simulasi (detik nyata)
LAYANI_DETIK = 2.0     # waktu bot melayani 1 pelanggan (detik nyata)
HABIS_TUNGGU_DETIK = 1.4  # pelanggan barang-habis menunggu lalu pulang


class SimError(ValueError):
    """Input simulasi tidak valid (save rusak, harga di luar batas, ...)."""


# ======================================================================
# Data game
# ======================================================================

class GameData:
    """Katalog + data game dari bot/data/ (salinan asset pack)."""

    def __init__(self, folder: str | Path) -> None:
        folder = Path(folder)
        self.barang = _muat(folder / "barang.json")["barang"]
        self.pelanggan = _muat(folder / "pelanggan.json")["pelanggan"]
        self.upgrade = _muat(folder / "upgrade.json")
        self.tugas = _muat(folder / "tugas.json")["tingkat"]
        self.cerita = _muat(folder / "cerita.json")
        self.event = _muat(folder / "event.json")["event"]
        self.katalog = {b["id"]: b for b in self.barang}
        self.urutan_barang = [b["id"] for b in self.barang]
        self.upgrade_by_id = {u["id"]: u for u in self.upgrade["upgrade"]}
        self.batas_efek = self.upgrade.get("batas", {})

    @classmethod
    def load(cls, folder: str | Path) -> "GameData":
        return cls(folder)


def _muat(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SimError(f"tidak bisa memuat {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SimError(f"{path} bukan object JSON")
    return data


# ======================================================================
# Harga
# ======================================================================

def efek_upgrade(data: GameData, dimiliki: list, kunci: str,
                 bawaan: float = 0.0) -> float:
    """Jumlah efek upgrade yang dimiliki (kurir: minimum).

    ``efek_upgrade()`` game_state.gd:7641 — dibatasi ``batas`` upgrade.json
    (ramai <= 0,5 ; sabar <= 0,85). Efek array (mis. genset: true) dilewati.
    """
    hasil = bawaan
    ada = False
    for uid in dimiliki:
        efek = data.upgrade_by_id.get(str(uid), {}).get("efek", {})
        if kunci not in efek or isinstance(efek.get(kunci), list):
            continue
        nilai = float(efek[kunci])
        if kunci == "kurir":
            hasil = nilai if not ada else min(hasil, nilai)
        elif kunci == "reputasi_turun":
            hasil *= nilai
        else:
            hasil += nilai
        ada = True
    if kunci in data.batas_efek:
        hasil = min(hasil, float(data.batas_efek[kunci]))
    return hasil


def agen_items(data: GameData, slot: dict) -> set:
    """Item yang dibuka lewat agen (event warga hasil 'tolak').

    ``lewat_agen()`` game_state.gd:8025 + ``_buka_barang_agen()``:8034 —
    item di ``hasil.tolong.buka`` dari event yang hasil akhirnya "tolak".
    Item ini kena markup agen +10% di harga_modal.
    """
    cerita_warga = slot.get("cerita_warga", {})
    if not isinstance(cerita_warga, dict):
        return set()
    hasil: set = set()
    for ev, data_ev in data.event.items():
        if cerita_warga.get(ev) != "tolak":
            continue
        buka = data_ev.get("hasil", {}).get("tolong", {}).get("buka", [])
        for item_id in buka:
            if item_id in data.katalog:
                hasil.add(item_id)
    return hasil


def harga_modal(data: GameData, item_id: str, slot: dict,
                lewat_agen: bool | None = None) -> int:
    """Harga modal beli stok (game_state.gd:5716).

    modal katalog x supplier(1,0) x (1+efek supplier) x (1+0,1 bila agen)
    x (1-diskon promo), dibulatkan ke ratusan.
    """
    item = data.katalog[item_id]
    dimiliki = slot.get("upgrade", []) or []
    pengali = 1.0 * (1.0 + efek_upgrade(data, dimiliki, "supplier"))
    if lewat_agen is None:
        lewat_agen = item_id in agen_items(data, slot)
    if lewat_agen:
        pengali *= 1.0 + TAMBAHAN_AGEN
    promo = slot.get("promo", {}) or {}
    if isinstance(promo, dict) and slot.get("promo_hari_ke") == slot.get("hari"):
        diskon = float(promo.get(item_id, 0.0) or 0.0)
        pengali *= 1.0 - diskon
    return int(round(float(item["modal"]) * pengali / 100.0) * 100)


def langkah_harga(data: GameData, item_id: str) -> int:
    """Langkah tombol +/- harga: dari harga KATALOG (game_state.gd:5723)."""
    return 100 if int(data.katalog[item_id]["jual"]) < 10000 else 500


def agen_aktif(slot: dict) -> bool:
    """Info harga pasar aktif mulai level 2 (game_state.gd:8833)."""
    return int(slot.get("tingkat", 0)) + 1 >= LEVEL_AGEN


def harga_pasar(data: GameData, item_id: str, slot: dict) -> int:
    """Harga pasar minggu ini (game_state.gd:8837).

    Tanpa agen / tanpa entri -> harga katalog. Ada lantai:
    max(pasar, min(dasar, max(modal, harga_modal)+100)).
    """
    item = data.katalog[item_id]
    dasar = int(item["jual"])
    pasaran = slot.get("harga_pasaran", {}) or {}
    if not agen_aktif(slot) or item_id not in pasaran:
        return dasar
    pasar = max(100, int(round(dasar * float(pasaran[item_id]) / 100.0)) * 100)
    lantai = min(dasar, max(int(item["modal"]), harga_modal(data, item_id, slot)) + 100)
    return max(pasar, lantai)


def batas_harga_jual(data: GameData, item_id: str, slot: dict) -> int:
    """Batas atas harga jual (game_state.gd:5706)."""
    normal = int(data.katalog[item_id]["jual"])
    langkah = langkah_harga(data, item_id)
    return max(int(normal * HARGA_JUAL_MAKS) // langkah * langkah,
               harga_pasar(data, item_id, slot))


def lantai_harga(data: GameData, item_id: str, slot: dict) -> int:
    """Batas bawah harga jual (game_state.gd:5730).

    min(max(modal katalog, harga_modal)+100, harga_pasar) — BOLEH di bawah
    modal+100 bila harga pasarnya lebih rendah.
    """
    item = data.katalog[item_id]
    return min(max(int(item["modal"]), harga_modal(data, item_id, slot)) + 100,
               harga_pasar(data, item_id, slot))


def harga_jual(data: GameData, item_id: str, slot: dict,
               harga_khusus: dict | None = None) -> int:
    """Harga yang dikenakan ke pelanggan (game_state.gd:5711)."""
    khusus = harga_khusus if harga_khusus is not None else slot.get("harga_jual_khusus", {}) or {}
    item = data.katalog[item_id]
    return min(int(khusus.get(item_id, item["jual"])),
               batas_harga_jual(data, item_id, slot))


def rasio_harga(data: GameData, item_id: str, slot: dict) -> float:
    """harga_jual / harga_pasar (game_state.gd:5758)."""
    return float(harga_jual(data, item_id, slot)) / float(harga_pasar(data, item_id, slot))


def efek_harga_murah(data: GameData, slot: dict) -> float:
    """Rata-rata murahnya harga vs pasar (game_state.gd:7896).

    Hanya barang fisik yang terbuka. Dibatasi 0,3/1,5 = 0,2.
    """
    total = 0.0
    n = 0
    terbuka = set(slot.get("barang_terbuka", []) or [])
    for item_id in data.urutan_barang:
        item = data.katalog[item_id]
        if item["jenis"] != "fisik" or item_id not in terbuka:
            continue
        total += max(0.0, 1.0 - rasio_harga(data, item_id, slot))
        n += 1
    if n == 0:
        return 0.0
    return min(total / n, BATAS_RAMAI_MURAH / PENGALI_RAMAI_MURAH)


# ======================================================================
# Reputasi, bantuan, tugas
# ======================================================================

def bintang_dari_reputasi(reputasi: float, ada_ulasan: bool) -> int:
    """Bintang dari reputasi (``_bintang_dari``, game_state.gd:4772)."""
    if not ada_ulasan:
        return 0
    b = 1
    for i, batas in enumerate(BATAS_BINTANG):
        if reputasi >= batas - 0.001:
            b = i + 1
    return b


def efek_datang(bintang: int) -> float:
    """Pengali interval kedatangan menurut bintang (5606)."""
    return {3: 0.95, 4: 0.9, 5: 0.85}.get(bintang, 1.0)


def tingkat_bantuan(slot: dict) -> float:
    """Bantuan dari riwayat layani 20 terakhir (game_state.gd:2965).

    Casual saja, butuh >= 8 entri; 0 bila kurang.
    """
    if str(slot.get("mode", "casual")) != "casual":
        return 0.0
    riwayat = slot.get("riwayat_layan", []) or []
    if len(riwayat) < 8:
        return 0.0
    batal = sum(1 for x in riwayat if not x)
    return max(0.0, min(1.0, (batal / len(riwayat) - 0.12) / 0.25))


def hari_di_level(slot: dict) -> int:
    return int(slot.get("hari", 1)) - int(slot.get("hari_level_mulai", 1))


def faktor_macet(slot: dict) -> float:
    """Ringan target inti setelah 45 hari di level (game_state.gd:3105)."""
    if str(slot.get("mode", "casual")) != "casual":
        return 1.0
    return max(0.5, min(1.0, 1.0 - 0.02 * (hari_di_level(slot) - MACET_MULAI_HARI)))


def hari_keringanan(slot: dict) -> int:
    """Hari sejak inti beres minus 5 (game_state.gd:3070)."""
    if str(slot.get("mode", "casual")) != "casual":
        return 0
    hib = int(slot.get("hari_inti_beres", 0) or 0)
    if hib <= 0:
        return 0
    return max(0, int(slot.get("hari", 1)) - hib - KERINGANAN_MULAI_HARI + 1)


def faktor_keringanan(slot: dict) -> float:
    return max(0.4, 1.0 - 0.1 * hari_keringanan(slot))


def target_inti(data: GameData, slot: dict, kunci: str) -> int:
    """Target inti level berjalan, dengan faktor_macet (game_state.gd:3115)."""
    tingkat = int(slot.get("tingkat", 0))
    if tingkat >= len(data.tugas):
        return 0
    n = int(data.tugas[tingkat].get(kunci, 0))
    if kunci == "omzet":
        return int(math.ceil(n * faktor_macet(slot) / 1000.0)) * 1000
    return math.ceil(n * faktor_macet(slot))


def target_khusus(data: GameData, slot: dict) -> int:
    """Target tugas khusus level berjalan (game_state.gd:3077)."""
    tingkat = int(slot.get("tingkat", 0))
    if tingkat >= len(data.tugas):
        return 0
    khusus = data.tugas[tingkat].get("khusus", {}) or {}
    n = int(khusus.get("target", 0))
    if n <= 0:
        return 0
    return max(1, math.ceil(n * faktor_keringanan(slot)))


def jenis_khusus(data: GameData, slot: dict) -> str:
    tingkat = int(slot.get("tingkat", 0))
    if tingkat >= len(data.tugas):
        return ""
    return str((data.tugas[tingkat].get("khusus", {}) or {}).get("jenis", ""))


# ======================================================================
# Jam & kedatangan
# ======================================================================

def nama_hari(hari: int) -> str:
    return NAMA_HARI[(int(hari) - 1) % 7]


def ramadan(hari: int) -> bool:
    """Hari 55-84 (game_state.gd:7714)."""
    return RAMADAN_MULAI <= int(hari) < HARI_LEBARAN


def jam_wajib_tutup(slot: dict) -> int:
    """Jam tutup jualan dalam menit (game_state.gd:7724)."""
    if slot.get("kios_milik"):
        if nama_hari(int(slot.get("hari", 1))) == "Kamis" and slot.get("ikut_ronda_jumatan"):
            return JAM_TUTUP_KIOS_MILIK_RONDA
        return JAM_TUTUP_KIOS_MILIK
    return JAM_TUTUP_RAMADAN if ramadan(int(slot.get("hari", 1))) else JAM_WAJIB_TUTUP


def pengali_jam(menit: float, is_ramadan: bool) -> float:
    """Keramaian menurut jam (layanan.gd:2321 — batas kode, bukan dokumen)."""
    jam = menit / 60.0
    if is_ramadan:
        if jam < 10.0:
            return 0.6
        if jam < 11.0:
            return 1.2
        if jam < 15.0:
            return 2.0
        if jam < 16.5:
            return 0.85
        if jam < 18.0:
            return 0.6
        return 1.8
    if jam < 10.0:
        return 0.55
    if jam < 11.0:
        return 0.9
    if jam < 13.0:
        return 0.8
    if jam < 15.5:
        return 1.3
    if jam < 17.0:
        return 0.55
    if jam < 19.0:
        return 1.3
    if jam < 21.0:
        return 2.4
    return 3.5


def pengali_keramaian(hari: int) -> float:
    return 1.0 / max(0.4, min(1.0, 0.4 + 0.06 * (int(hari) - 1)))


def pengali_ramai_upgrade(data: GameData, slot: dict, menit: float) -> float:
    bonus = efek_upgrade(data, slot.get("upgrade", []) or [], "ramai")
    if menit >= 15 * 60:
        bonus += efek_upgrade(data, slot.get("upgrade", []) or [], "malam")
    return 1.0 / (1.0 + bonus)


def pengali_ramai_promosi(slot: dict) -> float:
    mulai = int(slot.get("promosi_mulai", 0) or 0)
    hari = int(slot.get("hari", 1))
    if mulai > 0 and mulai <= hari < mulai + LAMA_PROMOSI:
        return 1.0 / (1.0 + PROMOSI_RAMAI)
    return 1.0


def pengali_sabar(data: GameData, slot: dict, saat_antre: bool) -> float:
    """Pengali kesabaran (game_state.gd:7912)."""
    dimiliki = slot.get("upgrade", []) or []
    bonus = efek_upgrade(data, dimiliki, "sabar")
    if saat_antre:
        bonus += efek_upgrade(data, dimiliki, "sabar_antre")
    bonus = min(bonus, float(data.batas_efek.get("sabar", 0.35)))
    if slot.get("agus_bantu_sampai", 0) and int(slot.get("hari", 1)) <= int(slot.get("agus_bantu_sampai", 0)):
        bonus += AGUS_BONUS_SABAR
    bonus += efek_harga_murah(data, slot) * PENGALI_SABAR_MURAH
    return 1.0 * (1.0 + bonus) * (1.0 + BANTUAN_SABAR * tingkat_bantuan(slot))


def sabar_antre_dasar(slot: dict) -> float:
    """Sabar antre dasar (game_state.gd:7376)."""
    aturan = {"casual": 16.0, "hard": 8.0}
    dasar = aturan.get(str(slot.get("mode", "casual")), 16.0)
    level = int(slot.get("tingkat", 0)) + 1
    keringanan = KERINGANAN_AWAL.get(level, (0.0, 0.0))[0]
    if str(slot.get("mode", "casual")) != "casual":
        keringanan = 0.0
    return dasar + keringanan


def batas_respon(data: GameData, slot: dict, jumlah_jenis: int) -> float:
    """Batas waktu layani di depan (game_state.gd:7381)."""
    aturan_respon = {"casual": 6.5, "hard": 4.0}
    aturan_per_barang = {"casual": 2.5, "hard": 1.6}
    mode = str(slot.get("mode", "casual"))
    level = int(slot.get("tingkat", 0)) + 1
    keringanan = KERINGANAN_AWAL.get(level, (0.0, 0.0))[1]
    if mode != "casual":
        keringanan = 0.0
    nilai = (aturan_respon.get(mode, 6.5) + keringanan
             + aturan_per_barang.get(mode, 2.5) * max(jumlah_jenis - 1, 0)
             + efek_upgrade(data, slot.get("upgrade", []) or [], "respon"))
    if float(slot.get("energi", 100.0)) < BATAS_LELAH:
        nilai *= 0.85
    return nilai


def maks_antre(data: GameData, slot: dict) -> int:
    aturan = {"casual": 4, "hard": 5}
    return int(aturan.get(str(slot.get("mode", "casual")), 4)) + int(
        efek_upgrade(data, slot.get("upgrade", []) or [], "maks_antre"))


def interval_datang(data: GameData, slot: dict, menit: float) -> tuple[float, float]:
    """Rentang (lo, hi) detik nyata sampai pelanggan berikut (layanan.gd:145)."""
    aturan_jeda = {"casual": (5.0, 11.0), "hard": (3.0, 8.0)}
    lo, hi = aturan_jeda.get(str(slot.get("mode", "casual")), (5.0, 11.0))
    is_ram = ramadan(int(slot.get("hari", 1)))
    bintang = bintang_dari_reputasi(
        float(slot.get("reputasi", 0.0) or 0.0),
        bool(slot.get("ulasan")))
    pengali = (pengali_jam(menit, is_ram)
               * efek_datang(bintang)
               * pengali_keramaian(int(slot.get("hari", 1)))
               * pengali_ramai_upgrade(data, slot, menit)
               * pengali_ramai_promosi(slot)
               * (1.0 / (1.0 + efek_harga_murah(data, slot) * PENGALI_RAMAI_MURAH))
               * PENGALI_JEDA_PEMBELI)
    # pengali_jeda_kejadian, pengali_pengajian, pengali_ramai_cerita = 1,0
    # di sim (tidak ada event/cuaca/pengajian yang aktif).
    return lo * pengali, hi * pengali


# ======================================================================
# Pesanan
# ======================================================================

def peluang_barang(data: GameData, slot: dict, item_id: str, menit: float) -> float:
    """Bobot minta barang (game_state.gd:2840)."""
    item = data.katalog[item_id]
    p = float(item.get("peluang", 1))
    jam = menit / 60.0
    for rentang in item.get("jam_laris", []) or []:
        if jam >= float(rentang[0]) and jam < float(rentang[1]):
            p *= float(rentang[2])
    if item.get("kategori", "") == "minuman":
        p *= 1.0 + efek_upgrade(data, slot.get("upgrade", []) or [], "minuman")
    p *= _pengali_barang_ramadan(item_id, menit, int(slot.get("hari", 1)))
    return p


def _pengali_barang_ramadan(item_id: str, menit: float, hari: int) -> float:
    """Pengali barang saat Ramadan (game_state.gd:7753)."""
    if not ramadan(hari):
        return 0.25 if item_id in BARANG_RAMADAN else 1.0
    jam = menit / 60.0
    p = 1.0
    if jam < 11.0 and item_id in BARANG_MASAK:
        p *= 1.8
    if jam < 15.0 and item_id in BARANG_JAJAN_SIANG:
        p *= 0.3
    if jam >= 15.0 and item_id in BARANG_TAKJIL:
        p *= 1.6
    return p


def bisa_diminta(data: GameData, slot: dict, item_id: str) -> bool:
    """Bisa dipesan: terbuka, dan titipan harus ada stok (game_state.gd:2835)."""
    terbuka = set(slot.get("barang_terbuka", []) or [])
    if item_id not in terbuka:
        return False
    if item_id in BARANG_TITIPAN and int((slot.get("stok", {}) or {}).get(item_id, 0)) <= 0:
        return False
    return True


def barang_acak(data: GameData, slot: dict, dilarang: list, suka: dict,
                menit: float, rng: random.Random) -> str | None:
    """Pilih barang berbobot peluang x suka (game_state.gd:2817)."""
    pilihan = [i for i in data.urutan_barang
               if bisa_diminta(data, slot, i) and i not in dilarang]
    if not pilihan:
        terbuka = set(slot.get("barang_terbuka", []) or [])
        pilihan = [i for i in data.urutan_barang
                   if i in terbuka and i not in dilarang]
    if not pilihan:
        return None
    bobot = [peluang_barang(data, slot, i, menit) * float(suka.get(i, 1.0))
             for i in pilihan]
    total = sum(bobot)
    if total <= 0:
        return pilihan[0]
    r = rng.random() * total
    for item_id, w in zip(pilihan, bobot):
        r -= w
        if r <= 0.0:
            return item_id
    return pilihan[0]


def peluang_pesanan_panjang(slot: dict) -> float:
    """Peluang pesanan panjang 4-7 jenis (game_state.gd:4648)."""
    level = int(slot.get("tingkat", 0)) + 1
    if level < 2 or tingkat_bantuan(slot) > 0.3:
        return 0.0
    return min(0.04 + 0.015 * (level - 2), 0.10)


def pesanan_acak(data: GameData, slot: dict, tipe: dict, menit: float,
                 rng: random.Random) -> list:
    """Pesanan satu pelanggan (game_state.gd:4606).

    Mengembalikan [(id, jumlah), ...]. Item titipan tanpa stok tidak bisa
    dipesan; barang lain BOLEH dipesan walau stok 0 (nanti dilayani
    sebagian — yang ada saja).
    """
    dilarang = list(tipe.get("tidak_boleh_beli", []) or [])
    suka = tipe.get("suka", {}) or {}
    bantuan = tingkat_bantuan(slot)
    banyak_jenis = 1
    panjang = rng.random() < peluang_pesanan_panjang(slot)
    if panjang:
        fisik = [i for i in data.urutan_barang if bisa_diminta(data, slot, i)
                 and i not in dilarang]
        r = rng.random()
        banyak_jenis = min(4 if r < 0.35 else (5 if r < 0.65 else (6 if r < 0.85 else 7)),
                           len(fisik))
        dilarang = dilarang + [i for i in data.urutan_barang if i not in fisik]
    else:
        peluang_banyak = {"casual": 0.35, "hard": 0.6}.get(
            str(slot.get("mode", "casual")), 0.35)
        peluang = (peluang_banyak
                   + efek_upgrade(data, slot.get("upgrade", []) or [], "banyak")) \
            * (1.0 - 0.5 * bantuan)
        if rng.random() < peluang:
            banyak_jenis = 2 if rng.random() < 0.7 + 0.3 * bantuan else 3
    hasil: list = []
    dipakai: set = set()
    for _ in range(banyak_jenis * 6):
        if len(hasil) >= banyak_jenis:
            break
        item_id = barang_acak(data, slot, dilarang, suka, menit, rng)
        if item_id is None or item_id in dipakai:
            continue
        dipakai.add(item_id)
        jumlah = 1
        if data.katalog[item_id]["jenis"] == "fisik":
            r = rng.random()
            if panjang:
                jumlah = 1 if r < 0.85 else 2
            elif (ramadan(int(slot.get("hari", 1))) and menit >= 15 * 60
                    and item_id in BARANG_TAKJIL and rng.random() < 0.3):
                jumlah = 2 + rng.randrange(2)
            else:
                jumlah = 1 if r < 0.65 else (2 if r < 0.92 else 3)
        hasil.append([item_id, jumlah])
    return hasil


# ======================================================================
# Simulasi satu hari
# ======================================================================

def _normalisasi_slot(slot: dict) -> dict:
    """Salinan slot dengan default aman untuk semua field yang dibaca sim."""
    s = copy.deepcopy(slot)
    s.setdefault("mode", "casual")
    s.setdefault("hari", 1)
    s.setdefault("uang", 0)
    s.setdefault("saldo_digital", 0)
    s.setdefault("saldo_layanan", 0)
    s.setdefault("stok", {})
    s.setdefault("kiriman_stok", {})
    s.setdefault("tas_grosir", {})
    s.setdefault("harga_jual_khusus", {})
    s.setdefault("harga_pasaran", {})
    s.setdefault("tingkat", 0)
    s.setdefault("progres", {"pelanggan": 0, "barang": 0, "omzet": 0, "khusus": 0})
    s.setdefault("beruntun_sekarang", 0)
    s.setdefault("hari_inti_beres", 0)
    s.setdefault("hari_level_mulai", 1)
    s.setdefault("upgrade", [])
    s.setdefault("misi_status", "")
    s.setdefault("cerita_tamat", False)
    s.setdefault("kios_milik", False)
    s.setdefault("rumah_renovasi", False)
    s.setdefault("motor_baru", False)
    s.setdefault("tunggakan_sewa", 0)
    s.setdefault("sewa_cicil", 0)
    s.setdefault("sewa_selesai_hari", 0)
    s.setdefault("minggu_tunggak", 0)
    s.setdefault("diusir", False)
    s.setdefault("reputasi", 0.0)
    s.setdefault("ulasan", [])
    s.setdefault("riwayat_layan", [])
    s.setdefault("promosi_mulai", 0)
    s.setdefault("promo", {})
    s.setdefault("promo_hari_ke", 0)
    s.setdefault("barang_terbuka", [])
    s.setdefault("energi", 100.0)
    s.setdefault("total_pembeli", 0)
    s.setdefault("pembeli_minggu", 0)
    s.setdefault("pembeli_bulan", 0)
    s.setdefault("omzet_minggu", 0)
    s.setdefault("omzet_bulan", 0)
    s.setdefault("riwayat", [])
    s.setdefault("penjualan_hari", {})
    s.setdefault("agus_bantu_sampai", 0)
    s.setdefault("istirahat_hari", {})
    # Koersi tipe: save asli kadang menyimpan field dict sebagai list kosong
    # (mis. penjualan_hari: []) — sim butuh dict/list yang benar di sini,
    # kalau tidak .get()/.append() crash di tengah simulasi.
    for kunci in ("stok", "kiriman_stok", "tas_grosir", "harga_jual_khusus",
                  "harga_pasaran", "progres", "penjualan_hari", "cerita_warga",
                  "keakraban", "promo", "istirahat_hari"):
        if not isinstance(s.get(kunci), dict):
            s[kunci] = {}
    for kunci in ("upgrade", "barang_terbuka", "riwayat_layan", "ulasan",
                  "agen_kenalan", "riwayat"):
        if not isinstance(s.get(kunci), list):
            s[kunci] = []
    return s


def _drain_energi(s: dict, dari: float, sampai: float) -> None:
    """Kurangi energi per menit game yang lewat (game_state.gd:953)."""
    if sampai <= dari:
        return
    siang = max(0.0, min(sampai, JAM_MALAM_LELAH) - dari)
    siang = min(siang, sampai - dari)
    malam = (sampai - dari) - siang
    k = PENGALI_ENERGI_RUMAH_BARU if s.get("rumah_renovasi") else 1.0
    s["energi"] = max(0.0, min(100.0, float(s.get("energi", 100.0))
                               - (siang * ENERGI_PER_MENIT_SIANG
                                  + malam * ENERGI_PER_MENIT_MALAM) * k))


def _istirahat(s: dict, rng: random.Random) -> bool:
    """Istirahat otomatis bot bila energi kritis (+30, 1x/hari/jenis).

    Ngopi pakai sachet/kopi_susu/minuman_energi, makan pakai mi_rebus
    (game_state.gd:987-1011). Mengembalikan True bila berhasil istirahat.
    """
    sudah = s.setdefault("istirahat_hari", {})
    if not isinstance(sudah, dict):
        sudah = s["istirahat_hari"] = {}
    stok = s.get("stok", {}) or {}
    for aksi, barang in (("ngopi", ["sachet", "kopi_susu", "minuman_energi"]),
                         ("makan", ["mi_rebus"])):
        if sudah.get(aksi):
            continue
        for item_id in barang:
            if int(stok.get(item_id, 0)) > 0:
                stok[item_id] = int(stok[item_id]) - 1
                sudah[aksi] = True
                s["energi"] = min(100.0, float(s.get("energi", 0.0)) + ENERGI_ISTIRAHAT)
                return True
    return False


def _cek_tugas(s: dict, data: GameData) -> bool:
    """Cek naik level seperti ``_cek_tugas()`` (game_state.gd:3158).

    Mengembalikan True bila naik level (hadiah sudah ditambahkan, progres
    direset, barang level baru dibuka). Dipanggil setelah tiap penjualan
    dan tiap pelanggan dilayani — sama seperti game.
    """
    tingkat = int(s.get("tingkat", 0))
    if tingkat >= len(data.tugas):
        return False
    t = data.tugas[tingkat]
    progres = s.get("progres", {}) or {}
    agus_beres = (str(s.get("misi_status", "")) in ("", "lunas")
                  or bool(s.get("cerita_tamat")))
    inti_beres = (
        int(progres.get("pelanggan", 0)) >= target_inti(data, s, "pelanggan")
        and int(progres.get("barang", 0)) >= target_inti(data, s, "barang")
        and int(progres.get("omzet", 0)) >= target_inti(data, s, "omzet")
        and agus_beres
    )
    if inti_beres and int(s.get("hari_inti_beres", 0) or 0) <= 0:
        s["hari_inti_beres"] = int(s.get("hari", 1))
    khusus_beres = int(progres.get("khusus", 0)) >= target_khusus(data, s)
    if not (inti_beres and khusus_beres):
        return False
    syarat_upgrade = t.get("upgrade", []) or []
    if syarat_upgrade and not any(u in (s.get("upgrade", []) or [])
                                  for u in syarat_upgrade):
        return False
    # Naik level.
    hadiah = int(t.get("hadiah", 0))
    s["uang"] = int(s.get("uang", 0)) + hadiah
    s["_hadiah_hari"] = int(s.get("_hadiah_hari", 0)) + hadiah
    buka = list(t.get("buka", []) or [])
    if str(s.get("misi_status", "")) == "lunas" and not s.get("cerita_tamat"):
        bab = int(s.get("bab", 0))
        daftar_bab = (data.cerita.get("bab", []) or [])
        if 0 <= bab < len(daftar_bab):
            buka += list(daftar_bab[bab].get("buka", []) or [])
    terbuka = s.setdefault("barang_terbuka", [])
    for item_id in buka:
        if item_id not in terbuka:
            terbuka.append(item_id)
    s["tingkat"] = tingkat + 1
    s["progres"] = {"pelanggan": 0, "barang": 0, "omzet": 0, "khusus": 0}
    s["beruntun_sekarang"] = 0
    s["hari_level_mulai"] = int(s.get("hari", 1))
    s["hari_inti_beres"] = 0
    if int(s.get("tingkat", 0)) >= len(data.tugas):
        s["cerita_tamat"] = True
    return True


def _jual_unit(s: dict, data: GameData, item_id: str, hari_ini: dict) -> None:
    """Satu unit terjual — ``jual()`` game_state.gd:2356 (tanpa _cek_tugas).

    Layanan: saldo_layanan -= modal (pastikan cukup sebelum dipanggil).
    """
    item = data.katalog[item_id]
    harga = harga_jual(data, item_id, s)
    if item["jenis"] == "fisik":
        s["stok"][item_id] = int(s["stok"].get(item_id, 0)) - 1
        modal = harga_modal(data, item_id, s)
    else:
        s["saldo_layanan"] = int(s.get("saldo_layanan", 0)) - int(item["modal"])
        modal = int(item["modal"])
    s["uang"] = int(s.get("uang", 0)) + harga
    hari_ini["omzet"] += harga
    hari_ini["laba"] += harga - modal
    hari_ini["modal"] += modal
    if item["jenis"] == "layanan":
        hari_ini["modal_layanan"] += modal
    hari_ini["barang"] += 1
    progres = s.setdefault("progres", {})
    progres["barang"] = int(progres.get("barang", 0)) + 1
    progres["omzet"] = int(progres.get("omzet", 0)) + harga
    if jenis_khusus(data, s) == "minuman" and item.get("kategori", "") == "minuman":
        progres["khusus"] = int(progres.get("khusus", 0)) + 1
    elif jenis_khusus(data, s) == "laba_hari":
        progres["khusus"] = max(int(progres.get("khusus", 0)), hari_ini["laba"])
    penjualan = s.setdefault("penjualan_hari", {})
    r = penjualan.get(item_id, [0, 0, 0])
    penjualan[item_id] = [int(r[0]) + 1, int(r[1]) + harga, int(r[2]) + harga - modal]


def _layani_pelanggan(s: dict, data: GameData, pelanggan: dict,
                      hari_ini: dict, rng: random.Random) -> str:
    """Selesaikan pelayanan 1 pelanggan di depan. Hasil: 'layani'/'mahal'/'habis'.

    Alur ``layanan.gd:505-600``: keluhan harga dulu, lalu jual per unit,
    lalu QRIS, lalu catat dilayani.
    """
    pesanan = pelanggan["pesanan"]
    stok = s.setdefault("stok", {})
    # Target = pesanan dipotong ke yang tersedia (layani sebagian).
    # Layanan: kapasitas = (saldo + isi otomatis 50rb-an) // modal
    # (``_tersedia`` layanan.gd:1883) — dihitung SEBELUM ada penjualan,
    # karena game memeriksa kecukupan dulu baru menjual.
    target: dict = {}
    for item_id, jumlah in pesanan:
        item = data.katalog[item_id]
        if item["jenis"] == "fisik":
            target[item_id] = min(int(jumlah), max(0, int(stok.get(item_id, 0))))
        else:
            isi = (int(s.get("uang", 0)) // JUMLAH_ISI_OTOMATIS) * JUMLAH_ISI_OTOMATIS
            mampu = (int(s.get("saldo_layanan", 0)) + isi) // max(int(item["modal"]), 1)
            target[item_id] = min(int(jumlah), mampu)
    target = {i: q for i, q in target.items() if q > 0}
    if not target:
        return "habis"
    # Keluhan harga mahal (rasio vs harga pasar, tertinggi di pesanan).
    rasio_max = max(rasio_harga(data, i, s) for i in target)
    p_keluh = max(0.0, min(1.0, (rasio_max - MAHAL_MULAI) / (MAHAL_PENUH - MAHAL_MULAI))) \
        * PELUANG_KELUH_MAKS
    if rng.random() < p_keluh and rng.random() >= PELUANG_TETAP_BELI:
        return "mahal"
    # Jual per unit (layanan: isi saldo otomatis dulu, potongan 50rb).
    for item_id, jumlah in target.items():
        item = data.katalog[item_id]
        if item["jenis"] == "layanan":
            perlu = int(item["modal"]) * int(jumlah)
            while int(s.get("saldo_layanan", 0)) < perlu \
                    and int(s.get("uang", 0)) >= JUMLAH_ISI_OTOMATIS:
                s["saldo_layanan"] = int(s.get("saldo_layanan", 0)) + JUMLAH_ISI_OTOMATIS
                s["uang"] = int(s.get("uang", 0)) - JUMLAH_ISI_OTOMATIS
                hari_ini["isi_layanan"] += JUMLAH_ISI_OTOMATIS
        for _ in range(int(target[item_id])):
            _jual_unit(s, data, item_id, hari_ini)
            _cek_tugas(s, data)
    total = sum(harga_jual(data, i, s) * int(q) for i, q in target.items())
    # QRIS: per pelanggan, bukan tipe anak (layanan.gd:627).
    if ("qris" in (s.get("upgrade", []) or [])
            and pelanggan["tipe"] != "anak"
            and rng.random() < PELUANG_BAYAR_QRIS):
        total = min(total, int(s.get("uang", 0)))
        s["uang"] = int(s.get("uang", 0)) - total
        s["saldo_digital"] = int(s.get("saldo_digital", 0)) + total
        hari_ini["qris"] += total
    # Catat dilayani (game_state.gd:2855).
    s["total_pembeli"] = int(s.get("total_pembeli", 0)) + 1
    s["pembeli_minggu"] = int(s.get("pembeli_minggu", 0)) + 1
    s["pembeli_bulan"] = int(s.get("pembeli_bulan", 0)) + 1
    s["omzet_minggu"] = int(s.get("omzet_minggu", 0)) + total
    s["omzet_bulan"] = int(s.get("omzet_bulan", 0)) + total
    hari_ini["dilayani"] += 1
    progres = s.setdefault("progres", {})
    progres["pelanggan"] = int(progres.get("pelanggan", 0)) + 1
    s["beruntun_sekarang"] = int(s.get("beruntun_sekarang", 0)) + 1
    khusus = jenis_khusus(data, s)
    if khusus == "beruntun":
        progres["khusus"] = max(int(progres.get("khusus", 0)),
                                int(s.get("beruntun_sekarang", 0)))
    elif khusus == "multi" and len(target) >= 2:
        progres["khusus"] = int(progres.get("khusus", 0)) + 1
    s.setdefault("riwayat_layan", []).append(True)
    while len(s["riwayat_layan"]) > BANTUAN_JENDELA:
        s["riwayat_layan"].pop(0)
    _cek_tugas(s, data)
    return "layani"


def _pelanggan_batal(s: dict, hari_ini: dict) -> None:
    """Pelanggan batal/kabur (game_state.gd:2873)."""
    hari_ini["batal"] += 1
    s["beruntun_sekarang"] = 0
    s.setdefault("riwayat_layan", []).append(False)
    while len(s["riwayat_layan"]) > BANTUAN_JENDELA:
        s["riwayat_layan"].pop(0)


def _biaya_harian(data: GameData, s: dict) -> int:
    """Biaya harian saat tutup hari (game_state.gd:6491)."""
    n = BIAYA_HARIAN.get(str(s.get("mode", "casual")), 10000)
    for uid in s.get("upgrade", []) or []:
        # biaya_hari bisa null di JSON (= 0, bukan error).
        n += int(data.upgrade_by_id.get(str(uid), {}).get("biaya_hari") or 0)
    return n


def _sewa_mingguan(data: GameData, s: dict) -> int:
    """Sewa minggu ini menurut tingkat (cerita.json). 0 bila kios milik."""
    if s.get("kios_milik"):
        return 0
    daftar = (data.cerita.get("sewa", {}) or {}).get("per_minggu", [0])
    i = max(0, min(int(s.get("tingkat", 0)), len(daftar) - 1))
    return int(daftar[i])


def _tutup_hari(s: dict, data: GameData, hari_ini: dict) -> None:
    """Tutup hari: hari_sempurna, biaya harian, sewa Minggu, ganti hari.

    Mengikuti ``tutup_hari()`` (game_state.gd:6715) + ``_bayar_sewa()``
    (6421-6470) + ``hari_sempurna`` (6740).
    """
    # hari_sempurna: tutup tanpa batal -> progres = max(progres, dilayani).
    if (jenis_khusus(data, s) == "hari_sempurna"
            and hari_ini["batal"] == 0):
        progres = s.setdefault("progres", {})
        progres["khusus"] = max(int(progres.get("khusus", 0)),
                                hari_ini["dilayani"])
        _cek_tugas(s, data)
    biaya = _biaya_harian(data, s)
    s["uang"] = int(s.get("uang", 0)) - biaya
    hari_ini["biaya_harian"] = biaya
    # Sewa tiap Minggu.
    sewa_dibayar = 0
    if int(s.get("hari", 1)) % 7 == 0 and not s.get("kios_milik"):
        tagihan = max(_sewa_mingguan(data, s) - int(s.get("sewa_cicil", 0) or 0), 0) \
            + int(s.get("tunggakan_sewa", 0) or 0)
        if int(s.get("sewa_cicil", 0) or 0) > min(int(s.get("sewa_cicil", 0) or 0),
                                                  _sewa_mingguan(data, s)):
            s["uang"] = int(s.get("uang", 0)) + int(s.get("sewa_cicil", 0)) \
                - min(int(s.get("sewa_cicil", 0) or 0), _sewa_mingguan(data, s))
        s["sewa_cicil"] = 0
        s["sewa_selesai_hari"] = int(s.get("hari", 1))
        # Tarik saldo digital dulu, lalu uang ( _tarik_qris_untuk ).
        dari_qris = min(int(s.get("saldo_digital", 0)), tagihan)
        s["saldo_digital"] = int(s.get("saldo_digital", 0)) - dari_qris
        s["uang"] = int(s.get("uang", 0)) + dari_qris
        bayar = min(max(int(s.get("uang", 0)), 0), tagihan)
        s["uang"] = int(s.get("uang", 0)) - bayar
        sewa_dibayar = bayar
        sisa = tagihan - bayar
        if sisa > 0:
            s["minggu_tunggak"] = int(s.get("minggu_tunggak", 0) or 0) + 1
            s["tunggakan_sewa"] = sisa
        else:
            s["tunggakan_sewa"] = 0
            s["minggu_tunggak"] = 0
    hari_ini["sewa"] = sewa_dibayar
    # Riwayat harian (catat_riwayat_hari, game_state.gd:4714).
    bersih = hari_ini["laba"] - biaya
    riwayat = s.setdefault("riwayat", [])
    entri = {"hari": int(s.get("hari", 1)), "omzet": hari_ini["omzet"],
             "laba": hari_ini["laba"], "bersih": bersih,
             "belanja": hari_ini.get("belanja", 0),
             "barang": hari_ini["barang"],
             "dilayani": hari_ini["dilayani"], "batal": hari_ini["batal"]}
    if riwayat and int(riwayat[-1].get("hari", -1)) == int(s.get("hari", 1)):
        riwayat[-1] = entri
    else:
        riwayat.append(entri)
    # Ganti hari.
    s["hari"] = int(s.get("hari", 1)) + 1
    s["menit"] = JAM_BUKA
    s["energi"] = 100.0
    s["istirahat_hari"] = {}
    s["penjualan_hari"] = {}
    s["catatan_hari"] = {"omzet": hari_ini["omzet"], "laba": hari_ini["laba"],
                         "terjual": hari_ini["barang"],
                         "belanja": hari_ini.get("belanja", 0),
                         "dilayani": hari_ini["dilayani"],
                         "batal": hari_ini["batal"],
                         "hadiah": int(s.get("_hadiah_hari", 0))}
    s["_hadiah_hari"] = 0


def _hari_baru() -> dict:
    return {"omzet": 0, "laba": 0, "modal": 0, "modal_layanan": 0, "barang": 0,
            "dilayani": 0, "batal": 0,
            "qris": 0, "isi_layanan": 0, "belanja": 0, "biaya_harian": 0,
            "sewa": 0, "datang": 0}


def simulate_day(s: dict, data: GameData, rng: random.Random,
                 layani_detik: float = LAYANI_DETIK,
                 dt: float = DT_DEFAULT,
                 istirahat_otomatis: bool = True) -> dict:
    """Simulasikan SATU hari jualan dari state ``s`` (diubah di tempat).

    Mengembalikan ringkasan hari. State ``s`` dimutasi: uang, stok,
    progres, hari, energi, dsb. — persis seperti satu hari main.
    """
    hari = int(s.get("hari", 1))
    hari_ini = _hari_baru()
    hari_ini["hari"] = hari
    hari_ini["libur"] = False
    hari_ini["ramadan"] = ramadan(hari)
    tutup = jam_wajib_tutup(s)
    buka = 0 if s.get("kios_milik") else JAM_BUKA
    menit = float(buka)
    s["menit"] = menit
    if nama_hari(hari) in HARI_LIBUR and not s.get("kios_milik"):
        hari_ini["libur"] = True
        _tutup_hari(s, data, hari_ini)
        hari_ini["menit_akhir"] = float(buka)
        hari_ini["energi_akhir"] = float(s.get("energi", 100.0))
        return hari_ini
    # Pelanggan pertama setelah 1,5-3,5 detik (layanan.gd:136).
    timer = rng.uniform(*JEDA_PERTAMA)
    antre: list = []          # status "antre" (menunggu giliran)
    depan: dict | None = None  # status "depan" (di kasir)
    melayani: dict | None = None  # {"pelanggan":..., "sisa": detik}
    habis_menunggu: dict | None = None  # {"pelanggan":..., "sisa": 1,4}
    kapasitas = maks_antre(data, s)
    while menit < tutup:
        langkah = min(dt, (tutup - menit) / KECEPATAN_WAKTU)
        if langkah <= 0:
            break
        menit_baru = menit + langkah * KECEPATAN_WAKTU
        _drain_energi(s, menit, menit_baru)
        menit = menit_baru
        s["menit"] = menit
        # Energi kritis -> istirahat otomatis, kalau tidak bisa -> tutup awal.
        if float(s.get("energi", 100.0)) <= 0.0:
            if istirahat_otomatis and _istirahat(s, rng):
                pass
            else:
                hari_ini["tutup_awal_energi"] = True
                break
        # Kedatangan.
        timer -= langkah
        if timer <= 0.0:
            lo, hi = interval_datang(data, s, menit)
            timer = rng.uniform(lo, hi)
            di_sistem = (len(antre) + (1 if depan else 0)
                         + (1 if melayani else 0) + (1 if habis_menunggu else 0))
            if di_sistem < kapasitas and menit < tutup:
                tipe = rng.choice(data.pelanggan)
                pesanan = pesanan_acak(data, s, tipe, menit, rng)
                if pesanan:
                    antre.append({
                        "tipe": str(tipe["id"]),
                        "pesanan": pesanan,
                        "status": "antre",
                        "waktu": 0.0,
                        "batas": sabar_antre_dasar(s) * pengali_sabar(data, s, True),
                    })
                    hari_ini["datang"] += 1
        # Kesabaran antrean (diperlambat bila ramai).
        n_antre = len(antre)
        laju = 1.0 / (1.0 + PERLAMBAT_SABAR_RAMAI * max(n_antre - 1, 0))
        for p in list(antre):
            p["waktu"] += langkah * laju
            if p["waktu"] >= p["batas"]:
                antre.remove(p)
                _pelanggan_batal(s, hari_ini)
        # Naikkan antrean terdepan ke kasir bila kasir kosong.
        if depan is None and melayani is None and habis_menunggu is None and antre:
            depan = antre.pop(0)
            depan["status"] = "depan"
            depan["waktu"] = 0.0
            depan["batas"] = batas_respon(data, s, len(depan["pesanan"])) \
                * pengali_sabar(data, s, False)
            # Target kosong -> pulang "habis" setelah 1,4 detik.
            target_kosong = True
            for item_id, jumlah in depan["pesanan"]:
                item = data.katalog[item_id]
                if item["jenis"] == "fisik" and int((s.get("stok", {}) or {}).get(item_id, 0)) > 0:
                    target_kosong = False
                    break
                if item["jenis"] == "layanan":
                    target_kosong = False
                    break
            if target_kosong:
                habis_menunggu = {"pelanggan": depan, "sisa": HABIS_TUNGGU_DETIK}
                depan = None
        # Pelanggan barang-habis menunggu lalu pulang.
        if habis_menunggu is not None:
            habis_menunggu["sisa"] -= langkah
            if habis_menunggu["sisa"] <= 0.0:
                habis_menunggu = None
                _pelanggan_batal(s, hari_ini)
        # Pelayanan di kasir.
        if depan is not None and melayani is None:
            melayani = {"pelanggan": depan, "sisa": layani_detik}
            depan = None
        if melayani is not None:
            p = melayani["pelanggan"]
            p["waktu"] += langkah
            if p["waktu"] >= p["batas"]:
                melayani = None
                _pelanggan_batal(s, hari_ini)
            else:
                melayani["sisa"] -= langkah
                if melayani["sisa"] <= 0.0:
                    hasil = _layani_pelanggan(s, data, p, hari_ini, rng)
                    melayani = None
                    if hasil in ("mahal", "habis"):
                        _pelanggan_batal(s, hari_ini)
    # Tutup: sisa antrean pulang tanpa dihitung batal (warung_tutup()).
    _tutup_hari(s, data, hari_ini)
    hari_ini["menit_akhir"] = float(menit)
    hari_ini["energi_akhir"] = float(s.get("energi", 100.0))
    hari_ini["tingkat_akhir"] = int(s.get("tingkat", 0))
    hari_ini["uang_akhir"] = int(s.get("uang", 0))
    hari_ini["qris_akhir"] = int(s.get("saldo_digital", 0))
    hari_ini["hadiah"] = int((s.get("catatan_hari", {}) or {}).get("hadiah", 0))
    return hari_ini


def simulate(slot: dict, data: GameData, jumlah_hari: int,
             seed: int | None = None, **opts) -> dict:
    """Simulasikan N hari dari slot. Mengembalikan hasil + slot akhir.

    ``seed`` None -> acak (SystemRandom). Seed sama -> hasil identik.
    Slot asli TIDAK diubah; yang dikembalikan adalah salinan hasil sim.
    """
    if jumlah_hari < 1:
        raise SimError("jumlah hari minimal 1")
    if jumlah_hari > 30:
        raise SimError("maksimal 30 hari per simulasi")
    rng = random.Random(seed) if seed is not None else random.Random()
    s = _normalisasi_slot(slot)
    # Terima kiriman stok yang menunggu (kurir mengantar saat game "dibuka").
    # Dalam game, kiriman masuk ke stok setelah ``durasi_kirim`` berjalan;
    # simulasi tidak membuka game nyata, jadi kiriman harus diantar di sini
    # agar stok yang dibeli bot tidak menggantung selamanya.
    kiriman = s.get("kiriman_stok") or {}
    if isinstance(kiriman, dict) and kiriman:
        stok = s.setdefault("stok", {})
        for item_id, jumlah in kiriman.items():
            if int(jumlah) > 0:
                stok[item_id] = int(stok.get(item_id, 0)) + int(jumlah)
        s["kiriman_stok"] = {}
    uang_awal = int(s.get("uang", 0))
    qris_awal = int(s.get("saldo_digital", 0))
    layanan_awal = int(s.get("saldo_layanan", 0))
    tingkat_awal = int(s.get("tingkat", 0))
    hari_awal = int(s.get("hari", 1))
    per_hari = []
    for _ in range(jumlah_hari):
        per_hari.append(simulate_day(s, data, rng, **opts))
        if s.get("diusir"):
            break
    uang_akhir = int(s.get("uang", 0))
    # Bersihkan kunci internal sim (awalan "_") sebelum slot dipakai game.
    for kunci in [k for k in s if k.startswith("_")]:
        del s[kunci]
    return {
        "hari": per_hari,
        "slot_akhir": s,
        "uang_awal": uang_awal,
        "uang_akhir": uang_akhir,
        "qris_awal": qris_awal,
        "qris_akhir": int(s.get("saldo_digital", 0)),
        "saldo_layanan_awal": layanan_awal,
        "saldo_layanan_akhir": int(s.get("saldo_layanan", 0)),
        "omzet": sum(h["omzet"] for h in per_hari),
        "laba": sum(h["laba"] for h in per_hari),
        "modal": sum(h["modal"] for h in per_hari),
        "modal_layanan": sum(h["modal_layanan"] for h in per_hari),
        "biaya_harian": sum(h["biaya_harian"] for h in per_hari),
        "sewa": sum(h["sewa"] for h in per_hari),
        "hadiah": sum(h.get("hadiah", 0) for h in per_hari),
        "dilayani": sum(h["dilayani"] for h in per_hari),
        "batal": sum(h["batal"] for h in per_hari),
        "datang": sum(h["datang"] for h in per_hari),
        "tingkat_awal": tingkat_awal,
        "tingkat_akhir": int(s.get("tingkat", 0)),
        "hari_awal": hari_awal,
        "hari_akhir": int(s.get("hari", 1)),
        "minggu_tunggak": int(s.get("minggu_tunggak", 0) or 0),
        "tunggakan_sewa": int(s.get("tunggakan_sewa", 0) or 0),
        "diusir": bool(s.get("diusir")),
    }
