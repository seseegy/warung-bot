import { useCallback, useEffect, useState } from 'react';
import {
  Banner,
  Button,
  Cell,
  List,
  Section,
  Spinner,
} from '@telegram-apps/telegram-ui';
import { api, ApiError, type TugasRes } from '../api';
import { confirmDialog, hapticGagal, hapticOk, hapticTap } from '../tg';
import { formatRupiah, progresPersen, progresTeks } from '../utils';

interface Props {
  raw: string;
  notify: (pesan: string, ok?: boolean) => void;
}

export default function Tugas({ raw, notify }: Props) {
  const [tugas, setTugas] = useState<TugasRes | null>(null);
  const [memuat, setMemuat] = useState(true);
  const [galat, setGalat] = useState('');
  const [mengirim, setMengirim] = useState(false);

  const muat = useCallback(async () => {
    setMemuat(true);
    setGalat('');
    try {
      setTugas(await api.tugas(raw));
    } catch (err) {
      setGalat(err instanceof ApiError ? err.message : 'Gagal memuat tugas.');
    } finally {
      setMemuat(false);
    }
  }, [raw]);

  useEffect(() => {
    void muat();
  }, [muat]);

  async function isiProgres() {
    if (!tugas || tugas.level_terakhir) return;
    const setuju = await confirmDialog({
      title: 'Selesaikan Tugas',
      message: `Isi progres "${tugas.nama ?? ''}" sampai selesai dan klaim hadiah ${formatRupiah(tugas.hadiah ?? 0)}? Hadiah dibayar saat game berikutnya menjalankan cek tugas.`,
      okText: 'Ya, Selesaikan',
    });
    if (!setuju) return;
    setMengirim(true);
    try {
      await api.tugasSelesai(raw);
      hapticOk();
      notify('Tugas diselesaikan — buka game untuk klaim hadiah.');
      await muat();
    } catch (err) {
      hapticGagal();
      notify(err instanceof ApiError ? err.message : 'Gagal menyelesaikan tugas.', false);
    } finally {
      setMengirim(false);
    }
  }

  if (memuat && !tugas) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 32 }}>
        <Spinner size="l" />
      </div>
    );
  }

  if (galat && !tugas) {
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

  if (!tugas) return null;

  if (tugas.level_terakhir) {
    return (
      <List>
        <Banner
          type="section"
          header="Level terakhir"
          description={tugas.pesan ?? 'Tidak ada tugas lagi.'}
        />
      </List>
    );
  }

  return (
    <List>
      <Section header={`Tugas Level ${tugas.level ?? ''} — ${tugas.nama ?? ''}`}>
        {(tugas.target ?? []).map((t) => (
          <Cell
            key={t.kunci}
            subhead={t.label}
            after={progresTeks(t.saat_ini, t.target)}
          >
            {`${progresPersen(t.saat_ini, t.target)}% selesai`}
          </Cell>
        ))}
        {tugas.khusus && (
          <Cell
            subhead={`Khusus (${tugas.khusus.jenis})`}
            after={progresTeks(tugas.khusus.saat_ini, tugas.khusus.target)}
          >
            {`${progresPersen(tugas.khusus.saat_ini, tugas.khusus.target)}% selesai`}
          </Cell>
        )}
        <Cell subhead="Hadiah" after={formatRupiah(tugas.hadiah ?? 0)}>
          Dibayar saat game menjalankan cek tugas
        </Cell>
      </Section>

      {(tugas.blockers ?? []).length > 0 && (
        <Banner
          type="section"
          header="Belum bisa diselesaikan"
          description={(tugas.blockers ?? []).join('\n')}
        />
      )}

      <div style={{ padding: '0 16px 16px' }}>
        <Button
          mode="filled"
          size="l"
          stretched
          loading={mengirim}
          disabled={mengirim || (tugas.blockers ?? []).length > 0}
          onClick={() => {
            hapticTap();
            void isiProgres();
          }}
        >
          Isi Progres
        </Button>
      </div>
    </List>
  );
}
