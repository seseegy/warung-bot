/// <reference types="vite/client" />

declare global {
  interface Window {
    Telegram?: {
      WebApp?: {
        initData: string;
        initDataUnsafe?: unknown;
        ready: () => void;
        expand: () => void;
      };
    };
  }
}

export {};
