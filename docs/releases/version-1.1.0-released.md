# Version 1.1.0 Released

**Date: 23rd October 2026**

**Cleanup release: the Docker tooling is gone, FastAlgo has a public home page you can host anywhere, and the startup banner now carries the FastAlgo name.**

This is the first release of Phase 2, milestone M2.1. It has 4 commits since
1.0.0. Nothing changes for a running installation: no database migration, no new
setting, no change to the API, the SDK, webhooks or any page in the app. Every
client is installed and updated by the TinyCompute team, so the upstream Docker
path was never used, and it is removed rather than left to drift.

**Highlights**

- **Docker tooling removed (`7930cc04e`)** - `Dockerfile`, `docker-compose.yaml`,
  `.dockerignore`, `docker-build.sh` and `.bat`, the container entrypoint
  `start.sh`, `DOCKER_README.md`, the six Docker install scripts and readmes in
  `install/`, `docs/docker/`, `docs/design/11-docker/`, and the `docker-build` and
  `docker-manifest` CI jobs. Everything that referred to them was repointed: the
  tests that read `start.sh` and `docker-run`, the security-audit checks (now
  `install/install.sh` and `.sample.env`), the broker-integration skill and guide,
  `.sample.env` comments and `CLAUDE.md`. The bare-metal scripts (`install.sh`,
  `install-multi.sh`, `update.sh`) are kept.
- **Static public site (`7930cc04e`)** - a new `static/` folder holds the home page
  as one self-contained HTML file, without the log-in and installation links, for
  hosting on S3 or GitHub Pages. It has no build step and no external files, works
  in light and dark mode, and fits a phone screen. The brand check now scans it.
  See `static/README.md` for hosting steps.
- **Startup banner says FastAlgo (`872c559fc`)** - the first line printed at startup
  read "Starting OpenAlgo...". It now reads "Starting FastAlgo...", matching the
  troubleshooting hint in `upgrade/init_db.py`, whose fresh-install message also
  now names FastAlgo.
- **Known failing tests recorded (`cc3c14de1`)** - 13 failures, 6 errors and one
  occasional hang that were already present before this release are listed in
  `docs/test/KNOWN_FAILING_TESTS.md`, each with its cause, a skip command and a
  suggested fix. None are caused by this release.

**Upgrading**

`git pull` on `main`. No migration and no restart beyond the usual one are needed.

**Dependencies**

No dependencies changed.

**Contributors**

- **@ranjeetthorat** - Phase 2 scope and M2.1: Docker removal, the public site and
  the startup banner fix (`7930cc04e`, `872c559fc`, `cc3c14de1`).

**Links**

- Repository: https://github.com/ranjeetthorat/ai-algo
- Product site: https://fastalgo.tinycompute.site
- Support: https://www.tinycompute.site
