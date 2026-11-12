# Crucible Hub

Part of the [Docker Compose installation guide](../README.md).

The Crucible Hub is the web interface. It is optional: without it, the API, API keys and the Python client work unchanged. Users sign in to it through the API, with any of the configured [sign-in methods](sign_in.md).

The Hub is a separate Compose project, from the [crucible-hub repository](https://github.com/MolecularFoundryCrucible/crucible-hub/tree/v1.8.0-alpha.1/deploy/compose), with its own small database for sign-in sessions. It runs on the same host or on a separate one; in both cases the bundle's Caddy serves it at `/hub/`, so users access a single address.

| | |
|---|---|
| Release | `v1.8.0-alpha.1`, the pre-release that matches this API version |
| Image | `ghcr.io/molecularfoundrycrucible/crucible-hub:1.8.0-alpha.1` (amd64 and arm64), prebuilt |
| Requires | API 4.0.0 or later: Hub 1.8 signs users in through the API's `/oauth` routes |

## Prerequisites

One of:

- **HTTPS**, configured as in [Network access and HTTPS](network.md). This is required for any installation that other hosts use: sign-in sets secure cookies.
- **A single-host evaluation at `http://localhost:8080`**, the bundle's default address. The Hub accepts plain HTTP only on `localhost`. Open it at exactly the configured address: `localhost` and `127.0.0.1` are not interchangeable. From another computer, forward the port first (`ssh -L 8080:localhost:8080 you@server`).

## 1. Register the Hub with the API

In the bundle's directory (`crucible-api/deploy/compose`), create the secret shared by the API and the Hub:

```bash
openssl rand -hex 32 > secrets/HUB_AUTH_CLIENT_SECRET
chmod 644 secrets/*
```

In `.env`:

```bash
COMPOSE_FILE=compose.yaml:compose.hub.yaml
# Public address: no /api/v3, no trailing slash; include the port if it is not 443.
# Leave it unset for a single-host evaluation at http://localhost:8080.
CRUCIBLE_PUBLIC_URL=https://crucible.mylab.org
```

Then run `docker compose up -d --wait`. `compose.hub.yaml` adds the Hub to the client applications allowed to sign users in, alongside the nano-crucible command-line interface. With ORCID, the line is `COMPOSE_FILE=compose.yaml:compose.hub.yaml:compose.orcid.yaml`. Until the Hub is running, `/hub/` returns `502`.

## 2. Start the Hub

### Hub on the same host

Clone the Hub next to this repository and create its secrets. The first one is the secret created in step 1:

```bash
git clone --branch v1.8.0-alpha.1 https://github.com/MolecularFoundryCrucible/crucible-hub.git
cd crucible-hub/deploy/compose
mkdir -p secrets && chmod 700 secrets
cp /path/to/crucible-api/deploy/compose/secrets/HUB_AUTH_CLIENT_SECRET secrets/hub_auth_client_secret
printf 'k1:%s' "$(openssl rand 32 | basenc --base64url | tr -d '=\n')" > secrets/hub_session_keys
openssl rand -base64 32 | tr -d '\n' > secrets/hub_session_database_password
openssl rand -base64 32 | tr -d '\n' > secrets/hub_db_admin_password
chmod 444 secrets/hub_*
cp example.env .env
```

In the Hub's `.env`, set:

```bash
HUB_IMAGE=ghcr.io/molecularfoundrycrucible/crucible-hub:1.8.0-alpha.1
HUB_PUBLIC_ORIGIN=https://crucible.mylab.org
HUB_AUTH_PUBLIC_API_URL=https://crucible.mylab.org/api/v3
# Single-host evaluation with the bundle's defaults:
# HUB_PUBLIC_ORIGIN=http://localhost:8080
# HUB_AUTH_PUBLIC_API_URL=http://localhost:8080/api/v3
```

The other defaults in `example.env` join the bundle's `crucible` network and call the API at `http://api:8000`. Start the Hub after the bundle, which creates the network:

```bash
docker compose pull hub hub-setup
docker compose up -d --wait
```

`https://crucible.mylab.org/hub/health` (or `http://localhost:8080/hub/health`) then returns `{"status":"ok","sessions":"ok"}`. Open `/hub/` and sign in with the administrator account created during installation.

Each Hub secret must be provided in exactly one way (a file in `secrets/`, a `NAME_FILE` path, or an environment variable); the Hub refuses to start when one is set twice. The Hub's own `README.md` documents its settings.

### Hub on a separate host

1. On the second host, clone the same release and create the Hub's secrets as above, copying `HUB_AUTH_CLIENT_SECRET` from the API host.
2. In the Hub's `.env`, comment out the same-machine block and use the separate-machine block:
   - `COMPOSE_FILE=compose.yaml:compose.published.yaml`
   - `HUB_BIND_ADDRESS`: the address on which the API host reaches the Hub
   - `CRUCIBLE_API_BASE_URL=https://crucible.mylab.org/api/v3`
   - `HUB_IMAGE`, `HUB_PUBLIC_ORIGIN` and `HUB_AUTH_PUBLIC_API_URL` as above
3. Start it with `docker compose pull hub hub-setup` and `docker compose up -d --wait`.
4. In the bundle's `.env` on the API host, set `CRUCIBLE_HUB_UPSTREAM=<that address>:3000` (an address and port, without `http://`) and run `docker compose up -d --wait`.

Warning: Caddy connects to the Hub over plain HTTP, and that connection carries sign-in cookies, so it must be encrypted. Place both hosts on a WireGuard or Tailscale network, use the Hub's address on that network, and allow only the API host to reach the Hub's port. A shared LAN alone is not sufficient. [Internal traffic](network.md#internal-traffic) describes what travels between the services.

## Removing the Hub

1. In the Hub's directory, run `docker compose down`; add `-v` to delete its session database.
2. In the bundle's `.env`, remove `compose.hub.yaml` from `COMPOSE_FILE`, and `CRUCIBLE_HUB_UPSTREAM` if set.
3. Run `docker compose up -d --wait`.

The API's data is unaffected; `/hub/` returns `404`.
