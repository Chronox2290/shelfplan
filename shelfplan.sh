#!/usr/bin/env bash
# Start, stop and look after Shelf Plan on Linux -- including a Raspberry Pi.
#
#   ./shelfplan.sh start | stop | restart | status | logs | update | backup

set -euo pipefail
cd "$(dirname "$0")"

port() {
    grep -E '^SHELFPLAN_PORT=' .env 2>/dev/null | cut -d= -f2 || echo 8000
}

compose() {
    if docker compose version >/dev/null 2>&1; then
        docker compose "$@"
    else
        docker-compose "$@"
    fi
}

case "${1:-help}" in
  start)
    compose up -d
    sleep 5
    P="$(port)"
    echo
    echo "Shelf Plan is running."
    echo "  On this machine: http://localhost:${P}"
    IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    [ -n "${IP:-}" ] && echo "  On your network: http://${IP}:${P}"
    if command -v tailscale >/dev/null 2>&1; then
        TS="$(tailscale status --json 2>/dev/null | grep -o '"DNSName":"[^"]*"' | head -1 | cut -d'"' -f4 || true)"
        [ -n "${TS:-}" ] && echo "  Over Tailscale:  http://${TS%.}:${P}"
    fi
    ;;
  stop)
    compose down
    echo "Stopped. Your data is kept."
    ;;
  restart) compose restart; echo "Restarted." ;;
  status)
    compose ps
    curl -fsS "http://127.0.0.1:$(port)/api/health" && echo || echo "Not responding yet."
    ;;
  logs)
    echo "Ctrl+C to stop watching. Reset links appear here when email is not set up."
    compose logs -f --tail 60
    ;;
  update)
    compose up -d --build
    echo "Rebuilt and restarted."
    ;;
  backup)
    mkdir -p backups
    F="backups/shelfplan-$(date +%Y-%m-%d-%H%M).db"
    compose cp shelfplan:/app/data/shelfplan.db "$F"
    echo "Saved $F"
    ;;
  *)
    cat <<'EOF'
Shelf Plan

  ./shelfplan.sh start     start it
  ./shelfplan.sh stop      stop it, keeping all data
  ./shelfplan.sh status    is it running?
  ./shelfplan.sh logs      watch the log, including password reset links
  ./shelfplan.sh update    rebuild after code changes
  ./shelfplan.sh backup    copy the database into ./backups/
EOF
    ;;
esac
