# Deploying on a Hetzner VPS, with phone access over Tailscale

This puts the scanner, the dashboard and the order-book recorder on a small Hetzner server. You
open the dashboard from your phone at a private address that only your own devices can reach. The
server has **no public ports**: no web port, and SSH only over Tailscale. Everything is read-only,
and nothing on the server places orders.

You paste one file, [`deploy/cloud-init.yaml`](../deploy/cloud-init.yaml), and change one value in it.
That file clones this repo and runs [`deploy/bootstrap.sh`](../deploy/bootstrap.sh), which does the rest.

## What you need
- A **Tailscale** account (free) and the Tailscale app on your phone.
- A **Hetzner Cloud** account with a payment method.
- About 15 minutes, all doable from a phone browser.

## 1. Tailscale (phone)
1. Install the **Tailscale** app (App Store or Play Store) and sign in. Pick the login you want to
   own the private network (your "tailnet"). Turn the VPN toggle on.
2. In a browser, open **login.tailscale.com/admin** and sign in with the same account.
3. **DNS** page: check that **MagicDNS** is on, and turn on **HTTPS Certificates**. The dashboard's
   `https://…ts.net` address needs both.
4. **Settings → Keys → Generate auth key**:
   - **Reusable: off.** It's a one-off key.
   - **Ephemeral: off.** Otherwise the server drops off your tailnet when it's offline.
   - **Expiration: the shortest it offers.**
   - Copy the key (`tskey-auth-…`).

   ⚠️ This key is saved in Hetzner's server metadata, which stays readable from inside the server.
   That's why it should be one-off and short-lived. It is used once at first boot, and the
   server deletes its own copy afterwards.

## 2. Hetzner server (phone browser)
1. Open **console.hetzner.com** → your project → **Add server**:
   - **Location:** Ashburn, VA (US East).
   - **Image:** Ubuntu 24.04.
   - **Type:** shared vCPU, x86. **CPX11**, or the smallest type offered there. The three services
     use about 180 MB of RAM, so the smallest type is enough.
   - **Networking:** keep **public IPv4** on. GitHub has no IPv6, and the server clones the repo from it.
   - **SSH key:** optional. If you add none, Hetzner emails a root password. Keep it, because the
     web console needs it. You can also reset it later under the server's **Rescue** tab.
   - **Cloud config:** paste the whole of `deploy/cloud-init.yaml`
     ([raw link](https://raw.githubusercontent.com/phat-d0/Tennis_Model/main/deploy/cloud-init.yaml)),
     then replace the word **`TS_AUTHKEY`** with your key from step 1.4. Change nothing else.
   - **Name:** `tennis-scanner`.
2. Click **Create & Buy**.

## 3. Wait about 5 minutes, then open the dashboard
On first boot, the server:
1. Installs updates and adds 1 GB of swap.
2. Installs Docker from Docker's official repo.
3. Clones this repo to `/opt/swinglock`.
4. Joins your tailnet as **tennis-scanner**, with Tailscale SSH on.
5. Publishes the dashboard to the tailnet.
6. Firewalls everything else.
7. Builds and starts the three services.

Then:
- In the Tailscale app, **tennis-scanner** appears under your devices.
- With the Tailscale VPN on, open **`https://tennis-scanner.<your-tailnet>.ts.net`**. The app shows
  your tailnet name, and the exact URL is listed on the admin **Machines** page under the device.
  The first load can take a few seconds while the HTTPS certificate is issued.
- In the admin **Machines** page, open tennis-scanner's **⋯ menu → Disable key expiry**. Otherwise the
  server leaves your tailnet after about 180 days.

**If the dashboard doesn't load after about 10 minutes**, open the Hetzner web console (server →
**>_ Console**), log in as root, and run:

```bash
tail -50 /var/log/swinglock-bootstrap.log
```

| Symptom in the log | Fix |
|---|---|
| `no Tailscale auth key` or `tailscale up failed` (the key was missing, used or expired) | Run `tailscale up --hostname=tennis-scanner --ssh` and open the login link it prints, then `tailscale serve --bg 8000`. Public SSH stays open until Tailscale is up. |
| `tailscale serve failed` | Turn on HTTPS Certificates (step 1.3), then run `tailscale serve --bg 8000` |
| Anything else | Re-run `bash /opt/swinglock/deploy/bootstrap.sh`. It's safe to run again. |

## Day to day
Run these from **Tailscale SSH** or from the **Hetzner web console**. For Tailscale SSH, use any SSH
app on the phone (e.g. Termius) to connect to `root@tennis-scanner` with the VPN on; no key is
needed. Tailscale may ask you to confirm in the browser.

```bash
cd /opt/swinglock
docker compose -f deploy/docker-compose.yml ps               # scanner, dashboard, recorder: "running"
docker compose -f deploy/docker-compose.yml logs -f --tail 50 scanner   # or: recorder, dashboard
tail -f data/alerts.log                                       # alerts (also on the dashboard)

git pull && systemctl restart swinglock                       # update to the latest main (rebuilds)
systemctl restart swinglock                                   # restart all services
systemctl stop swinglock                                      # stop everything
```

- **Your positions:** edit them with `nano /opt/swinglock/data/positions.json`. The format is in
  `positions.example.json`. The scanner reloads the file when it changes; no restart is needed.
- **Thresholds:** they're in `config.yaml`. Changing them to a tested rule needs the owner's go-ahead
  (CLAUDE.md). Run `systemctl restart swinglock` afterwards.
- **Is the recorder writing?** New part files should appear every minute, and finished days are
  compacted to `<table>/<day>.parquet`:
  ```bash
  ls -lt data/recorded/kalshi/quotes/$(date -u +%F)/ | head -3
  docker compose -f deploy/docker-compose.yml logs --tail 20 recorder
  ```
- **Disk:** recorded data grows every day. Check it with `du -sh data/recorded` and `df -h /`.

## What runs, and its limits
| Service | What it does | Kalshi requests |
|---|---|---|
| `scanner` | Live arb and lock alerts → `data/live/state.json`, `data/alerts.log` | capped at `scanner.max_rps` (0.5 req/s): one orderbooks call per 50 matches each poll, so with 250 open matches polls are 12 s apart instead of 5 s |
| `recorder` | Order books, top-5 depth, matches and scores → daily parquet in `data/recorded/kalshi/` | ≤ 1 req/s cap; grows with the number of open matches (~0.45 req/s at 252 matches) |
| `dashboard` | Web page on 127.0.0.1:8000, reachable only through `tailscale serve` (tailnet-only HTTPS) | none |

- **One IP, one rate limit.** The scanner and the recorder share the server's IP, and with it Kalshi's
  unauthenticated limit, which is undocumented. **Never run a backfill on this server.** In the
  test below, the two together ran at about 0.95 req/s and got an occasional 429 (about 1 a minute),
  which both clients retry after a short wait.
- **Firewall:** ufw denies all inbound except the `tailscale0` interface and Tailscale's UDP port 41641.
  The dashboard port is only bound to 127.0.0.1. Docker-published ports would bypass ufw, so none are
  published on a public interface.
- **Restarts:** containers restart on failure, and systemd brings the stack back after a reboot.
  Ubuntu's unattended-upgrades installs security updates automatically.
- **Logs:** Docker caps each service's log at 5 × 10 MB. logrotate rotates `data/*.log` weekly and keeps 12.
- The optional `public` compose profile (a Caddy proxy with basic auth on ports 80/443) is **not used**
  with Tailscale. It's kept for a setup without Tailscale.

## Tested (2026-10-26)
- `cloud-init schema --config-file deploy/cloud-init.yaml` is valid (cloud-init on Ubuntu 24.04).
- `deploy/bootstrap.sh` ran twice in a fresh `ubuntu:24.04` container with systemd, Tailscale and ufw
  skipped, since a container has none of them. The second run was a clean no-op.
  - Docker Engine and the compose plugin installed from download.docker.com.
  - `data/` was set up with owner 1000 and the positions file copied in.
  - The unit and logrotate files were installed. Swap is refused inside a container, so the script
    warned and went on.
  - The ufw rules were checked with `--dry-run`, and `logrotate -d` parses.
- `COMPOSE_PROFILES=recorder docker compose up` ran all three services against live Kalshi for about
  9 minutes. During the last 6 minutes:
  - **scanner:** 181 requests (0.50 req/s, polls 12 s apart), 6 × 429.
  - **recorder:** 161 requests (0.45 req/s), 3 × 429.
  - All 429s were retried after a 2 s backoff, with no lost polls.

  | Check | Result |
  |---|---|
  | Matches in `state.json` | 251, including **32 KXATPCHALLENGERMATCH**, 24 WTA 125, 27 ATP, 21 WTA, 148 ITF |
  | Recorder parquet | quotes 14,598 rows, depth 140,945 rows, score 84 rows; 252 matches in `matches.parquet` |
  | Dashboard | HTTP 200 |
  | Memory | scanner 31 MB, dashboard 28 MB, recorder 119 MB |

  Odd result: the first 3 minutes, before the scanner's rate cap existed (scanner at about 1 req/s,
  about 1.5 req/s combined), had no 429s at all. So the limit isn't a simple rate, and the test
  machine's IP may be shared.
- **Not tested here:** the Tailscale install, `tailscale up`/`serve` (pkgs.tailscale.com is blocked in
  the test sandbox, and joining needs a real key), a real systemd boot, and enabling ufw on a real host.
  These steps are guarded: public SSH stays open unless Tailscale came up.

## Files
| File | Purpose |
|---|---|
| `deploy/cloud-init.yaml` | Pasted into Hetzner. Writes the auth key file, clones the repo, runs bootstrap |
| `deploy/bootstrap.sh` | Swap, Docker, data dir, systemd and logrotate, Tailscale and `serve`, ufw, start. Safe to re-run |
| `deploy/Dockerfile`, `deploy/docker-compose.yml` | One image; services `scanner`, `dashboard`, `recorder` (profile), `caddy` (profile) |
| `deploy/systemd/swinglock.service` | Starts the stack at boot with `COMPOSE_PROFILES=recorder` |
| `deploy/logrotate/swinglock` | Rotation for `data/*.log` |
| `deploy/env.example` | Template for `deploy/.env` (gitignored). Nothing in it is needed today |
