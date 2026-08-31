#!/usr/bin/env bash
# One-command setup for Linux and Raspberry Pi.
#
#   bash install.sh
#
# Installs Docker if it is missing, writes a config with a fresh secret,
# builds the app, starts it, and prints the address to open. Safe to re-run.

set -euo pipefail
cd "$(dirname "$0")"

green() { printf '\033[0;32m%s\033[0m\n' "$1"; }
warn()  { printf '\033[0;33m%s\033[0m\n' "$1"; }
fail()  { printf '\033[0;31m%s\033[0m\n' "$1"; exit 1; }
step()  { printf '\n\033[1m%s\033[0m\n' "$1"; }

echo
echo "  Shelf Plan setup"
echo "  ================"

# ---- 1. sanity ------------------------------------------------------------
step "Checking this machine"

ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|aarch64|arm64) green "  Architecture $ARCH is supported." ;;
    armv6l|armv7l)
        fail "  This is a 32-bit ARM system ($ARCH).
  Shelf Plan needs 64-bit. On a Raspberry Pi, reflash with the 64-bit
  Raspberry Pi OS and run this again. A Pi 3 or newer can do this;
  a Pi Zero or Pi 1 cannot." ;;
    *) warn "  Unrecognised architecture $ARCH -- carrying on, but it may not build." ;;
esac

MEM_MB=$(( $(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}' || echo 2000000) / 1024 ))
if [ "$MEM_MB" -lt 900 ]; then
    warn "  Only ${MEM_MB} MB of RAM. The build may run out of memory."
    warn "  If it fails, add swap:  sudo dphys-swapfile swapoff && \\"
    warn "    sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile && \\"
    warn "    sudo dphys-swapfile setup && sudo dphys-swapfile swapon"
else
    green "  ${MEM_MB} MB of RAM is enough."
fi

# ---- 2. docker ------------------------------------------------------------
step "Checking Docker"

if command -v docker >/dev/null 2>&1; then
    green "  Docker is already installed."
else
    warn "  Docker is not installed. Installing it now (a few minutes)."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    green "  Docker installed."
    echo
    warn "  IMPORTANT: log out and back in, then run this script again."
    warn "  Your user was just added to the 'docker' group, and that only"
    warn "  takes effect on a new login."
    exit 0
fi

if ! docker info >/dev/null 2>&1; then
    if sudo -n true 2>/dev/null; then sudo systemctl start docker || true; fi
    sleep 3
fi
docker info >/dev/null 2>&1 || fail "  Docker is installed but not running.
  Try:  sudo systemctl start docker
  If it says permission denied, log out and back in first."
green "  Docker is running."

# ---- 3. settings ----------------------------------------------------------
step "Setting up configuration"

if [ ! -f .env ]; then
    [ -f .env.example ] && cp .env.example .env || touch .env
    green "  Created .env"
fi

set_default() {
    local key="$1" value="$2"
    if grep -qE "^${key}=.+" .env; then return; fi
    grep -vE "^${key}=" .env > .env.tmp 2>/dev/null || true
    mv .env.tmp .env
    printf '%s=%s\n' "$key" "$value" >> .env
    echo "  set $key"
}

if ! grep -qE '^SESSION_SECRET=.+' .env; then
    SECRET="$(openssl rand -base64 48 2>/dev/null || head -c 36 /dev/urandom | base64)"
    set_default SESSION_SECRET "$SECRET"
    green "  Generated a login secret."
fi
set_default SHELFPLAN_PORT 8000
set_default COOKIE_SECURE 0
set_default SIGNUP_MODE open
set_default DATABASE_URL "sqlite:////app/data/shelfplan.db"

# ---- 4. build -------------------------------------------------------------
step "Building and starting"
echo "  The first build takes 15-40 minutes on a Raspberry Pi."
echo "  It is compiling for ARM. Leave it running."
echo

if docker compose version >/dev/null 2>&1; then
    docker compose up -d --build
else
    docker-compose up -d --build
fi

# ---- 5. wait and report ---------------------------------------------------
step "Waiting for it to answer"
PORT="$(grep -E '^SHELFPLAN_PORT=' .env | cut -d= -f2 || echo 8000)"
for _ in $(seq 1 40); do
    if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
        break
    fi
    sleep 3
done

if ! curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    fail "  It built but is not answering. See what happened with:
    docker compose logs"
fi

echo
green "  Shelf Plan is running."
echo
echo "  Open it at:"
echo "    http://localhost:${PORT}"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -n "${IP:-}" ] && echo "    http://${IP}:${PORT}      (from other devices at home)"
if command -v tailscale >/dev/null 2>&1; then
    TS="$(tailscale status --json 2>/dev/null | grep -o '"DNSName":"[^"]*"' | head -1 | cut -d'"' -f4 || true)"
    [ -n "${TS:-}" ] && echo "    http://${TS%.}:${PORT}   (from anywhere, over Tailscale)"
else
    echo
    echo "  To reach it from outside the house, install Tailscale:"
    echo "    curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up"
fi
echo
echo "  From now on:  ./shelfplan.sh start | stop | status | logs | backup"
echo "  It also starts itself whenever this machine boots."
echo
