"""Decode raw METAR weather reports into plain English.

A METAR looks like:

    METAR KHIO 210953Z AUTO 00000KT 10SM CLR 06/03 A2997 RMK AO2 SLP145 T00560033

Each space-separated group has a fixed meaning (station, time, wind, visibility,
weather, clouds, temperature/dewpoint, pressure). Unknown groups are ignored so a
single odd token never breaks the whole report.
"""

import math
import re
from datetime import datetime, timedelta, timezone

WIND_RE = re.compile(r"^(?P<dir>\d{3}|VRB)(?P<speed>\d{2,3})(?:G(?P<gust>\d{2,3}))?(?P<unit>KT|MPS|KMH)$")
WIND_VARIATION_RE = re.compile(r"^(?P<start>\d{3})V(?P<end>\d{3})$")
VIS_MILES_RE = re.compile(r"^(?P<mod>[PM])?(?P<value>\d+(?:/\d+)?)SM$")
VIS_METERS_RE = re.compile(r"^(?P<value>\d{4})(?:NDV|[NSEW]{1,2})?$")
CLOUD_RE = re.compile(r"^(?P<cover>FEW|SCT|BKN|OVC|VV)(?P<height>\d{3}|///)(?P<type>CB|TCU|///)?$")
# Automated stations may detect convective clouds without measuring cover or height.
UNKNOWN_CLOUD_RE = re.compile(r"^/{6}(?P<type>CB|TCU)$")
TEMP_RE = re.compile(r"^(?P<temp>M?\d{2})/(?P<dew>M?\d{2})?$")
PRESSURE_RE = re.compile(r"^(?P<unit>[AQ])(?P<value>\d{4})$")
TIME_RE = re.compile(r"^(?P<day>\d{2})(?P<hour>\d{2})(?P<minute>\d{2})Z$")
# Remarks group with temperature/dewpoint to tenths of a degree, e.g. T00560033.
PRECISE_TEMP_RE = re.compile(r"^T(?P<tsign>[01])(?P<temp>\d{3})(?:(?P<dsign>[01])(?P<dew>\d{3}))?$")
WEATHER_RE = re.compile(
    r"^(?P<intensity>[-+]|VC)?"
    r"(?P<descriptor>MI|PR|BC|DR|BL|SH|TS|FZ)?"
    r"(?P<phenomena>(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)*)$"
)

COMPASS_POINTS = [
    "north", "north-northeast", "northeast", "east-northeast",
    "east", "east-southeast", "southeast", "south-southeast",
    "south", "south-southwest", "southwest", "west-southwest",
    "west", "west-northwest", "northwest", "north-northwest",
]

TO_MPH = {"KT": 1.15078, "MPS": 2.23694, "KMH": 0.621371}

DESCRIPTORS = {
    "MI": "shallow",
    "PR": "partial",
    "BC": "patches of",
    "DR": "low drifting",
    "BL": "blowing",
}

PHENOMENA = {
    "DZ": "drizzle", "RA": "rain", "SN": "snow", "SG": "snow grains",
    "IC": "ice crystals", "PL": "ice pellets", "GR": "hail", "GS": "small hail",
    "UP": "unknown precipitation", "BR": "mist", "FG": "fog", "FU": "smoke",
    "VA": "volcanic ash", "DU": "dust", "SA": "sand", "HZ": "haze", "PY": "spray",
    "PO": "dust whirls", "SQ": "squalls", "FC": "funnel cloud",
    "SS": "sandstorm", "DS": "dust storm",
}

CLOUD_COVER = {
    "FEW": "A few clouds",
    "SCT": "Scattered clouds",
    "BKN": "Broken clouds",
    "OVC": "Overcast",
}

# Overall sky condition, keyed by the most extensive cloud layer reported.
SKY_SUMMARY = {
    None: "Clear skies",
    "FEW": "Mostly clear",
    "SCT": "Partly cloudy",
    "BKN": "Mostly cloudy",
    "OVC": "Overcast",
    "VV": "Sky obscured",
}
COVER_RANK = {"FEW": 1, "SCT": 2, "BKN": 3, "OVC": 4, "VV": 5}

# Groups after which the rest of the report is remarks or a forecast trend.
END_OF_BODY = {"RMK", "TEMPO", "BECMG", "NOSIG"}


def compass_name(degrees):
    return COMPASS_POINTS[round((degrees % 360) / 22.5) % 16]


def c_to_f(celsius):
    return celsius * 9 / 5 + 32


def parse_signed_temp(text):
    """'M05' -> -5, '12' -> 12."""
    return -int(text[1:]) if text.startswith("M") else int(text)


def parse_fraction(text):
    """'1 1/2' -> 1.5, '3/4' -> 0.75, '10' -> 10."""
    total = 0.0
    for part in text.split():
        if "/" in part:
            num, den = part.split("/")
            total += int(num) / int(den)
        else:
            total += int(part)
    return total


def relative_humidity(temp_c, dew_c):
    """Magnus approximation, returns percent."""
    def vapor(t):
        return math.exp(17.625 * t / (243.04 + t))
    return 100 * vapor(dew_c) / vapor(temp_c)


def feels_like_f(temp_f, wind_mph, humidity):
    """Wind chill when cold and breezy, heat index when hot; otherwise None."""
    if temp_f <= 50 and wind_mph > 3:
        v = wind_mph ** 0.16
        return 35.74 + 0.6215 * temp_f - 35.75 * v + 0.4275 * temp_f * v
    if temp_f >= 80 and humidity is not None:
        t, rh = temp_f, humidity
        return (-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh
                - 0.00683783 * t * t - 0.05481717 * rh * rh + 0.00122874 * t * t * rh
                + 0.00085282 * t * rh * rh - 0.00000199 * t * t * rh * rh)
    return None


def describe_weather(match):
    """Turn a present-weather group like '-SHRA' into 'light rain showers'."""
    intensity = match["intensity"]
    descriptor = match["descriptor"]
    codes = [match["phenomena"][i:i + 2] for i in range(0, len(match["phenomena"]), 2)]

    if intensity == "+" and codes == ["FC"]:
        return "tornado or waterspout"

    text = " and ".join(PHENOMENA[c] for c in codes)
    intensity_word = {"-": "light", "+": "heavy"}.get(intensity)
    if intensity_word and text:
        text = f"{intensity_word} {text}"

    if descriptor == "SH":
        text = f"{text} showers" if text else "showers"
    elif descriptor == "TS":
        text = f"thunderstorms with {text}" if text else "thunderstorms"
    elif descriptor == "FZ":
        text = f"freezing {text}"
    elif descriptor:
        text = f"{DESCRIPTORS[descriptor]} {text}"

    if intensity_word and not codes:
        text = f"{intensity_word} {text}"
    if intensity == "VC":
        text = f"{text} nearby"
    return text


def observation_time(day, hour, minute, now):
    """METARs only give day-of-month; assume the most recent matching date."""
    year, month = now.year, now.month
    for _ in range(3):
        try:
            candidate = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        except ValueError:
            candidate = None
        if candidate and candidate <= now + timedelta(hours=1):
            return candidate
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return None


def time_ago(then, now):
    minutes = int((now - then).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    return f"{hours // 24} days ago"


def format_visibility(token_mod, value_text, miles):
    if token_mod == "P":
        return f"More than {value_text} miles"
    if token_mod == "M":
        return f"Less than {value_text} mile{'s' if miles > 1 else ''}"
    return f"{value_text} mile{'s' if miles != 1 else ''}"


def visibility_quality(miles):
    if miles >= 5:
        return "good"
    if miles >= 3:
        return "moderate"
    if miles >= 1:
        return "poor"
    return "very poor"


def choose_icon(weather_codes, top_cover):
    joined = " ".join(weather_codes)
    if "TS" in joined:
        return "⛈️"
    if any(c in joined for c in ("SN", "SG", "PL", "IC")):
        return "🌨️"
    if any(c in joined for c in ("RA", "DZ", "SH", "GR", "GS", "UP")):
        return "🌧️"
    if any(c in joined for c in ("FG", "BR", "HZ", "FU", "DU", "SA")):
        return "🌫️"
    return {"OVC": "☁️", "VV": "☁️", "BKN": "🌥️", "SCT": "⛅", "FEW": "🌤️"}.get(top_cover, "☀️")


def decode_metar(raw, now=None):
    """Decode a raw METAR string into a dict of plain-English fields.

    The returned dict always has 'raw', 'summary', 'icon' and 'details'
    (a list of (label, text) pairs); other keys are present when the
    corresponding group appears in the report.
    """
    now = now or datetime.now(timezone.utc)
    tokens = raw.split()
    result = {"raw": raw.strip(), "weather": [], "clouds": [], "notes": []}
    weather_codes = []
    top_cover = None
    cavok = False

    # Remarks may carry a more precise temperature; grab it before we stop at RMK.
    if "RMK" in tokens:
        for token in tokens[tokens.index("RMK") + 1:]:
            m = PRECISE_TEMP_RE.match(token)
            if m:
                result["temp_c"] = int(m["temp"]) / 10 * (-1 if m["tsign"] == "1" else 1)
                if m["dew"]:
                    result["dewpoint_c"] = int(m["dew"]) / 10 * (-1 if m["dsign"] == "1" else 1)
                break

    i = 0
    if tokens and tokens[0] in ("METAR", "SPECI"):
        result["report_type"] = tokens[0]
        i = 1
    if i < len(tokens):
        result["station"] = tokens[i]
        i += 1

    while i < len(tokens):
        token = tokens[i]
        next_token = tokens[i + 1] if i + 1 < len(tokens) else ""
        i += 1

        if token in END_OF_BODY:
            if token == "NOSIG":
                result["notes"].append("No significant change expected in the next two hours.")
            break

        if m := TIME_RE.match(token):
            observed = observation_time(int(m["day"]), int(m["hour"]), int(m["minute"]), now)
            if observed:
                result["observed_at"] = observed
                result["observed_ago"] = time_ago(observed, now)
        elif token == "AUTO":
            result["notes"].append("Fully automated report (no human observer).")
        elif token == "COR":
            result["notes"].append("This is a corrected report.")
        elif m := WIND_RE.match(token):
            factor = TO_MPH[m["unit"]]
            speed = int(m["speed"])
            wind = {
                "speed_mph": round(speed * factor),
                "gust_mph": round(int(m["gust"]) * factor) if m["gust"] else None,
                "raw_unit": m["unit"],
                "speed": speed,
                "gust": int(m["gust"]) if m["gust"] else None,
                "calm": speed == 0,
                "variable": m["dir"] == "VRB",
                "direction": None if m["dir"] == "VRB" else int(m["dir"]),
            }
            result["wind"] = wind
        elif (m := WIND_VARIATION_RE.match(token)) and "wind" in result:
            result["wind"]["varies"] = (int(m["start"]), int(m["end"]))
        elif token == "CAVOK":
            cavok = True
            result["visibility"] = {"miles": 6.2, "text": "10 km or more (over 6 miles)"}
        elif "visibility" not in result and token.isdigit() and len(token) <= 2 and VIS_MILES_RE.match(next_token):
            # Whole number followed by a fraction, e.g. "1 1/2SM".
            frac = VIS_MILES_RE.match(next_token)
            value_text = f"{token} {frac['value']}"
            miles = parse_fraction(value_text)
            result["visibility"] = {"miles": miles, "text": format_visibility(frac["mod"], value_text, miles)}
            i += 1
        elif "visibility" not in result and (m := VIS_MILES_RE.match(token)):
            miles = parse_fraction(m["value"])
            result["visibility"] = {"miles": miles, "text": format_visibility(m["mod"], m["value"], miles)}
        elif "visibility" not in result and (m := VIS_METERS_RE.match(token)):
            meters = int(m["value"])
            miles = meters / 1609.34
            if meters == 9999:
                text = "10 km or more (over 6 miles)"
            elif meters < 50:
                text = "Less than 50 meters"
            else:
                text = f"{miles:.1f} miles ({meters:,} m)"
            result["visibility"] = {"miles": miles, "text": text}
        elif token in ("SKC", "CLR", "NSC", "NCD"):
            pass  # No clouds reported; the sky summary defaults to clear.
        elif m := CLOUD_RE.match(token):
            cover = m["cover"]
            height = None if m["height"] == "///" else int(m["height"]) * 100
            if cover == "VV":
                text = "Sky obscured" + (f", can see up to {height:,} ft" if height is not None else "")
            else:
                text = CLOUD_COVER[cover] + (f" at {height:,} ft" if height is not None else " (height unknown)")
            if m["type"] == "CB":
                text += " (cumulonimbus, thunderstorm clouds)"
            elif m["type"] == "TCU":
                text += " (towering cumulus)"
            result["clouds"].append({"cover": cover, "height_ft": height, "text": text})
            if top_cover is None or COVER_RANK[cover] > COVER_RANK[top_cover]:
                top_cover = cover
        elif m := UNKNOWN_CLOUD_RE.match(token):
            kind = "Thunderstorm clouds (cumulonimbus)" if m["type"] == "CB" else "Towering cumulus clouds"
            result["clouds"].append({"cover": None, "height_ft": None, "text": f"{kind} detected nearby"})
        elif m := TEMP_RE.match(token):
            result.setdefault("temp_c", parse_signed_temp(m["temp"]))
            if m["dew"]:
                result.setdefault("dewpoint_c", parse_signed_temp(m["dew"]))
        elif m := PRESSURE_RE.match(token):
            value = int(m["value"])
            if m["unit"] == "A":
                inhg = value / 100
                hpa = inhg * 33.8639
            else:
                hpa = value
                inhg = hpa / 33.8639
            result["pressure_inhg"] = round(inhg, 2)
            result["pressure_hpa"] = round(hpa)
        elif token.startswith("RE"):
            pass  # Recent weather (e.g. RERA) — not current conditions.
        elif (m := WEATHER_RE.match(token)) and (m["descriptor"] or m["phenomena"]):
            result["weather"].append(describe_weather(m))
            weather_codes.append(token)

    result["sky"] = SKY_SUMMARY[top_cover]
    if cavok:
        result["clouds"].append({"cover": None, "height_ft": None, "text": "No significant clouds below 5,000 ft"})

    if "temp_c" in result:
        result["temp_f"] = c_to_f(result["temp_c"])
    if "dewpoint_c" in result:
        result["dewpoint_f"] = c_to_f(result["dewpoint_c"])
        if "temp_c" in result:
            result["humidity"] = round(relative_humidity(result["temp_c"], result["dewpoint_c"]))
    if "temp_f" in result:
        wind_mph = result.get("wind", {}).get("speed_mph", 0)
        feels = feels_like_f(result["temp_f"], wind_mph, result.get("humidity"))
        if feels is not None and abs(feels - result["temp_f"]) >= 2:
            result["feels_like_f"] = feels

    result["icon"] = choose_icon(weather_codes, top_cover)
    result["summary"] = build_summary(result)
    result["details"] = build_details(result)
    return result


def describe_wind(wind, verbose=False):
    if wind["calm"]:
        return "Calm" if verbose else "calm winds"
    speed = f"{wind['speed_mph']} mph"
    if verbose and wind["raw_unit"] == "KT":
        speed += f" ({wind['speed']} knots)"
    if wind["variable"]:
        text = f"variable direction at {speed}" if verbose else f"variable winds at {speed}"
    else:
        direction = compass_name(wind["direction"])
        if verbose:
            direction += f" ({wind['direction']}°)"
        text = f"from the {direction} at {speed}"
    if wind["gust_mph"]:
        text += f", gusting to {wind['gust_mph']} mph"
        if verbose and wind["raw_unit"] == "KT":
            text += f" ({wind['gust']} knots)"
    if verbose and "varies" in wind:
        start, end = wind["varies"]
        text += f"; direction shifting between {start}° and {end}°"
    if verbose:
        return text[0].upper() + text[1:]
    return text if wind["variable"] else f"wind {text}"


def build_summary(r):
    """One friendly sentence, e.g. 'Partly cloudy, 72°F, wind from the south at 5 mph.'"""
    parts = []
    sky = r["sky"]
    if r["weather"]:
        weather = " and ".join(r["weather"])
        # When fog/precip hides the sky, lead with the weather itself.
        sky = f"{sky} with {weather}" if sky not in ("Sky obscured",) else weather[0].upper() + weather[1:]
    parts.append(sky)

    if "temp_f" in r:
        temp = f"{round(r['temp_f'])}°F ({round(r['temp_c'])}°C)"
        if "feels_like_f" in r:
            temp += f", feels like {round(r['feels_like_f'])}°F"
        parts.append(temp)

    if "wind" in r:
        parts.append(describe_wind(r["wind"]))

    vis = r.get("visibility")
    if vis and vis["miles"] < 3:
        parts.append(f"visibility {vis['text'].lower()}")

    return ", ".join(parts) + "."


def build_details(r):
    details = []
    if "temp_f" in r:
        details.append(("Temperature", f"{round(r['temp_f'])}°F ({r['temp_c']:g}°C)"))
    if "feels_like_f" in r:
        details.append(("Feels like", f"{round(r['feels_like_f'])}°F"))
    if "wind" in r:
        details.append(("Wind", describe_wind(r["wind"], verbose=True)))
    if r["clouds"]:
        details.append(("Clouds", "; ".join(c["text"] for c in r["clouds"])))
    else:
        details.append(("Clouds", "None reported, clear skies"))
    if r["weather"]:
        weather = "; ".join(r["weather"])
        details.append(("Weather", weather[0].upper() + weather[1:]))
    if "visibility" in r:
        vis = r["visibility"]
        text = vis["text"][0].lower() + vis["text"][1:]
        details.append(("Visibility", f"{visibility_quality(vis['miles']).capitalize()}, {text}"))
    if "humidity" in r:
        details.append(("Humidity", f"{r['humidity']}%"))
    if "dewpoint_f" in r:
        details.append(("Dew point", f"{round(r['dewpoint_f'])}°F ({r['dewpoint_c']:g}°C)"))
    if "pressure_inhg" in r:
        details.append(("Pressure", f"{r['pressure_inhg']:.2f} inHg ({r['pressure_hpa']} hPa)"))
    if "observed_at" in r:
        details.append(("Observed", f"{r['observed_at']:%b %d, %H:%M} UTC ({r['observed_ago']})"))
    for note in r["notes"]:
        details.append(("Note", note))
    return details
