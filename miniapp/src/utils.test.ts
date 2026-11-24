import { describe, expect, it } from 'vitest';
import {
  formatAngka,
  formatRupiah,
  formatRupiahCompact,
  progresPersen,
  progresTeks,
} from './utils';

describe('formatRupiah', () => {
  it('memisah ribuan dengan titik', () => {
    expect(formatRupiah(0)).toBe('Rp0');
    expect(formatRupiah(500)).toBe('Rp500');
    expect(formatRupiah(1_500_000)).toBe('Rp1.500.000');
    expect(formatRupiah(21_000_000)).toBe('Rp21.000.000');
  });

  it('membulatkan ke bawah', () => {
    expect(formatRupiah(1500.9)).toBe('Rp1.500');
  });
});

describe('formatRupiahCompact', () => {
  it('ratusan ribu', () => {
    expect(formatRupiahCompact(500_000)).toBe('Rp500 rb');
    expect(formatRupiahCompact(999)).toBe('Rp999');
  });

  it('jutaan dengan koma', () => {
    expect(formatRupiahCompact(1_200_000)).toBe('Rp1,2 jt');
    expect(formatRupiahCompact(13_500_000)).toBe('Rp13,5 jt');
    expect(formatRupiahCompact(2_000_000)).toBe('Rp2 jt');
  });
});

describe('formatAngka', () => {
  it('memisah ribuan', () => {
    expect(formatAngka(1234)).toBe('1.234');
    expect(formatAngka(100)).toBe('100');
  });
});

describe('progres', () => {
  it('teks dan persen', () => {
    expect(progresTeks(210, 350)).toBe('210/350');
    expect(progresPersen(210, 350)).toBe(60);
    expect(progresPersen(400, 350)).toBe(100);
    expect(progresPersen(0, 0)).toBe(100);
  });
});
