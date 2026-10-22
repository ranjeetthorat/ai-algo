# Contributing to FastAlgo

FastAlgo is developed by TinyCompute. This guide is for anyone working on the
code. The detailed rules (runtime constraints, invariants, conventions) are in
[CLAUDE.md](CLAUDE.md), and the documentation map is [docs/INDEX.md](docs/INDEX.md).
Read both before changing anything near orders, risk, streaming or the database.

## Setup

Python 3.12+ with [uv](https://docs.astral.sh/uv/), and Node.js for the frontend.

```bash
git clone https://github.com/ranjeetthorat/ai-algo.git
cd ai-algo
uv sync
cp .sample.env .env            # fill in broker credentials
cd frontend && npm ci && npm run build && cd ..
uv run app.py                  # http://127.0.0.1:5000
```

Always use `uv run` for Python. Never use a global Python or a hand-made virtualenv.

## Workflow

1. Branch from `dev`. `main` is what ships to clients.
2. Make the change, with tests for any behaviour you change.
3. Run the checks:

   ```bash
   uv run ruff check . && uv run ruff format .
   uv run pytest test/ -v
   cd frontend && npm run lint && npm run test:run && npm run build && cd ..
   node scripts/brand-check.mjs
   ```

4. Commit using [Conventional Commits](https://www.conventionalcommits.org/): `feat:`,
   `fix:`, `docs:`, `refactor:` or `chore:`.
5. Open a pull request into `dev`.

## Rules that matter most

- **Order and risk code**: `services/risk/` and the order-path locking are
  invariants (see CLAUDE.md). Do not change them without a test that pins the
  behaviour.
- **Production runs eventlet with a single worker.** Code that works on
  `uv run app.py` can still fail in production. No `asyncio`, and no blocking
  across the eventlet boundary.
- **Schema changes ship as a migration** in `upgrade/`, registered in
  `migrate_all.py`.
- **User-facing text is written for traders**: name the cause and the next action,
  and never show a status code or an exception.
- **Branding**: the product name, links and logo come from
  `frontend/src/brand/brand.ts` (frontend) and `utils/brand.py` (backend). Never
  hard-code a product name or link to OpenAlgo properties. `scripts/brand-check.mjs`
  must pass. The design language is in
  [docs/design/brand/design-language.md](docs/design/brand/design-language.md).
- **No emojis or icons in text**, anywhere: code, logs, commits or docs.

## Adding a page

A page needs three registrations: the route in `frontend/src/App.tsx`, the same
path in `blueprints/react_app.py`, and the navigation entry in
`frontend/src/config/navigation.ts`. See CLAUDE.md, "Adding a page".

## Brokers

Broker plugins live in `broker/<name>/`. Use the `broker-integration` skill and
`docs/broker-integration-guide.md` when adding or changing one.

## License

FastAlgo is licensed under the GNU AGPL-3.0 (see [License.md](License.md) and
[NOTICE](NOTICE)). By contributing, you agree that your contribution is licensed
the same way.
