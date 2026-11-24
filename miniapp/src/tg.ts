/** Pembungkus SDK Telegram (@telegram-apps/sdk-react / @telegram-apps/sdk).
 *
 * Semua pemanggilan SDK dibungkus try/catch: di luar Telegram (mis. dibuka
 * dari browser biasa) fungsi-fungsi ini mengembalikan nilai aman, bukan
 * melempar — App menampilkan Placeholder, bukan crash.
 */

import {
  expandViewport,
  hapticFeedbackImpactOccurred,
  hapticFeedbackNotificationOccurred,
  hapticFeedbackSelectionChanged,
  init,
  miniApp,
  mountMainButton,
  offMainButtonClick,
  onMainButtonClick,
  retrieveRawInitData,
  setMainButtonParams,
  showPopup,
} from '@telegram-apps/sdk-react';
import { useEffect } from 'react';

export interface TgUser {
  id: number;
  first_name?: string;
  username?: string;
}

export interface TgContext {
  /** initData mentah (query string) — dikirim ke backend untuk divalidasi. */
  raw: string;
  user: TgUser | null;
}

/** Inisialisasi SDK sekali. Kembalikan null bila bukan di dalam Telegram. */
export function initTelegram(): TgContext | null {
  let raw = '';
  try {
    init();
  } catch {
    return null;
  }
  try {
    raw = retrieveRawInitData() ?? '';
  } catch {
    raw = '';
  }
  if (!raw) return null;
  let user: TgUser | null = null;
  try {
    const params = new URLSearchParams(raw);
    const userJson = params.get('user');
    if (userJson) {
      const parsed = JSON.parse(userJson) as TgUser;
      if (typeof parsed.id === 'number') user = parsed;
    }
  } catch {
    user = null;
  }
  try {
    miniApp.ready();
  } catch {
    /* abaikan */
  }
  try {
    expandViewport();
  } catch {
    /* abaikan */
  }
  return { raw, user };
}

export function hapticTap(): void {
  try {
    hapticFeedbackImpactOccurred('light');
  } catch {
    /* perangkat tidak mendukung */
  }
}

export function hapticSelect(): void {
  try {
    hapticFeedbackSelectionChanged();
  } catch {
    /* abaikan */
  }
}

export function hapticOk(): void {
  try {
    hapticFeedbackNotificationOccurred('success');
  } catch {
    /* abaikan */
  }
}

export function hapticGagal(): void {
  try {
    hapticFeedbackNotificationOccurred('error');
  } catch {
    /* abaikan */
  }
}

/** Dialog konfirmasi native Telegram. Fallback ke window.confirm. */
export async function confirmDialog(opts: {
  title: string;
  message: string;
  okText?: string;
  destructive?: boolean;
}): Promise<boolean> {
  const okText = opts.okText ?? 'Ya';
  try {
    const hasil = await showPopup({
      title: opts.title,
      message: opts.message,
      buttons: [
        {
          id: 'ok',
          type: opts.destructive ? 'destructive' : 'default',
          text: okText,
        },
        { id: 'batal', type: 'cancel' },
      ],
    });
    return hasil === 'ok';
  } catch {
    return window.confirm(`${opts.title}\n\n${opts.message}`);
  }
}

/** Hook MainButton (BottomButton) Telegram: tampil saat `visible`. */
export function useMainButton(
  text: string,
  visible: boolean,
  onClick: () => void,
): void {
  useEffect(() => {
    if (!visible) return undefined;
    let off: (() => void) | undefined;
    try {
      mountMainButton();
      setMainButtonParams({ text, isVisible: true });
      off = onMainButtonClick(onClick);
    } catch {
      /* di luar Telegram / tidak didukung — tombol di halaman tetap ada */
    }
    return () => {
      try {
        if (off) off();
        else offMainButtonClick(onClick);
      } catch {
        /* abaikan */
      }
      try {
        // Sembunyikan lewat state (tidak ada show/hide terpisah di SDK v3).
        setMainButtonParams({ isVisible: false });
      } catch {
        /* abaikan */
      }
    };
    // onClick sengaja tidak di deps: handler stabil via ref di pemanggil
    // bila berubah tiap render. Di sini cukup text/visible.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, visible]);
}
