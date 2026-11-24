import { useCallback, useEffect, useState } from 'react';
import {
  Banner,
  Button,
  Cell,
  Input,
  List,
  Section,
  Spinner,
} from '@telegram-apps/telegram-ui';
import { api, ApiError, type StatusRes } from '../api';
import { confirmDialog, hapticGagal, hapticOk, hapticTap } from '../tg';
import { formatAngka, formatRupiah, progresTeks } from '../utils';

interface Props {
  raw: string;
  notify: (pesan: string, ok?: boolean) => void;
  onTugas?: () => void;
}

const TAMBAH_CEPAT = [100_000, 500_000, 1_000_000];

export default function Beranda({ raw, notify, onTugas }: Props) {
  const [status, setStatus] = useState<StatusRes | null>(null);
  const [memuat, setMemuat] = useState(true);
  const [galat, setGalat] = useState('');
  const [jumlahKetik, setJumlahKetik] = useState('');
  const [mengirim, setMengirim] = useState(false);

  const muat = useCallback(async () => {
    setMemuat(true);
    setGalat('');
    try {
      const hasil = await api.status(raw);
      setStatus(hasil);
    } catch (err) {
      setGalat(err instanceof ApiError ? err.message : 'Gagal memuat status.');
    } finally {
      setMemuat(false);
    }
  }, [raw]);

  useEffect(() => {
    void muat();
  }, [muat]);

  async function ubahUang(jumlahBaru: number) {
    if (!status) return;
    if (jumlahBaru < 0 || jumlahBaru > 999_999_999) {
      notify('Jumlah tidak valid.', false);
      return;
    }
    const setuju = await confirmDialog({
      title: 'Ubah Uang',
      message: `Uang warung diubah dari ${formatRupiah(status.uang)} menjadi ${formatRupiah(jumlahBaru)}? Perubahan ini diunggah ke cloud.`,
      okText: 'Ya, Ubah',
    });
    if (!setuju) return;
    setMengirim(true);
    try {
      await api.uang(raw, jumlahBaru);
      hapticOk();
      notify('Uang diperbarui.');
      setJumlahKetik('');
      await muat();
    } catch (err) {
      hapticGagal();
      notify(err instanceof ApiError ? err.message : 'Gagal mengubah uang.', false);
    } finally {
      setMengirim(false);
    }
  }

  if (memuat && !status) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 32 }}>
        <Spinner size="l" />
      </div>
    );
  }

  if (galat && !status) {
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

  if (!status) return null;

  return (
    <List>
      {status.peringatan.length > 0 && (
        <Banner
          type="section"
          header="Perhatian"
          description={status.peringatan.join('\n')}
        />
      )}

      <Section header="Warung">
        <Cell subhead="Nama warung">{status.nama_warung}</Cell>
        <Cell subhead="Uang" after={formatRupiah(status.uang)}>
          {`Level ${status.level} · Hari ${status.hari}`}
        </Cell>
        <Cell subhead="Saldo QRIS" after={formatRupiah(status.qris)}>
          Disimpan {status.disimpan}
        </Cell>
        <Cell
          subhead="Energi"
          after={`${formatAngka(status.energi)}%`}
        >
          {status.energi < 30
            ? 'Energi rendah — istirahat di game (ngopi/makan).'
            : 'Energi cukup.'}
        </Cell>
        <Cell
          subhead="Stok"
          after={`${status.stok_terisi}/${status.stok_total}`}
        >
          Barang dengan stok tersedia
        </Cell>
        <Cell subhead="Kerja 24/7" after={status.tier}>
          {status.otomatis ? 'Otomatis aktif' : 'Otomatis mati'}
        </Cell>
      </Section>

      {status.tugas && (
        <Section header="Tugas Level">
          <Cell
            subhead={status.tugas.nama}
            after={`Hadiah ${formatRupiah(status.tugas.hadiah)}`}
            onClick={() => {
              hapticTap();
              onTugas?.();
            }}
          >
            {`Pelanggan ${progresTeks(...status.tugas.pelanggan)} · Barang ${progresTeks(...status.tugas.barang)} · Omzet ${formatRupiah(status.tugas.omzet[0])}/${formatRupiah(status.tugas.omzet[1])}`}
          </Cell>
        </Section>
      )}

      <Section header="Ubah Uang">
        <Cell multiline subtitle="Tombol menambah ke uang sekarang; ketik jumlah untuk mengatur total.">
          Tambah cepat
        </Cell>
        <div style={{ display: 'flex', gap: 8, padding: '0 16px 8px' }}>
          {TAMBAH_CEPAT.map((n) => (
            <Button
              key={n}
              mode="bezeled"
              size="m"
              disabled={mengirim}
              onClick={() => {
                hapticTap();
                void ubahUang(status.uang + n);
              }}
            >
              +{formatRupiah(n)}
            </Button>
          ))}
        </div>
        <div style={{ padding: '0 16px 16px' }}>
          <Input
            header="Atur total uang (Rp)"
            type="number"
            inputMode="numeric"
            placeholder="mis. 5000000"
            value={jumlahKetik}
            onChange={(e) => setJumlahKetik(e.target.value)}
          />
          <div style={{ height: 8 }} />
          <Button
            mode="filled"
            size="m"
            stretched
            loading={mengirim}
            disabled={!jumlahKetik || mengirim}
            onClick={() => {
              hapticTap();
              void ubahUang(Number(jumlahKetik));
            }}
          >
            Simpan Total Baru
          </Button>
        </div>
      </Section>

      <div style={{ padding: '0 16px 16px' }}>
        <Button mode="gray" size="m" stretched onClick={() => void muat()}>
          Perbarui
        </Button>
      </div>
    </List>
  );
}
