# Crucible self-hosting

Guide to self-host and run your own installation of [Crucible](https://github.com/MolecularFoundryCrucible), the Molecular Foundry's scientific data platform.

This repository is an example for labs and institutions that host Crucible themselves. The Molecular Foundry's own deployment is configured elsewhere.

## Components

| Component | Role | Source |
|---|---|---|
| API | Authenticated way to interact with the database. | [crucible-api](https://github.com/MolecularFoundryCrucible/crucible-api) |
| Hub | Web interface for browsing and managing records. | [crucible-hub](https://github.com/MolecularFoundryCrucible/crucible-hub) |
| nano-crucible | Python client and `crucible` CLI | [nano-crucible](https://github.com/MolecularFoundryCrucible/nano-crucible) |
| PostgreSQL | The API's database | |
| File store | SeaweedFS in the bundle, or an external S3-compatible store or Google Cloud Storage | |
| Reverse proxy | Caddy: one address for the API and the Hub, and HTTPS | |

The API and the Hub are published as images on the GitHub Container Registry (`ghcr.io/molecularfoundrycrucible/crucible-api`, `.../crucible-hub`). Each release of this repository pins the versions it was tested with.

## Installation guides

| Method | Suits | Guide |
|---|---|---|
| Docker Compose | One host, a lab with a few workstations | [compose/README.md](compose/README.md) |

## License

BSD 3-Clause, see [LICENSE](LICENSE).
