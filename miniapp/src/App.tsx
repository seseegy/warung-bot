import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AppRoot,
  List,
  Placeholder,
  Snackbar,
  Tabbar,
} from '@telegram-apps/telegram-ui';
import { api, ApiError } from './api';
import Beranda from './pages/Beranda';
import Pengaturan from './pages/Pengaturan';
import Simulasi from './pages/Simulasi';
import Tugas from './pages/Tugas';
import { hapticSelect, initTelegram, type TgContext } from './tg';

type Tab = 'beranda' | 'tugas' | 'simulasi' | 'pengaturan';
type StatusTautan = 'memuat' | 'ok' | 'belum' | 'bukan_telegram' | 'galat';

interface Snack {
  pesan: string;
  ok: boolean;
}

function IkonBeranda({ aktif }: { aktif: boolean }) {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1v-8.5Z"
        fill={aktif ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IkonTugas({ aktif }: { aktif: boolean }) {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M5 12.5 9.5 17 19 7"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect
        x="3.5"
        y="3.5"
        width="17"
        height="17"
        rx="4"
        fill={aktif ? 'currentColor' : 'none'}
        fillOpacity="0.15"
        stroke="currentColor"
        strokeWidth="1.5"
      />
    </svg>
  );
}

function IkonSimulasi({ aktif }: { aktif: boolean }) {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M4 20V10M10 20V4M16 20v-8M22 20H2"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
      {aktif && <circle cx="10" cy="4" r="1.6" fill="currentColor" />}
    </svg>
  );
}

function IkonPengaturan() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="3.2" stroke="currentColor" strokeWidth="1.5" />
      <path
        d="M12 2.8v2.6M12 18.6v2.6M2.8 12h2.6M18.6 12h2.6M5.5 5.5l1.8 1.8M16.7 16.7l1.8 1.8M18.5 5.5l-1.8 1.8M7.3 16.7l-1.8 1.8"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

export default function App() {
  const [tg] = useState<TgContext | null>(() => initTelegram());
  const [tab, setTab] = useState<Tab>('beranda');
  const [tautan, setTautan] = useState<StatusTautan>(
    tg ? 'memuat' : 'bukan_telegram',
  );
  const [pesanGalat, setPesanGalat] = useState('');
  const [snack, setSnack] = useState<Snack | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const notify = useCallback((pesan: string, ok = true) => {
    setSnack({ pesan, ok });
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setSnack(null), 3000);
  }, []);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  // Cek akun tertaut saat pertama dibuka.
  useEffect(() => {
    if (!tg) return;
    let batal = false;
    api
      .status(tg.raw)
      .then(() => {
        if (!batal) setTautan('ok');
      })
      .catch((err: unknown) => {
        if (batal) return;
        if (err instanceof ApiError && err.code === 'belum_tertaut') {
          setTautan('belum');
        } else {
          setTautan('galat');
          setPesanGalat(
            err instanceof ApiError ? err.message : 'Gagal menghubungi server.',
          );
        }
      });
    return () => {
      batal = true;
    };
  }, [tg]);

  function pindah(ke: Tab) {
    hapticSelect();
    setTab(ke);
  }

  return (
    <AppRoot>
      {tautan === 'bukan_telegram' && (
        <List>
          <Placeholder
            header="Buka dari Telegram"
            description="Dashboard ini hanya bisa dibuka dari tombol Buka Dashboard di chat bot Warung, atau dari Menu Button bot."
          />
        </List>
      )}

      {tautan === 'belum' && (
        <List>
          <Placeholder
            header="Belum ada akun tertaut"
            description="Kirim /link di chat bot dan kirim file akun.json dari game dulu, lalu buka lagi dashboard ini."
          />
        </List>
      )}

      {tautan === 'galat' && (
        <List>
          <Placeholder
            header="Tidak bisa terhubung"
            description={pesanGalat || 'Server bot tidak menjawab.'}
          />
        </List>
      )}

      {tautan === 'memuat' && (
        <List>
          <Placeholder header="Memuat…" description="Menghubungi server bot." />
        </List>
      )}

      {tautan === 'ok' && tg && (
        <div style={{ paddingBottom: 72 }}>
          {tab === 'beranda' && (
            <Beranda
              raw={tg.raw}
              notify={notify}
              onTugas={() => pindah('tugas')}
            />
          )}
          {tab === 'tugas' && <Tugas raw={tg.raw} notify={notify} />}
          {tab === 'simulasi' && <Simulasi raw={tg.raw} notify={notify} />}
          {tab === 'pengaturan' && (
            <Pengaturan
              raw={tg.raw}
              notify={notify}
              onUnlink={() => {
                setTautan('belum');
                setTab('beranda');
              }}
            />
          )}

          <Tabbar>
            <Tabbar.Item
              text="Beranda"
              selected={tab === 'beranda'}
              onClick={() => pindah('beranda')}
            >
              <IkonBeranda aktif={tab === 'beranda'} />
            </Tabbar.Item>
            <Tabbar.Item
              text="Tugas"
              selected={tab === 'tugas'}
              onClick={() => pindah('tugas')}
            >
              <IkonTugas aktif={tab === 'tugas'} />
            </Tabbar.Item>
            <Tabbar.Item
              text="Simulasi"
              selected={tab === 'simulasi'}
              onClick={() => pindah('simulasi')}
            >
              <IkonSimulasi aktif={tab === 'simulasi'} />
            </Tabbar.Item>
            <Tabbar.Item
              text="Pengaturan"
              selected={tab === 'pengaturan'}
              onClick={() => pindah('pengaturan')}
            >
              <IkonPengaturan />
            </Tabbar.Item>
          </Tabbar>
        </div>
      )}

      {snack && (
        <Snackbar
          duration={3000}
          onClose={() => setSnack(null)}
          description={snack.ok ? undefined : 'Coba lagi.'}
        >
          {snack.pesan}
        </Snackbar>
      )}
    </AppRoot>
  );
}
