# Crucible self-hosting

Installation guides and example configurations for running Crucible. The component code lives in its own repositories (crucible-api, crucible-hub, nano-crucible); this repository only pulls their published images.

## Rules

- Changes reach `main` only through a pull request that the user merges. Never push or force-push `main`.
- Guides and examples describe what the CI jobs in `.github/workflows/compose.yml` check. A change to a guide's steps changes the job too.
- Pin images by version. Bumping the API or Hub version is a pull request that runs both jobs.
- Settings of a component are documented in that component's repository; link to them instead of copying.
