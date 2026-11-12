# Network access and HTTPS

Part of the [Docker Compose installation guide](../README.md). Commands run in `deploy/compose`.

By default the server answers only on the local host, over plain HTTP. Other hosts reach it by a single name, over HTTPS, with a certificate that browsers and Python already trust. Any name that every client resolves to the server works, including a hostname assigned by the institution; a separately registered domain is not required. Choose the name once and keep it: the Hub, nano-crucible, sign-in and every upload or download link include it, and moving to another server later only requires pointing the name at the new host.

## Public address

In `.env`, set these together:

```bash
CRUCIBLE_SITE_ADDRESS=crucible.mylab.org
CRUCIBLE_HTTP_PORT=80
CRUCIBLE_HTTPS_PORT=443
CRUCIBLE_BIND_ADDRESS=0.0.0.0
CRUCIBLE_PUBLIC_URL=https://crucible.mylab.org
```

Then run `docker compose up -d --wait`.

- `CRUCIBLE_SITE_ADDRESS` is the bare name, without `https://` or a port.
- With rootless Docker, ports below 1024 require `sudo sysctl net.ipv4.ip_unprivileged_port_start=80`.
- Users outside the lab network should connect through the institution's VPN rather than through a server exposed to the internet, unless external collaborators need access.

## Certificates

Caddy requires a certificate for the name. Use the first option that applies:

1. **Institutional certificate.** Most universities and national laboratories manage their own DNS and run a certificate service; request a name and a certificate for it from IT. If the service supports ACME (the protocol used by Let's Encrypt), Caddy renews the certificate automatically. Put the settings provided by IT in `local/global-acme.caddy`:

   ```
   acme_ca https://acme.myinstitution.edu/directory
   acme_eab {
   	key_id YOUR_KEY_ID
   	mac_key YOUR_MAC_KEY
   }
   ```

   If IT provides certificate files instead, save them as `local/cert.pem` and `local/key.pem`, write `local/site-tls.caddy` as follows, and renew the files manually before they expire:

   ```
   tls /etc/caddy/local/cert.pem /etc/caddy/local/key.pem
   ```

2. **Server reachable from the internet.** With the name's DNS record pointing at the server and ports 80 and 443 open to the internet, Caddy obtains and renews a Let's Encrypt certificate with no further configuration. Let's Encrypt validates the name by connecting to the server, so this fails behind an institutional firewall that blocks incoming connections, even when the name resolves publicly.

3. **Own domain, server not reachable from the internet.** Let's Encrypt can validate the name through its DNS records instead. This requires a Caddy image built with the DNS provider's module ([caddy-dns](https://github.com/caddy-dns), using Caddy's official builder image), a provider token limited to that one zone, and `acme_dns` with that token in `local/global-acme.caddy`. The bundle does not ship such an image, and this option has not been tested with it. Some routers refuse public names that resolve to local addresses; if the name does not resolve inside the lab, add it to the lab's DNS.

4. **Caddy's own certificate authority, for testing.** Caddy issues the certificate itself, and no client trusts it until Caddy's root certificate is installed there. Write `local/site-tls.caddy`:

   ```
   tls internal
   ```

   After `docker compose up -d --wait`, export the root certificate:

   ```bash
   docker compose exec proxy cat /data/caddy/pki/authorities/local/root.crt > crucible-root.crt
   ```

   Import that file into each browser, and pass it to nano-crucible for its own commands only: `REQUESTS_CA_BUNDLE=crucible-root.crt crucible ...`. Setting the variable for a whole shell makes other tools distrust public sites.

Files in `local/` are read only by Caddy, are not tracked in git, and may contain credentials: restrict the directory like `secrets/` (`chmod 700 local`).

Caddy retries a failed certificate request for 30 days. After changing the certificate settings, run `docker compose up -d --force-recreate --wait proxy`.

## Behind an institutional reverse proxy

When an institutional reverse proxy or load balancer already terminates HTTPS and forwards to this host, keep Caddy on plain HTTP, listen on an address the proxy can reach, and name the host it forwards for:

```bash
CRUCIBLE_BIND_ADDRESS=10.0.0.5
CRUCIBLE_HTTP_HOSTS=crucible.mylab.org
CRUCIBLE_PUBLIC_URL=https://crucible.mylab.org
```

Caddy ignores forwarding headers from another proxy until that proxy is declared trusted. Add its address to `local/global-proxy.caddy`:

```
servers {
	trusted_proxies static 10.0.0.1/32
}
```

The proxy must pass `Host`, set `X-Forwarded-For` to the client address and `X-Forwarded-Proto` to `https`, and be the only host that can reach this port. Without the trusted address, all users appear to connect from the proxy, and the sign-in attempt limits treat them as a single client.

## Replacing Caddy

Caddy can be replaced by any reverse proxy that meets these requirements:

- `/api/v3/` routes to the API (`api:8000` inside Compose, or the API container's port) with the `/api/v3` prefix removed; the API serves its documentation under that prefix (`API_PATH=api/v3`).
- Pass `Host`, `X-Forwarded-For` (set to the client address, not appended to the value the client sent), and `X-Forwarded-Proto`. The API trusts forwarding headers from any address (`FORWARDED_ALLOW_IPS="*"`), so it must be reachable only through the proxy.
- Allow request bodies of 10 MB, 20 MB for thumbnails (the API's own limits), and read timeouts of at least 60 seconds.
- Limit the sign-in routes, `/api/v3/oauth/` and `/api/v3/auth/hub/`, to 8 KB bodies and a 20 second timeout, as Caddy does here.
- Do not serve `/api/v3/metrics` to the outside.
- `/crucible-files/` routes to SeaweedFS (`seaweedfs:8333`) with the path and `Host` unchanged, since the store validates the signed URL against both. Remove the `Authorization` and `Cookie` request headers, allow request bodies of 64 MB (one upload part) and read timeouts of a few minutes, and do not compress responses. Add `Content-Security-Policy: sandbox; default-src 'none'`, `X-Content-Type-Options: nosniff`, and `Cross-Origin-Resource-Policy: same-site` to the responses, so that a downloaded file never runs as a page of the site and other sites cannot embed it ([web.dev, "Securely hosting user data"](https://web.dev/articles/securely-hosting-user-data)); current Chrome and Firefox still display PDFs and images in the browser with these headers. Do not route the records bucket.
- With the Hub: `/hub/` routes to the Hub (`hub:3000`) with the prefix kept. `X-Forwarded-For` must again be set, not appended: the Hub limits sign-in attempts per client address and trusts one proxy (`HUB_TRUSTED_PROXY_HOPS=1`).

Example nginx configuration, for nginx running as a service in the same Compose project (remove the `proxy` service and publish nginx instead):

```nginx
server {
    listen 80;
    server_name crucible.mylab.org;
    client_max_body_size 20m;

    location = /api/v3 { return 301 /api/v3/; }
    location = /api/v3/metrics { return 404; }

    location /api/v3/ {
        proxy_pass http://api:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_read_timeout 60s;
    }

    location /crucible-files/ {
        proxy_pass http://seaweedfs:8333;
        proxy_set_header Host $http_host;
        proxy_set_header Authorization "";
        proxy_set_header Cookie "";
        proxy_request_buffering off;
        client_max_body_size 80m;
        proxy_read_timeout 300s;
        add_header Content-Security-Policy "sandbox; default-src 'none'" always;
        add_header X-Content-Type-Options nosniff always;
        add_header Cross-Origin-Resource-Policy same-site always;
    }

    # Only with the Hub.
    location /hub/ {
        proxy_pass http://hub:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Internal traffic

HTTPS terminates at Caddy. Behind it, Caddy, the API and the Hub communicate over plain HTTP, and those connections carry API keys, sign-in tokens and cookies, and, when the Hub exchanges a sign-in, the shared client secret.

On a single host this is the usual setup and is safe as configured here: the database is on an internal network that only the API joins, every container drops the Linux capabilities that would allow it to intercept other containers' traffic and cannot gain new privileges, and nothing else should be attached to the `crucible` network. This is not a zero-trust architecture, in which every connection is encrypted and authenticated (NIST SP 800-207).

Any connection that leaves the host requires encryption: the Hub refuses plain HTTP to the API except to a container name or a private address, and the connection to a Hub on a separate host must use an encrypted private network (see [Crucible Hub](hub.md#hub-on-a-separate-host)).

To encrypt traffic within the host as well, Caddy can issue internal certificates (`tls internal`) for an additional HTTPS address in front of the API, the Hub can call that address, and the Hub can be given Caddy's root certificate through `NODE_EXTRA_CA_CERTS`. This requires no code change but is not configured here.
