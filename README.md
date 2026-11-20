# Crucible self-hosting

Everything needed to run your own installation of [Crucible](https://github.com/MolecularFoundryCrucible), the Molecular Foundry's platform for scientific records: installation guides, working example configurations, and a description of each component.

This repository is for labs and institutions that host Crucible themselves. The Molecular Foundry's own deployment is configured elsewhere.

## Components

| Component | Role | Source |
|---|---|---|
| API | Stores projects, samples, datasets and files, and decides who may see them. Signs users in with passwords or an identity provider | [crucible-api](https://github.com/MolecularFoundryCrucible/crucible-api) |
| Hub | Web interface for browsing and managing records. Optional | [crucible-hub](https://github.com/MolecularFoundryCrucible/crucible-hub) |
| nano-crucible | Python client and `crucible` command line used by people and instruments | [nano-crucible](https://github.com/MolecularFoundryCrucible/nano-crucible) |
| PostgreSQL | The API's database, with pgvector | |
| File store | Holds uploaded files: SeaweedFS in the bundle, or an external S3-compatible store or Google Cloud Storage | |
| Reverse proxy | Caddy: one address for the API and the Hub, and HTTPS | |

The API and the Hub are published as images on the GitHub Container Registry (`ghcr.io/molecularfoundrycrucible/crucible-api`, `.../crucible-hub`). Each release of this repository pins the versions it was tested with.

## Ways to install

| Method | Suits | Guide |
|---|---|---|
| Docker Compose | One host, a lab with a few workstations | [compose/README.md](compose/README.md) |

## Tests

`.github/workflows/compose.yml` installs the bundle as the guide describes, alone and with the Hub, and checks it through its public address. Run a job locally with `uv run --with pyyaml python scripts/run_ci_job.py compose-smoke` (or `compose-hub`); set `CRUCIBLE_API_IMAGE` to test another API image.

## License

BSD 3-Clause, see [LICENSE](LICENSE).
