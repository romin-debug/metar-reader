# METAR Reader

A small Flask app that looks up the current METAR (aviation weather report) for an
airport and explains it in plain English, for example:

> Mostly cloudy with light rain, 50°F (10°C), feels like 43°F, wind from the west at 23 mph.

Data comes from the [aviationweather.gov API](https://aviationweather.gov/data/api/).

## Run it

```bash
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000 and enter an airport code. You can type a 4-letter
ICAO code (`KJFK`, `EGLL`) or a 3-letter code (`JFK`, `HNL`, `YVR`). The app tries the
US, Alaska/Hawaii, and Canadian prefixes for you.

## Tests

```bash
python -m pytest
```

## Files

- `app.py`: Flask routes and the call to aviationweather.gov
- `metar_decoder.py`: turns raw METAR text into a friendly summary and details
- `templates/index.html`, `static/style.css`: the page
