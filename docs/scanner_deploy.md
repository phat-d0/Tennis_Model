# Deploying the scanner on a small VPS

Everything runs from one Docker image under `docker compose`, started at boot by a systemd unit.
Nothing here places orders. Files are in `deploy/`:

| File | What it does |
|---|---|
| `deploy/Dockerfile` | One image for every service (Python 3.13-slim, deps from `pyproject.toml`, runs as uid 1000) |
| `deploy/docker-compose.yml` | `scanner`, `dashboard`, plus opt-in `recorder` and `caddy` profiles |
| `deploy/env.example` | Template for `deploy/.env` (gitignored): secrets and options |
| `deploy/systemd/swinglock.service` | Starts the stack at boot; `systemctl restart swinglock` rebuilds and restarts it |
| `deploy/logrotate/swinglock` | Weekly rotation of `data/*.log` (`alerts.log`), 12 kept, compressed |
| `deploy/caddy/Caddyfile` | Optional HTTPS + basic-auth front for the dashboard |

## Services

| Service | Command | On by default | Notes |
|---|---|---|---|
| `scanner` | `python -m swinglock.scanner --positions data/positions.json` | yes | Writes `data/live/state.json` and `data/alerts.log` |
| `dashboard` | `python -m swinglock.dashboard --state data/live/state.json --host 0.0.0.0` | yes | Published on **127.0.0.1:8000 only**; mounts `data/` read-only |
| `recorder` | `python -m swinglock.collectors.recorder` | no (`--profile recorder`) | Placeholder for Data's order-book recorder, which doesn't exist yet. Enabling it before then just crash-loops |
| `caddy` | Caddy 2.8 reverse proxy | no (`--profile public`) | Use it only if you want the dashboard on the internet: HTTPS plus basic auth |

All services share the repo's `data/` directory as a volume and `config.yaml` read-only, and use
`restart: unless-stopped`, so a crashed process restarts on its own and the stack comes back after
a reboot. Container stdout logs are capped by Docker (`json-file`, 5 × 10 MB per service), and
`alerts.log` is rotated by logrotate.

**Dashboard exposure:** the dashboard has no login of its own, so it is never published on a
public interface. Reach it with an SSH tunnel (below). To put it on the internet, use the `public`
profile, which puts Caddy with basic auth and automatic HTTPS in front of it.

**Kalshi rate limit on one IP:** the scanner and Data's recorder will share the VPS's IP, and with
it Kalshi's unauthenticated REST limit (429 after about 8 rapid calls). The scanner uses about
0.22 req/s, roughly 5 % of that limit. Keep the recorder's rate within Data's half when it is enabled.

## Tested (2026-10-24, in the cloud dev container)
- `docker compose config` is valid with every profile enabled. `systemd-analyze verify` is clean on the unit,
  and `logrotate -d` parses the rotation config.
- I built the image and ran `scanner` and `dashboard` with compose. The scanner discovered 92 open matches
  and wrote `state.json` to the shared volume. The dashboard returned HTTP 200 on 127.0.0.1:8000 from that file.
  Memory use: scanner about 25 MB, dashboard about 16 MB. Image size 647 MB.
- **Not tested:** the Caddy profile (it needs a real domain), the recorder (its module doesn't exist yet),
  and the systemd unit on a real boot.

## Provisioning (owner, about 20 minutes)

A small Ubuntu 24.04 VPS (1 vCPU, 1 GB RAM, 20 GB disk) is enough.

1. **Create the server** with SSH-key login. Then, as root or with sudo:
   ```bash
   apt update && apt -y upgrade
   ufw allow OpenSSH && ufw enable            # add: ufw allow 80,443/tcp  only for the public profile
   fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile \
     && echo '/swapfile none swap sw 0 0' >> /etc/fstab   # headroom for image builds on 1 GB
   ```
2. **Install Docker Engine + the compose plugin** with Docker's official apt instructions
   (https://docs.docker.com/engine/install/ubuntu/). Check that it works with `docker compose version`.
3. **Get the code.** The repo is private, so use a read-only deploy key or a fine-grained token with
   read access to `phat-d0/Tennis_Model` only:
   ```bash
   git clone git@github.com:phat-d0/Tennis_Model.git /opt/swinglock
   cd /opt/swinglock
   mkdir -p data/live && chown -R 1000:1000 data     # containers run as uid 1000
   ```
4. **Positions and secrets:**
   ```bash
   cp positions.example.json data/positions.json && nano data/positions.json   # your holdings
   cp deploy/env.example deploy/.env && chmod 600 deploy/.env                   # fill in as needed
   ```
   The scanner reloads `data/positions.json` whenever the file changes, so no restart is needed.
   It needs no secrets today, because Kalshi market data is public. `ODDS_API_KEY` goes in
   `deploy/.env` later for Data's collectors.
5. **Start at boot, and rotate logs:**
   ```bash
   cp deploy/systemd/swinglock.service /etc/systemd/system/
   cp deploy/logrotate/swinglock /etc/logrotate.d/swinglock
   systemctl daemon-reload && systemctl enable --now swinglock
   docker compose -f deploy/docker-compose.yml ps        # scanner + dashboard "running"
   docker compose -f deploy/docker-compose.yml logs -f scanner
   ```
   The paths assume `/opt/swinglock`. Edit `WorkingDirectory` and the logrotate path if you clone elsewhere.
6. **Open the dashboard** from your own computer:
   ```bash
   ssh -N -L 8000:127.0.0.1:8000 you@your-vps
   # then browse http://localhost:8000
   ```
   Alerts are also in `/opt/swinglock/data/alerts.log` (`tail -f`).

### Day to day
- **Update:** `cd /opt/swinglock && git pull && systemctl restart swinglock`. This rebuilds the image and recreates the containers.
- **Change thresholds:** edit `config.yaml` (owner go-ahead needed per CLAUDE.md), then `systemctl restart swinglock`.
- **Enable the recorder** once Data ships `swinglock.collectors.recorder`: add `--profile recorder` to
  both `ExecStart` and `ExecStop` in `/etc/systemd/system/swinglock.service`, then run
  `systemctl daemon-reload && systemctl restart swinglock`.
- **Public dashboard (optional):** point a DNS name at the VPS and open ports 80/443. Set
  `DASHBOARD_DOMAIN`, `DASHBOARD_USER` and `DASHBOARD_PASSWORD_HASH` in `deploy/.env`. Get the hash from
  `docker run --rm caddy:2.8 caddy hash-password --plaintext '...'` and write each `$` as `$$`.
  Then add `--profile public` as above.
- **Stop everything:** `systemctl stop swinglock`.
