# Deploying golem to a VPS

A single-host Docker Compose setup. No reverse proxy, no TLS, no CI — the bot
talks to Telegram outbound; you manage golems either by SSH-tunnelling to the
forge UI or by hand-editing `data/forge.json`.

## What lives where

| Thing | Location | Notes |
|---|---|---|
| Code | image (rebuilt on `--build`) | ephemeral, no state |
| Runtime knobs | `.env` on the host | `FORGE_PORT`, `GOLEM_LOG_LEVEL`, `NOTION_TOKEN`, … |
| **Telegram tokens, LLM API keys, every golem's spec** | `./data/forge.json` | bind-mounted into the container — **back this up** |
| Per-golem memory | `./data/<name>/memory.json` | same volume |

The `.env` file does **not** hold secrets in this project — those live in
`data/forge.json` and are entered through the forge UI. The single most
important deployment artifact is the `data/` directory.

## 1. Initial setup on the VPS

```bash
# Install Docker Engine + the compose plugin first if needed (docs.docker.com).

git clone <your-fork-url> golem
cd golem

cp .env.example .env
chmod 600 .env
# Edit .env if you need to change log level / port / set NOTION_TOKEN.
# You do NOT put Telegram or LLM keys here — those go in the forge UI.

mkdir -p data
chmod 700 data
```

## 2. First deploy

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f golem    # Ctrl-C to stop tailing
```

## 3. Configuring golems (first time only)

The forge UI is HTTP on port 8765 inside the container. By default the compose
file does **not** publish it — the bot still works for any golem already
defined in `data/forge.json`, but to create or edit golems you need UI access.

**Option A — SSH tunnel (recommended).** Uncomment the `ports:` block in
`docker-compose.yml`, then:

```bash
docker compose up -d                       # on the VPS, applies the port change
# From your laptop:
ssh -L 8765:127.0.0.1:8765 user@vps
# Now open http://127.0.0.1:8765 in your browser.
```

The host binding is `127.0.0.1:8765:8765`, so the port is reachable from the
VPS itself but not from the public internet.

**Option B — edit `data/forge.json` directly.** It's a TinyDB JSON file. Stop
the container first (`docker compose stop`), edit, start again.

## 4. Updating

```bash
cd ~/golem
git pull
docker compose up -d --build
docker compose logs -f golem
```

`restart: unless-stopped` means the container comes back on reboot and after
crashes. Logs rotate at 10 MB × 3 files (json-file driver).

## 5. Viewing logs

```bash
docker compose logs -f golem            # follow
docker compose logs --tail=200 golem    # recent
docker compose logs --since=1h golem    # last hour
```

To raise verbosity, set `GOLEM_LOG_LEVEL=DEBUG` in `.env` and
`docker compose up -d` (no rebuild needed — env_file is re-read on start).

## 6. Backing up `data/`

Everything that matters for recovery is in `./data/`. A tarball-to-`$HOME` job
covers it:

```bash
# Manual backup
tar czf ~/golem-data-$(date +%F).tar.gz -C ~/golem data

# Daily at 03:30, keep 14 days. Run `crontab -e` and add:
30 3 * * * cd $HOME/golem && tar czf $HOME/backups/golem-data-$(date +\%F).tar.gz data && find $HOME/backups -name 'golem-data-*.tar.gz' -mtime +14 -delete
```

(Create `~/backups` first.) Restore by stopping the container, replacing
`./data/`, and starting it again.

## 7. Common operations

```bash
docker compose stop golem            # stop without removing
docker compose start golem           # start again
docker compose restart golem         # restart (e.g. after editing .env)
docker compose down                  # stop + remove container (data/ survives)
docker compose exec golem sh        # shell into the running container
docker image prune -f                # reclaim space after rebuilds
```
