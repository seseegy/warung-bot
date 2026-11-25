"""Aksi otomatis Fase 3 (Kerja 24/7) — logika MURNI, tanpa I/O.

Semua digrounding ke kode game hasil decompile (GDRE). Bila dokumen dan
kode tidak cocok, KODE yang menang — perbedaannya dicatat di README.

Grounding utama:
- Login harian: ``login_harian.gd`` — PANJANG=30, UANG_HARIAN=15000,
  HADIAH {4:100rb, 8:150rb, 12:200rb, 16:250rb, 20:300rb, 24:350rb,
  26:"bebas_iklan", 28:400rb, 30:"baju"}, pengganti baju 500rb,
  pengganti iklan 100rb, BAJU_TESTER="sarung" (game_state.gd:9990).
  PENTING: state login tinggal di ``pengaturan.cfg`` lokal HP, BUKAN di
  paket cloud, dan divalidasi HMAC ``tanda`` (game_state.gd:4257-4263).
  Bot TIDAK BISA mengklaim login lewat cloud — yang diimplementasikan
  di sini hanyalah hitung hadiah + pelacak pengingat (klaim tetap
  dilakukan pengguna di game, lalu menekan "Sudah Klaim").
  Kalender 30 hari adalah SATU SIKLUS tanpa reset di kode v1.2:
  setelah hari ke-30, ``hari_berikut()`` selalu 0 (login_harian.gd:130).
- Beli stok: ``beli_stok()`` (game_state.gd:2393) — syarat etalase bila
  ``wajib_etalase``, item harus terbuka, bukan titipan sales
  (SALES_TITIPAN = roti, jamu), jumlah <= sisa_muat_stok
  (MAKS_STOK_BARANG=100 - stok - kiriman - tas_grosir), biaya =
  harga_modal x jumlah, uang -= biaya, KIRIMAN (bukan stok langsung):
  ``kiriman_stok[id] += jumlah``; game memulai ulang timer kirim saat
  load bila kiriman tidak kosong (game_state.gd:3819), stok masuk ~30
  detik setelah game dibuka.
- Harga pasar: ``harga_pasar()`` (game_state.gd:8837) — dari dict
  ``harga_pasaran`` DI SAVE (diacak lokal tiap Senin, bukan dari server).
  Bot hanya MENGIKUTI pasaran yang sudah ada, tidak membuat pasaran baru.
  Lantai/batas dari ``ubah_harga_jual()`` (game_state.gd:5730-5758);
  bila harga baru == harga normal, entri khusus DIHAPUS.
- Sewa: ``_bayar_sewa()`` (game_state.gd:6448) — jatuh tempo tiap
  hari % 7 == 0, tagihan = sisa minggu ini + tunggakan, tarik QRIS dulu
  bila uang kurang, bayar = clamp(uang, 0, tagihan). Denda efektif 0
  (MAKS_DENDA_SEWA=0, game_state.gd:6330); diusir bila minggu_tunggak
  mencapai 3 (MINGGU_DIUSIR=3). ``cicil_sewa()`` (game_state.gd:6394)
  untuk bayar di muka: tunggakan dulu, sisanya jadi sewa_cicil.
- Zakat: ``boleh_zakat()`` (game_state.gd:7819) — hari 81..84
  (HARI_ZAKAT=81, HARI_LEBARAN=85), ZAKAT_FITRAH=45000, dari uang saja.
  Terlewat sampai Lebaran -> game menandai lunas sendiri + ulasan 2*.
- Cicilan motor: ``bayar_cicilan_motor()`` (game_state.gd:1356) —
  bayar = min(angsuran, sisa), dari uang saja; tempo berikutnya =
  _hari_tempo(tempo + 30) dengan Jumat dilewati. Telat -> matel bisa
  datang dan menyita motor (``matel_perlu_datang()``).
- Hutang: ``kasih_hutang()`` (game_state.gd:5375) — hutang adalah uang
  yang DIPINJAMKAN pemain ke warga; pemain adalah KREDITUR. Tidak ada
  aksi "bayar hutang" untuk pemain; bot hanya melaporkan yang aktif.
- Transaksi: ``catat_transaksi()`` (game_state.gd:5881) — entri
  {"hari", "jam", "teks", "jumlah"}, maks 80 entri.
- Batas harian: BUKAN aturan game — pilihan bot (RANCANGAN §14 tidak
  memberi angka). Default 1.000.000 kenaikan bersih uang per siklus.
"""

from __future__ import annotations

import copy
import hashlib
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from . import plan as plan_mod
from . import save as save_mod
from . import sim as sim_mod
from .sim import GameData

WIB = ZoneInfo("Asia/Jakarta")

# -- login harian (login_harian.gd) ---------------------------------------
PANJANG_LOGIN = 30
UANG_HARIAN = 15_000
HADIAH_LOGIN = {
    4: 100_000, 8: 150_000, 12: 200_000, 16: 250_000, 20: 300_000,
    24: 350_000, 26: "bebas_iklan", 28: 400_000, 30: "baju",
}
UANG_PENGGANTI_BAJU = 500_000
UANG_PENGGANTI_IKLAN = 100_000
BAJU_TESTER = "sarung"

# -- stok (game_state.gd) --------------------------------------------------
MAKS_STOK_BARANG = 100
SALES_TITIPAN = {"roti", "jamu"}
AMBANG_STOK = 5      # di bawah ini -> beli
TARGET_STOK = 20     # beli sampai segini
CADANGAN_UANG_MIN = 50_000  # uang tidak boleh turun di bawah ini krn auto-beli

# -- sewa / zakat / motor (game_state.gd) ----------------------------------
MAKS_DENDA_SEWA = 0
MINGGU_DIUSIR = 3
ZAKAT_FITRAH = 45_000
HARI_ZAKAT = 81
HARI_LEBARAN = 85
MOTOR_HARI_BULAN = 30
MOTOR_ANGSURAN_JATUH_TEMPO = 3  # bayar cicilan maks 3 hari sebelum tempo

# -- transaksi --------------------------------------------------------------
MAKS_TRANSAKSI = 80


def _rupiah(nilai: int) -> str:
    return f"Rp{int(nilai):,}".replace(",", ".")


def tanggal_wib(saat: datetime | None = None) -> str:
    """Tanggal WIB 'YYYY-MM-DD' (game memakai UTC+7, login_harian.gd)."""
    saat = saat or datetime.now(WIB)
    return saat.astimezone(WIB).strftime("%Y-%m-%d")


def jam_wib(saat: datetime | None = None) -> str:
    """Jam WIB 'HH:MM' untuk entri transaksi."""
    saat = saat or datetime.now(WIB)
    return saat.astimezone(WIB).strftime("%H:%M")


# -- login harian -----------------------------------------------------------

def hadiah_login(n: int, tanpa_iklan: bool = False,
                 punya_baju: bool = False) -> dict:
    """Hadiah hari ke-n, persis ``hadiah(n)`` (login_harian.gd:138).

    Mengembalikan {"jenis": "uang"|"bebas_iklan"|"baju", "n"|"teks",
    "besar": bool}. Uang pengganti dipakai bila hadiahnya sudah dimiliki.
    """
    if n not in HADIAH_LOGIN:
        return {"jenis": "uang", "n": UANG_HARIAN,
                "teks": _rupiah(UANG_HARIAN), "besar": False}
    h = HADIAH_LOGIN[n]
    if h == "baju":
        if not punya_baju:
            return {"jenis": "baju", "teks": "Baju Kaos & sarung",
                    "besar": True}
        h = UANG_PENGGANTI_BAJU
    elif h == "bebas_iklan":
        if not tanpa_iklan:
            return {"jenis": "bebas_iklan", "teks": "Tanpa Iklan 1 hari",
                    "besar": True}
        h = UANG_PENGGANTI_IKLAN
    return {"jenis": "uang", "n": int(h), "teks": _rupiah(int(h)),
            "besar": True}


def login_berikut(hari_ke: int, tanggal_terakhir: str,
                  hari_ini: str) -> int | None:
    """Hari login berikutnya yang bisa diklaim, seperti ``hari_berikut()``
    (login_harian.gd:127).

    None bila sudah klaim hari ini (tanggal_terakhir >= hari_ini) atau
    kalender sudah selesai (hari_ke >= 30). Terlewat beberapa hari TIDAK
    mereset streak dan TIDAK mengejar ketinggalan: berikutnya = hari_ke+1.
    """
    if int(hari_ke) >= PANJANG_LOGIN:
        return None
    if tanggal_terakhir and tanggal_terakhir >= hari_ini:
        return None
    return int(hari_ke) + 1


# -- transaksi --------------------------------------------------------------

def catat_transaksi(slot: dict, teks: str, jumlah: int) -> None:
    """Tambah entri transaksi seperti ``catat_transaksi()``
    (game_state.gd:5881). Maks 80 entri, yang lama dibuang."""
    daftar = slot.get("transaksi")
    if not isinstance(daftar, list):
        daftar = slot["transaksi"] = []
    daftar.append({
        "hari": int(slot.get("hari", 1)),
        "jam": jam_wib(),
        "teks": teks,
        "jumlah": int(jumlah),
    })
    if len(daftar) > MAKS_TRANSAKSI:
        slot["transaksi"] = daftar[-MAKS_TRANSAKSI:]


# -- sewa -------------------------------------------------------------------

def minggu_sewa_berjalan(slot: dict) -> int:
    """``minggu_sewa_berjalan()`` (game_state.gd:6262)."""
    hari = int(slot.get("hari", 1))
    tambah = 1 if (int(slot.get("sewa_selesai_hari", 0)) == hari
                   and hari % 7 == 0) else 0
    return int((hari - 1) / 7) + tambah


def sewa_per_minggu(slot: dict, cerita: dict) -> int:
    """``sewa_per_minggu()`` (game_state.gd:6238) — dari cerita.json
    per_minggu[tingkat], dengan kunci mingguan (sewa_kunci)."""
    if slot.get("kios_milik"):
        return 0
    daftar = (cerita.get("sewa", {}) or {}).get("per_minggu", [0]) or [0]
    tingkat = int(slot.get("tingkat", 0))
    sewa = int(daftar[max(0, min(tingkat, len(daftar) - 1))])
    kunci = slot.get("sewa_kunci", {}) or {}
    if int(kunci.get("minggu", -1)) == minggu_sewa_berjalan(slot):
        return min(int(kunci.get("jumlah", sewa)), sewa)
    return sewa


def hari_sewa(hari: int) -> bool:
    """``hari_sewa()`` — tiap hari kelipatan 7 (game_state.gd:6284)."""
    return int(hari) % 7 == 0


def hari_jatuh_tempo_sewa(hari: int) -> int:
    """``hari_jatuh_tempo_sewa()`` (game_state.gd:6295)."""
    hari = int(hari)
    if hari % 7 == 0:
        return hari + 7
    return hari + (7 - hari % 7) % 7


def sisa_sewa_minggu_ini(slot: dict, cerita: dict) -> int:
    return max(sewa_per_minggu(slot, cerita) - int(slot.get("sewa_cicil", 0) or 0), 0)


def tagihan_sewa(slot: dict, cerita: dict) -> int:
    """``tagihan_sewa()`` = sisa minggu ini + tunggakan."""
    return sisa_sewa_minggu_ini(slot, cerita) + int(slot.get("tunggakan_sewa", 0) or 0)


def _tarik_qris_untuk(slot: dict, jumlah: int) -> None:
    """``_tarik_qris_untuk()`` — pindah dari saldo digital ke uang tunai
    sebanyak yang kurang (maks saldo digital)."""
    kurang = min(max(jumlah - int(slot.get("uang", 0)), 0),
                int(slot.get("saldo_digital", 0) or 0))
    if kurang <= 0:
        return
    slot["saldo_digital"] = int(slot.get("saldo_digital", 0)) - kurang
    slot["uang"] = int(slot.get("uang", 0)) + kurang


def bayar_sewa(slot: dict, cerita: dict) -> dict:
    """Bayar sewa seperti ``_bayar_sewa()`` (game_state.gd:6448).

    HANYA bila hari ini hari sewa dan uang+QRIS cukup untuk tagihan penuh
    (bot tidak membayar sebagian — menunggak sebagian tetap menaikkan
    minggu_tunggak). Mengembalikan dict hasil; slot diubah bila berhasil.
    """
    hari = int(slot.get("hari", 1))
    if slot.get("kios_milik"):
        return {"ok": False, "alasan": "kios sudah milik sendiri"}
    if not hari_sewa(hari):
        return {"ok": False, "alasan": "hari ini bukan hari sewa"}
    if int(slot.get("sewa_selesai_hari", 0)) == hari:
        return {"ok": False, "alasan": "sewa hari ini sudah selesai"}
    tagihan = tagihan_sewa(slot, cerita)
    if int(slot.get("uang", 0)) + int(slot.get("saldo_digital", 0) or 0) < tagihan:
        return {"ok": False, "alasan": "uang tidak cukup",
                "tagihan": tagihan,
                "kurang": tagihan - int(slot.get("uang", 0))
                - int(slot.get("saldo_digital", 0) or 0)}
    sewa_minggu = sewa_per_minggu(slot, cerita)
    dicicil = min(int(slot.get("sewa_cicil", 0) or 0), sewa_minggu)
    if int(slot.get("sewa_cicil", 0) or 0) > dicicil:
        kembali = int(slot.get("sewa_cicil", 0)) - dicicil
        slot["uang"] = int(slot.get("uang", 0)) + kembali
        catat_transaksi(slot, "Kelebihan cicilan sewa dikembalikan", kembali)
    slot["sewa_cicil"] = 0
    slot["sewa_kunci"] = {}
    _tarik_qris_untuk(slot, tagihan)
    bayar = max(0, min(int(slot.get("uang", 0)), tagihan))
    slot["uang"] = int(slot.get("uang", 0)) - bayar
    slot["sewa_selesai_hari"] = hari
    slot["sewa_dibayar_hari"] = bayar
    slot["denda_sewa_hari"] = 0  # MAKS_DENDA_SEWA = 0 -> denda selalu 0
    sisa = tagihan - bayar
    if bayar > 0:
        catat_transaksi(slot, "Sewa kios minggu ini", -bayar)
    diusir = False
    if sisa > 0:
        # Tidak seharusnya terjadi (sudah dicek cukup) — pertahanan saja.
        slot["minggu_tunggak"] = int(slot.get("minggu_tunggak", 0) or 0) + 1
        slot["tunggakan_sewa"] = sisa
        if int(slot.get("minggu_tunggak", 0)) >= MINGGU_DIUSIR:
            slot["diusir"] = True
            diusir = True
    else:
        slot["tunggakan_sewa"] = 0
        slot["minggu_tunggak"] = 0
    return {"ok": True, "dibayar": bayar, "tagihan": tagihan,
            "tunggakan": int(slot.get("tunggakan_sewa", 0)),
            "minggu_tunggak": int(slot.get("minggu_tunggak", 0)),
            "diusir": diusir}


def cicil_sewa(slot: dict, cerita: dict, jumlah: int) -> dict:
    """Bayar sewa di muka seperti ``cicil_sewa()`` (game_state.gd:6394):
    tunggakan dulu, sisanya jadi sewa_cicil minggu ini."""
    if slot.get("kios_milik"):
        return {"ok": False, "alasan": "kios sudah milik sendiri"}
    sisa = int(slot.get("tunggakan_sewa", 0) or 0) + sisa_sewa_minggu_ini(slot, cerita)
    if sisa <= 0:
        return {"ok": False, "alasan": "sewa minggu ini sudah lunas"}
    jumlah = min(int(jumlah), sisa)
    if int(slot.get("uang", 0)) + int(slot.get("saldo_digital", 0) or 0) < jumlah:
        return {"ok": False, "alasan": "uang tidak cukup", "kurang": jumlah
                - int(slot.get("uang", 0))
                - int(slot.get("saldo_digital", 0) or 0)}
    _tarik_qris_untuk(slot, jumlah)
    slot["uang"] = int(slot.get("uang", 0)) - jumlah
    ke_tunggakan = min(jumlah, int(slot.get("tunggakan_sewa", 0) or 0))
    if ke_tunggakan > 0:
        slot["tunggakan_sewa"] = int(slot.get("tunggakan_sewa", 0)) - ke_tunggakan
        catat_transaksi(slot, "Cicil tunggakan sewa", -ke_tunggakan)
        if int(slot.get("tunggakan_sewa", 0)) <= 0:
            slot["tunggakan_sewa"] = 0
            slot["minggu_tunggak"] = 0
    ke_minggu_ini = jumlah - ke_tunggakan
    if ke_minggu_ini > 0:
        slot["sewa_cicil"] = int(slot.get("sewa_cicil", 0) or 0) + ke_minggu_ini
        catat_transaksi(slot, "Cicil sewa kios", -ke_minggu_ini)
    return {"ok": True, "dibayar": jumlah, "ke_tunggakan": ke_tunggakan,
            "ke_minggu_ini": ke_minggu_ini,
            "tunggakan": int(slot.get("tunggakan_sewa", 0))}


# -- zakat ------------------------------------------------------------------

def boleh_zakat(slot: dict) -> bool:
    """``boleh_zakat()`` (game_state.gd:7819): hari 81..84, belum dibayar."""
    return (not slot.get("zakat_dibayar")
            and HARI_ZAKAT <= int(slot.get("hari", 1)) < HARI_LEBARAN)


def bayar_zakat(slot: dict) -> dict:
    """Bayar zakat seperti ``bayar_zakat()`` (game_state.gd:7823):
    Rp45.000 dari uang tunai saja (bukan QRIS)."""
    if not boleh_zakat(slot):
        if slot.get("zakat_dibayar"):
            return {"ok": False, "alasan": "zakat fitrah sudah dibayar"}
        return {"ok": False, "alasan": "belum waktunya zakat fitrah"}
    if int(slot.get("uang", 0)) < ZAKAT_FITRAH:
        return {"ok": False, "alasan": "uang tidak cukup",
                "kurang": ZAKAT_FITRAH - int(slot.get("uang", 0))}
    slot["uang"] = int(slot.get("uang", 0)) - ZAKAT_FITRAH
    slot["zakat_dibayar"] = True
    catat_transaksi(slot, "Zakat fitrah", -ZAKAT_FITRAH)
    return {"ok": True, "dibayar": ZAKAT_FITRAH}


# -- cicilan motor ----------------------------------------------------------

def _hari_tempo(h: int) -> int:
    """``_hari_tempo()`` — lewati hari libur (Jumat)."""
    n = 0
    while sim_mod.nama_hari(h) == "Jumat" and n < 7:
        h += 1
        n += 1
    return h


def bayar_cicilan_motor(slot: dict) -> dict:
    """Bayar cicilan motor seperti ``bayar_cicilan_motor()``
    (game_state.gd:1356): bayar = min(angsuran, sisa), dari uang saja.
    Tempo berikutnya = tempo + 30 hari (lewati Jumat)."""
    cicil = slot.get("motor_cicil", {}) or {}
    if not isinstance(cicil, dict):
        cicil = {}
    sisa = int(cicil.get("sisa", 0))
    if sisa <= 0:
        return {"ok": False, "alasan": "cicilan motor sudah lunas"}
    angsuran = int(cicil.get("angsuran", 1_000_000))
    bayar = min(angsuran, sisa)
    if int(slot.get("uang", 0)) < bayar:
        return {"ok": False, "alasan": "uang tidak cukup",
                "kurang": bayar - int(slot.get("uang", 0)), "bayar": bayar}
    slot["uang"] = int(slot.get("uang", 0)) - bayar
    sisa -= bayar
    ke = int(cicil.get("ke", 1))
    catat_transaksi(slot, f"Cicilan motor ke-{ke}", -bayar)
    if sisa <= 0:
        slot["motor_cicil"] = {}
        return {"ok": True, "dibayar": bayar, "lunas": True, "ke": ke}
    cicil["sisa"] = sisa
    cicil.pop("ditunda", None)
    cicil["ke"] = ke + 1
    cicil["tempo"] = _hari_tempo(int(cicil.get("tempo", int(slot.get("hari", 1))))
                                + MOTOR_HARI_BULAN)
    slot["motor_cicil"] = cicil
    return {"ok": True, "dibayar": bayar, "lunas": False, "ke": ke,
            "sisa": sisa, "tempo_baru": cicil["tempo"]}


def motor_tempo_dekat(slot: dict, hari_ini: int | None = None) -> bool:
    """True bila cicilan motor jatuh tempo dalam 3 hari atau sudah lewat."""
    cicil = slot.get("motor_cicil", {}) or {}
    if not isinstance(cicil, dict) or int(cicil.get("sisa", 0)) <= 0:
        return False
    hari = int(hari_ini if hari_ini is not None else slot.get("hari", 1))
    tempo = int(cicil.get("tempo", -1))
    return tempo >= 0 and tempo - hari <= MOTOR_ANGSURAN_JATUH_TEMPO


# -- hutang (hanya laporan — pemain adalah kreditur) ------------------------

def hutang_aktif_ringkasan(slot: dict) -> list:
    """Hutang aktif (status 'belum') — uang yang DIPINJAMKAN pemain ke
    warga (``kasih_hutang()``). Tidak ada aksi bayar untuk pemain;
    warga membayar sendiri sesuai ``menit_bayar``. Bot hanya melaporkan."""
    hasil = []
    for h in slot.get("hutang", []) or []:
        if not isinstance(h, dict) or str(h.get("status")) != "belum":
            continue
        hasil.append({
            "nama": str(h.get("nama", h.get("tipe", "?"))),
            "jumlah": int(h.get("jumlah", 0)),
            "tempo": int(h.get("tempo", 0)),
            "hari_pinjam": int(h.get("hari", 0)),
        })
    return hasil


# -- stok -------------------------------------------------------------------

def sisa_muat_stok(slot: dict, item_id: str) -> int:
    """``sisa_muat_stok()`` (game_state.gd:4719): maks 100 - stok -
    kiriman - tas_grosir."""
    stok = slot.get("stok", {}) or {}
    kiriman = slot.get("kiriman_stok", {}) or {}
    grosir = slot.get("tas_grosir", {}) or {}
    return max(MAKS_STOK_BARANG - int(stok.get(item_id, 0))
               - int(kiriman.get(item_id, 0))
               - int(grosir.get(item_id, 0)), 0)


def auto_beli_stok(slot: dict, data: GameData) -> tuple[dict, list]:
    """Beli stok otomatis seperti ``beli_stok()`` (game_state.gd:2393).

    Untuk tiap barang fisik terbuka yang stok+kiriman+grosir < 5: beli
    sampai 20 (dibatasi sisa muat rak). Uang sesudah beli tidak boleh
    turun di bawah Rp50.000, dan bila sewa jatuh tempo dalam 7 hari,
    tagihan sewa ikut dicadangkan. Biaya = harga_modal x jumlah;
    uang -= biaya; barang LANGSUNG masuk ``stok`` (bukan ``kiriman_stok``)
    supaya bisa dijual pada simulasi berikutnya tanpa menunggu kurir.
    Mengembalikan (slot_baru, aksi).
    """
    slot = copy.deepcopy(slot)
    aksi: list[dict] = []
    if slot.get("wajib_etalase") and "etalase" not in (slot.get("upgrade", []) or []):
        return slot, [{"aksi": "beli_stok", "ok": False,
                       "alasan": "etalase kaca belum dimiliki"}]
    stok = slot.setdefault("stok", {})
    kiriman = slot.setdefault("kiriman_stok", {})
    grosir = slot.get("tas_grosir", {}) or {}
    terbuka = set(slot.get("barang_terbuka", []) or [])
    hari = int(slot.get("hari", 1))
    # Cadangan sewa bila jatuh tempo dalam 7 hari.
    cadangan = CADANGAN_UANG_MIN
    if hari_jatuh_tempo_sewa(hari) - hari <= 7:
        cadangan = max(cadangan, tagihan_sewa(slot, data.cerita))
    for item_id in data.urutan_barang:
        item = data.katalog[item_id]
        if item.get("jenis") != "fisik" or item_id not in terbuka:
            continue
        if item_id in SALES_TITIPAN:
            continue
        punya = (int(stok.get(item_id, 0)) + int(kiriman.get(item_id, 0))
                 + int(grosir.get(item_id, 0)))
        if punya >= AMBANG_STOK:
            continue
        muat = sisa_muat_stok(slot, item_id)
        jumlah = min(TARGET_STOK - punya, muat)
        if jumlah <= 0:
            continue
        biaya = sim_mod.harga_modal(data, item_id, slot) * jumlah
        if int(slot.get("uang", 0)) - biaya < cadangan:
            aksi.append({"aksi": "beli_stok", "ok": False, "id": item_id,
                         "alasan": "uang tidak cukup setelah cadangan sewa",
                         "biaya": biaya})
            continue
        slot["uang"] = int(slot.get("uang", 0)) - biaya
        # Langsung masuk stok (bukan kiriman_stok) supaya barang tersedia
        # untuk dijual pada simulasi berikutnya. Game asli menunggu kurir
        # mengantar (kiriman_stok), tapi Mode Target tidak membuka game
        # sehingga kiriman tidak pernah sampai -> pelanggan selalu batal.
        stok[item_id] = int(stok.get(item_id, 0)) + jumlah
        slot["belanja_hari"] = int(slot.get("belanja_hari", 0) or 0) + biaya
        catat_transaksi(
            slot, f"Belanja {jumlah} {str(item.get('nama', item_id)).lower()}",
            -biaya)
        aksi.append({"aksi": "beli_stok", "ok": True, "id": item_id,
                     "nama": str(item.get("nama", item_id)),
                     "jumlah": jumlah, "biaya": biaya})
    return slot, aksi


# -- harga ------------------------------------------------------------------

def auto_harga_pasar(slot: dict, data: GameData) -> tuple[dict, list]:
    """Ikuti harga pasar seperti tombol harga di game.

    Untuk tiap barang fisik terbuka: harga_jual = harga_pasar() dari dict
    ``harga_pasaran`` DI SAVE. Bila sama dengan harga normal, entri khusus
    dihapus (seperti ``ubah_harga_jual()``). Tanpa agen (level < 2) atau
    tanpa entri pasaran -> tidak berubah.
    """
    slot = copy.deepcopy(slot)
    perubahan: list[dict] = []
    if not sim_mod.agen_aktif(slot):
        return slot, [{"aksi": "harga_pasar", "ok": False,
                       "alasan": "agen harga pasar belum aktif (level < 2)"}]
    khusus = dict(slot.get("harga_jual_khusus", {}) or {})
    terbuka = set(slot.get("barang_terbuka", []) or [])
    for item_id in data.urutan_barang:
        item = data.katalog[item_id]
        if item.get("jenis") != "fisik" or item_id not in terbuka:
            continue
        target = sim_mod.harga_pasar(data, item_id, slot)
        sekarang = sim_mod.harga_jual(data, item_id, slot)
        if target == sekarang:
            continue
        normal = int(item["jual"])
        if target == normal:
            khusus.pop(item_id, None)
        else:
            khusus[item_id] = target
        perubahan.append({"aksi": "harga_pasar", "ok": True, "id": item_id,
                          "nama": str(item.get("nama", item_id)),
                          "lama": sekarang, "baru": target})
    slot["harga_jual_khusus"] = khusus
    return slot, perubahan


def auto_harga_dinamis(slot: dict, data: GameData,
                       seed: int | None = 12345) -> tuple[dict, list]:
    """Harga dinamis (Profesional): pakai ``plan.harga_terbaik`` — hanya
    terapkan harga yang laba hariannya LEBIH BESAR dari sekarang.
    Harga di bawah lantai tidak pernah disarankan (dijamin plan)."""
    slot = copy.deepcopy(slot)
    hasil = plan_mod.harga_terbaik(slot, data, seed=seed)
    khusus = dict(slot.get("harga_jual_khusus", {}) or {})
    perubahan: list[dict] = []
    for entri in hasil:
        if entri["laba_terbaik"] <= entri["laba_sekarang"]:
            continue
        item_id = entri["id"]
        normal = int(data.katalog[item_id]["jual"])
        if entri["harga_terbaik"] == normal:
            khusus.pop(item_id, None)
        else:
            khusus[item_id] = int(entri["harga_terbaik"])
        perubahan.append({"aksi": "harga_dinamis", "ok": True, "id": item_id,
                          "nama": entri["nama"],
                          "lama": entri["harga_sekarang"],
                          "baru": entri["harga_terbaik"],
                          "laba_lama": entri["laba_sekarang"],
                          "laba_baru": entri["laba_terbaik"]})
    slot["harga_jual_khusus"] = khusus
    return slot, perubahan


# -- tugas ------------------------------------------------------------------

def auto_isi_tugas(slot: dict, tugas_data: dict) -> tuple[dict, dict]:
    """Isi progres tugas seperti /tugas_selesai (Fase 1): hadiah dibayar
    game saat berikutnya mengecek tugas. Mengembalikan (slot, hasil
    fill_task_progress) — hasil berisi 'blockers' bila ada syarat yang
    belum beres (upgrade/misi)."""
    slot = copy.deepcopy(slot)
    hasil = save_mod.fill_task_progress(slot, tugas_data)
    return slot, hasil


# -- batas harian -----------------------------------------------------------

def cek_batas_harian(uang_awal: int, uang_akhir: int, batas: int) -> dict:
    """Batas harian bot (BUKAN aturan game): kenaikan bersih uang dalam
    satu siklus tidak boleh melebihi batas. Mengembalikan
    {"melewati": bool, "selisih": int}."""
    selisih = int(uang_akhir) - int(uang_awal)
    return {"melewati": selisih > int(batas), "selisih": selisih}


# -- penjaga saldo ------------------------------------------------------------

def jaga_saldo(slot: dict, minimum: int = CADANGAN_UANG_MIN) -> tuple[dict, int]:
    """Penjaga Saldo: uang tidak boleh di bawah ``minimum`` (Rp50.000).

    Bila ``uang < minimum``, set ``uang = minimum`` dan kembalikan jumlah
    yang ditambahkan; bila sudah cukup, kembalikan 0 dan slot tidak
    berubah. Bila saat itu ``hari_minus > 0`` dan warung belum diusir,
    ``hari_minus`` direset ke 0 dan ``bangkrut`` dibersihkan — meniru
    rumus game (``tutup_hari()``, game_state.gd:6723-6738): bangkrut =
    hari_minus >= BATAS_HARI_MINUS (casual 3, hard 1) ATAU diusir; dengan
    hari_minus = 0 dan tidak diusir, bangkrut pasti False. Bila warung
    sudah diusir, jejak minus TIDAK disentuh (warung sudah hilang,
    penjaga tidak bisa mengembalikannya). Field lain tidak disentuh.
    Fungsi murni — slot awal TIDAK diubah.

    JUJUR: uang ini ditambahkan dari ketiadaan atas perintah pengguna
    (24 Nov 2026: "bot tidak boleh pernah minus dan tidak boleh pernah
    bangkrut"), BUKAN dari permainan. Setiap top-up dicatat di audit log
    (aksi "jaga_saldo") supaya bisa dilacak.
    """
    s = copy.deepcopy(slot)
    try:
        uang = int(s.get("uang", 0) or 0)
    except (TypeError, ValueError):
        uang = 0
    if uang >= int(minimum):
        return s, 0
    tambah = int(minimum) - uang
    s["uang"] = int(minimum)
    if not bool(s.get("diusir")) and int(s.get("hari_minus", 0) or 0) > 0:
        s["hari_minus"] = 0
        s["bangkrut"] = False
    return s, tambah


# -- siklus harian (murni — tanpa Telegram/cloud) ---------------------------

def jalankan_siklus(slot_awal: dict, data: GameData, tugas_data: dict,
                    tier: int, batas_harian: int,
                    seed: int | None = None) -> dict:
    """Satu siklus otomatis harian (murni). Urutan:

    0. Penjaga Saldo — perbaiki minus yang sudah ada di save SEBELUM
       langkah lain (aksi "jaga_saldo" bila ada top-up).
    1. Harga ikut pasar (Standar+) lalu harga dinamis (Profesional).
    2. Auto-beli stok (Standar+) — SEBELUM simulasi supaya ada barang
       untuk dijual hari ini.
    3. Simulasi 1 hari (Standar) / terbaik dari 3 (Profesional).
       Bila kenaikan uang simulasi melebihi batas harian -> simulasi
       TIDAK diterapkan (harga tetap, stok/tugas/bayar tetap jalan).
    4. Auto-isi progres tugas (Standar+), lalu terapkan naik level bila
       semua syarat sudah terpenuhi.
    5. Auto-bayar (Profesional): sewa (hari sewa / cicil 3 hari sebelum
       jatuh tempo), zakat (hari 81-84), cicilan motor (tempo <= 3 hari).
    6. Penjaga Saldo — pastikan save yang di-upload tidak pernah minus:
       sim memotong biaya harian walau uang habis (seperti game asli,
       ``tutup_hari()``), jadi tanpa ini uang bisa berakhir minus.
    Mengembalikan {"slot": slot_akhir, "aksi": [...], "sim": {...}|None,
    "uang_awal": int, "uang_akhir": int, "batas_terlampaui": bool}.
    Slot awal TIDAK diubah.
    """
    from .tiers import TIER_PROFESIONAL, TIER_STANDAR

    uang_awal = int(slot_awal.get("uang", 0))
    slot = copy.deepcopy(slot_awal)
    aksi: list[dict] = []

    # 0. Penjaga Saldo (awal): perbaiki minus yang sudah ada di save.
    slot, tambah = jaga_saldo(slot)
    if tambah > 0:
        aksi.append({"aksi": "jaga_saldo", "ok": True, "jumlah": tambah,
                     "dari": uang_awal, "ke": int(slot.get("uang", 0))})

    # 1. Harga.
    if tier >= TIER_STANDAR:
        slot, ubah = auto_harga_pasar(slot, data)
        aksi.extend(ubah)
    if tier >= TIER_PROFESIONAL:
        slot, ubah = auto_harga_dinamis(slot, data)
        aksi.extend(ubah)

    # 2. Auto-beli stok (SEBELUM simulasi) supaya ada barang untuk dijual
    # hari ini. Tanpa ini, hari sewa mengunci uang di cadangan -> tidak
    # bisa beli stok -> pelanggan batal -> rugi terus.
    if tier >= TIER_STANDAR:
        slot, beli = auto_beli_stok(slot, data)
        aksi.extend(beli)

    # 3. Simulasi hari.
    sim_ringkasan: dict | None = None
    batas_terlampaui = False
    if tier >= TIER_STANDAR:
        if tier >= TIER_PROFESIONAL:
            # Terbaik dari 3 simulasi (seed berbeda).
            kandidat = []
            for i in range(3):
                s = seed + i if seed is not None else None
                kandidat.append(sim_mod.simulate(slot, data, 1, seed=s))
            hasil_sim = max(kandidat, key=lambda r: r["laba"])
            hasil_sim["percobaan"] = 3
        else:
            hasil_sim = sim_mod.simulate(slot, data, 1, seed=seed)
            hasil_sim["percobaan"] = 1
        # Mode cuan (fitur /cuan): batas harian tidak berlaku — override
        # bebas atas permintaan pengguna, supaya laba besar tidak ditolak.
        cek = ({"melewati": False, "selisih": 0}
               if sim_mod.cuan_aktif(slot)
               else cek_batas_harian(uang_awal, int(hasil_sim["uang_akhir"]),
                                     batas_harian))
        if cek["melewati"]:
            batas_terlampaui = True
            aksi.append({"aksi": "simulasi", "ok": False,
                         "alasan": "batas harian terlampaui "
                         f"(+{_rupiah(cek['selisih'])} > batas "
                         f"{_rupiah(batas_harian)})",
                         "selisih": cek["selisih"]})
        else:
            slot = hasil_sim["slot_akhir"]
            sim_ringkasan = {
                "omzet": int(hasil_sim["omzet"]),
                "laba": int(hasil_sim["laba"]),
                "uang_akhir": int(hasil_sim["uang_akhir"]),
                "dilayani": int(hasil_sim["dilayani"]),
                "batal": int(hasil_sim["batal"]),
                "datang": int(hasil_sim["datang"]),
                "tingkat_akhir": int(hasil_sim["tingkat_akhir"]),
                "percobaan": int(hasil_sim["percobaan"]),
            }
            aksi.append({"aksi": "simulasi", "ok": True, **sim_ringkasan})

    # 4. Auto-isi tugas.
    if tier >= TIER_STANDAR:
        try:
            slot, isi = auto_isi_tugas(slot, tugas_data)
            aksi.append({"aksi": "isi_tugas", "ok": True,
                         "blockers": isi.get("blockers", [])})
        except save_mod.TaskError as exc:
            aksi.append({"aksi": "isi_tugas", "ok": False,
                         "alasan": str(exc)})

    # 4b. Terapkan naik level bila semua syarat sudah terpenuhi.
    # _cek_tugas() di game hanya terpicu saat penjualan/pelanggan dilayani;
    # auto_isi_tugas mengisi progres langsung (tanpa penjualan) sehingga
    # level tidak pernah naik walau progres penuh + upgrade + misi beres.
    # Panggil eksplisit di sini agar hadiah cair + progres reset + level
    # naik — persis seperti game mengecek tugas.
    tingkat_sebelum = int(slot.get("tingkat", 0))
    while sim_mod._cek_tugas(slot, data):
        # Bisa naik beberapa level sekaligus bila progres sengaja penuh
        # (mis. /tugas_selesai) — ulangi sampai stabil.
        pass
    if int(slot.get("tingkat", 0)) != tingkat_sebelum:
        aksi.append({"aksi": "naik_level", "ok": True,
                     "dari": tingkat_sebelum + 1,
                     "ke": int(slot.get("tingkat", 0)) + 1})

    # 5. Auto-bayar (Profesional).
    if tier >= TIER_PROFESIONAL:
        hari = int(slot.get("hari", 1))
        if hari_sewa(hari):
            hasil = bayar_sewa(slot, data.cerita)
            aksi.append({"aksi": "bayar_sewa", **hasil})
        else:
            # Cicil 3 hari sebelum jatuh tempo bila uang longgar.
            tempo = hari_jatuh_tempo_sewa(hari)
            if 0 < tempo - hari <= 3:
                tagihan = tagihan_sewa(slot, data.cerita)
                if tagihan > 0 and (int(slot.get("uang", 0))
                                    >= tagihan + CADANGAN_UANG_MIN):
                    hasil = cicil_sewa(slot, data.cerita, tagihan)
                    aksi.append({"aksi": "cicil_sewa", **hasil})
        hasil = bayar_zakat(slot)
        # Hanya laporkan bila dibayar atau gagal karena uang; "belum
        # waktunya"/"sudah dibayar" adalah keadaan normal, bukan aksi.
        if hasil["ok"] or "uang tidak cukup" in str(hasil.get("alasan", "")):
            aksi.append({"aksi": "bayar_zakat", **hasil})
        if motor_tempo_dekat(slot):
            hasil = bayar_cicilan_motor(slot)
            aksi.append({"aksi": "bayar_motor", **hasil})

    # 6. Penjaga Saldo (akhir): pastikan save yang di-upload tidak pernah
    # minus — sim bisa memotong biaya harian melewati nol.
    uang_sebelum_jaga = int(slot.get("uang", 0))
    slot, tambah = jaga_saldo(slot)
    if tambah > 0:
        aksi.append({"aksi": "jaga_saldo", "ok": True, "jumlah": tambah,
                     "dari": uang_sebelum_jaga,
                     "ke": int(slot.get("uang", 0))})

    return {
        "slot": slot,
        "aksi": aksi,
        "sim": sim_ringkasan,
        "uang_awal": uang_awal,
        "uang_akhir": int(slot.get("uang", 0)),
        "batas_terlampaui": batas_terlampaui,
    }
