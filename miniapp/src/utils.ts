/** Util format angka/rupiah (murni, tanpa dependensi Telegram). */

/** Rp1.234.567 — pemisah ribuan titik, tanpa desimal. */
export function formatRupiah(nilai: number): string {
  const n = Math.trunc(nilai);
  return `Rp${Math.abs(n).toLocaleString('id-ID')}`;
}

/** Bentuk ringkas: Rp500 rb, Rp1,2 jt, Rp13,5 jt. */
export function formatRupiahCompact(nilai: number): string {
  const n = Math.abs(Math.trunc(nilai));
  if (n >= 1_000_000) {
    const jt = n / 1_000_000;
    const teks = jt >= 100 ? String(Math.trunc(jt)) : jt.toFixed(1).replace('.', ',').replace(/,0$/, '');
    return `Rp${teks} jt`;
  }
  if (n >= 1_000) {
    return `Rp${Math.trunc(n / 1_000)} rb`;
  }
  return `Rp${n}`;
}

/** 1.234 — pemisah ribuan titik. */
export function formatAngka(nilai: number): string {
  return Math.trunc(nilai).toLocaleString('id-ID');
}

/** "210/350" + persen. */
export function progresTeks(saatIni: number, target: number): string {
  if (target <= 0) return `${formatAngka(saatIni)}`;
  return `${formatAngka(saatIni)}/${formatAngka(target)}`;
}

export function progresPersen(saatIni: number, target: number): number {
  if (target <= 0) return 100;
  return Math.min(100, Math.round((saatIni / target) * 100));
}
