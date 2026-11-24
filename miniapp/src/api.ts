/** Klien API bot (FastAPI, /api/*).
 *
 * Setiap request membawa header X-Telegram-Init-Data berisi initData mentah
 * dari Telegram WebApp — server memvalidasi HMAC-nya. TIDAK ada token atau
 * rahasia apa pun yang disimpan di sini.
 */

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export interface TugasRingkasan {
  nama: string;
  hadiah: number;
  pelanggan: [number, number];
  barang: [number, number];
  omzet: [number, number];
}

export interface StatusRes {
  ok: boolean;
  nama_warung: string;
  level: number;
  hari: number;
  uang: number;
  qris: number;
  energi: number;
  stok_terisi: number;
  stok_total: number;
  versi: number;
  disimpan: string;
  tugas: TugasRingkasan | null;
  peringatan: string[];
  tier: string;
  otomatis: boolean;
}

export interface TugasTarget {
  kunci: string;
  label: string;
  saat_ini: number;
  target: number;
}

export interface TugasRes {
  ok: boolean;
  level_terakhir?: boolean;
  pesan?: string;
  level?: number;
  nama?: string;
  hadiah?: number;
  target?: TugasTarget[];
  khusus?: { jenis: string; saat_ini: number; target: number } | null;
  blockers?: string[];
}

export interface StokItem {
  id: string;
  nama: string;
  stok: number;
  harga_jual: number;
  harga_pasar: number;
  harga_modal: number;
  lantai: number;
  batas: number;
}

export interface StokRes {
  ok: boolean;
  versi_dasar: number;
  uang: number;
  daftar: StokItem[];
}

export interface HargaSaran {
  id: string;
  nama: string;
  stok: number;
  harga_sekarang: number;
  harga_terbaik: number;
  laba_sekarang: number;
  laba_terbaik: number;
}

export interface HargaTerbaikRes {
  ok: boolean;
  versi_dasar: number;
  daftar: HargaSaran[];
}

export interface HariSim {
  hari: number;
  omzet: number;
  laba: number;
  dilayani: number;
  batal: number;
}

export interface SimulasiRes {
  ok: boolean;
  sim_id: string;
  versi_dasar: number;
  jumlah_hari: number;
  omzet: number;
  laba: number;
  uang_awal: number;
  uang_akhir: number;
  qris_awal: number;
  qris_akhir: number;
  dilayani: number;
  batal: number;
  datang: number;
  tingkat_awal: number;
  tingkat_akhir: number;
  hari_akhir: number;
  diusir: boolean;
  tunggakan_sewa: number;
  per_hari: HariSim[];
  catatan: string;
}

export interface PengaturanRes {
  ok: boolean;
  tier: number;
  tier_nama: string;
  otomatis: boolean;
  batas_harian: number;
  jam_otomatis: number;
  jam_laporan: number | null;
  laporan_aktif: boolean;
  baca_saja: boolean;
}

async function request<T>(
  raw: string,
  path: string,
  init?: RequestInit,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: {
        'X-Telegram-Init-Data': raw,
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new ApiError(0, 'jaringan', 'Tidak bisa menghubungi server bot.');
  }
  let data: Record<string, unknown> = {};
  try {
    data = (await res.json()) as Record<string, unknown>;
  } catch {
    throw new ApiError(res.status, 'respons_rusak', 'Respons server rusak.');
  }
  if (!res.ok || data.ok === false) {
    throw new ApiError(
      res.status,
      String(data.code ?? `http_${res.status}`),
      String(data.message ?? `Server menjawab ${res.status}.`),
    );
  }
  return data as T;
}

const get = <T>(raw: string, path: string) => request<T>(raw, path);

const post = <T>(raw: string, path: string, body?: unknown) =>
  request<T>(raw, path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const api = {
  status: (raw: string) => get<StatusRes>(raw, '/api/status'),
  tugas: (raw: string) => get<TugasRes>(raw, '/api/tugas'),
  stok: (raw: string) => get<StokRes>(raw, '/api/stok'),
  hargaTerbaik: (raw: string) => get<HargaTerbaikRes>(raw, '/api/harga-terbaik'),
  simulasi: (raw: string, hari: number) =>
    post<SimulasiRes>(raw, '/api/simulasi', { hari }),
  terapkanSimulasi: (raw: string, sim_id: string) =>
    post<{ ok: boolean; teks: string }>(raw, '/api/terapkan-simulasi', {
      sim_id,
    }),
  uang: (raw: string, jumlah: number) =>
    post<{ ok: boolean; teks: string }>(raw, '/api/uang', { jumlah }),
  tugasSelesai: (raw: string) =>
    post<{ ok: boolean; teks: string }>(raw, '/api/tugas-selesai'),
  terapkanHarga: (raw: string, versi_dasar: number, harga: Record<string, number>) =>
    post<{ ok: boolean; teks: string }>(raw, '/api/terapkan-harga', {
      versi_dasar,
      harga,
    }),
  pengaturan: (raw: string) => get<PengaturanRes>(raw, '/api/pengaturan'),
  ubahPengaturan: (raw: string, body: Record<string, unknown>) =>
    post<PengaturanRes>(raw, '/api/pengaturan', body),
  unlink: (raw: string) =>
    post<{ ok: boolean; teks: string }>(raw, '/api/unlink'),
};
