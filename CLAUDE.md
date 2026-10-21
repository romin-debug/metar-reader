# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -r requirements.txt          # flask, requests, pytest
python app.py                            # dev server at http://127.0.0.1:5000 (debug mode)
python -m pytest                         # all tests (use `python -m` so the repo root is importable)
python -m pytest tests/test_metar_decoder.py::test_weather_phrases   # single test
```

There is no linter or build step configured.

On Windows, printing decoder output (emoji icons, `°`) to the console needs `PYTHONIOENCODING=utf-8`, or it fails with `UnicodeEncodeError`.

## Architecture

A Flask app with one page. The user enters an airport code, the app fetches that airport's METAR from aviationweather.gov, and the page shows it decoded into plain English.

**Request flow** (`app.py`): `index()` reads `?code=` (a GET form, so result URLs can be shared) and calls `lookup()`. That calls `candidate_ids()` → `fetch_metar()` → `decode_metar()`. Every error meant for the user is raised as `MetarError`, whose message is shown verbatim in the page's error card.

**Weather API** (`https://aviationweather.gov/api/data/metar?ids=...&format=json`):
- Returns **HTTP 204 with an empty body** for unknown stations. That case is not an error.
- Each record has `icaoId`, `name` (the full airport name) and `rawOb` (the raw METAR string). Only `rawOb` is decoded. The pre-parsed JSON fields are deliberately ignored.
- 3-letter input is expanded to `K`/`P`/`C` prefixes and fetched in **one** comma-separated request. The API returns results in its own order (not request order), so `lookup()` picks a station by our preference order.

**Decoder** (`metar_decoder.py`, no external METAR library):
- `decode_metar(raw, now=None)` returns a plain dict. The template relies only on `station`, `name` (added by `app.py`), `icon`, `temp_f`, `summary`, `details` (a list of `(label, text)` tuples) and `raw`. Other keys appear only when their group is present in the report.
- It walks tokens through one `if/elif` chain of regexes, and **order matters**:
  - Visibility is accepted only once (`"visibility" not in result`), so later 4-digit tokens aren't misread.
  - Split fractions like `1 1/2SM` are handled by looking ahead one token.
  - `RE*` (recent weather) tokens are skipped before the weather regex runs.
  - Unrecognised tokens are silently ignored. The decoder should never raise on odd input.
- Parsing stops at `RMK`/`TEMPO`/`BECMG`/`NOSIG`, so forecast trends aren't read as current conditions. A pre-pass first takes the precise temperature from the `T` group in remarks (e.g. `T01060022` = 10.6°C). Integer temperatures from the main body are only used through `setdefault`, as a fallback.
- `summary` (one sentence) and `details` are built last, from the parsed fields, by `build_summary()` and `build_details()`. Change those functions to change the wording.
- METAR wind direction is the direction the wind blows **from**. Keep the wording "wind from the X".

## Tests

- Decoder tests pass a fixed `NOW` to `decode_metar` so "X minutes ago" and month rollover are deterministic.
- App tests monkeypatch `app.fetch_metar`, so no test touches the network.
