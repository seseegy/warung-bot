"""Pemantauan Fase 5: harga pasar Senin, peringatan harga, cek versi game,
pengingat adu laris mingguan.

Grounding (kode game menang):
- Harga pasar: ``harga_pasaran`` di save = {id_barang: faktor} — faktor 1.0
  = harga normal; ``_perbarui_pasaran()`` (game_state.gd:8904) tiap Senin:
  entri lama meluruh ke 1.0 (``p = 1.0 + (lama - 1.0) * 0.5``, di-snap
  0.05, dihapus bila |p - 1.0| < 0.01), lalu 3-5 barang acak dari barang
  belanja yang terbuka diubah +-5..20% (``PERUBAHAN_PASARAN``,
  game_state.gd:8829), dijepit 0.8-1.25. Bot TIDAK menebak pasaran baru —
  ia membaca ``harga_pasaran`` dari save terbaru dan membandingkannya
  dengan snapshot minggu lalu yang disimpan di Store.
- Harga pasar per barang: ``harga_pasar()`` (game_state.gd:8837) =
  katalog jual x faktor (dibulatkan ke 100), tidak aktif bila agen belum
  aktif (level < 2, ``LEVEL_AGEN``) atau tidak ada entri pasaran.
  Di sini dipakai ``sim.harga_pasar`` yang meniru rumus itu.
- Versi game: https://neopawstudio.github.io/versi.json — diverifikasi
  langsung 24 Nov 2026: {"min_kode": 0, "kode_terbaru": 47,
  "versi_terbaru": "1.1", ...} — TIDAK ADA field ``jeda_server`` saat ini,
  dan filenya ketinggalan (kode 47 < 49, versi 1.1 < 1.2). Karena itu
  pengecekan hanya memberi tahu bila server LEBIH BARU dari game, dan
  tidak crash bila field hilang/berubah bentuk.
- Adu laris: papan mingguan (``papan.py``); peringkat dibandingkan dengan
  yang tersimpan di Store (tab "minggu").
"""

from __future__ import annotations

import httpx

from . import papan as papan_mod
from . import sim as sim_mod
from .sim import GameData

URL_VERSI = "https://neopawstudio.github.io/versi.json"
VERSI_GAME = "1.2"
KODE_GAME = 49

# Ambang peringatan harga jual vs harga pasar (pilihan bot, bukan game):
# 20% di atas/bawah pasar dianggap "jauh".
AMBANG_HARGA_JAUH = 0.20


class VersionCheckError(ValueError):
    """versi.json tidak bisa dijangkau/dibaca (bukan bukti ada update)."""


def _faktor(nilai: object) -> float | None:
    """Faktor pasaran -> float, atau None bila bukan angka."""
    try:
        if isinstance(nilai, bool):
            return None
        return float(nilai)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def bandingkan_pasaran(pasaran_lama: dict, pasaran_baru: dict,
                       data: GameData, slot: dict) -> list:
    """Perubahan harga pasar minggu ini vs minggu lalu.

    Mengembalikan list entri: id, nama, faktor_lama, faktor_baru,
    harga_lama, harga_baru (Rp, via ``sim.harga_pasar``), arah
    ("naik"/"turun"/"baru"/"hilang"), saran. Entri yang faktornya sama
    (atau tidak dikenal katalog) tidak dilaporkan — tidak ada notifikasi
    bila harga sama. ``pasaran_lama`` None/{} pada jalan pertama = tidak
    ada pembanding (pemanggil sebaiknya menyimpan snapshot diam-diam).
    """
    lama = pasaran_lama or {}
    baru = pasaran_baru or {}
    hasil = []
    for item_id in sorted(set(lama) | set(baru)):
        if item_id not in data.katalog:
            continue
        f_lama = _faktor(lama.get(item_id))
        f_baru = _faktor(baru.get(item_id))
        if f_lama is not None and f_baru is not None and f_lama == f_baru:
            continue
        if f_lama is None and f_baru is None:
            continue
        if f_lama is None:
            arah = "baru"
        elif f_baru is None:
            arah = "hilang"
        elif f_baru > f_lama:
            arah = "naik"
        else:
            arah = "turun"
        slot_lama = dict(slot)
        slot_lama["harga_pasaran"] = dict(lama)
        slot_baru = dict(slot)
        slot_baru["harga_pasaran"] = dict(baru)
        harga_lama = sim_mod.harga_pasar(data, item_id, slot_lama)
        harga_baru = sim_mod.harga_pasar(data, item_id, slot_baru)
        nama = str(data.katalog[item_id].get("nama", item_id))
        if arah == "naik":
            saran = (f"Pasar naik — pertimbangkan naikkan harga jual "
                     f"{nama} ke {harga_baru}.")
        elif arah == "turun":
            saran = (f"Pasar turun — pertimbangkan turunkan harga jual "
                     f"{nama} ke {harga_baru}.")
        elif arah == "baru":
            if f_baru is not None and f_baru < 1:
                saran = (f"Harga pasar {nama} turun — pertimbangkan "
                         f"turunkan harga jual ke {harga_baru}.")
            elif f_baru is not None and f_baru > 1:
                saran = (f"Harga pasar {nama} naik — pertimbangkan "
                         f"naikkan harga jual ke {harga_baru}.")
            else:
                saran = (f"Harga pasar {nama} kini {harga_baru} — "
                         "sesuaikan harga jual bila perlu.")
        else:
            saran = (f"Harga pasar {nama} kembali normal "
                     f"({harga_baru}) — harga jual bisa dikembalikan.")
        hasil.append({
            "id": item_id,
            "nama": nama,
            "faktor_lama": f_lama,
            "faktor_baru": f_baru,
            "harga_lama": harga_lama,
            "harga_baru": harga_baru,
            "arah": arah,
            "saran": saran,
        })
    return hasil


def peringatan_harga(data: GameData, slot: dict,
                     ambang: float = AMBANG_HARGA_JAUH) -> list:
    """Barang yang harga jualnya jauh dari harga pasar.

    Hanya barang fisik terbuka yang ADA stoknya (yang lain tidak bisa
    dijual sekarang). Entri: id, nama, harga_jual, harga_pasar, rasio,
    arah ("mahal"/"murah"), di_lantai (harga sudah di lantai game
    sehingga tidak bisa diturunkan lagi — ``lantai_harga``,
    game_state.gd:5730). Harga wajar (dalam ambang) tidak dilaporkan.
    """
    terbuka = set(slot.get("barang_terbuka", []) or [])
    stok = slot.get("stok", {}) or {}
    hasil = []
    for item_id in data.urutan_barang:
        item = data.katalog[item_id]
        if item["jenis"] != "fisik" or item_id not in terbuka:
            continue
        if int(stok.get(item_id, 0) or 0) <= 0:
            continue
        harga_jual = sim_mod.harga_jual(data, item_id, slot)
        harga_pasar = sim_mod.harga_pasar(data, item_id, slot)
        if harga_pasar <= 0:
            continue
        rasio = harga_jual / harga_pasar
        if rasio > 1.0 + ambang:
            arah = "mahal"
        elif rasio < 1.0 - ambang:
            arah = "murah"
        else:
            continue
        lantai = sim_mod.lantai_harga(data, item_id, slot)
        hasil.append({
            "id": item_id,
            "nama": str(item.get("nama", item_id)),
            "harga_jual": harga_jual,
            "harga_pasar": harga_pasar,
            "rasio": round(rasio, 2),
            "arah": arah,
            "di_lantai": harga_jual <= lantai,
            "lantai": lantai,
        })
    hasil.sort(key=lambda x: abs(x["rasio"] - 1.0), reverse=True)
    return hasil


def _parse_kode(nilai: object) -> int | None:
    """kode_terbaru -> int, atau None bila hilang/bukan angka."""
    if isinstance(nilai, bool):
        return None
    if isinstance(nilai, int):
        return nilai
    if isinstance(nilai, str) and nilai.strip().isdigit():
        return int(nilai.strip())
    return None


def _parse_versi(teks: object) -> tuple[int, ...] | None:
    """'1.2' -> (1, 2). None bila bukan string versi angka bertitik."""
    if not isinstance(teks, str):
        return None
    bagian = teks.strip().split(".")
    if not bagian or not all(p.isdigit() for p in bagian):
        return None
    return tuple(int(p) for p in bagian)


def cek_versi(data: object) -> dict:
    """Nilai isi versi.json (sudah di-fetch) terhadap game yang dianalisis.

    Mengembalikan: diketahui (bool — False bila field kunci hilang/tidak
    bisa dibaca), ada_update (bool), kode_server, versi_server, catatan.
    TIDAK PERNAH melempar untuk bentuk yang tak terduga: data bukan dict
    atau field aneh -> diketahui False. Perbandingan versi memakai tuple
    angka (bukan string) supaya "1.10" > "1.2" benar.
    """
    if not isinstance(data, dict):
        return {"diketahui": False, "ada_update": False, "kode_server": None,
                "versi_server": None,
                "catatan": "versi.json bukan object JSON."}
    kode = _parse_kode(data.get("kode_terbaru"))
    versi_teks = data.get("versi_terbaru")
    versi = _parse_versi(versi_teks)
    if kode is None and versi is None:
        return {"diketahui": False, "ada_update": False, "kode_server": None,
                "versi_server": (str(versi_teks) if versi_teks is not None
                                else None),
                "catatan": "versi.json tidak berisi kode_terbaru/versi_terbaru "
                           "yang bisa dibaca."}
    ada_update = False
    if kode is not None and kode > KODE_GAME:
        ada_update = True
    if versi is not None and versi > _parse_versi(VERSI_GAME):
        ada_update = True
    catatan = ""
    if kode is not None and kode < KODE_GAME:
        catatan = (f"File versi di server lebih lama dari game "
                   f"(kode {kode} < {KODE_GAME}) — game di HP lebih baru.")
    elif not ada_update:
        catatan = "Tidak ada versi baru di server."
    return {"diketahui": True, "ada_update": ada_update,
            "kode_server": kode,
            "versi_server": (str(versi_teks) if versi_teks is not None
                            else None),
            "catatan": catatan}


async def fetch_versi_json(client=None) -> dict:
    """GET versi.json. ``client`` opsional (objek dengan ``get`` async —
    untuk tes). Tanpa client, buat AsyncClient sendiri.

    Melempar VersionCheckError bila tidak bisa dijangkau, bukan 200,
    atau isinya bukan JSON object. Pemanggil yang memutuskan: gagal cek
    = "tidak diketahui", bukan "ada update" dan bukan "tidak ada update".
    """
    if client is not None:
        try:
            resp = await client.get(URL_VERSI)
        except Exception as exc:
            raise VersionCheckError(
                f"tidak bisa mengjangkau versi.json: {exc}") from exc
        status = getattr(resp, "status_code", 200)
        if status != 200:
            raise VersionCheckError(f"versi.json menjawab HTTP {status}")
        try:
            data = resp.json()
        except Exception as exc:
            raise VersionCheckError(
                f"versi.json bukan JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise VersionCheckError("versi.json bukan object JSON")
        return data
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=15.0) as c:
            resp = await c.get(URL_VERSI)
    except Exception as exc:
        raise VersionCheckError(
            f"tidak bisa mengjangkau versi.json: {exc}") from exc
    if resp.status_code != 200:
        raise VersionCheckError(
            f"versi.json menjawab HTTP {resp.status_code}")
    try:
        data = resp.json()
    except Exception as exc:
        raise VersionCheckError(f"versi.json bukan JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise VersionCheckError("versi.json bukan object JSON")
    return data


def teks_pengingat_adu_laris(peringkat_lama: int | None,
                             peringkat_baru: int | None,
                             jumlah_warung: int = 0) -> str | None:
    """Pengingat adu laris mingguan (Jumat sore, sebelum minggu berganti).

    None bila peringkat minggu ini belum diketahui (belum masuk papan /
    papan tidak bisa dibaca) — tidak ada yang bisa diingatkan. Arah
    dihitung seperti ``papan.bandingkan_peringkat``.
    """
    if peringkat_baru is None:
        return None
    arah = papan_mod.bandingkan_peringkat(peringkat_lama, peringkat_baru)
    total = f" dari {jumlah_warung} warung" if jumlah_warung else ""
    if arah == "baru":
        return (f"Adu laris minggu ini: kamu di peringkat #{peringkat_baru}"
                f"{total}. Minggu berganti sebentar lagi — mainkan gamenya "
                f"supaya skor minggu ini terkirim.")
    if arah == "naik":
        return (f"Adu laris minggu ini: peringkatmu naik #{peringkat_lama} "
                f"→ #{peringkat_baru}{total}. Minggu berganti sebentar "
                f"lagi — pertahankan.")
    if arah == "turun":
        return (f"Adu laris minggu ini: peringkatmu turun #{peringkat_lama} "
                f"→ #{peringkat_baru}{total}. Minggu berganti sebentar "
                f"lagi — mainkan gamenya supaya tidak makin turun.")
    return (f"Adu laris minggu ini: kamu tetap di peringkat "
            f"#{peringkat_baru}{total}. Minggu berganti sebentar lagi.")
