# Known failing tests

Tests that fail on a clean checkout, before any change of yours. Check this list
before treating a red run as a regression. Each entry gives the cause, so it can
also serve as the starting point for a fix.

Recorded 2026-10-23 during Phase 2 milestone M2.1 (Docker removal), on Windows
with `uv run pytest test/`. None of these files were touched by that change. If
you fix one, delete its entry.

## Summary

| File | Result | Cause in one line |
| --- | --- | --- |
| `test/test_tradesmart_rate_limiter.py` | 7 of 15 fail | Test predates a change to `_reserve_slot()`'s signature |
| `test/test_telegram_startup.py` | 1 fails | Needs `eventlet`, which only production installs |
| `test/test_telegram_bot.py` | 1 fails | Async test, no async pytest plugin |
| `test/test_telegram_charts.py` | 1 fails | Async test, no async pytest plugin |
| `test/test_websocket.py` | 3 fail | Async tests, no async pytest plugin |
| `test/test_websocket_service.py` | 6 errors | Manual script: asks for a `client` fixture that does not exist |
| `test/test_strategy_module_db.py` | Hangs sometimes | Slow SQLite on Windows hits the 60 s per-test timeout |
| `test/test_python_editor.py` | Passes, but has side effects | Talks to a live server on port 5000 and can leave a file behind |

## Skipping them

To run the suite without the known failures:

```sh
uv run pytest test/ \
  --ignore=test/test_tradesmart_rate_limiter.py \
  --ignore=test/test_telegram_startup.py \
  --ignore=test/test_telegram_bot.py \
  --ignore=test/test_telegram_charts.py \
  --ignore=test/test_websocket.py \
  --ignore=test/test_websocket_service.py \
  --ignore=test/test_python_editor.py
```

Run `test/test_strategy_module_db.py` on its own if it hangs inside the full run;
alone it passes (44 of 44, about two minutes).

The full suite takes longer than ten minutes, so run it where nothing will cut
it off, and keep the machine awake: the pacing tests measure wall-clock time.

## Details

### test_tradesmart_rate_limiter.py

Six tests fail with:

```
TypeError: _reserve_slot() missing 4 required positional arguments:
'lock', 'reserved', 'max_per_second', and 'max_per_minute'
```

`broker/tradesmart/api/rate_limiter.py` changed `_reserve_slot()` to take its
budget as arguments when quotes got their own 100/sec budget (#1928, commit
`b8e4cbdd9`, 2026-08-28). The test still calls it with no arguments. The seventh
failure, `test_the_call_after_the_cap_waits_a_full_second`, is the same drift
seen as a timing assertion (`elapsed >= 0.9` gets about 0.003 s).

**Fix:** update the test to the new signature, or test through the public
rate-limited call instead of the private helper.

### test_telegram_startup.py

`test_bot_starts_and_stops_cleanly_in_eventlet_env` starts a child process that
does `import eventlet`, and fails with `ModuleNotFoundError: No module named
'eventlet'`. `eventlet` and `gunicorn` come from `requirements-nginx.txt`, which
only server installs use, so a development environment does not have them.

**Fix:** `pytest.importorskip("eventlet")` at the top of the test, so it skips
where eventlet is absent and still runs on a server.

### test_telegram_bot.py, test_telegram_charts.py, test_websocket.py

These are `async def` tests. pytest needs a plugin such as `pytest-asyncio` to
run them, and none is configured, so each fails with "async def functions are not
natively supported". They were written as scripts to run by hand against a live
bot or feed.

**Fix:** move them out of `test/` into a manual-scripts folder, or add the plugin
and mark them as integration tests that need a live service.

### test_websocket_service.py

Six tests error with `fixture 'client' not found`. The file is a manual script:
`client` is meant to be a connected WebSocket client created in its `__main__`
block, not a pytest fixture.

**Fix:** same as above. Move it out of `test/`, or give it a real fixture that
skips when no feed is running.

### test_strategy_module_db.py

In the full run, the third test sometimes hangs until pytest-timeout (60 s,
`pyproject.toml`) stops it. On its own the file passes every time. The cause is
slow SQLite on Windows under load, not a defect in the module.

**Fix:** none needed for correctness. Run it on its own when it trips.

### test_python_editor.py

This is a script that posts to `http://127.0.0.1:5000/python`. If a dev server
is running, it writes `test_editor_strategy.py` to the current directory, tries
to upload it, and crashes on the login page's HTML before it deletes the file.
pytest still reports it as passed, because the test returns instead of
asserting. The stray `test_editor_strategy.py` in the repo root comes from here.
Without a login session nothing is uploaded.

**Fix:** move it out of `test/`, or skip it when no server is reachable, and
write its temporary file to `tmp_path`.
