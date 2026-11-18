# Sign-in methods

Part of the [Docker Compose installation guide](../README.md). Commands run in `deploy/compose`.

Users sign in with a password, through an identity provider, or both. The bundle enables passwords by default. Every setting is described in [Authentication configuration](../../../docs/sign_in_operations.md).

## Passwords

Passwords suit small deployments. An administrator creates each user (`POST /users`, or the Hub's Users page) and sends them a one-time link to set their password:

```bash
docker compose run --rm api python -m app.cli admin password-link USER
```

`POST /users/{user_ref}/password-link` does the same through the API. Passwords require at least 15 characters; repeated guessing is slowed and then locked per account.

| Task | How |
|---|---|
| Self-registration | Set `CRUCIBLE_AUTH_PASSWORD_REGISTRATION=approval` in `.env`. Users request an account at `/api/v4/oauth/register`; an administrator reviews requests with `admin pending`, then `admin approve USER` or `admin reject USER`, or on the Hub's Users page |
| Locked-out user or administrator | `admin password-link USER` works for any account; a new link restores access |
| Additional administrator | `admin create --allow-additional`; without the option, a second run changes nothing |
| Scripted creation of the first administrator | `admin create --no-input --first-name Ada --last-name Lovelace --email ada@example.org`, run with `docker compose run --rm -T`. The output contains the API key and the password link: keep it out of logs |
| Incident response | `auth revoke-passwords --commit` removes every password and ends the sessions created with them; `auth end-sessions --all --commit` ends all sessions. Issue new links afterwards. API keys are separate: revoke a user's keys with `DELETE /users/{user_ref}/apikey` |

Each command is run as `docker compose run --rm api python -m app.cli <command>`.

## Identity providers

An identity provider (ORCID, or an institutional login through any OpenID Connect service such as Keycloak, Authentik or Entra ID) suits larger groups: no passwords are managed locally, and users who leave lose access at the source. Identity providers require HTTPS (see [Network access and HTTPS](network.md)).

When passwords and providers are both enabled, the sign-in page shows the password form with the providers below it. Once a provider is configured, set `CRUCIBLE_AUTH_PASSWORD_ENABLED=false` unless some users still need passwords.

### ORCID

1. Register Public API credentials at [ORCID developer tools](https://orcid.org/developer-tools) (free; requires a verified email), with the redirect URI `https://<your address>/api/v4/oauth/callback/orcid`, including the port when it is not 443. ORCID accepts only HTTPS and requires an exact match of the address. For evaluation, use the [ORCID sandbox](https://sandbox.orcid.org) and its separate accounts.

2. Store the client secret:

   ```bash
   printf '%s' 'your-orcid-client-secret' > secrets/ORCID_CLIENT_SECRET
   chmod 644 secrets/*
   ```

3. In `.env`, add `compose.orcid.yaml` to `COMPOSE_FILE`, after any other files, and set the client ID:

   ```bash
   COMPOSE_FILE=compose.yaml:compose.orcid.yaml
   ORCID_CLIENT_ID=APP-XXXXXXXXXXXXXXXX
   # For the ORCID sandbox:
   # ORCID_ISSUER=https://sandbox.orcid.org
   # closed admits only users an administrator added; approval makes new users wait for one.
   # ORCID_REGISTRATION=open
   ```

4. Run `docker compose up -d --wait`.

### Other providers

For another provider, or several at once, list them in `CRUCIBLE_AUTH_PROVIDERS` as in `auth-providers.example.json` and [the provider list](../../../docs/sign_in_operations.md#the-provider-list). Each entry specifies whether new users are refused, wait for approval, or are admitted immediately.
