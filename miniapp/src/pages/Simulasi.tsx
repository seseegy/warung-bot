import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Banner,
  Button,
  Card,
  Cell,
  Input,
  List,
  Section,
  Spinner,
  Switch,
} from '@telegram-apps/telegram-ui';
import {
  api,
  ApiError,
  type HargaTerbaikRes,
  type SimulasiRes,
  type StokRes,
} from '../api';
import {
  confirmDialog,
  hapticGagal,
  hapticOk,
  hapticTap,
  useMainButton,
} from '../tg';
import { formatAngka, formatRupiah } from '../utils';

interface Props {
  raw: string;
  notify: (pesan: string, ok?: boolean) => void;
}

export default function Simulasi({ raw, notify }: Props) {
  const [hari, setHari] = useState('1');
  const [hasil, setHasil] = useState<SimulasiRes | null>(null);
  const [stok, setStok] = useState<StokRes | null>(null);
  const [saran, setSaran] = useState<HargaTerbaikRes | null>(null);
  const [memuat, setMemuat] = useState(true);
  const [menjalankan, setMenjalankan] = useState(false);
  const [menerapkan, setMenerapkan] = useState(false);
  const [galat, setGalat] = useState('');

  const hasilRef = useRef<SimulasiRes | null>(null);
  hasilRef.current = hasil;

  const muatStok = useCallback(async () => {
    try {
      const [s, h] = await Promise.all([
        api.stok(raw),
        api.hargaTerbaik(raw),
      ]);
      setStok(s);
      setSaran(h);
    } catch (err) {
      setGalat(err instanceof ApiError ? err.message : 'Gagal memuat stok.');
    } finally {
      setMemuat(false);
    }
  }, [raw]);

  useEffect(() => {
    void muatStok();
  }, [muatStok]);

  async function jalankan() {
    const n = Number(hari);
    if (!Number.isInteger(n) || n < 1 || n > 30) {
      notify('Jumlah hari harus 1–30.', false);
      return;
    }
    setMenjalankan(true);
    try {
      const res = await api.simulasi(raw, n);
      setHasil(res);
      hapticOk();
    } catch (err) {
      hapticGagal();
      notify(err instanceof ApiError ? err.message : 'Simulasi gagal.', false);
    } finally {
      setMenjalankan(false);
    }
  }

  async function terapkan() {
    const sim = hasilRef.current;
    if (!sim) return;
    const setuju = await confirmDialog({
      title: 'Terapkan Simulasi',
      message: `Hasil simulasi ${sim.jumlah_hari} hari (uang ${formatRupiah(sim.uang_awal)} → ${formatRupiah(sim.uang_akhir)}) akan diunggah ke cloud dan menimpa simpanan. Lanjutkan?`,
      okText: 'Ya, Terapkan',
    });
    if (!setuju) return;
    setMenerapkan(true);
    try {
      await api.terapkanSimulasi(raw, sim.sim_id);
      hapticOk();
      notify('Simulasi diterapkan ke save.');
      setHasil(null);
      await muatStok();
    } catch (err) {
      hapticGagal();
      notify(
        err instanceof ApiError ? err.message : 'Gagal menerapkan simulasi.',
        false,
      );
    } finally {
      setMenerapkan(false);
    }
  }

  // MainButton Telegram muncul bila ada hasil simulasi.
  useMainButton('Terapkan ke Save', hasil !== null, () => void terapkan());

  async function ikutHargaPasar(nyala: boolean) {
    if (!nyala || !stok || !saran) return;
    const harga: Record<string, number> = {};
    for (const item of stok.daftar) {
      if (item.stok > 0) harga[item.id] = item.harga_pasar;
    }
    if (Object.keys(harga).length === 0) {
      notify('Tidak ada barang berstok untuk diubah harganya.', false);
      return;
    }
    const setuju = await confirmDialog({
      title: 'Ikut Harga Pasar',
      message: `Harga ${Object.keys(harga).length} barang diubah ke harga pasar minggu ini (batas & lantai game tetap dicek server). Lanjutkan?`,
      okText: 'Ya, Ubah Harga',
    });
    if (!setuju) return;
    setMenerapkan(true);
    try {
      await api.terapkanHarga(raw, stok.versi_dasar, harga);
      hapticOk();
      notify('Harga diubah ke harga pasar.');
      await muatStok();
    } catch (err) {
      hapticGagal();
      notify(
        err instanceof ApiError ? err.message : 'Gagal mengubah harga.',
        false,
      );
    } finally {
      setMenerapkan(false);
    }
  }

  const saranMap = new Map((saran?.daftar ?? []).map((s) => [s.id, s]));

  return (
    <List>
      <Section header="Simulasi">
        <div style={{ padding: '0 16px 8px' }}>
          <Input
            header="Jumlah hari (1–30)"
            type="number"
            inputMode="numeric"
            value={hari}
            onChange={(e) => setHari(e.target.value)}
          />
          <div style={{ height: 8 }} />
          <Button
            mode="filled"
            size="m"
            stretched
            loading={menjalankan}
            disabled={menjalankan}
            onClick={() => {
              hapticTap();
              void jalankan();
            }}
          >
            Jalankan Simulasi
          </Button>
        </div>
      </Section>

      {hasil && (
        <Section header={`Hasil ${hasil.jumlah_hari} hari`}>
          <Card type="plain">
            <div style={{ padding: 12 }}>
              <div>Omzet {formatRupiah(hasil.omzet)}</div>
              <div>Laba {formatRupiah(hasil.laba)}</div>
              <div>
                Uang {formatRupiah(hasil.uang_awal)} →{' '}
                {formatRupiah(hasil.uang_akhir)}
              </div>
              <div>
                Dilayani {formatAngka(hasil.dilayani)} · Batal{' '}
                {formatAngka(hasil.batal)}
              </div>
              {hasil.diusir && (
                <div>Diperingatkan: warung DIUSIR dalam simulasi ini.</div>
              )}
            </div>
          </Card>
          {hasil.per_hari.slice(0, 7).map((h) => (
            <Cell
              key={h.hari}
              subhead={`Hari ${h.hari}`}
              after={formatRupiah(h.laba)}
            >
              {`Omzet ${formatRupiah(h.omzet)} · ${formatAngka(h.dilayani)} dilayani`}
            </Cell>
          ))}
          {hasil.per_hari.length > 7 && (
            <Cell subhead="Hari berikutnya">
              {`+${hasil.per_hari.length - 7} hari lagi di ringkasan`}
            </Cell>
          )}
          <div style={{ padding: '8px 16px 16px' }}>
            <Button
              mode="filled"
              size="m"
              stretched
              loading={menerapkan}
              disabled={menerapkan}
              onClick={() => {
                hapticTap();
                void terapkan();
              }}
            >
              Terapkan ke Save
            </Button>
          </div>
        </Section>
      )}

      <Section
        header="Harga & Stok"
        footer="Proyeksi simulasi, bukan hasil main sungguhan — RNG, event acak, dan pilihan cerita tidak disimulasikan."
      >
        {memuat ? (
          <div
            style={{ display: 'flex', justifyContent: 'center', padding: 24 }}
          >
            <Spinner size="m" />
          </div>
        ) : galat ? (
          <Banner type="section" header="Gagal memuat" description={galat} />
        ) : (
          (stok?.daftar ?? []).map((item) => {
            const s = saranMap.get(item.id);
            return (
              <Cell
                key={item.id}
                subhead={item.nama}
                after={formatRupiah(item.harga_jual)}
                multiline
                subtitle={
                  `Stok ${formatAngka(item.stok)} · Pasar ${formatRupiah(item.harga_pasar)}` +
                  (s && s.harga_terbaik !== item.harga_jual
                    ? ` · Saran ${formatRupiah(s.harga_terbaik)}`
                    : '')
                }
              >
                {`Modal ${formatRupiah(item.harga_modal)}`}
              </Cell>
            );
          })
        )}
        <Cell
          Component="label"
          after={
            <Switch
              checked={false}
              onChange={(e) => {
                hapticTap();
                void ikutHargaPasar(e.target.checked);
              }}
            />
          }
        >
          Ikut harga pasar
        </Cell>
      </Section>
    </List>
  );
}
