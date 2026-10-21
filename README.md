# METAR Reader

A small web app that turns cryptic airport weather reports into plain English.

Airports publish their current weather as a **METAR**, a standardized report that looks like this:

```
METAR EGLL 211020Z AUTO 28020KT 9999 -RA BKN011 BKN018 10/09 Q0998
```

Type an airport code into METAR Reader and it tells you what that report means:

> 🌧️ **Mostly cloudy with light rain, 50°F (10°C), feels like 43°F, wind from the west at 23 mph.**

## Features

- **Plain-English summary**: sky, temperature, wind and any rain, snow or fog, in one sentence.
- **Details for the curious**: feels-like temperature, wind gusts, cloud heights, visibility, humidity, dew point, pressure, and the age of the report.
- **Codes you already know**: enter a 3-letter code (`JFK`, `HNL`, `YVR`) or a 4-letter ICAO code (`KJFK`, `EGLL`, `RJTT`).
- **Works worldwide**: handles both US-style and international report formats.
- **Shareable links**: every result has its own URL, e.g. `/?code=JFK`.
- **Original report included**: the raw METAR is shown beneath the summary.

## Installation

You need **Python 3.9 or newer** and **git**.

1. Clone the repository:

   ```bash
   git clone https://github.com/romin-debug/metar-reader.git
   cd metar-reader
   ```

2. Create and activate a virtual environment (recommended):

   ```bash
   python -m venv .venv
   ```

   - Windows (PowerShell): `.venv\Scripts\Activate.ps1`
   - macOS / Linux: `source .venv/bin/activate`

3. Install the dependencies:

   ```bash
   pip install -r requirements.txt
   ```

## Usage

Start the app:

```bash
python app.py
```

Then open **http://127.0.0.1:5000** in your browser, type an airport code, and press **Get weather**.

No API key or account is needed. Weather data comes from the free [aviationweather.gov API](https://aviationweather.gov/data/api/).

`python app.py` starts Flask's development server, which is only reachable from your own computer. To put the app on the internet, run it behind a production WSGI server instead.

## Airport codes

| You type | App looks up | Airport |
|---|---|---|
| `JFK` or `KJFK` | KJFK | New York JFK |
| `HNL` | PHNL | Honolulu |
| `YVR` | CYVR | Vancouver |
| `EGLL` | EGLL | London Heathrow |

For a 3-letter code, the app tries the US (`K`), Alaska/Hawaii (`P`) and Canadian (`C`) versions. Airports elsewhere need their 4-letter ICAO code.

## Running the tests

The tests use [pytest](https://pytest.org), which `requirements.txt` installs. Run them from the project folder:

```bash
python -m pytest                          # all tests
python -m pytest tests/test_app.py        # just the web app tests
python -m pytest "tests/test_app.py::test_mock_metar_summary[dense-fog]"   # a single test
```

There are two test files:

- **`tests/test_metar_decoder.py`** tests the decoder by itself: weather phrases like `-SHRA` → "light rain showers", visibility formats, compass directions, and handling of unusual input.
- **`tests/test_app.py`** tests the whole web app with mock METAR readings. It checks that:
  - each mock report produces the correct plain-English summary
  - the result page shows the right details
  - airport codes are cleaned up and expanded correctly
  - unknown airports, service outages and bad data show friendly error messages

The tests never connect to the internet. In `tests/test_app.py`, the call to aviationweather.gov is replaced with a mock that returns a canned response, so the tests are fast and give the same results every time.

### Adding a weather case

To check how a new METAR is interpreted, add an entry to `WEATHER_CASES` in `tests/test_app.py`: the raw report and the summary sentence you expect.

```python
pytest.param(
    "METAR KSFO 211056Z 00000KT 1/4SM FG VV002 12/12 A3001",
    "Fog, 54°F (12°C), calm winds, visibility 1/4 mile.",
    id="dense-fog",
),
```

## How it works

1. `app.py` checks the airport code and fetches the latest METAR from aviationweather.gov.
2. `metar_decoder.py` reads each part of the report (wind, visibility, weather, clouds, temperature, pressure) and writes the summary and details. The decoder is built from scratch and doesn't use a METAR library.
3. `templates/index.html` and `static/style.css` display the result.

The app decodes current conditions only. It skips forecast sections and most of the remarks at the end of a report.

## Disclaimer

METAR Reader is for general information only. **Do not use it for flight planning or other decisions where safety is at stake.** Use official aviation weather sources instead.

## License

Released under the [MIT License](LICENSE).
