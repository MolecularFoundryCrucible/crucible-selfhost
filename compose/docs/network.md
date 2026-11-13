# Network access and HTTPS

Part of the [Docker Compose installation guide](../README.md). Commands run in `deploy/compose`.

By default the server answers only on the local host, over plain HTTP. Other hosts reach it by a single name, over HTTPS, with a certificate that browsers and Python already trust. Any name that every client resolves to the server works, including a hostname assigned by the institution; a separately registered domain is not required. Choose the name once and keep it: the Hub, nano-crucible, sign-in and every upload or download link include it, and moving to another server later only requires pointing the name at the new host.

## Setups

The bundle supports three network setups. Each is one consistent set of values in `.env`; mixing values from two of them leaves the server unreachable or hands clients links that nothing serves.

| Setting | Local host only (default) | HTTPS on a network | Behind another reverse proxy |
|---|---|---|---|
| `CRUCIBLE_SITE_ADDRESS` | `:80` | `crucible.mylab.org` | `:80` |
| `CRUCIBLE_HTTP_PORT` | `8080` | `80` | `8080` |
| `CRUCIBLE_HTTPS_PORT` | `8443` (unused) | `443` | `8443` (unused) |
| `CRUCIBLE_BIND_ADDRESS` | `127.0.0.1` | `0.0.0.0` | An address the proxy reaches |
| `CRUCIBLE_PUBLIC_URL` | unset | `https://crucible.mylab.org` | `https://crucible.mylab.org` |
| `CRUCIBLE_HTTP_HOSTS` | unset | unset | `crucible.mylab.org` |
| Certificate | None | Obtained by Caddy (see [Certificates](#certificates)) | Held by the other proxy |
| Described in | [Quick start](../README.md#quick-start) | [Public address](#public-address) | [Behind an institutional reverse proxy](#behind-an-institutional-reverse-proxy) |

## Choosing the name

- The name must point at a fixed address: a static address or a DHCP reservation registered under the name. If a DHCP lease changes, the name, the certificate and every client point at the wrong host.
- Publish only an IPv4 (`A`) record while `CRUCIBLE_BIND_ADDRESS=0.0.0.0`. Docker then publishes the ports on IPv4 only, and clients that prefer an IPv6 (`AAAA`) record fail to connect.
- A registered name and a fixed address do not open the institution's border firewall. Ask IT whether incoming connections from the internet are allowed: the answer decides the certificate option below and who can reach the server.

## Public address

In `.env`, set these together:

```bash
CRUCIBLE_SITE_ADDRESS=crucible.mylab.org
CRUCIBLE_HTTP_PORT=80
CRUCIBLE_HTTPS_PORT=443
CRUCIBLE_BIND_ADDRESS=0.0.0.0
CRUCIBLE_PUBLIC_URL=https://crucible.mylab.org
```

Then run `docker compose up -d --wait`, and verify from another host:

```bash
curl https://crucible.mylab.org/api/v3/health/ready
```

- `CRUCIBLE_SITE_ADDRESS` is the bare name, without `https://` or a port.
- With rootless Docker, ports below 1024 require `sudo sysctl net.ipv4.ip_unprivileged_port_start=80`.
- Leave `CRUCIBLE_HTTP_HOSTS` unset. It allows plain HTTP for the names it lists and is only for running [behind another reverse proxy](#behind-an-institutional-reverse-proxy) that already provides HTTPS.
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

   If IT provides certificate files instead, follow [Certificate files](#certificate-files).

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

Caddy retries a failed certificate request for 30 days. After changing the certificate settings, run `docker compose up -d --force-recreate --wait proxy`.

### Certificate files

Generate the key on the server and give IT only the certificate signing request (CSR). The key never leaves the server: do not paste it into a web form, an email or a ticket, even if a form asks for it. If it was shared, generate a new key and request a new certificate.

```bash
(umask 077; openssl req -new -newkey rsa:2048 -noenc \
  -keyout local/key.pem -out local/crucible.csr \
  -subj "/CN=crucible.mylab.org" \
  -addext "subjectAltName=DNS:crucible.mylab.org")
```

Clients check the name against the subjectAltName, not the CN, so it must list the name, and any other name the server answers to (`DNS:crucible.mylab.org,DNS:crucible`).

`local/cert.pem` must hold the full chain in PEM format: the server's certificate first, then the intermediate certificates, without the root. Certificate services usually offer it as a separate download (often labeled "with chain" or "full chain"); otherwise join the files:

```bash
cat crucible.crt intermediate.crt > local/cert.pem
```

If the intermediate certificate is missing, the server's certificate gives its download address (`CA Issuers`). The file there is usually in DER format; convert it:

```bash
openssl x509 -in crucible.crt -noout -ext authorityInfoAccess
curl -o intermediate.der <the CA Issuers URI>
openssl x509 -inform DER -in intermediate.der -out intermediate.crt
```

Before starting Caddy, check that the chain is complete and that the certificate matches the key. The first command prints `OK`; the two hashes must be equal:

```bash
openssl verify -untrusted local/cert.pem local/cert.pem
openssl x509 -in local/cert.pem -noout -pubkey | sha256sum
openssl pkey -in local/key.pem -pubout | sha256sum
```

Some browsers complete a missing chain themselves, but Python, nano-crucible and curl do not, so a chain that works in a browser can still fail for clients.

Write `local/site-tls.caddy`:

```
tls /etc/caddy/local/cert.pem /etc/caddy/local/key.pem
```

Set the [permissions](#permissions-of-local), run `docker compose up -d --force-recreate --wait proxy`, and check from another computer:

```bash
echo | openssl s_client -connect crucible.mylab.org:443 -servername crucible.mylab.org 2>/dev/null \
  | grep -E '^ *[0-9] s:|Verify return code'
curl https://crucible.mylab.org/api/v3/health/ready
```

The output lists the server's certificate and each intermediate, and ends with `Verify return code: 0 (ok)`.

Caddy does not renew these files. Read the expiry date (`openssl x509 -in local/cert.pem -noout -enddate`) and set a reminder a month before it. To renew, request a new certificate, replace `local/cert.pem` (and `local/key.pem` if a new key was generated), check it as above (with `sudo` for the key), and recreate the proxy.

### Permissions of `local/`

Files in `local/` are read only by Caddy, are not tracked in git, and may contain credentials: `key.pem`, and the `mac_key` in `global-acme.caddy`. Caddy runs as root inside its container, but without the capabilities that let root read other users' files. With rootful Docker it can therefore read a file only if root owns it or everyone can read it. Make the secret files root-owned and keep the rest readable:

```bash
sudo chown root:root local/key.pem
sudo chmod 600 local/key.pem
chmod 755 local
chmod 644 local/cert.pem local/site-tls.caddy
```

Treat `global-acme.caddy`, if present, like `key.pem`. Do not restrict the directory itself (`chmod 700`): Caddy then cannot list it, logs `No files matching import glob pattern` for `/etc/caddy/local/site-*.caddy`, ignores the certificate settings, and requests a Let's Encrypt certificate instead. Making the directory root-owned works for Caddy, but git can then no longer read the tracked `local/README`.

With rootless Docker, root in the container is your own user: keep the files owned by you, with `chmod 600` on the secret ones.

## Host firewall

Ports published by Docker bypass ufw and firewalld: Docker forwards the traffic to the container before those rules apply. To limit who can connect, add rules to the `DOCKER-USER` chain, which Docker evaluates first. For example, to accept the web ports only from one address range (replace the interface and the range; add a `RETURN` rule per range):

```bash
sudo iptables -I DOCKER-USER -i eth0 -p tcp -m multiport --dports 80,443 -j DROP
sudo iptables -I DOCKER-USER -i eth0 -p udp --dport 443 -j DROP
sudo iptables -I DOCKER-USER -i eth0 -p tcp -m multiport --dports 80,443 -s 192.0.2.0/24 -j RETURN
sudo iptables -I DOCKER-USER -i eth0 -p udp --dport 443 -s 192.0.2.0/24 -j RETURN
```

Each rule is inserted at the top, so the `RETURN` rules come before the `DROP` rules. The ports are the container's (80 and 443) whatever `CRUCIBLE_HTTP_PORT` and `CRUCIBLE_HTTPS_PORT` are, since Docker has already translated the address. These rules are lost on reboot unless saved with the distribution's tool (for example `netfilter-persistent save`). See Docker's [Packet filtering and firewalls](https://docs.docker.com/engine/network/packet-filtering-firewalls/), which also covers its nftables backend.

## Behind an institutional reverse proxy

When an institutional reverse proxy or load balancer already terminates HTTPS and forwards to this host, keep Caddy on plain HTTP (`CRUCIBLE_SITE_ADDRESS=:80`, the default), listen on an address the proxy can reach, and name the host it forwards for. `CRUCIBLE_HTTP_HOSTS` applies only to this setup: without another proxy providing HTTPS, it does not make the server reachable.

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
