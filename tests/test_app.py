"""Unit tests for app.py using mock METAR readings.

Every test replaces ``requests.get`` with a mock that returns a canned
aviationweather.gov response, so all of app.py runs for real (input handling,
the API request, error handling, decoding and the rendered page) without any
network access.
"""

import json
from unittest.mock import patch

import pytest
import requests

import app as metar_app


# --- Helpers and fixtures -------------------------------------------------

def api_response(records=None, status=200, body=None):
    """Build a real ``requests.Response`` like the one aviationweather.gov sends.

    Args:
        records: List of METAR records to return as JSON.
        status: HTTP status code (204 means "no report for that station").
        body: Raw response body, overriding ``records`` (for malformed data).
    """
    resp = requests.Response()
    resp.status_code = status
    resp.encoding = "utf-8"
    if body is None:
        body = "" if records is None else json.dumps(records)
    resp._content = body.encode("utf-8")
    return resp


def metar_record(raw, name="Test Airport, XX, US"):
    """One API record for a raw METAR, with the station ID taken from the text."""
    station = raw.split()[1]
    return {"icaoId": station, "name": name, "rawOb": raw}


@pytest.fixture(autouse=True)
def mock_get():
    """Replace the HTTP call in every test, so tests never touch the network."""
    with patch("app.requests.get") as mock:
        mock.return_value = api_response(status=204)
        yield mock


@pytest.fixture
def client():
    metar_app.app.testing = True
    return metar_app.app.test_client()


def page(client, code):
    """Fetch the page for an airport code and return its HTML."""
    resp = client.get("/", query_string={"code": code})
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


# --- Mock METAR readings are interpreted correctly ------------------------

# (raw METAR, expected one-sentence summary). Each expected value was checked
# by hand against the raw report; comments note the less obvious conversions.
WEATHER_CASES = [
    pytest.param(
        "METAR KHIO 210953Z AUTO 00000KT 10SM CLR 06/03 A2997 RMK AO2 SLP145 T00560033",
        "Clear skies, 42°F (6°C), calm winds.",  # T0056 = 5.6°C = 42°F
        id="clear-and-calm",
    ),
    pytest.param(
        "METAR KJFK 210951Z 02014KT 10SM FEW250 11/02 A3023 RMK AO2 SLP236 T01060022",
        "Mostly clear, 51°F (11°C), wind from the north-northeast at 16 mph.",  # 14 kt = 16 mph
        id="few-clouds-breezy",
    ),
    pytest.param(
        "METAR EGLL 211020Z AUTO 28020KT 9999 -RA BKN011 BKN018 10/09 Q0998",
        "Mostly cloudy with light rain, 50°F (10°C), feels like 43°F, wind from the west at 23 mph.",
        id="light-rain-international",
    ),
    pytest.param(
        "METAR PANC 210953Z 35010G18KT 10SM FEW040 BKN075 03/M06 A2944",
        "Mostly cloudy, 37°F (3°C), feels like 30°F, wind from the north at 12 mph, gusting to 21 mph.",
        id="gusty-and-cold",
    ),
    pytest.param(
        "METAR KXYZ 211053Z 18012G25KT 1 1/2SM +TSRA VV005 M02/M04 A2990",
        "Thunderstorms with heavy rain, 28°F (-2°C), feels like 17°F, "
        "wind from the south at 14 mph, gusting to 29 mph, visibility 1 1/2 miles.",
        id="thunderstorm",
    ),
    pytest.param(
        "METAR KDEN 211053Z 36015KT 1/2SM SN FZFG OVC008 M05/M07 A2985",
        "Overcast with snow and freezing fog, 23°F (-5°C), feels like 9°F, "
        "wind from the north at 17 mph, visibility 1/2 mile.",
        id="snow-and-freezing-fog",
    ),
    pytest.param(
        "METAR KSFO 211056Z 00000KT 1/4SM FG VV002 12/12 A3001",
        "Fog, 54°F (12°C), calm winds, visibility 1/4 mile.",  # VV = sky hidden, so lead with the fog
        id="dense-fog",
    ),
    pytest.param(
        "METAR KMIA 211853Z 14008KT 10SM SCT030 33/26 A2995",
        "Partly cloudy, 91°F (33°C), feels like 108°F, wind from the southeast at 9 mph.",  # heat index
        id="hot-and-humid",
    ),
    pytest.param(
        "METAR LFPG 211030Z VRB03KT CAVOK 22/12 Q1020 NOSIG",
        "Clear skies, 72°F (22°C), variable winds at 3 mph.",
        id="cavok-variable-wind",
    ),
    pytest.param(
        "METAR VIDP 210930Z 30004KT 1500 HZ NSC 28/14 Q1012 NOSIG",
        "Clear skies with haze, 82°F (28°C), wind from the west-northwest at 5 mph, "
        "visibility 0.9 miles (1,500 m).",
        id="haze-metric-visibility",
    ),
]


@pytest.mark.parametrize("raw, expected_summary", WEATHER_CASES)
def test_mock_metar_summary(client, mock_get, raw, expected_summary):
    mock_get.return_value = api_response([metar_record(raw)])
    html = page(client, raw.split()[1])
    assert expected_summary in html


def test_page_shows_station_details_and_raw_report(client, mock_get):
    raw = "METAR KJFK 210951Z 02014KT 10SM FEW250 11/02 A3023 RMK AO2 SLP236 T01060022"
    mock_get.return_value = api_response([metar_record(raw, name="New York/JF Kennedy Intl, NY, US")])
    html = page(client, "KJFK")

    assert "New York/JF Kennedy Intl, NY, US" in html
    assert "🌤️" in html                          # few clouds icon
    assert "51°F</div>" in html                  # big headline temperature
    assert "From the north-northeast (20°) at 16 mph (14 knots)" in html
    assert "A few clouds at 25,000 ft" in html   # FEW250 = 250 hundred feet
    assert "Good, 10 miles" in html
    assert "56%" in html                         # humidity from 10.6°C / 2.2°C
    assert "30.23 inHg (1024 hPa)" in html
    assert raw in html                           # original METAR is shown


def test_trend_forecast_is_not_reported_as_current_weather(client, mock_get):
    # Everything after TEMPO is a forecast; the current wind has no gusts.
    raw = "METAR RJTT 211030Z 20019KT 9999 FEW020 27/20 Q1007 TEMPO 22024G36KT"
    mock_get.return_value = api_response([metar_record(raw)])
    html = page(client, "RJTT")
    assert "wind from the south-southwest at 22 mph." in html
    assert "gusting" not in html


# --- Airport code handling ------------------------------------------------

def test_api_request_is_built_correctly(client, mock_get):
    page(client, "jfk")
    mock_get.assert_called_once()
    args, kwargs = mock_get.call_args
    assert args == (metar_app.METAR_URL,)
    assert kwargs["params"] == {"ids": "KJFK,PJFK,CJFK", "format": "json"}
    assert kwargs["headers"]["User-Agent"] == metar_app.USER_AGENT
    assert kwargs["timeout"] == metar_app.REQUEST_TIMEOUT


@pytest.mark.parametrize("typed, expected_ids", [
    ("KJFK", ["KJFK"]),                       # 4-letter ICAO codes are used as-is
    ("  egll ", ["EGLL"]),                    # whitespace and case are cleaned up
    ("LAX", ["KLAX", "PLAX", "CLAX"]),         # 3-letter codes try US, Alaska/Hawaii, Canada
    ("S50", ["S50"]),                         # codes with digits aren't IATA, so no prefix
])
def test_candidate_ids(typed, expected_ids):
    assert metar_app.candidate_ids(typed) == expected_ids


def test_three_letter_code_prefers_us_station_whatever_the_api_order(client, mock_get):
    # The API may list results in any order; KXXX should still win over CXXX.
    mock_get.return_value = api_response([
        metar_record("METAR CABC 211000Z 00000KT 10SM OVC010 01/00 A3000"),
        metar_record("METAR KABC 211000Z 00000KT 10SM CLR 20/10 A3000"),
    ])
    report = metar_app.lookup("ABC")
    assert report["station"] == "KABC"
    assert report["sky"] == "Clear skies"


def test_three_letter_code_falls_back_to_hawaii(client, mock_get):
    raw = "METAR PHNL 211053Z 07013G19KT 10SM FEW030 25/18 A3002"
    mock_get.return_value = api_response([metar_record(raw, name="Honolulu Intl, HI, US")])
    html = page(client, "HNL")
    assert "Honolulu Intl" in html
    assert "PHNL" in html


@pytest.mark.parametrize("typed", ["AB", "ABCDE", "K-JF", "<script>"])
def test_invalid_code_shows_error_without_calling_api(client, mock_get, typed):
    html = page(client, typed)
    assert "3- or 4-character airport code" in html
    mock_get.assert_not_called()


def test_empty_search_shows_form_only(client, mock_get):
    html = client.get("/").get_data(as_text=True)
    assert 'name="code"' in html
    assert 'role="alert"' not in html
    mock_get.assert_not_called()


# --- Missing data and service failures ------------------------------------

@pytest.mark.parametrize("response", [
    pytest.param(api_response(status=204), id="204-no-content"),
    pytest.param(api_response([]), id="empty-list"),
    pytest.param(api_response([{"icaoId": "ZZZZ", "name": "No report"}]), id="record-without-metar"),
])
def test_unknown_station(client, mock_get, response):
    mock_get.return_value = response
    html = page(client, "ZZZZ")
    assert "No current weather report found for &#34;ZZZZ&#34;" in html


@pytest.mark.parametrize("error", [requests.Timeout(), requests.ConnectionError()])
def test_service_unreachable(client, mock_get, error):
    mock_get.side_effect = error
    html = page(client, "KJFK")
    assert "reach the aviation weather service" in html


def test_service_server_error(client, mock_get):
    mock_get.return_value = api_response(status=500, body="Internal Server Error")
    html = page(client, "KJFK")
    assert "reach the aviation weather service" in html


def test_service_returns_malformed_json(client, mock_get):
    mock_get.return_value = api_response(body="<html>maintenance</html>")
    html = page(client, "KJFK")
    assert "sent back something unexpected" in html


def test_api_text_is_html_escaped(client, mock_get):
    raw = "METAR KJFK 210951Z 02014KT 10SM FEW250 11/02 A3023"
    mock_get.return_value = api_response([metar_record(raw, name="<script>alert(1)</script>")])
    html = page(client, "KJFK")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
