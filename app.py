"""METAR Reader: look up an airport's current weather report and explain it in plain English."""

import re

import requests
from flask import Flask, render_template, request

from metar_decoder import decode_metar

METAR_URL = "https://aviationweather.gov/api/data/metar"
USER_AGENT = "METAR-Reader/1.0 (Flask demo app)"
CODE_RE = re.compile(r"^[A-Z0-9]{3,4}$")
EXAMPLE_CODES = ["KJFK", "KLAX", "KORD", "KHIO", "EGLL", "RJTT"]

app = Flask(__name__)


class MetarError(Exception):
    """A problem worth showing to the user as-is."""


def candidate_ids(user_input):
    """Turn what the user typed into the ICAO codes to request.

    Most people know 3-letter codes (JFK, LAX), but the API needs 4-letter
    ICAO codes. For 3-letter input we try the US (K), Alaska/Hawaii (P) and
    Canada (C) prefixes, in that order of preference.
    """
    code = user_input.strip().upper()
    if not CODE_RE.match(code):
        raise MetarError("Please enter a 3- or 4-character airport code, like JFK or KJFK.")
    if len(code) == 3 and code.isalpha():
        return [f"K{code}", f"P{code}", f"C{code}"]
    return [code]


def fetch_metar(ids):
    """Return the list of METAR records the API has for the given station IDs."""
    try:
        resp = requests.get(
            METAR_URL,
            params={"ids": ",".join(ids), "format": "json"},
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise MetarError("Couldn't reach the aviation weather service right now. Please try again in a moment.") from exc

    # The API answers 204 No Content when it has no report for the station.
    if resp.status_code == 204 or not resp.content.strip():
        return []
    try:
        return resp.json()
    except ValueError as exc:
        raise MetarError("The aviation weather service sent back something unexpected. Please try again.") from exc


def lookup(user_input):
    ids = candidate_ids(user_input)
    by_station = {rec.get("icaoId"): rec for rec in fetch_metar(ids)}
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
def index():
    query = request.args.get("code", "").strip()
    report = error = None
    if query:
        try:
            report = lookup(query)
        except MetarError as exc:
            error = str(exc)
    return render_template("index.html", query=query, report=report, error=error, examples=EXAMPLE_CODES)


if __name__ == "__main__":
    app.run(debug=True)
