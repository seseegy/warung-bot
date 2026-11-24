import { useCallback, useEffect, useState } from 'react';
import {
  Banner,
  Button,
  Cell,
  Input,
  List,
  Section,
  SegmentedControl,
  Spinner,
  Switch,
} from '@telegram-apps/telegram-ui';
import { api, ApiError, type PengaturanRes } from '../api';
import {
  confirmDialog,
  hapticGagal,
  hapticOk,
  hapticSelect,
  hapticTap,
} from '../tg';
import { formatRupiah } from '../utils';

interface Props {
  raw: string;
  notify: (pesan: string, ok?: boolean) => void;
  onUnlink: () => void;
}

const TIERS = [
  { id: 1, nama: 'Pemula' },
  { id: 2, nama: 'Standar' },
  { id: 3, nama: 'Profesional' },
];

export default function Pengaturan({ raw, notify, onUnlink }: Props) {
  const [data, setData] = useState<PengaturanRes | null>(null);
  const [memuat, setMemuat] = useState(true);
  const [galat, setGalat] = useState('');
  const [batas, setBatas] = useState('');
  const [jamOtomatis, setJamOtomatis] = useState('');
  const [jamLaporan, setJamLaporan] = useState('');
  const [menyimpan, setMenyimpan] = useState(false);

  const muat = useCallback(async () => {
    setMemuat(true);
    setGalat('');
    try {
      const hasil = await api.pengaturan(raw);
      setData(hasil);
      setBatas(String(hasil.batas_harian));
      setJamOtomatis(String(hasil.jam_otomatis));
      setJamLaporan(
        hasil.jam_laporan === null ? '' : String(hasil.jam_laporan),
      );
    } catch (err) {
      setGalat(
        err instanceof ApiError ? err.message : 'Gagal memuat pengaturan.',
      );
    } finally {
      setMemuat(false);
    }
  }, [raw]);

  useEffect(() => {
    void muat();
  }, [muat]);

  async function ubah(patch: Record<string, unknown>) {
    setMenyimpan(true);
    try {
      const hasil = await api.ubahPengaturan(raw, patch);
      setData(hasil);
      setBatas(String(hasil.batas_harian));
      setJamOtomatis(String(hasil.jam_otomatis));
      setJamLaporan(
        hasil.jam_laporan === null ? '' : String(hasil.jam_laporan),
      );
      hapticOk();
      notify('Pengaturan disimpan.');
    } catch (err) {
      hapticGagal();
      notify(
        err instanceof ApiError ? err.message : 'Gagal menyimpan pengaturan.',
        false,
      );
    } finally {
      setMenyimpan(false);
    }
  }

  async function putuskan() {
    const setuju = await confirmDialog({
      title: 'Putuskan Tautan',
      message:
        'Semua data kamu (token akun, cadangan, jadwal) akan dihapus dari bot. Tindakan ini tidak bisa dibatalkan.',
      okText: 'Ya, Putuskan',
      destructive: true,
    });
    if (!setuju) return;
    try {
      await api.unlink(raw);
      hapticOk();
      notify('Tautan diputuskan.');
      onUnlink();
    } catch (err) {
      hapticGagal();
      notify(
        err instanceof ApiError ? err.message : 'Gagal memutuskan tautan.',
        false,
      );
    }
  }

  if (memuat && !data) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 32 }}>
        <Spinner size="l" />
      </div>
    );
  }

  if (galat && !data) {
    return (
      <List>
        <Banner type="section" header="Gagal memuat" description={galat}>
          <Button mode="filled" size="s" onClick={() => void muat()}>
            Coba Lagi
          </Button>
        </Banner>
      </List>
    );
  }

  if (!data) return null;

  return (
    <List>
      <Section header="Kerja 24/7 — Tier">
        <div style={{ padding: '12px 16px' }}>
          <SegmentedControl>
            {TIERS.map((t) => (
              <SegmentedControl.Item
                key={t.id}
                selected={data.tier === t.id}
                onClick={() => {
                  hapticSelect();
                  void ubah({ tier: t.id });
                }}
              >
                {t.nama}
              </SegmentedControl.Item>
            ))}
          </SegmentedControl>
        </div>
        <Cell subhead="Tier aktif" after={data.tier_nama}>
          Pemula: dasar · Standar: +laporan · Profesional: +peringkat
        </Cell>
      </Section>

      <Section header="Otomatis & Laporan">
        <Cell
          Component="label"
          after={
            <Switch
              checked={data.otomatis}
              disabled={menyimpan}
              onChange={(e) => {
                hapticTap();
                void ubah({ otomatis: e.target.checked });
              }}
            />
          }
        >
          Kerja 24/7 otomatis
        </Cell>
        <Cell
          Component="label"
          after={
            <Switch
              checked={data.laporan_aktif}
              disabled={menyimpan}
              onChange={(e) => {
                hapticTap();
                void ubah({ laporan_aktif: e.target.checked });
              }}
            />
          }
        >
          Laporan harian
        </Cell>
        <Cell
          Component="label"
          after={
            <Switch
              checked={data.baca_saja}
              disabled={menyimpan}
              onChange={(e) => {
                hapticTap();
                void ubah({ baca_saja: e.target.checked });
              }}
            />
          }
        >
          Mode baca saja
        </Cell>
        <Cell
          multiline
          subtitle="Mode baca saja memblokir semua aksi tulis dari Mini App."
        >
          Perubahan jadwal/otomatis berlaku paling lambat 10 menit.
        </Cell>
      </Section>

      <Section header="Batas & Jam">
        <div style={{ padding: '0 16px 16px' }}>
          <Input
            header="Batas perubahan uang harian (Rp)"
            type="number"
            inputMode="numeric"
            value={batas}
            onChange={(e) => setBatas(e.target.value)}
          />
          <div style={{ height: 8 }} />
          <Input
            header="Jam kerja otomatis (0–23 WIB)"
            type="number"
            inputMode="numeric"
            value={jamOtomatis}
            onChange={(e) => setJamOtomatis(e.target.value)}
          />
          <div style={{ height: 8 }} />
          <Input
            header="Jam laporan harian (0–23 WIB)"
            type="number"
            inputMode="numeric"
            value={jamLaporan}
            onChange={(e) => setJamLaporan(e.target.value)}
          />
          <div style={{ height: 8 }} />
          <Button
            mode="filled"
            size="m"
            stretched
            loading={menyimpan}
            disabled={menyimpan}
            onClick={() => {
              hapticTap();
              const patch: Record<string, unknown> = {};
              const b = Number(batas);
              const jo = Number(jamOtomatis);
              const jl = jamLaporan === '' ? null : Number(jamLaporan);
              if (!Number.isInteger(b) || b < 0) {
                notify('Batas harian tidak valid.', false);
                return;
              }
              if (!Number.isInteger(jo) || jo < 0 || jo > 23) {
                notify('Jam otomatis harus 0–23.', false);
                return;
              }
              if (jl !== null && (!Number.isInteger(jl) || jl < 0 || jl > 23)) {
                notify('Jam laporan harus 0–23.', false);
                return;
              }
              patch.batas_harian = b;
              patch.jam_otomatis = jo;
              if (jl !== null) patch.jam_laporan = jl;
              void ubah(patch);
            }}
          >
            Simpan Batas & Jam
          </Button>
          <div style={{ height: 8 }} />
          <Cell subhead="Batas saat ini" after={formatRupiah(data.batas_harian)}>
            {`Jam otomatis ${data.jam_otomatis}:00 · Laporan ${data.jam_laporan ?? '-'}:00`}
          </Cell>
        </div>
      </Section>

      <div style={{ padding: '0 16px 16px' }}>
        <Button
          mode="outline"
          size="m"
          stretched
          onClick={() => {
            hapticTap();
            void putuskan();
          }}
        >
          Putuskan Tautan
        </Button>
      </div>
    </List>
  );
}
