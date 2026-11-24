#!/usr/bin/env bash
# Pasang / perbarui service systemd warung-bot + warung-bot-api.
#
# Dipakai saat pertama kali DAN setelah VM di-redeploy: unit di
# /etc/systemd/system tidak selamat dari redeploy, sementara proyek,
# .env, dan database (data/bot.db) selamat karena ada di home.
#
# Yang dilakukan script ini:
#   1. Menulis ulang baris HTTPS_PROXY/HTTP_PROXY di .env dari shell
#      saat ini (kredensial proxy egress BEROTASI tiap VM diganti).
#      BOT_TOKEN/FERNET_KEY/ALLOWED_CHAT_IDS di .env TIDAK disentuh.
#   2. Menyalin unit systemd, daemon-reload, enable + restart.
#
# Jalankan dari shell yang punya proxy env (shell biasa VM ini):
#   bash scripts/install-services.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  echo "ERROR: .env belum ada — salin .env.example ke .env dan isi BOT_TOKEN + FERNET_KEY dulu." >&2
  exit 1
fi

PROXY="${https_proxy:-${HTTPS_PROXY:-}}"
if [ -z "$PROXY" ]; then
  echo "PERINGATAN: tidak ada https_proxy di shell — service jalan tanpa proxy (cocok untuk VPS, TIDAK untuk VM ini)." >&2
else
  python3 - "$PROXY" <<'PYEOF'
import os, sys
proxy = sys.argv[1]
baris = [b for b in open(".env").read().splitlines()
         if not b.startswith(("HTTPS_PROXY=", "HTTP_PROXY="))]
baris += [f"HTTPS_PROXY={proxy}", f"HTTP_PROXY={proxy}"]
open(".env", "w").write("\n".join(baris) + "\n")
print("proxy ditulis ke .env (host:", proxy.split("@")[-1] + ")")
PYEOF
  chmod 600 .env
fi

cp systemd/warung-bot.service systemd/warung-bot-api.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now warung-bot warung-bot-api
systemctl restart warung-bot warung-bot-api
sleep 3
systemctl is-active warung-bot warung-bot-api
echo "OK — bot + API jalan. Cek log: journalctl -u warung-bot -f"
