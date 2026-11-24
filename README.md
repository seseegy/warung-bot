# Bot Telegram — Warung Life Simulator 1.2 (Fase 1 MVP + Fase 2 Simulasi + Fase 3 Kerja 24/7 + Fase 4 Mini App + Fase 5 Pemantauan & jaga-jaga)

Kerangka bot Fase 1: baca save warung dari cloud Supabase, ubah (uang,
progres tugas), lalu unggah kembali. **Fase 2** menambah mesin simulasi
satu hari game + perencana (kapan naik level, ROI upgrade, what-if harga,
harga terbaik) + laporan harian terjadwal. **Fase 3** menambah Kerja 24/7
tiga tier: pengingat login harian, siklus otomatis harian (simulasi,
auto-beli stok, harga ikut pasar/dinamis, auto-bayar sewa/zakat/motor),
lacak peringkat, dan log audit. **Fase 4** menambah Mini App dashboard.
**Fase 5** menambah pemantauan & jaga-jaga: notifikasi harga pasar
Senin, peringatan harga jauh dari pasar, cek update game, backup paket
harian + rollback, aksi cepat (/jual, /beli, /ngopi, /tutup, /slot),
rencana 7 hari, dan statistik dari riwayat save. Bot **tidak memainkan game** —
ia membaca → menghitung proyeksi → (bila disetujui) menulis file save,
lalu game di HP menampilkan hasilnya. Rancangan lengkap:
`../reverse-apk-analysis/warung-life-simulator/RANCANGAN_BOT_TELE.md`.

> Status: kerangka Fase 1 + Fase 2 + Fase 3 + Fase 4 + Fase 5,
> **siap dijalankan setelah `BOT_TOKEN` + `akun.json` tersedia**.
> Belum pernah diuji terhadap Supabase live maupun Bot API live —
> lihat "Yang belum bisa dites".

## Fitur Fase 1

- `/start` (welcome + status tautan), `/menu`, `/bantuan`, `/batal`
- `/link` — terima file `akun.json`, validasi, simpan terenkripsi, uji `akun_ambil`
- `/status` — kartu status (uang, level, hari, progres tugas) + tombol inline
- Ubah uang — tombol cepat +100rb/+500rb/+1jt (menambah) dan ketik sendiri
  (mengganti total), selalu lewat layar konfirmasi (lama → baru)
- `/tugas_selesai` — isi progres sampai target + konfirmasi (termasuk
  peringatan jujur bila syarat lain belum terpenuhi — lihat di bawah)
- `/sync` (ambil cloud), `/upload_paksa` (timpa setelah bentrok),
  `/unlink` (hapus semua data pengguna dari bot)
- Menu = **inline keyboard, teks polos tanpa emoji**. Tanpa perintah
  berparameter. Satu pesan per layar (diedit, bukan dikirim baru).
  Konfirmasi sebelum setiap upload.

## Fitur Fase 2 — Simulasi & perencana

- `/simulasi` — proyeksi 1/3/7 hari dari simpanan terbaru (omzet, laba,
  uang akhir, tugas tercapai) + tombol [Terapkan ke Save] (konfirmasi
  dulu; ditolak bila cloud berubah sejak simulasi dibuat)
- `/harga_terbaik` — harga per barang yang memaksimalkan laba harian
  (brute force per langkah harga game, 1 hari × 2 seed; tidak pernah di
  bawah lantai harga) + tombol [Terapkan Semua Harga]
- `/stok` — stok menipis + rekomendasi beli (biaya, batas rak 100/barang,
  durasi + ongkir kurir reguler). Hanya rekomendasi — belum membeli.
- `/jadwal` — atur jam laporan harian (WIB, per chat, tersimpan di SQLite;
  job APScheduler `laporan:<chat_id>`, dimuat ulang saat bot start)
- `/kapan_naik` — perkiraan hari sampai naik level pada laju simulasi,
  lengkap dengan blocker jujur (upgrade belum dimiliki / misi belum lunas)
- `/roi_upgrade` — urutan upgrade dari yang paling cepat balik modal
  (3 hari sim, biaya harian ikut dihitung); cctv/genset ditandai karena
  efek utamanya pencegahan, bukan uang
- `/whatif` — coba harga lain lewat teks bebas (`mi_goreng 4000,
  teh_botol 5000`), bandingkan omzet/laba/dilayani dengan harga sekarang
  (seed sama); harga di bawah lantai / di atas batas ditolak

Semua hasil simulasi diberi label jelas: **"Proyeksi simulasi, bukan
hasil main sungguhan — RNG, event acak, dan pilihan cerita tidak
disimulasikan."**

## Fitur Fase 3 — Kerja 24/7 (tiga tier)

Tier disimpan per chat (default Pemula) dan **ditegakkan di kode**, bukan
cuma di UI — aksi di atas tier pengguna ditolak (`TierError`).

- **Pemula** — pengingat klaim login harian (pesan pagi + tombol
  [Sudah Klaim] untuk mencatat streak), laporan harian, pengingat stok
  menipis + sewa jatuh tempo. Tidak mengubah save.
- **Standar** — semua Pemula + siklus otomatis harian: simulasi 1 hari,
  auto-beli stok saat menipis (biaya = harga_modal × jumlah, masuk
  kiriman — bukan instan), harga ikut harga pasar Senin (dari
  `harga_pasaran` DI SAVE, tidak ditebak), auto-isi progres tugas.
- **Profesional** — semua Standar + harga dinamis per barang (brute force,
  hanya yang labanya lebih besar), terbaik dari 3 simulasi, auto-bayar
  sewa/zakat/cicilan motor, lacak posisi peringkat.
- `/tier` — pilih tier lewat kartu inline (penjelasan tiap tier +
  konfirmasi sebelum aktivasi pertama), `/otomatis` — nyalakan/matikan
  siklus (tombol, tanpa parameter), `/laporan` — ringkasan harian/mingguan
  + semua aksi otomatis dari log audit, `/bandingkan` — bandingkan 4
  strategi harga dalam simulasi 1 hari (butuh tier Profesional).
- Siklus harian jalan default **07.00 WIB** (job APScheduler
  `otomatis:<chat_id>`, dimuat ulang saat bot start). Urutan tiap siklus:
  ambil state terbaru → pengingat login → harga → simulasi (cek batas
  harian, default Rp1.000.000) → auto-beli → isi tugas → auto-bayar →
  **satu upload** → laporan ke chat. Bila versi cloud berubah sejak
  siklus mulai, siklus dibatalkan (tidak menimpa). Bila bentrok atau sesi
  habis, otomatisasi **dimatikan** dan pengguna diberi tahu — tidak
  mencoba lagi diam-diam.
- **Batas harian** (bukan aturan game — pilihan bot, RANCANGAN §14 tidak
  memberi angka): kenaikan bersih uang dalam satu siklus maks
  Rp1.000.000; bila simulasi melewatinya, simulasi tidak diterapkan
  (harga/beli/tugas/bayar tetap jalan).
- **Log audit** — semua aksi otomatis tercatat (apa, kapan, detail) dan
  muncul di `/laporan`. `/unlink` menghapus tier + jadwal + log audit +
  pelacak login + peringkat pengguna.
- **Peringkat hanya dibaca, tidak pernah dikirim** (lihat "Keputusan:
  skor adu laris tidak dikirim" di bawah).

## Fitur Fase 4 — Mini App dashboard

Dashboard Telegram Mini App (Vite + React 18 + TypeScript +
`@telegram-apps/telegram-ui` 2.1.13 + `@telegram-apps/sdk` 3.11.8),
disajikan API FastAPI (`bot/api.py`) di path `/` bersama endpoint
`/api/*`. Dua proses terpisah — bot polling (`python -m bot.main`) dan
API (`python -m bot.api`, systemd `warung-bot-api.service`) — karena
`Store` membuka sqlite dengan `check_same_thread=True`; berbagi satu
koneksi antar-thread melempar `sqlite3.ProgrammingError`.

- **Autentikasi initData** (persis dokumen `core.telegram.org/bots/webapps`):
  `data_check_string` = field kecuali `hash`/`signature`, urut alfabet,
  `key=value`, pemisah LF; secret = `HMAC-SHA256(key=b"WebAppData",
  msg=bot_token)`; bandingkan hex HMAC dengan `hash` via
  `hmac.compare_digest`; `auth_date` maksimal 24 jam, tolak masa depan
  > 300 detik. Header: `X-Telegram-Init-Data`. Setelah itu cek allowlist
  + akun tertaut di store.
- **Tabbar bawah** — Beranda | Tugas | Simulasi | Pengaturan. Tema ikut
  ThemeParams Telegram otomatis via `AppRoot` (tidak ada warna hardcode);
  safe area + mobile-first; Spinner saat memuat, Snackbar saat
  sukses/gagal, HapticFeedback di ketukan penting, konfirmasi native
  `showPopup` sebelum semua aksi tulis.
- **Beranda** — uang/level/hari/energi/stok, Banner peringatan (stok
  habis, energi < 30, tunggakan sewa), ringkasan tugas, ubah uang
  (tambah cepat +100rb/+500rb/+1jt dan atur total).
- **Tugas** — target level + progres ("210/350") + blocker jujur
  (mis. upgrade kipas belum dimiliki); tombol Isi Progres (konfirmasi dulu).
- **Simulasi** — input hari 1–30, hasil di Card (+ per hari), MainButton
  Telegram "Terapkan ke Save" (konfirmasi `showPopup` dulu). Harga &
  Stok: daftar barang (harga jual/pasar/modal/stok) + saran harga terbaik
  + Switch "Ikut harga pasar" (terapkan harga pasar semua barang berstok).
- **Pengaturan** — Switch mode baca saja / laporan harian / kerja 24/7,
  SegmentedControl tier (Pemula/Standar/Profesional), input batas harian
  + jam otomatis + jam laporan, tombol Putuskan Tautan (destructive,
  konfirmasi dulu).
- **Mode baca saja** (`store.baca_saja`, kolom baru di `users`) —
  memblokir semua aksi tulis lewat API (403 `baca_saja`), baca tetap jalan.
- **Sinkronisasi jadwal** — job interval 10 menit
  (`jobs.sinkronkan_semua` + `atur_sinkronisasi`): perubahan pengaturan
  dari Mini App (API hanya menulis DB) diterapkan bot polling tanpa
  restart; idempotent (job yang jamnya sudah benar dibiarkan).
- **Bot chat** — tombol inline [Buka Dashboard] (web_app) di Menu dan
  kartu Status bila env `MINIAPP_URL` diisi.
- **Keamanan** — tidak ada token/rahasia di frontend (cek: `grep` di
  `miniapp/dist/` bersih); initData mentah hanya dikirim sebagai header,
  tidak disimpan di localStorage; tidak ada RAHASIA HMAC game ke frontend.
  Semua aksi tulis tetap memakai alur `akun_ambil`-dulu + cek versi
  seperti Fase 1–3 (simulasi disimpan per chat dengan `sim_id`, ditolak
  410 bila diganti hasil yang lebih baru).

## Fitur Fase 5 — Pemantauan & jaga-jaga

- **Notifikasi harga pasar Senin** (job `pasar_senin`, Senin 07.00 WIB) —
  membaca `harga_pasaran` dari save terbaru, membandingkan dengan
  snapshot minggu lalu (meta `pasaran` di Store), mengabari bila ada
  barang yang naik/turun/baru/kembali normal + saran ikut naik/turun
  harga jual. Jalan pertama hanya menyimpan snapshot diam-diam (tidak
  ada pembanding). Catatan: pasaran di save baru berubah setelah game
  dimainkan hari Senin (`_perbarui_pasaran` jalan di game, bukan di
  server) — notifikasi muncul saat bot pertama kali melihat pasaran
  baru, belum tentu tepat Senin 07.00 bila game belum dibuka.
- **Peringatan harga jauh dari pasar** — tiap notifikasi Senin juga
  memeriksa harga jual vs harga pasar (ambang 20%, pilihan bot);
  barang fisik terbuka yang ada stoknya saja. Bila harga sudah di lantai
  game, dicatat "tidak bisa diturunkan".
- **Cek update game** (job `cek_versi`, harian 07.05 WIB) — GET
  `neopawstudio.github.io/versi.json`, kabari tiap chat SEKALI per kode
  baru bila server lebih baru dari game (kode > 49 / versi > 1.2).
  Gagal fetch atau format tak terduga = diam (log saja), bukan crash.
  Fakta live 24 Nov 2026: file server ketinggalan (kode 47, versi 1.1)
  dan TIDAK ADA field `jeda_server` — bot tidak menganggapnya ada.
- **Backup paket harian + rollback** (job `backup_harian`, harian 03.00
  WIB; tabel `backups` yang sudah ada, `p_data` terenkripsi Fernet) —
  satu arsip per hari. `/backup` menampilkan daftar + tombol [Pulihkan
  tanggal]. Rollback butuh konfirmasi 2 langkah (tinjau arsip → konfirmasi
  upload); arsip diunggah sebagai versi baru dengan `p_versi_dasar`
  terbaru; paket cloud saat ini dicadangkan dulu sebelum ditimpa. Arsip
  rusak/tidak bisa di-decode ditolak sebelum ada yang diunggah. (Bukan
  perintah berparameter: tidak ada `/rollback <tanggal>` — sesuai §15,
  tanggal dipilih lewat tombol.)
- **Aksi cepat** (butuh tier Standar + mode baca saja mati + batas
  harian) — semua lewat layar konfirmasi, semua dicatat ke log audit:
  - `/jual` — ketik "mi goreng 5": akuntansi `jual()` per unit (stok −1,
    uang += harga, omzet/laba, progres barang/omzet/khusus,
    `_cek_tugas()`). Layanan memakai saldo layanan. TIDAK menambah
    progres pelanggan/total_pembeli (`jual()` tidak melakukannya).
  - `/beli` — ketik "beras 10": akuntansi `beli_stok()` (biaya =
    harga_modal × jumlah, kiriman kurir — stok datang saat game dibuka,
    bukan instan).
  - `/ngopi` — `istirahat("ngopi")`: +30 energi (maks 100), 1x/hari,
    jeda 120 menit, tolak bila energi ≥ 99 / Ramadan / stok minuman habis.
  - `/tutup` — `tutup_hari()`: biaya harian + sewa Minggu, riwayat
    harian, hari +1, energi 100. Angka hari ini dari `penjualan_hari` +
    `catatan_hari` (lihat Grounding Fase 5 soal jendela kemarin).
  - `/slot` — pilih slot 1–6 yang dipakai bot (default: slot terbaik
    seperti `kemajuan_hp` — level lalu hari). Tersimpan per chat
    (`users.slot_aktif`); `/unlink` menghapusnya.
- **`/rencana`** — rencana 7 hari (simulasi + restock + 3 upgrade
  tercepat balik modal + kapan naik level). Proyeksi, bukan janji.
- **`/statistik`** — barang terlaris hari ini (`penjualan_hari`),
  omzet/laba per hari dari `riwayat`, hari terbaik/terburuk. JUJUR:
  pelanggan tersering TIDAK BISA dihitung — `riwayat_layan` hanya
  boolean berhasil/gagal (lihat Grounding Fase 5).
- **Pengingat adu laris mingguan** (job `adu_laris_jumat`, Jumat 17.00
  WIB, tier Profesional) — peringkat papan "minggu" vs yang tersimpan,
  sekali per minggu per chat.
- **Menu** — tombol [Aksi Cepat] di menu utama + layar menu cepat
  (Jual/Beli/Ngopi/Tutup/Slot/Backup/Rencana/Statistik). Mode baca saja
  kini juga ditegakkan di bot chat (sebelumnya hanya API Mini App).

## Menjalankan

```bash
cp .env.example .env   # isi BOT_TOKEN dan FERNET_KEY
# FERNET_KEY: .venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python3 -m venv .venv
.venv/bin/pip install -r bot/requirements.txt
.venv/bin/python -m bot.main
```

`.env` (wajib): `BOT_TOKEN`, `FERNET_KEY`. Opsional: `SUPABASE_URL`,
`SUPABASE_KEY` (default = server + publishable key game, publik by design),
`ALLOWED_CHAT_IDS` (koma; kosong = semua chat boleh — tidak disarankan),
`DB_PATH` (default `data/bot.db`), `MINIAPP_URL` (URL HTTPS Mini App;
kosong = tombol Buka Dashboard tidak muncul), `API_HOST`/`API_PORT`
(default `127.0.0.1:8000`), `MINIAPP_DIST` (default `miniapp/dist`).

Systemd (VPS): sesuaikan path di `systemd/warung-bot.service`, lalu
`systemctl enable --now warung-bot`. Pastikan `.env` mode `600`.

### Mini App (Fase 4)

```bash
cd miniapp && npm install && npm run build   # hasil di miniapp/dist/
# Jalankan API (proses kedua, port 8000 default):
.venv/bin/python -m bot.api
```

Systemd: `systemd/warung-bot-api.service`
(`systemctl enable --now warung-bot-api`). API menyajikan `miniapp/dist/`
di `/` dan endpoint di `/api/*`. **Telegram hanya menerima URL HTTPS** —
pasang reverse proxy TLS (Nginx/Caddy) di depan `127.0.0.1:8000`, atau
untuk pengujian pakai Cloudflare Tunnel
(`cloudflared tunnel --url http://127.0.0.1:8000`) lalu isi
`MINIAPP_URL=https://<domain-tunnel>/` di `.env` dan restart kedua service.

BotFather — Menu Button: buka @BotFather → `/mybots` → pilih bot →
Bot Settings → Menu Button → isi URL Mini App (sama dengan
`MINIAPP_URL`). Tombol [Buka Dashboard] juga muncul di pesan Menu/Status
bot bila `MINIAPP_URL` diisi.

## Tes

```bash
.venv/bin/python -m pytest -q
```

285 tes (saat penyerahan Fase 4) + 113 tes Fase 5 = **398 tes**
(saat penyerahan Fase 5): Fase 1 (70) + Fase 2 (73) +
`test_tiers.py` (tier gating + Store Fase 3 + audit + hapus total),
`test_auto.py` (login, auto-beli, auto-harga, auto-bayar, batas harian,
siklus per tier), `test_papan.py` (parse peringkat + `fetch_papan` mock),
`test_tg_tiers.py` (perintah/kartu tier, login callback, laporan,
bandingkan + gating), `test_jobs_fase3.py` (job siklus, bentrok/sesi
habis mematikan otomatisasi, guard versi kind "siklus" di `execute_upload`).
Fase 4: `test_api.py` (32 — validasi initData benar/salah/kedaluwarsa/
masa depan/kosong/tanpa-hash/tanpa-user + tiap endpoint API dengan
`httpx.ASGITransport` + cloud mock + penolakan allowlist/belum-tertaut/
baca-saja), `test_jobs_sinkron.py` (5 — tambah/idempotent/perbarui-jam/
hapus-saat-unlink/job interval), `test_main.py` (+5 — `load_context`,
tombol web_app di Menu/Status). Frontend: `cd miniapp && npm run test`
(vitest, 6 tes util format rupiah/progres) + `npm run build`.
Fase 5: `test_monitor.py` (pasaran naik/turun/baru/hilang/sama,
peringatan harga mahal/murah/wajar, cek versi update/kadaluarsa/format
aneh, fetch versi mock, pengingat adu laris), `test_backup.py` (satu
arsip per hari, daftar terbaru dulu, muat identik, arsip rusak ditolak),
`test_cepat.py` (parse/cari barang, jual/beli/ngopi/tutup +
penolakannya, daftar slot), `test_strategi.py` (identitas akuntansi
rencana 7 hari, restock, stok 0 tidak ditebak) +
`test_statistik.py` (terlaris, total riwayat, pelanggan tersering =
None + alasan), `test_store_fase5.py` (slot aktif, meta, daftar arsip,
`delete_user` bersih), `test_tg_cepat.py` (alur teks /jual, penolakan
baca saja/tier, /slot, /backup, rollback 2 langkah tanpa upload di
langkah 1, format rencana/statistik), `test_jobs_fase5.py` (4 job
terdaftar, notifikasi pasar, cek versi sekali per kode, backup harian,
pengingat adu laris sekali seminggu + tier), `test_confirm_fase5.py`
(kind "cepat"/"rollback" di `execute_upload`, tolak bila cloud berubah,
arsip rusak ditolak).
Fase 1–2: `test_sim.py` (mesin simulasi: determinisme seed, rekonsiliasi
akuntansi, lantai/batas harga, Jumat libur, stok 0, uang 0, level
terakhir, SHA-256 data), `test_plan.py` (kapan_naik, ROI, what-if,
harga_terbaik), `test_jobs.py` (jadwal per chat + scheduler APScheduler +
kirim laporan), `test_tg_sim.py` (format pesan Fase 2 + input
what-if/jadwal), `test_confirm_fase2.py` (terapkan simulasi/harga ke
cloud mock, termasuk penolakan bila versi cloud berubah).

## Arsitektur

```
bot/
  main.py            entry point, long polling, env, post_init (scheduler)
                     + post_shutdown. load_context() dipakai ulang bot.api
                     (Fase 4: sinkronisasi jadwal tiap 10 menit)
  api.py             (Fase 4) FastAPI: validasi initData Telegram, endpoint
                     /api/*, sajikan miniapp/dist/ di /
  tg/
    handlers.py      router perintah/tombol/teks, allowlist (Fase 1 + 2)
    keyboards.py     inline keyboard (teks polos)
                     (Fase 4: tombol web_app Buka Dashboard bila MINIAPP_URL)
    link.py          alur /link (terima + validasi akun.json)
    status.py        kartu status/tugas + ambil state terbaru
    confirm.py       pending action: konfirmasi -> upload -> bentrok
                     (kind baru Fase 2: "simulasi", "harga";
                      kind baru Fase 3: "siklus")
    sim.py           handler Fase 2: simulasi/harga/stok/jadwal/perencana
    tiers.py         handler Fase 3: /tier, /otomatis, /laporan, /bandingkan
                     + callback tier/otomatis/login/laporan
  core/
    cloud.py         Supabase: refresh, akun_ambil, akun_simpan
                     (Fase 3: fetch_papan / fetch_papan_adu — anonim)
    save.py          paket "1:"+base64(gzip(JSON)), sidik, edit save
    store.py         SQLite + Fernet, validasi akun.json, tabel jadwal
                     (Fase 3: kolom tier/otomatis/batas_harian/jam_otomatis
                     + tabel audit_log, login_lacak, peringkat)
                     (Fase 4: kolom baca_saja + get/set_baca_saja)
    sim.py           mesin simulasi 1 hari game (seed-able)
    plan.py          kapan_naik, roi_upgrade, whatif, harga_terbaik
    jobs.py          APScheduler: laporan harian per chat (WIB)
                     (Fase 3: siklus otomatis harian + pengingat login
                     + cek peringkat)
                     (Fase 4: sinkronkan_semua + atur_sinkronisasi)
    tiers.py         definisi tier + require_tier (TierError)
    auto.py          aksi otomatis murni: login, beli stok, harga pasar/
                     dinamis, sewa/zakat/motor, isi tugas, jalankan_siklus
    papan.py         parse papan peringkat (hanya baca; tanpa kirim skor)
  data/              barang.json, tugas.json, pelanggan.json,
                     upgrade.json, cerita.json, event.json
                     (salinan asset pack game, SHA-256 terverifikasi)
miniapp/             (Fase 4) Vite + React 18 + TS + @telegram-apps/telegram-ui
  src/tg.ts          init SDK, initData, haptics, showPopup, MainButton
  src/api.ts         klien /api/* (header X-Telegram-Init-Data)
  src/utils.ts       format rupiah/progres (vitest)
  src/App.tsx        AppRoot + Tabbar (Beranda/Tugas/Simulasi/Pengaturan)
  src/pages/         Beranda, Tugas, Simulasi (+ Harga & Stok), Pengaturan
systemd/             warung-bot.service + warung-bot-api.service (Fase 4)
```

Alur tulis: konfirmasi → `akun_ambil` (paket terbaru) → terapkan edit ke
paket terbaru → cadangkan paket lama → `akun_simpan` dengan `p_versi_dasar`
terbaru → simpan versi/sidik baru. Bentrok → upload ditahan, pengguna
memilih [Pakai Simpanan Online] atau [Timpa dengan Punya Saya].

## Grounding — sumber yang dipakai

Semua format RPC/paket/save diverifikasi dari kode hasil decompile GDRE
(`gdre-recovered/scripts/`), bukan ditebak:

- `akun_online.gd`: `URL_SUPABASE`, `KUNCI_PUBLIK`, `_pastikan_token()`
  (refresh bila sisa < 90 dtk; 400/401 → sesi dihapus), `_rpc()` (header
  apikey + Bearer; timeout 20/40 dtk), `kirim()` (payload `akun_simpan`,
  `bentrok` + auto-pulih), `pakai_cloud()` (`akun_ambil`), `_sidik()`,
  `kemajuan_hp()`, `selesaikan_tautan()` (`akun_status`).
- `game_state.gd`: `_paket_pindah()` / `paket_cloud()` / `_buka_paket_pindah()`
  (format `"1:" + base64(gzip(JSON))`, batas dekompresi 20 MB),
  `simpan()` (field slot + JSON indent TAB), `info_slot()` (level =
  tingkat+1, qris = saldo_digital), `_cek_tugas()` + `target_inti` /
  `target_khusus` / `target_bintang` / `syarat_upgrade_beres`,
  `JUMLAH_SLOT = 6`.
- `FORMAT_API.md` (§7–§8, termasuk koreksi dari request asli 24 Nov 2026)
  dan `RANCANGAN_BOT_TELE.md` (§1–§12, §15 UI/UX revisi).

## Grounding Fase 2 — rumus simulasi (kode game menang)

Mesin simulasi (`core/sim.py`, docstring per fungsi mencantumkan nomor
baris sumber) digrounding ke `game_state.gd` + `layanan.gd` hasil decompile
GDRE, bukan ke dokumen:

- **Jendela jualan 09:00–17:00** (`JAM_BUKA`, `JAM_WAJIB_TUTUP`), **Jumat
  libur** (`HARI_LIBUR`), Ramadan hari 55–84, hari 1 = Senin.
- **Kedatangan dalam DETIK NYATA** (`layanan.gd` `_process(delta)`); jam
  game maju `delta × 1,52`. Interval `randf(5,11) × 1,4 × pengali_jam ×
  keramaian × ramai_upgrade × ramai_promosi × ramai_murah × …`; pelanggan
  pertama setelah 1,5–3,5 detik.
- **Harga:** `harga_modal = bulat(modal × pengali / 100) × 100` (pengali =
  supplier × (1+efek upgrade) × 1,1 bila agen × (1−diskon promo));
  `langkah_harga` dari harga katalog (<10rb → 100, ≥10rb → 500);
  `batas = max(normal×1,3 ke kelipatan langkah, pasar)`;
  `lantai = min(max(modal, harga_modal)+100, pasar)`.
- **Harga murah:** `efek = rata-rata max(0, 1 − harga_jual/harga_pasar)`
  (dibatasi 0,2) → interval × `1/(1+efek×1,5)` (maks +30% ramai).
- **Reputasi bintang HANYA mengubah interval** kedatangan (3★ ×0,95,
  4★ ×0,9, 5★ ×0,85) — tidak memengaruhi sabar/beli/tip/kurir.
- **Pesanan:** panjang 4–7 jenis (Lv≥2, peluang ≤10%), biasa multi 2–3
  jenis; jumlah per jenis 1 (65%)/2 (27%)/3 (8%); `barang_acak` berbobot
  `peluang_barang × suka` (suka 0 = tak pernah pesan); `jam_laris`,
  Ramadan/takjil, borong takjil 30% (Ramadan ≥15.00).
- **Kesabaran:** antre `sabar_antre_dasar × pengali_sabar`; depan
  `batas_respon × pengali_sabar`; antre diperlambat bila ramai.
- **QRIS:** per pelanggan, upgrade qris + `rand < 0,35`, bukan tipe anak.
- **Energi:** 0,039/menit siang, 0,099/menit malam; istirahat otomatis
  bot +30 (ngopi/makan, 1×/hari/jenis).
- **Tutup hari:** biaya 10rb casual / 20rb hard + biaya upgrade;
  sewa tiap Minggu dari `cerita.json` (100rb–500rb per level), bayar dari
  QRIS dulu lalu uang; kurang → `minggu_tunggak += 1`; diusir bila ≥3.
- **Tugas:** `faktor_macet` (casual, mulai hari ke-45 di level),
  `faktor_keringanan` (5 hari setelah inti beres), target omzet dibulatkan
  ke ribuan; naik level = hadiah + buka barang + reset progres.

**Yang TIDAK disimulasikan** (dinyatakan di setiap pesan hasil):
ulasan/reputasi dinamis (bintang ditahan dari save), cuaca & event acak,
hutang pelanggan, minigame tip/QRIS, titipan sales, grosir, jelajah,
kerja sampingan, cerita/misi (uang misi tidak dibayar di sim), harga
pasar Senin (ditahan dari save), sakit, palak/pencurian. Waktu layani
bot tetap 2,0 detik/pelanggan (parameter `LAYANI_DETIK`).

## Grounding Fase 3 — otomatisasi (kode game menang)

- **Login harian — TIDAK BISA auto-klaim lewat cloud** (koreksi terhadap
  RANCANGAN §13). State login (`login_hari_ke`, `login_tanggal`,
  `login_siklus`, `bebas_iklan_dari/sampai`) tinggal di `pengaturan.cfg`
  lokal HP, bukan di paket cloud, dan divalidasi HMAC `tanda`
  (`game_state.gd:4257-4263`; tanda tidak sah → reset ke 0 + peringatan
  "Catatan kalender hadiah tidak sah, diulang dari awal"). Bot hanya
  MENGINGATKAN + mencatat klaim yang dikonfirmasi pengguna (tombol
  [Sudah Klaim]). Hadiah dari `login_harian.gd:138`: 30 hari, Rp15.000/
  hari; milestone hari 4→100rb, 8→150rb, 12→200rb, 16→250rb, 20→300rb,
  24→350rb, 26→bebas iklan 1 hari (atau Rp100.000 bila sudah bebas iklan),
  28→400rb, 30→"Baju Kaos & sarung" (atau Rp500.000 bila sudah punya).
  Hari terlewat TIDAK mereset dan TIDAK mengejar ketinggalan
  (`hari_berikut()` = hari_ke+1). Kalender 30 hari SEKALI jalan — setelah
  hari ke-30, `hari_berikut()` selalu 0 dan UI menampilkan "selesai";
  `login_siklus` hanya naik dan dipakai di HMAC.
- **Sewa** (`game_state.gd:6238-6448`): `sewa_per_minggu()` dari
  `cerita.json` `per_minggu` [100rb, 100rb, 200rb, 200rb, 300rb, 300rb,
  400rb, 400rb, 500rb, 500rb] menurut tingkat (clamp) + kunci mingguan
  (`sewa_kunci`); jatuh tempo tiap `hari % 7 == 0`; `tagihan_sewa()` =
  sisa minggu ini + tunggakan; `_bayar_sewa()` tarik QRIS dulu bila tunai
  kurang, bayar `clamp(uang, 0, tagihan)`, set `sewa_selesai_hari` /
  `sewa_dibayar_hari`; `cicil_sewa()` bayar di muka (tunggakan dulu,
  sisa jadi `sewa_cicil`). **Denda sewa efektif 0** (`MAKS_DENDA_SEWA =
  0`, `game_state.gd:6330`) — risiko nyata adalah DIUSIR setelah 3 minggu
  (`MINGGU_DIUSIR = 3`).
- **"Auto-bayar hutang" TIDAK ADA.** Hutang di game = uang yang
  DIPINJAMKAN pemain ke warga (`kasih_hutang()`, `game_state.gd:5375`;
  entri `{tipe, nama, jumlah, hari, tempo: hari+randi(1,2), tak_bayar,
  status: "belum"}`) — pemain adalah kreditur, NPC membayar sendiri
  sesuai jadwal. Bot hanya MELAPORKAN hutang aktif di `/laporan`.
- **Zakat** (`game_state.gd`): `boleh_zakat()` = belum dibayar dan hari
  81–84 (`HARI_ZAKAT=81`, `HARI_LEBARAN=85`); `ZAKAT_FITRAH = 45000`,
  dari tunai saja; terlewat sampai Lebaran → game menandai lunas +
  ulasan 2 bintang.
- **Cicilan motor** (`game_state.gd:1356`): bayar = min(angsuran, sisa),
  tunai saja; tempo berikut = +30 hari (lewati Jumat); telat → debt
  collector bisa datang dan menyita motor. Harga 12.000.000, DP
  2.000.000, tenor 10, `MOTOR_HARI_BULAN = 30`.
- **Auto-beli stok** = `beli_stok()` (`game_state.gd:2393`): etalase wajib
  bila `wajib_etalase`; barang harus terbuka; bukan titipan sales
  (`SALES_TITIPAN = {roti, jamu}`); jumlah ≤ sisa muat
  (`MAKS_STOK_BARANG = 100` − stok − kiriman − tas_grosir); biaya =
  `harga_modal` × n, uang dipotong langsung, stok masuk `kiriman_stok`
  (bukan instan — game memulai ulang timer kirim saat load;
  reguler ~30 dtk, cepat 20 dtk, instan 1 dtk; `DURASI_KIRIM = 30.0`).
  Bot: beli bila stok+kiriman+grosir < 5, sampai 20; tidak pernah
  membiarkan uang di bawah Rp50.000 sesudah beli, dan mencadangkan
  tagihan sewa bila jatuh tempo dalam 7 hari.
- **Auto-harga** membaca `harga_pasaran` DARI SAVE (diacak lokal tiap
  Senin oleh `_perbarui_pasaran()`, 3–5 barang ±5–20%, meluruh ke 1.0);
  bot tidak pernah mengarang harga pasar. Memakai helper `sim.py`
  (`harga_pasar`, `harga_jual`, `lantai_harga`, `batas_harga_jual`,
  `langkah_harga`, `harga_modal`); agen aktif dari level 2
  (`LEVEL_AGEN = 2`); bila harga baru = harga katalog, entri khusus
  dihapus (seperti `ubah_harga_jual()`).
- **Papan peringkat** (`papan_online.gd`, `papan_peringkat.gd`): ambil =
  `ambil_papan2 {p_jenis, p_id, p_hp}` (anonim, apikey saja, timeout 12
  dtk); baris `[nama, pembeli, kode, bintang, level, omzet, jempol,
  jempol_saya]`; kode = `md5(id_papan)[:12]`; peringkat = posisi
  penyisipan menurut pembeli (atau field server `peringkat` bila ada).
  Jumlah pembeli kumulatif = `total_pembeli` (`game_state.gd:98`).

## Grounding Fase 5 — pemantauan & aksi cepat (kode game menang)

- **Harga pasar.** `harga_pasaran` di save = {id: faktor};
  `_perbarui_pasaran()` (game_state.gd:8904) tiap Senin: entri lama
  meluruh ke 1.0 (`p = 1.0 + (lama - 1.0) * 0.5`, snap 0.05, hapus bila
  |p − 1.0| < 0.01), lalu 3–5 barang acak diubah ±5–20%
  (`PERUBAHAN_PASARAN`, :8829), jepit 0.8–1.25. `harga_pasar()`
  (:8837) = katalog jual × faktor (bulat ke 100), tidak aktif bila agen
  belum aktif (level < 2) atau tidak ada entri. `monitor.py` memakai
  `sim.harga_pasar` yang meniru rumus itu; ambang peringatan 20%
  adalah pilihan bot, bukan game.
- **`/jual` = `jual()`** (game_state.gd:2356): stok −1 / saldo layanan
  −= modal; uang += harga; omzet minggu/bulan += harga (kecuali mode
  latihan); laba += harga − modal; `penjualan_hari[id]` =
  [jumlah, omzet, laba]; progres barang/omzet/khusus; `_cek_tugas()`.
  `alasan_tidak_bisa_jual` (:2335) mensyaratkan warung buka — bot
  SENGAJA tidak mengecek `status_hari`: gate itu untuk main langsung,
  bot mengedit save saat game tertutup (lihat perbedaan #24).
- **`/beli` = `beli_stok()`** (:2393): etalase wajib, harus terbuka,
  bukan titipan (roti/jamu), jumlah ≤ sisa_muat_stok
  (`maks 100 − stok − kiriman − tas_grosir`, :4719), biaya =
  harga_modal × jumlah, uang cukup; `kiriman_stok` += jumlah
  (kurir jalan saat game dibuka — `detik_kiriman` runtime, tidak
  tersimpan); `belanja_hari` += biaya; `catat_transaksi`.
- **`/ngopi` = `istirahat("ngopi")`** (:1547) + `ISTIRAHAT` (:939):
  minuman [sachet, kopi_susu, minuman_energi] (pertama yang ada
  stoknya), +30 energi (`ENERGI_KOPI = 30.0`), maks 1x/hari
  (`MAKS_ISTIRAHAT_HARIAN = 1`), jeda 120 menit, tolak bila energi ≥ 99
  ("masih segar"), tolak saat Ramadan sebelum Maghrib, majukan waktu
  10 menit.
- **`/tutup` = `tutup_hari()`** (:6715) via `sim._tutup_hari`: biaya
  harian, sewa tiap Minggu (`hari % 7 == 0`), riwayat harian, hari + 1,
  energi 100. Diusir bila tunggakan 3 minggu (`MINGGU_DIUSIR = 3`).
- **`catatan_hari` — jendela kemarin.** `simpan()` (:3343) menulis
  `catatan_hari` = penghitung hari BERJALAN. Bila save ditulis tepat
  setelah `tutup_hari` (sebelum simpan berikutnya), isinya masih
  ringkasan kemarin — terdeteksi karena `penjualan_hari` kosong tapi
  catatan berisi angka; bot meresetnya ke penghitung kosong (persis
  yang dilakukan game saat hari baru). `/tutup` memakai `dilayani`/
  `batal` dari `catatan_hari` hanya bila hari ini ada penjualan.
- **`/slot` = `kemajuan_hp()`** (akun_online.gd:623): slot terbaik =
  level tertinggi, seri → hari terbanyak (`_lebih_jauh`).
- **`/statistik`.** `penjualan_hari` = satu-satunya rincian per barang
  (hari ini); `riwayat` = ringkasan per hari (tanpa rincian barang);
  `riwayat_layan` = boolean berhasil/gagal 20 layanan terakhir
  (game_state.gd:2887–2960) — tanpa jenis pelanggan. Karena itu
  pelanggan tersering TIDAK dilaporkan (bukan ditebak).
- **Versi game.** `versi.json` diverifikasi langsung 24 Nov 2026:
  `{"min_kode": 0, "kode_terbaru": 47, "versi_terbaru": "1.1", ...}` —
  tanpa `jeda_server`, dan ketinggalan dari game (49/1.2).
- **`/rencana`.** Gabungan `simulate(7 hari)` + `roi_upgrade` +
  `kapan_naik` — tanpa rumus baru. Identitas akuntansi yang diuji:
  uang_akhir = uang_awal + omzet − qris_masuk − isi_layanan_bersih −
  biaya_harian − sewa + hadiah.

## Keputusan: skor adu laris TIDAK dikirim

Bot hanya MEMBACA papan peringkat. Alasannya (dari `papan_online.gd`):

- `kirim_skor5` mengirim angka kumulatif permainan nyata (`total_pembeli`,
  omzet, dsb.) yang ditandatangani HMAC `RAHASIA` — RANCANGAN §9 melarang
  menyimpan `RAHASIA` di repo bot.
- `kirim_adu_laris` butuh `p_hp` (id perangkat analitik — 16 byte hex acak
  yang tersimpan di file konfigurasi lokal HP, bukan di `akun.json` atau
  paket cloud; bot tidak memilikinya), `hasil` (menang/kalah dari
  kompetisi mingguan nyata), dan `rekaman` (catatan harian) — tidak satu
  pun bisa direpresentasikan dengan setia dari simulasi.
- Yang bot lakukan: menaikkan angka save lewat simulasi yang setia;
  **game di HP-lah yang mengirim skor** saat dimainkan. Mengirim skor
  hasil simulasi akan menjadi data palsu di papan peringkat.

## Perbedaan dokumen-vs-kode-sumber (kode sumber menang)

1. **Sidik — RANCANGAN §7 salah.** Dokumen menulis sidik dari SEMUA slot
   1..6. Kode asli (`_sidik()`, akun_online.gd) hanya menghitung slot yang
   ADA (`if GameState.ada_slot(n)`), dan bagian flag adalah
   `"%s%s%s%d" % [tanpa_iklan, pendukung, kode_pendukung, len(baju)]`
   dengan bool Godot dirender `"true"`/`"false"`. Implementasi di
   `core/save.py:compute_sidik` mengikuti kode, bukan dokumen.
2. **Paket `toko` — RANCANGAN §7 tidak lengkap.** Dokumen menulis 3 field;
   kode asli punya 5: `tanpa_iklan`, `pendukung`, `kode_pendukung`,
   `dukungan_iklan_dicek`, `kode_iklan`. Bot mempertahankan paket apa adanya
   (hanya mengganti slot yang diedit + `dibuat`), jadi field ekstra tidak hilang.
3. **`/tugas_selesai` TIDAK menjamin hadiah cair — RANCANGAN §5 terlalu
   optimistis.** `_cek_tugas()` juga mensyaratkan `syarat_upgrade_beres`
   (punya ≥1 dari `t["upgrade"]` — Level 2–10 SEMUA punya syarat upgrade
   di tugas.json saat ini) dan `agus_beres` (`misi_status` "" atau "lunas",
   atau `cerita_tamat`). Bot mengisi progres sampai target mentah (batas
   atas yang aman — `faktor_macet`/`faktor_keringanan` hanya bisa
   meringankan target) dan menampilkan blocker-nya dengan jujur di layar
   konfirmasi dan kartu tugas.
4. **`bintang` bukan syarat level.** RANCANGAN/LAPORAN lama menyebut bintang
   sebagai syarat; tugas.json saat ini TIDAK punya field `bintang` di level
   mana pun → `target_bintang = 0` → selalu lolos.
5. **Timeout.** `FORMAT_API.md` menulis 12/20/40 dtk; kode: `_http` default
   15, `_rpc` default 20, simpan/ambil 40. Bot memakai 20/40.
6. **Perintah berparameter.** RANCANGAN §5 menulis `/uang <jumlah>`, tapi
   §15 (revisi UI/UX, mengikuti Bot Guidelines) melarang perintah
   berparameter. Fase 1 mengikuti §15: ubah uang lewat tombol + ketik.
7. **Penanganan error RPC.** Game mengembalikan `{}` untuk SEMUA kegagalan
   RPC sehingga tidak bisa membedakan 401 vs gangguan jaringan. Bot sengaja
   membedakan status HTTP (401 → sesi habis; lain → CloudError) agar
   pesannya tepat.
8. **Jendela jualan — RANCANGAN §6 salah.** Dokumen menulis hari
   07.00–26.00 (1.140 menit). Kode: jualan 09.00–17.00 (480 menit),
   Jumat libur, Ramadan 19.00, kios milik 24.00.
9. **`pengali_jam` — UX_RUMUS_TUGAS §4.4 salah di batas.** Dokumen:
   15.30/16.30. Kode (`layanan.gd:2321`): 15.5/17.0.
10. **Rasio harga murah — UX §4.10 salah.** Dokumen membandingkan harga
    jual vs harga *normal*. Kode membandingkan vs harga *pasar*.
11. **Interval kedatangan — LAPORAN §11.4 menyesatkan.** Dokumen menulis
    "~40–70 detik (waktu game)". Kode: interval DETIK NYATA 5–11 ×
    pengali; 40–70 hanya reset saat semua pelanggan kabur.
12. **Lantai harga — dokumen tidak lengkap.** Lantai =
    `min(modal+100, pasar)`, bukan mutlak modal+100 — boleh di bawah
    modal+100 bila pasar lebih rendah.
13. **`jam_laris` ADA di barang.json.** UX §16 menulis belum diekstrak —
    salah; datanya ada dan dipakai sim.
14. **`biaya_hari` bisa `null` di upgrade.json** (etalase, spanduk, bangku,
    kurir_cepat) — `int(None)` crash; sim & plan memakai `or 0`.
15. **APScheduler 3.11: `replace_existing=True` tidak mengganti job bila
    scheduler belum jalan** (duplikat diam-diam, diverifikasi tes).
    `jobs.atur_laporan` menghapus eksplisit dulu (`remove_job` bekerja
    dalam kedua keadaan).
16. **"Auto-klaim login harian" — RANCANGAN §13 tidak bisa dikerjakan
    lewat cloud.** State login ada di `pengaturan.cfg` HP + HMAC, bukan
    di paket cloud. Bot hanya mengingatkan + mencatat konfirmasi pengguna.
17. **"Auto-bayar hutang" — RANCANGAN §13 salah arah.** Hutang = pemain
    meminjamkan ke warga; tidak ada yang bisa dibayar bot. Yang dibayar:
    sewa, zakat, cicilan motor. Hutang aktif hanya dilaporkan.
18. **"Sebelum denda" — RANCANGAN §13 menyesatkan.** Denda sewa efektif
    0; risiko nyata adalah diusir setelah 3 minggu menunggak.
19. **`/otomatis on|off` — brief Fase 3 menulis parameter, §15 melarang.**
    Fase 3 mengikuti §15: `/otomatis` menampilkan tombol
    [Nyalakan]/[Matikan], tanpa parameter.
20. **`hadiah(n)` di luar tabel kembali ke uang harian** (bukan 0).
    Game tidak pernah memanggilnya untuk n>30 — `login_berikut()`
    mengembalikan None setelah hari ke-30.
21. **Bug `nama_tier(None)` diperbaiki saat Fase 3** — `int(None)` di
    `TIER_NAMA.get(...)` melempar TypeError tepat di jalur penolakan
    (tier rusak di DB). Sekarang memakai `tier_valid()` yang toleran.
22. **`/rollback <tanggal>` — brief Fase 5 menulis parameter, §15
    melarang.** Fase 5 mengikuti §15: tanggal dipilih lewat tombol
    [Pulihkan tanggal] di `/backup`, lalu konfirmasi 2 langkah.
23. **Pelanggan tersering TIDAK ADA di save.** Brief Fase 5 meminta
    dari `riwayat_layan` — isinya hanya boolean berhasil/gagal
    (game_state.gd:2887). `/statistik` melaporkan None + alasan, bukan
    menebak. Begitu pula barang terlaris sepanjang waktu: rincian per
    barang hanya ada untuk hari ini (`penjualan_hari`).
24. **`/jual` tidak mengecek `status_hari`.** `alasan_tidak_bisa_jual`
    menolak bila warung tutup — tapi itu gate main langsung. Bot
    mengedit save saat game tertutup; memeriksa status save terakhir
    (yang bisa "tutup" karena game ditutup malam hari) akan membuat
    /jual hampir tidak pernah bisa dipakai. Akuntansi `jual()`-nya
    tetap ditiru penuh.
25. **Ejaan "mi" vs "mie".** Nama game "Mie goreng", ketikan umum
    "mi goreng". `cepat.cari_barang` menyamakan kata "mie" → "mi"
    saat membandingkan (juga berlaku untuk nama/sebutan lain).
26. **Mode baca saja di bot chat (Fase 5).** Sebelum Fase 5, mode baca
    saja hanya ditegakkan API Mini App. Sejak Fase 5, aksi cepat +
    rollback di chat juga menolak bila mode aktif.
27. **Notifikasi pasar Senin tidak tepat waktu.** Pasaran baru hanya
    ada di save setelah game dimainkan hari Senin; job Senin 07.00
    mengabari saat bot pertama kali MELIHAT perubahan, bukan saat
    game mengubahnya.

## Yang belum bisa dites (tanpa kredensial/token asli)

- Panggilan live ke Supabase (`akun_ambil`/`akun_simpan`/refresh) — semua
  dites dengan `httpx.MockTransport`.
- Alur Telegram live (kirim file, tombol, polling) — hanya dites
  wiring-nya (`build_application` + pendaftaran handler).
- Apakah server menerima paket hasil edit bot (validasi isi save di server
  tidak terlihat di kode klien; sejauh ini server hanya menyimpan string).
- Apakah layar pilih simpanan di game selalu muncul setelah bot upload.
- Respons persis `akun_simpan` untuk gagal non-bentrok (nilai `alasan`
  lain selain `"bentrok"` belum dipetakan — lihat RANCANGAN §16).
- **Simulasi vs game asli.** Sim dites deterministik + rekonsiliasi
  akuntansi, tapi belum pernah dibandingkan head-to-head dengan satu hari
  main sungguhan di HP (butuh save sebelum/sesudah main + catat omzet
  game). Angka sim adalah proyeksi — jangan diklaim "akurat seperti game".
- Laporan harian live (job APScheduler + kirim pesan ke chat asli) dan
  alur tombol Fase 2 di Telegram live — hanya dites dengan mock/fake.
- Apakah server menerima paket hasil edit simulasi/harga (sama seperti
  Fase 1: server sejauh ini hanya menyimpan string).
- Siklus otomatis live (job `otomatis:<chat_id>` + pengingat login +
  cek peringkat + laporan siklus ke chat asli) — hanya dites dengan
  mock/fake; perilaku `ambil_papan2` dengan `p_hp: ""` belum
  dikonfirmasi terhadap server live (server bisa menolak tanpa id
  perangkat yang valid).
- Apakah pengingat login harian sampai tepat waktu di chat asli dan
  apakah pengguna menekan [Sudah Klaim] secara konsisten — streak yang
  dilacak bot hanya seakurat konfirmasi pengguna.
- **Mini App live (Fase 4).** Build + API + validasi initData dites
  (mock + smoke test proses asli: `/api/health` 200, `/` 200,
  `/api/status` tanpa header 401), tapi Mini App belum pernah dibuka di
  Telegram sungguhan: butuh domain HTTPS + URL di BotFather + token bot
  asli. Perilaku MainButton/BackButton/showPopup/HapticFeedback di klien
  Telegram asli belum terverifikasi; `expandViewport` dan safe area di
  perangkat nyata belum dilihat. Tes komponen React (selain util) belum
  ada — hanya `npm run build` + `typecheck` + vitest util.
- **Sinkronisasi jadwal live.** `sinkronkan_semua` dites dengan scheduler
  di memori; bahwa perubahan pengaturan dari Mini App benar-benar
  diterapkan bot polling yang sedang jalan (dua proses, satu file DB)
  belum diuji end-to-end — butuh kedua proses jalan bersamaan.
- **Fase 5 live.** Job pemantauan global (pasar Senin, cek versi, backup
  harian, adu laris Jumat) dites dengan mock/fake; belum pernah jalan
  terjadwal di bot asli — butuh BOT_TOKEN + akun tertaut + waktu
  (Senin/Jumat) berlalu. Notifikasi pasar juga bergantung pada game
  yang dimainkan hari Senin (pasaran baru hanya ada di save setelah itu).
- **Rollback live.** Alur 2 langkah + upload arsip dites dengan cloud
  mock; belum pernah memulihkan arsip sungguhan ke Supabase live, dan
  belum dikonfirmasi game menampilkan pilih simpanan setelah rollback.
- **Aksi cepat live.** `/jual`, `/beli`, `/ngopi`, `/tutup` dites pada
  slot contoh; belum pernah diterapkan ke save sungguhan lalu dibuka di
  game (mis. apakah kurir benar mengantar `kiriman_stok` bot, apakah
  `_cek_tugas` di game membayar hadiah yang sama seperti `_cek_tugas`
  bot).

## Batasan & keputusan yang perlu diketahui

- **Satu penulis.** Bot hanya boleh menulis saat game tertutup. Bot tidak
  bisa mendeteksi game sedang jalan — ia hanya bisa melihat versi cloud.
  Bila game mengunggah di antara bot mengambil dan bot mengunggah, server
  menjawab bentrok dan bot berhenti.
- **Slot yang tidak disentuh dipertahankan byte-for-byte** di paket, agar
  sidik yang dihitung game setelah mengunduh tetap cocok. Hanya slot yang
  diedit yang di-serialisasi ulang (JSON indent TAB seperti game).
- **Token hasil refresh ikut exception** (`CloudError.session`): refresh
  token di-rotasi server, jadi bila refresh terjadi lalu RPC berikutnya
  gagal, sesi baru tetap disimpan — kalau dibuang, akun terkunci sampai
  `/link` ulang.
- **Koneksi langsung, tanpa proxy env.** `SupabaseClient` dan klien PTB
  dibuat dengan `trust_env=False`: proxy env host tidak dipakai. Alasan:
  httpx gagal total saat konstruksi bila `no_proxy` berisi entri IPv6
  `"[::1]"` (teramati di VM ini). Bila VPS butuh proxy, atur eksplisit.
- **Uang 0** diizinkan di lapis core (bangkrut = keadaan sah di game),
  tapi input ketik di chat menolak 0 sebagai kemungkinan salah ketik.
- **`/upload_paksa` mandiri** hanya bermakna setelah ada upload yang
  ditolak bentrok; tanpa pending, bot menjelaskan cara pakainya.
- **Siklus otomatis tidak bisa tahu game sedang tertutup.** Bot hanya
  bisa melihat versi cloud. Bila game terbuka dan mengunggah di tengah
  siklus, siklus dibatalkan (atau bentrok → otomatisasi dimatikan).
  **Otomatisasi bukan "aman seperti main sendiri"** — ia mengedit save
  dan mengunggah tanpa game berjalan; risiko tertimpa tetap ada bila
  pengguna membuka game di saat yang sama.
- **Login harian tidak diklaim bot** — pengingat saja; klaim tetap di
  game. Bila pengguna tidak menekan [Sudah Klaim], streak bot tertinggal
  dari game.
- **Skor adu laris tidak dikirim** — hanya dibaca. Lihat "Keputusan:
  skor adu laris tidak dikirim" di atas.
- **Batas harian Rp1.000.000 adalah pilihan bot**, bukan aturan game.
  Ubah per chat dengan `store.set_batas_harian(chat_id, n)` (belum ada
  perintah chat untuk ini).
- **`/link` memakai `akun_ambil` sebagai uji**, bukan `akun_status`
  (sesuai penugasan; `akun_status` dipakai game saat `selesaikan_tautan`).
- **Mini App dua proses.** Bot polling dan API adalah proses terpisah
  dengan koneksi sqlite masing-masing; jangan jalankan API di thread yang
  sama dengan bot (akan `sqlite3.ProgrammingError`). Perubahan pengaturan
  dari Mini App berlaku paling lambat 10 menit (sinkronisasi jadwal).
  Pending simulasi disimpan di memori proses API saja — restart API
  membuat `sim_id` lama kedaluwarsa (410), jalankan simulasi ulang.
- **Mini App butuh HTTPS.** Telegram menolak URL http; tanpa domain/TLS
  (atau Cloudflare Tunnel untuk pengujian), dashboard tidak bisa dibuka
  dari Telegram walau kode + build sudah siap.
- Token bot, FERNET_KEY, dan token akun tidak pernah ditulis ke log/chat.
