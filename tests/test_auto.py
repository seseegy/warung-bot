"""Tes Fase 3 — aksi otomatis (bot/core/auto.py).

Semua angka dihitung dari kode game / data, bukan ditebak:
- hadiah login dari login_harian.gd (15rb/hari; milestone hari 4 = 100rb)
- harga_modal dari sim.py (katalog x pengali, dibulatkan ke 100)
- sewa dari cerita.json (per_minggu[tingkat], jatuh tempo hari % 7 == 0)
- zakat: hari 81-84, Rp45.000 (game_state.gd)
"""

from __future__ import annotations

import copy

from bot.core import auto as auto_mod
from bot.core import sim as sim_mod


# -- login harian -------------------------------------------------------------

def test_hadiah_login_hari_pertama():
    assert auto_mod.hadiah_login(1) == {"jenis": "uang", "n": 15000,
                                        "teks": "Rp15.000", "besar": False}


def test_hadiah_login_milestone_hari_4():
    assert auto_mod.hadiah_login(4)["n"] == 100000
    assert auto_mod.hadiah_login(4)["besar"] is True


def test_hadiah_login_hari_26_tanpa_iklan():
    assert auto_mod.hadiah_login(26) == {"jenis": "bebas_iklan",
                                         "teks": "Tanpa Iklan 1 hari",
                                         "besar": True}


def test_hadiah_login_hari_26_sudah_tanpa_iklan_jadi_uang():
    assert auto_mod.hadiah_login(26, tanpa_iklan=True)["n"] == 100000


def test_hadiah_login_hari_30_baju():
    assert auto_mod.hadiah_login(30) == {"jenis": "baju",
                                         "teks": "Baju Kaos & sarung",
                                         "besar": True}


def test_hadiah_login_hari_30_sudah_punya_baju_jadi_uang():
    assert auto_mod.hadiah_login(30, punya_baju=True)["n"] == 500000


def test_hadiah_login_di_luar_tabel_kembali_ke_harian():
    # hadiah(n) game: hari bukan milestone = uang harian. Game tidak
    # pernah memanggilnya untuk n>30 (login_berikut mengembalikan None).
    assert auto_mod.hadiah_login(0)["n"] == 15000
    assert auto_mod.hadiah_login(31)["n"] == 15000


def test_login_berikut_hari_pertama():
    assert auto_mod.login_berikut(0, "", "2026-11-24") == 1


def test_login_berikut_sudah_klaim_hari_ini():
    assert auto_mod.login_berikut(3, "2026-11-24", "2026-11-24") is None


def test_login_berikut_streak_berlanjut_tanpa_reset():
    # Lewat 3 hari tanpa klaim: lanjut ke hari berikutnya, tidak reset.
    assert auto_mod.login_berikut(3, "2026-11-20", "2026-11-24") == 4


def test_login_berikut_siklus_selesai():
    assert auto_mod.login_berikut(30, "2026-11-20", "2026-11-24") is None


# -- auto-beli stok -----------------------------------------------------------

def test_auto_beli_stok_membeli_saat_menipis(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["stok"]["beras"] = 2
    slot["uang"] = 500000
    slot_baru, aksi = auto_mod.auto_beli_stok(slot, game_data)
    beli = [a for a in aksi if a["aksi"] == "beli_stok" and a.get("ok")]
    assert len(beli) == 1
    assert beli[0]["id"] == "beras"
    assert beli[0]["jumlah"] == 18  # target 20 - stok 2
    modal = sim_mod.harga_modal(game_data, "beras", slot)
    assert beli[0]["biaya"] == modal * 18
    assert slot_baru["uang"] == 500000 - modal * 18
    # Stok LANGSUNG masuk stok (bukan kiriman_stok) supaya bisa dijual
    # pada simulasi berikutnya tanpa menunggu kurir (Mode Target).
    assert slot_baru["stok"]["beras"] == 20
    assert slot_baru["kiriman_stok"].get("beras", 0) == 0
    # Slot asli tidak diubah (fungsi murni).
    assert slot["uang"] == 500000


def test_auto_beli_tidak_beli_bila_uang_tidak_cukup(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["stok"]["beras"] = 2
    slot["uang"] = 60000  # beli beras (18 x modal ~234rb) jauh di bawah
    # cadangan Rp50.000 — hari=1 (6 hari sebelum sewa) cadangan hanya
    # Rp50.000, bukan tagihan sewa; tetap tidak terbeli karena biayanya
    # sendiri sudah melebihi uang yang ada.
    slot_baru, aksi = auto_mod.auto_beli_stok(slot, game_data)
    assert not any(a.get("ok") for a in aksi if a["aksi"] == "beli_stok")
    assert any("uang tidak cukup" in a.get("alasan", "") for a in aksi)
    assert slot_baru["uang"] == 60000
    assert slot_baru["kiriman_stok"].get("beras", 0) == 0


def test_auto_beli_tidak_beli_bila_rak_penuh(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["stok"]["beras"] = 100  # MAKS_STOK_BARANG
    slot_baru, aksi = auto_mod.auto_beli_stok(slot, game_data)
    assert aksi == []
    assert slot_baru["kiriman_stok"].get("beras", 0) == 0


def test_auto_beli_tidak_beli_bila_stok_cukup(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)  # beras 20
    _, aksi = auto_mod.auto_beli_stok(slot, game_data)
    assert aksi == []


def test_auto_beli_membeli_semua_yang_menipis(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["stok"]["beras"] = 1
    slot["stok"]["gula"] = 1
    slot["uang"] = 2_000_000
    slot_baru, aksi = auto_mod.auto_beli_stok(slot, game_data)
    beli = {a["id"] for a in aksi if a.get("ok")}
    assert beli == {"beras", "gula"}
    assert slot_baru["stok"]["beras"] == 20
    assert slot_baru["stok"]["gula"] == 20
    assert slot_baru["kiriman_stok"].get("beras", 0) == 0
    assert slot_baru["kiriman_stok"].get("gula", 0) == 0


def test_auto_beli_tidak_beli_barang_titipan(rich_slot, game_data):
    # Roti/jamu = barang titipan (SALES_TITIPAN) — tidak pernah dibeli.
    slot = copy.deepcopy(rich_slot)
    slot["stok"]["roti"] = 0
    slot["barang_terbuka"].append("roti")
    _, aksi = auto_mod.auto_beli_stok(slot, game_data)
    assert aksi == []


# -- auto-harga ikut pasar ----------------------------------------------------

def test_auto_harga_mengikuti_pasaran_dari_save(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 1  # agen aktif mulai level 2
    slot["harga_pasaran"] = {"mi_goreng": 120}
    slot_baru, perubahan = auto_mod.auto_harga_pasar(slot, game_data)
    assert len(perubahan) == 1
    assert perubahan[0]["id"] == "mi_goreng"
    assert perubahan[0]["baru"] == sim_mod.harga_pasar(game_data, "mi_goreng", slot)
    assert slot_baru["harga_jual_khusus"]["mi_goreng"] == perubahan[0]["baru"]


def test_auto_harga_tidak_pernah_di_bawah_lantai(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 1
    slot["harga_pasaran"] = {"mi_goreng": 10}  # pasar anjlok
    _, perubahan = auto_mod.auto_harga_pasar(slot, game_data)
    for p in perubahan:
        lantai = sim_mod.lantai_harga(game_data, p["id"], slot)
        assert p["baru"] >= lantai


def test_auto_harga_tidak_pernah_di_atas_batas(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 1
    slot["harga_pasaran"] = {"mi_goreng": 300}  # pasar meledak
    _, perubahan = auto_mod.auto_harga_pasar(slot, game_data)
    for p in perubahan:
        batas = sim_mod.batas_harga_jual(game_data, p["id"], slot)
        assert p["baru"] <= batas


def test_auto_harga_tanpa_pasaran_tidak_mengubah(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 1
    slot["harga_pasaran"] = {}
    slot_baru, perubahan = auto_mod.auto_harga_pasar(slot, game_data)
    assert perubahan == []
    assert slot_baru["harga_jual_khusus"] == {}


def test_auto_harga_dinamis_dalam_lantai_batas(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 1
    slot_baru, perubahan = auto_mod.auto_harga_dinamis(slot, game_data)
    assert isinstance(perubahan, list)
    for p in perubahan:
        lantai = sim_mod.lantai_harga(game_data, p["id"], slot)
        batas = sim_mod.batas_harga_jual(game_data, p["id"], slot)
        assert lantai <= p["baru"] <= batas
        assert p["laba_baru"] > p["laba_lama"]  # hanya yang lebih untung
        assert slot_baru["harga_jual_khusus"][p["id"]] == p["baru"]


# -- auto-bayar ---------------------------------------------------------------

def test_bayar_sewa_sebelum_jatuh_tempo(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["hari"] = 7  # Minggu: hari % 7 == 0
    slot["uang"] = 500000
    hasil = auto_mod.bayar_sewa(slot, game_data.cerita)
    assert hasil["ok"] is True
    assert hasil["dibayar"] == 100000  # per_minggu[tingkat 0]
    assert slot["uang"] == 400000
    assert slot["sewa_selesai_hari"] == 7
    assert slot["tunggakan_sewa"] == 0


def test_bayar_sewa_tidak_bayar_bila_uang_tidak_cukup(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["hari"] = 7
    slot["uang"] = 50000
    hasil = auto_mod.bayar_sewa(slot, game_data.cerita)
    assert hasil["ok"] is False
    assert slot["uang"] == 50000  # tidak pernah negatif / tidak berubah
    assert slot["sewa_selesai_hari"] == 0


def test_bayar_sewa_bukan_hari_sewa_tidak_membayar(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["hari"] = 3
    hasil = auto_mod.bayar_sewa(slot, game_data.cerita)
    assert hasil["ok"] is False
    assert slot["uang"] == 500000


def test_bayar_sewa_tunggakan_dibayar_dulu(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["hari"] = 7
    slot["uang"] = 500000
    slot["tunggakan_sewa"] = 100000
    hasil = auto_mod.bayar_sewa(slot, game_data.cerita)
    assert hasil["ok"] is True
    assert hasil["dibayar"] == 200000  # tunggakan + minggu ini
    assert slot["tunggakan_sewa"] == 0


def test_bayar_sewa_qris_dipakai_bila_tunai_kurang(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["hari"] = 7
    slot["uang"] = 60000
    slot["saldo_digital"] = 50000
    hasil = auto_mod.bayar_sewa(slot, game_data.cerita)
    assert hasil["ok"] is True
    assert hasil["dibayar"] == 100000
    assert slot["uang"] == 0
    assert slot["saldo_digital"] == 10000


def test_bayar_zakat_di_jendela(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["hari"] = 82
    slot["uang"] = 500000
    hasil = auto_mod.bayar_zakat(slot)
    assert hasil["ok"] is True
    assert hasil["dibayar"] == 45000
    assert slot["uang"] == 455000
    assert slot["zakat_dibayar"] is True


def test_bayar_zakat_di_luar_jendela_tidak_membayar(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["hari"] = 50
    hasil = auto_mod.bayar_zakat(slot)
    assert hasil["ok"] is False
    assert slot["uang"] == 500000


def test_bayar_zakat_tidak_bayar_bila_uang_tidak_cukup(rich_slot, game_data):
    slot = copy.deepcopy(rich_slot)
    slot["hari"] = 82
    slot["uang"] = 10000
    hasil = auto_mod.bayar_zakat(slot)
    assert hasil["ok"] is False
    assert slot["uang"] == 10000


# -- isi tugas ----------------------------------------------------------------

def test_isi_tugas_level_1_penuh(rich_slot, game_data, tugas_data):
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 0
    slot_baru, hasil = auto_mod.auto_isi_tugas(slot, tugas_data)
    assert slot_baru["progres"]["pelanggan"] == 15
    assert slot_baru["progres"]["barang"] == 25
    assert slot_baru["progres"]["omzet"] == 100000
    assert hasil["blockers"] == []


def test_isi_tugas_level_2_lapor_blocker_upgrade(rich_slot, tugas_data):
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 1  # syarat upgrade: kipas (tidak dimiliki)
    _, hasil = auto_mod.auto_isi_tugas(slot, tugas_data)
    assert hasil["blockers"], "harus ada blocker upgrade"
    assert "kipas" in hasil["blockers"][0]


# -- batas harian -------------------------------------------------------------

def test_batas_harian_nol_melewati_simulasi(rich_slot, game_data, tugas_data):
    hasil = auto_mod.jalankan_siklus(
        rich_slot, game_data, tugas_data, tier=2, batas_harian=0)
    assert hasil["batas_terlampaui"] is True
    assert hasil["sim"] is None
    # Harga/beli/tugas tetap jalan meski sim ditahan — hanya sim yang batal.
    assert any(a["aksi"] == "simulasi" and not a.get("ok")
               for a in hasil["aksi"])


# -- jalankan_siklus ----------------------------------------------------------

def test_siklus_tier_1_tidak_mengubah_save(rich_slot, game_data, tugas_data):
    slot = copy.deepcopy(rich_slot)
    hasil = auto_mod.jalankan_siklus(slot, game_data, tugas_data,
                                     tier=1, batas_harian=1_000_000)
    assert hasil["aksi"] == []
    assert hasil["slot"] == slot


def test_siklus_tier_2_jalan_simulasi_dan_beli(rich_slot, game_data, tugas_data):
    slot = copy.deepcopy(rich_slot)
    slot["stok"]["beras"] = 1
    hasil = auto_mod.jalankan_siklus(slot, game_data, tugas_data,
                                     tier=2, batas_harian=1_000_000)
    assert hasil["sim"] is not None
    assert hasil["sim"]["omzet"] > 0
    aksi = [a["aksi"] for a in hasil["aksi"]]
    assert "simulasi" in aksi
    assert "beli_stok" in aksi
    assert hasil["slot"]["uang"] >= 0
    # Slot hasil adalah salinan — slot asli tidak berubah.
    assert slot["stok"]["beras"] == 1


def test_siklus_tier_3_harga_dinamis_dan_bayar(rich_slot, game_data, tugas_data):
    slot = copy.deepcopy(rich_slot)
    slot["hari"] = 7
    slot["tingkat"] = 1
    slot["harga_pasaran"] = {"mi_goreng": 120}
    hasil = auto_mod.jalankan_siklus(slot, game_data, tugas_data,
                                     tier=3, batas_harian=1_000_000)
    aksi = [a["aksi"] for a in hasil["aksi"]]
    assert "harga_pasar" in aksi  # mi_goreng 120% pasti berubah
    # Sewa hari ini TERBAYAR — jalurnya ada dua dan bergantung pada sim
    # acak (seed=None): bila sim diterima, hari maju ke 8 dan sewa dibayar
    # DI DALAM sim (tutup_hari); bila sim ditolak batas harian, hari
    # tetap 7 dan langkah 5 membayar lewat aksi "bayar_sewa". Dulu tes
    # ini mengasersi aksi "bayar_sewa" sehingga flaky (gagal bila sim
    # diterima). Yang deterministik adalah sewa_selesai_hari == 7.
    assert hasil["slot"].get("sewa_selesai_hari") == 7
    assert hasil["slot"]["uang"] >= 0


def test_siklus_uang_tidak_pernah_negatif(rich_slot, game_data, tugas_data):
    slot = copy.deepcopy(rich_slot)
    slot["uang"] = 60000
    slot["hari"] = 7
    hasil = auto_mod.jalankan_siklus(slot, game_data, tugas_data,
                                     tier=3, batas_harian=1_000_000)
    assert hasil["slot"]["uang"] >= 0
    assert hasil["slot"].get("saldo_digital", 0) >= 0


def test_siklus_slot_tanpa_field_tidak_crash(game_data, tugas_data):
    # Save minimal (field hilang) — semua helper harus toleran.
    slot = {"uang": 100000, "hari": 1, "tingkat": 0}
    hasil = auto_mod.jalankan_siklus(slot, game_data, tugas_data,
                                     tier=3, batas_harian=1_000_000)
    assert hasil["slot"]["uang"] >= 0


def test_siklus_stok_nol_semua_tidak_crash(rich_slot, game_data, tugas_data):
    slot = copy.deepcopy(rich_slot)
    slot["stok"] = {k: 0 for k in slot["stok"]}
    slot["uang"] = 500000
    hasil = auto_mod.jalankan_siklus(slot, game_data, tugas_data,
                                     tier=2, batas_harian=1_000_000)
    assert hasil["sim"] is not None
    # Auto-beli tetap jalan (stok 0 < 5) bila uang cukup.
    assert any(a["aksi"] == "beli_stok" and a.get("ok")
               for a in hasil["aksi"])


# -- perbaikan 25 Nov 2026: bayar misi di siklus harian + cadangan sewa ------

def _slot_misi_aktif(rich_slot, uang=500000, target=150000):
    slot = copy.deepcopy(rich_slot)
    slot["misi_status"] = "aktif"
    slot["target_bab"] = target
    slot["kiriman_bab"] = 0
    slot["uang"] = uang
    return slot


def test_siklus_bayar_misi_standar(rich_slot, game_data, tugas_data):
    """Tugas 3b: siklus harian Standar membayar misi (sekali lunas +
    cadangan Rp50.000) sebelum harga — tanpa ini siklus tidak pernah
    naik level bila misi belum lunas di game asli. Bukti bayar adalah
    aksi 'bayar_misi'; status akhir misi adalah 'aktif' karena siklus
    ini sekaligus NAIK LEVEL (auto_isi_tugas + 4b) dan misi bab
    berikutnya langsung disiapkan."""
    slot = _slot_misi_aktif(rich_slot)
    hasil = auto_mod.jalankan_siklus(slot, game_data, tugas_data,
                                     tier=2, batas_harian=1_000_000)
    bayar = [a for a in hasil["aksi"] if a["aksi"] == "bayar_misi"]
    assert len(bayar) == 1
    assert bayar[0]["jumlah"] == 150000
    assert hasil["slot"]["tingkat"] == 1  # naik level berkat misi lunas
    assert hasil["slot"]["bab"] == 1
    assert hasil["slot"]["misi_status"] == "aktif"  # misi bab 1
    assert hasil["slot"]["target_bab"] == 350000


def test_siklus_tidak_bayar_misi_pemula(rich_slot, game_data, tugas_data):
    """Tier Pemula tidak menjalankan langkah 0b (tidak ada sim/restock)."""
    slot = _slot_misi_aktif(rich_slot)
    hasil = auto_mod.jalankan_siklus(slot, game_data, tugas_data,
                                     tier=1, batas_harian=1_000_000)
    assert not any(a["aksi"] == "bayar_misi" for a in hasil["aksi"])
    assert hasil["slot"]["misi_status"] == "aktif"


def test_siklus_tidak_bayar_misi_bila_sisa_di_bawah_cadangan(
        rich_slot, game_data, tugas_data):
    """Langkah 0b menolak bila sisa < Rp50.000. batas_harian negatif
    dipakai untuk MEMAKSA penolakan sim secara deterministik supaya
    pembayaran misi DI DALAM sim (langkah 3, dari hasil jualan hari
    itu) ikut dibuang — yang diuji di sini hanya langkah 0b."""
    slot = _slot_misi_aktif(rich_slot, uang=180000)
    hasil = auto_mod.jalankan_siklus(slot, game_data, tugas_data,
                                     tier=2, batas_harian=-1_000_000_000)
    assert hasil["batas_terlampaui"] is True
    assert not any(a["aksi"] == "bayar_misi" for a in hasil["aksi"])
    assert hasil["slot"]["misi_status"] == "aktif"
    assert hasil["slot"]["uang"] >= 0


def test_siklus_bayar_misi_tetap_jalan_walau_sim_ditolak(
        rich_slot, game_data, tugas_data):
    """Pembayaran misi langkah 0b mengedit slot langsung (bukan bagian
    sim), jadi tetap berlaku walau simulasi ditolak batas harian —
    dibuktikan aksi 'bayar_misi' yang ada meski sim dibuang; siklus
    ini sekaligus naik level sehingga misi bab berikutnya aktif.
    batas_harian negatif dipakai untuk MEMAKSA penolakan sim secara
    deterministik (cek_batas_harian: selisih > batas; batas 0 tidak
    cukup karena 0b sudah membelanjakan Rp150rb sehingga sim harus
    untung >Rp150rb sehari untuk ditolak)."""
    slot = _slot_misi_aktif(rich_slot)
    hasil = auto_mod.jalankan_siklus(slot, game_data, tugas_data,
                                     tier=2, batas_harian=-1_000_000_000)
    assert hasil["batas_terlampaui"] is True
    assert hasil["sim"] is None
    bayar = [a for a in hasil["aksi"] if a["aksi"] == "bayar_misi"]
    assert len(bayar) == 1 and bayar[0]["jumlah"] == 150000
    assert hasil["slot"]["tingkat"] == 1
    assert hasil["slot"]["bab"] == 1


# -- Tugas 5: cadangan sewa auto_beli_stok -----------------------------------
#
# Sewa Lv6 (tingkat=5) = Rp300.000/minggu (cerita.json). Hari sewa = hari
# kelipatan 7; hari=1 -> jatuh tempo 6 hari lagi (di luar jendela cicil
# 3 hari), hari=5 -> 2 hari lagi (di dalam jendela), hari=7 -> hari sewa.

def _slot_lv6(rich_slot, hari, uang):
    slot = copy.deepcopy(rich_slot)
    slot["tingkat"] = 5
    slot["hari"] = hari
    slot["uang"] = uang
    slot["stok"] = {}  # rak kosong semua
    slot["kiriman_stok"] = {}
    slot["tas_grosir"] = {}
    return slot


def test_auto_beli_restock_saat_sewa_6_hari_lagi(rich_slot, game_data):
    """Regresi spiral Lv6: uang Rp150.000 (< tagihan sewa Rp300.000) +
    rak kosong + sewa 6 hari lagi -> bot TETAP restock (cadangan hanya
    Rp50.000 di luar jendela cicil), bukan diam sampai mati. Kebijakan
    lama mencadangkan tagihan penuh SETIAP hari dan memblokir semua."""
    slot = _slot_lv6(rich_slot, hari=1, uang=150000)
    assert auto_mod.tagihan_sewa(slot, game_data.cerita) == 300000
    slot_baru, aksi = auto_mod.auto_beli_stok(slot, game_data)
    dibeli = [a for a in aksi if a["aksi"] == "beli_stok" and a.get("ok")]
    assert dibeli, "harus ada barang yang dibeli"
    assert slot_baru["uang"] >= 50000  # lantai cadangan tetap berlaku
    assert sum(slot_baru["stok"].values()) > 0


def test_auto_beli_cadangan_sewa_di_jendela_cicil(rich_slot, game_data):
    """2 hari sebelum jatuh tempo: cadangan = tagihan + Rp50.000, supaya
    cicil (uang >= tagihan + 50rb) tetap bisa jalan sesudah restock."""
    slot = _slot_lv6(rich_slot, hari=5, uang=400000)
    slot_baru, aksi = auto_mod.auto_beli_stok(slot, game_data)
    assert slot_baru["uang"] >= 350000  # 300000 tagihan + 50000 cadangan
    assert slot_baru["uang"] <= 400000


def test_auto_beli_cadangan_sewa_hari_sewa(rich_slot, game_data):
    """Hari sewa: cadangan = tagihan + Rp50.000, supaya bayar_sewa penuh
    tetap bisa jalan sesudah restock."""
    slot = _slot_lv6(rich_slot, hari=7, uang=400000)
    slot_baru, aksi = auto_mod.auto_beli_stok(slot, game_data)
    assert slot_baru["uang"] >= 350000


def test_auto_beli_tidak_beli_bila_uang_di_bawah_tagihan_plus_cadangan(
        rich_slot, game_data):
    """Di dalam jendela cicil dengan uang < tagihan + Rp50.000, sewa
    diprioritaskan: tidak ada restock (jendela paling lama 4 hari)."""
    slot = _slot_lv6(rich_slot, hari=5, uang=200000)
    slot_baru, aksi = auto_mod.auto_beli_stok(slot, game_data)
    assert not any(a["aksi"] == "beli_stok" and a.get("ok") for a in aksi)
    assert slot_baru["uang"] == 200000
