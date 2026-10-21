"""METAR Reader: a Flask web app that explains airport weather in plain English.

The user enters an airport code; the app fetches that airport's latest METAR
(a standardized aviation weather report) from the aviationweather.gov API and
decodes it into a friendly summary such as
"Partly cloudy, 72°F (22°C), wind from the south at 5 mph."

Run locally with::

    python app.py

then open http://127.0.0.1:5000.
"""

import re
from typing import Any

import requests
from flask import Flask, render_template, request

from metar_decoder import decode_metar

# Public METAR endpoint. No API key is required.
METAR_URL = "https://aviationweather.gov/api/data/metar"

# Identify this app to the API, as aviationweather.gov asks clients to do.
USER_AGENT = "METAR-Reader/1.0 (Flask demo app)"

# Seconds to wait for the API before showing a "service unavailable" message.
REQUEST_TIMEOUT = 10

# Airport codes are 3 (IATA, e.g. JFK) or 4 (ICAO, e.g. KJFK) letters/digits.
CODE_RE = re.compile(r"^[A-Z0-9]{3,4}$")

# Quick-pick links shown under the search box.
EXAMPLE_CODES = ["KJFK", "KLAX", "KORD", "KHIO", "EGLL", "RJTT"]

app = Flask(__name__)


class MetarError(Exception):
    """An error whose message is safe and friendly enough to show the user as-is."""


def candidate_ids(user_input: str) -> list[str]:
    """Convert what the user typed into the ICAO station IDs to request.

    Most people know 3-letter codes (JFK, LAX), but the API only accepts
    4-letter ICAO codes. For a 3-letter code we try the US (``K``),
    Alaska/Hawaii (``P``) and Canada (``C``) prefixes, in that order of
    preference.

    Args:
        user_input: The raw text from the search box.

    Returns:
        One or more ICAO codes, most preferred first.

    Raises:
        MetarError: If the input isn't a plausible airport code.
    """
    code = user_input.strip().upper()
    if not CODE_RE.match(code):
        raise MetarError("Please enter a 3- or 4-character airport code, like JFK or KJFK.")
    # Codes containing digits (e.g. small airfields like "S50") aren't IATA
    # codes, so prefixing them would only produce wrong stations.
    if len(code) == 3 and code.isalpha():
        return [f"K{code}", f"P{code}", f"C{code}"]
    return [code]


def fetch_metar(ids: list[str]) -> list[dict[str, Any]]:
    """Fetch the latest METAR records for the given stations.

    All IDs are sent in a single comma-separated request.

    Args:
        ids: ICAO station codes, e.g. ``["KJFK"]``.

    Returns:
        The API's JSON records (possibly empty). Each record includes
        ``icaoId``, ``name`` and ``rawOb`` (the raw METAR text).

    Raises:
        MetarError: If the API can't be reached or returns invalid data.
    """
    try:
        resp = requests.get(
            METAR_URL,
            params={"ids": ",".join(ids), "format": "json"},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise MetarError("Couldn't reach the aviation weather service right now. Please try again in a moment.") from exc

    # The API answers 204 No Content (empty body) when it has no report for
    # any of the stations. That means "not found", not a failure.
    if resp.status_code == 204 or not resp.content.strip():
        return []
    try:
        return resp.json()
    except ValueError as exc:
        raise MetarError("The aviation weather service sent back something unexpected. Please try again.") from exc


def lookup(user_input: str) -> dict[str, Any]:
    """Fetch and decode the current weather for an airport code.

    Args:
        user_input: The raw text from the search box.

    Returns:
        The decoded report from :func:`metar_decoder.decode_metar`, plus the
        resolved ``station`` code and the airport's full ``name``.

    Raises:
        MetarError: If the input is invalid, the station has no current
            report, or the API is unavailable.
    """
    ids = candidate_ids(user_input)
    by_station = {rec.get("icaoId"): rec for rec in fetch_metar(ids)}
    # The API doesn't return results in request order, so choose the first
    # station in *our* preference order that came back.
    record = next((by_station[i] for i in ids if i in by_station), None)
    if not record or not record.get("rawOb"):
        raise MetarError(
            f"No current weather report found for \"{user_input.strip().upper()}\". "
            "Check the code; not every airfield publishes METARs."
        )

    report = decode_metar(record["rawOb"])
    report["station"] = record.get("icaoId", report.get("station"))
    report["name"] = record.get("name")
    return report


@app.route("/")
def index() -> str:
    """Render the search page and, if ``?code=`` is given, the weather report.

    The form uses GET so every result has a shareable URL, e.g. ``/?code=JFK``.
    """
    query = request.args.get("code", "").strip()
    report = error = None
    if query:
        try:
            report = lookup(query)
        except MetarError as exc:
            error = str(exc)
    return render_template("index.html", query=query, report=report, error=error, examples=EXAMPLE_CODES)


if __name__ == "__main__":
    # Development server only (auto-reload and in-browser debugger). It listens
    # on 127.0.0.1, so it's not reachable from other machines. For a public
    # deployment, run the app with a production WSGI server instead.
    app.run(debug=True)
