#!/usr/bin/env bash
# One-shot server setup for the swing-lock stack on Ubuntu 24.04 (run as root).
# cloud-init (deploy/cloud-init.yaml) clones the repo to /opt/swinglock and runs this; it is safe to
# re-run by hand: sudo bash /opt/swinglock/deploy/bootstrap.sh
#
# Steps: swap -> Docker Engine + compose (Docker's apt repo) -> data/ + positions -> systemd unit +
# logrotate -> Tailscale (auth key from /root/tailscale-authkey, then deleted) + `tailscale serve`
# -> ufw -> start the stack. Public SSH is closed only once Tailscale is up, so a failed join never locks you out.
#
# Env switches (for testing in a container): SKIP_SYSTEMD=1, SKIP_TAILSCALE=1, SKIP_UFW=1.
# Read-only stack: nothing here or in the services places orders.
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/swinglock}
AUTHKEY_FILE=${AUTHKEY_FILE:-/root/tailscale-authkey}
TS_HOSTNAME=${TS_HOSTNAME:-tennis-scanner}
LOG=/var/log/swinglock-bootstrap.log
exec > >(tee -a "$LOG") 2>&1
step() { echo; echo "=== $(date -u +%FT%TZ) $*"; }
export DEBIAN_FRONTEND=noninteractive

step "swap (1 GB)"
if ! swapon --show | grep -q /swapfile && [ ! -f /swapfile ]; then
  if fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile; then
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  else
    echo "WARN: could not enable swap (fine inside a container)"; rm -f /swapfile
  fi
else
  echo "swap already set up"
fi

step "base packages"
apt-get update -q
apt-get install -y -q ca-certificates curl git logrotate ufw

step "Docker Engine + compose plugin (download.docker.com)"
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
docker --version; docker compose version

step "code and data in $APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone --depth 1 https://github.com/phat-d0/Tennis_Model.git "$APP_DIR"
fi
cd "$APP_DIR"
mkdir -p data/live
[ -f data/positions.json ] || cp positions.example.json data/positions.json
chown -R 1000:1000 data          # containers run as uid 1000

step "systemd unit + logrotate"
install -m 0644 deploy/logrotate/swinglock /etc/logrotate.d/swinglock
install -m 0644 deploy/systemd/swinglock.service /etc/systemd/system/swinglock.service
if [ "${SKIP_SYSTEMD:-0}" = 1 ]; then
  echo "SKIP_SYSTEMD=1: not enabling the unit"
else
  systemctl daemon-reload
  systemctl enable --now docker
  systemctl enable swinglock      # started at the end, after Tailscale is up
fi

TS_UP=0
step "Tailscale"
if [ "${SKIP_TAILSCALE:-0}" = 1 ]; then
  echo "SKIP_TAILSCALE=1"
else
  if ! command -v tailscale >/dev/null; then
    . /etc/os-release
    curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/${VERSION_CODENAME}.noarmor.gpg" \
      -o /usr/share/keyrings/tailscale-archive-keyring.gpg
    curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/${VERSION_CODENAME}.tailscale-keyring.list" \
      -o /etc/apt/sources.list.d/tailscale.list
    apt-get update -q && apt-get install -y -q tailscale
  fi
  systemctl enable --now tailscaled
  KEY=$(tr -d '[:space:]' < "$AUTHKEY_FILE" 2>/dev/null || true)
  if tailscale status >/dev/null 2>&1; then
    echo "already on the tailnet"; TS_UP=1
  elif [ -z "$KEY" ] || [ "$KEY" = TS_AUTHKEY ]; then
    echo "WARN: no Tailscale auth key in $AUTHKEY_FILE (placeholder not replaced)."
    echo "      Join by hand: tailscale up --hostname=$TS_HOSTNAME --ssh"
  elif tailscale up --authkey="$KEY" --hostname="$TS_HOSTNAME" --ssh; then
    TS_UP=1
  else
    echo "WARN: tailscale up failed (expired or used key?). Public SSH stays open."
  fi
  shred -u "$AUTHKEY_FILE" 2>/dev/null || rm -f "$AUTHKEY_FILE"
  if [ "$TS_UP" = 1 ]; then
    # HTTPS on https://<host>.<tailnet>.ts.net -> the dashboard on 127.0.0.1:8000 (tailnet only).
    tailscale serve --bg 8000 || echo "WARN: tailscale serve failed: enable HTTPS certificates in the Tailscale admin (DNS page), then run: tailscale serve --bg 8000"
    tailscale serve status || true
  fi
fi

step "firewall (ufw)"
if [ "${SKIP_UFW:-0}" = 1 ]; then
  echo "SKIP_UFW=1"
else
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow in on tailscale0
  ufw allow 41641/udp comment 'tailscale direct connections'
  if [ "$TS_UP" = 1 ]; then
    ufw delete allow OpenSSH >/dev/null 2>&1 || true
    echo "public SSH closed: use Tailscale SSH or the Hetzner web console"
  else
    ufw allow OpenSSH
    echo "Tailscale not up: public SSH (22) left open"
  fi
  ufw --force enable
  ufw status verbose
fi

step "start the stack (first run builds the image: a few minutes on a small VPS)"
if [ "${SKIP_SYSTEMD:-0}" = 1 ]; then
  echo "SKIP_SYSTEMD=1: start by hand with COMPOSE_PROFILES=recorder docker compose -f deploy/docker-compose.yml up -d --build"
else
  systemctl restart swinglock
  docker compose -f deploy/docker-compose.yml ps
fi

step "done. Dashboard (tailnet only): https://$TS_HOSTNAME.<your-tailnet>.ts.net  Log: $LOG"
