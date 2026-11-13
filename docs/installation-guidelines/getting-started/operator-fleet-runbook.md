# Operator Fleet Runbook

For the team that provisions and runs client servers. It covers standing up one
client on a fresh Linux VM, handing it over, and the day-to-day operations:
updating code, switching a client's broker, changing a domain, and backups.

This is the Linux, operator-run path. It is separate from the Windows desktop
build, which clients install and update themselves. The **application is one
codebase**: a bug fix or feature merged to `main` reaches every server by
`git pull` (below) and every desktop by the next release. Only installation,
update and reset differ between the two. There is **no license gate on servers**
- that is a Windows-desktop control only. Clients receive login credentials.

## The model

- **One client per VM** (the default). Each client gets a subdomain or domain and
  its own server. You own the servers; the client logs in to use the platform.
- **One broker per client.** `VALID_BROKERS` in `.env` is set to the single
  broker that client trades, so there is no broker choice on the login screen.
- **You set up the account, then hand it over.** You run the install, create the
  login, connect the broker once, and give the client the URL and credentials.

Paths and names used throughout (from `install/install.sh`):

| Thing | Value |
|---|---|
| Install path | `/var/python/openalgo` |
| systemd service | `openalgo` |
| Virtualenv | `/var/python/openalgo/.venv` |
| Env file | `/var/python/openalgo/.env` |
| Databases | `/var/python/openalgo/db/` |

## Before you provision

1. **DNS.** Add an A record for the client's hostname (for example
   `client.example.com`) pointing at the VM's public IP. Wait for it to resolve.
2. **Broker credentials.** The client's callback URL will be
   `https://<hostname>/<broker>/callback`. Tell the client that URL so they
   register it in their broker's developer portal, and have them send you the
   **API key and secret** (plus the market-data key and secret for XTS brokers:
   `fivepaisaxts, compositedge, ibulls, iifl, jainamxts, rmoney, wisdom`).

## Provision a new VM

SSH into the fresh VM, then:

```bash
mkdir -p ~/fastalgo-install && cd ~/fastalgo-install
wget https://raw.githubusercontent.com/ranjeetthorat/ai-algo/main/install/install.sh
chmod +x install.sh
sudo ./install.sh
```

Answer the prompts: domain/hostname, broker name (the installer prints the
callback URL to confirm), broker API key and secret, market-data credentials if
the broker is XTS, and the Remote MCP option. The installer then, unattended:

- installs system packages, `uv`, nginx and Certbot
- clones the repo to `/var/python/openalgo` (frontend `dist/` comes with it - no
  Node.js needed on the server)
- generates unique `APP_KEY` and `API_KEY_PEPPER`, writes `.env`
- issues the SSL certificate and configures nginx
- creates and starts the `openalgo` service

### Finish the account

1. **Lock the broker** (one broker per client). Confirm `.env` has
   `VALID_BROKERS` set to just that broker; the installer sets it from your
   answer. If you need to change it, edit `.env` and
   `sudo systemctl restart openalgo`.
2. **Create the login.** Open `https://<hostname>`, complete first-run setup, and
   set the client's username and password.
3. **Connect the broker once.** Log in, connect the broker (the OAuth redirect
   uses the callback you registered), and confirm the dashboard and live data
   work.

### Hand over

Send the client their URL, username and password over a secure channel, and
suggest they change the password. Record which client is on which VM, and add the
host to your fleet list (below).

## Day-to-day operations

### Update one server

A fix or feature merged to `main` reaches a server with:

```bash
cd /var/python/openalgo/install && sudo ./update.sh
```

`update.sh` stops the service, backs up the databases, `git pull`s (bringing the
CI-built frontend `dist/` too), reinstalls only changed dependencies, runs
pending migrations, and restarts. A code-only fix is seconds of downtime.

### Update the whole fleet

From your operator machine (not a client server), roll one `main` fix to every
client at once:

```bash
# one-time: list your servers
sudo install -D -m 600 install/fleet.hosts.sample /etc/openalgo/fleet.hosts
sudoedit /etc/openalgo/fleet.hosts        # one user@host per line

# roll it out (one host at a time, with a summary)
./install/update-all.sh                    # uses /etc/openalgo/fleet.hosts
./install/update-all.sh --dry-run          # show targets, run nothing
```

Requires key-based SSH to each host, and the remote user able to run `update.sh`
with `sudo` (or as root). A failure on one host does not stop the rest; the run
ends with which hosts succeeded and which failed.

### Switch a client to a new broker

Keeps the client's login and their own work (strategies, workflows, settings,
watchlists); clears the old broker's session, symbol master and trading history.
Does **not** touch the domain, nginx or SSL.

```bash
cd /var/python/openalgo/install && sudo ./change-broker.sh
```

It validates the new broker, shows a preview of what will be cleared, backs up
`.env` and all databases, rewrites `.env` (keys, `REDIRECT_URL`, and
`VALID_BROKERS` locked to the new broker), clears the broker data, and restarts -
restoring from the backup if anything fails. Afterwards, register the new
callback URL it prints in the new broker's developer portal, and the client logs
in again and connects the new broker.

### Change a client's domain

```bash
cd /var/python/openalgo/install && sudo ./change-domain.sh
```

Updates `.env`, the nginx config and the SSL certificate to a new hostname. It
prints the new broker callback URL to register.

### Backups

Run on each client server (or install the nightly cron once):

```bash
cd /var/python/openalgo/install
sudo ./backup.sh                 # back up now
sudo ./backup.sh --install-cron  # nightly at 02:30 (or pass HH:MM)
sudo ./backup.sh --list          # list existing backups
```

Backups go to `/var/backups/openalgo/<deployment>/` as compressed archives of the
databases and `.env`, keeping the newest 14 per deployment. Override with
`BACKUP_ROOT` and `RETENTION`. SQLite databases are copied with the online backup
API when `sqlite3` is present, so a backup taken while the service runs is
consistent.

Backups are disaster recovery (disk failure, VM loss, accidental deletion). They
are independent of `change-broker.sh`, which already backs itself up before
changing anything.

### Restore from a backup

```bash
sudo systemctl stop openalgo
mkdir -p /tmp/restore && tar -xzf /var/backups/openalgo/openalgo/openalgo-<timestamp>.tar.gz -C /tmp/restore
sudo cp /tmp/restore/db/*.db /tmp/restore/db/*.duckdb /var/python/openalgo/db/ 2>/dev/null
sudo cp /tmp/restore/.env /var/python/openalgo/.env
sudo chown -R www-data:www-data /var/python/openalgo/db /var/python/openalgo/.env
sudo chmod 600 /var/python/openalgo/.env
sudo systemctl start openalgo
```

(The web user is `www-data` on Ubuntu/Debian, `nginx` on RHEL/Fedora, `http` on
Arch.)

## Troubleshooting

```bash
sudo systemctl status openalgo
sudo journalctl -u openalgo -n 100 --no-pager
tail -f /var/python/openalgo/log/errors.jsonl     # one JSON object per line
```

## Quick reference

| Task | Command (in `/var/python/openalgo/install`) |
|---|---|
| Provision | `sudo ./install.sh` |
| Update one server | `sudo ./update.sh` |
| Update the fleet | `./update-all.sh` (operator machine) |
| Switch broker | `sudo ./change-broker.sh` |
| Change domain | `sudo ./change-domain.sh` |
| Back up | `sudo ./backup.sh` / `--install-cron` / `--list` |
