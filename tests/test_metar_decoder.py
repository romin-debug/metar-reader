from datetime import datetime, timezone

import pytest

from metar_decoder import compass_name, decode_metar

NOW = datetime(2026, 10, 21, 11, 0, tzinfo=timezone.utc)


def decode(raw):
    return decode_metar(raw, now=NOW)


def test_clear_calm_morning():
    r = decode("METAR KHIO 210953Z AUTO 00000KT 10SM CLR 06/03 A2997 RMK AO2 SLP145 T00560033")
    assert r["summary"] == "Clear skies, 42°F (6°C), calm winds."
    assert r["temp_c"] == pytest.approx(5.6)  # precise value from the T group in remarks
    assert r["pressure_inhg"] == 29.97
    assert r["observed_ago"] == "1 hour ago"
    assert r["icon"] == "☀️"


def test_rain_broken_clouds_and_unknown_cb_layer():
    r = decode("METAR EGLL 211020Z AUTO 28020KT 9999 -RA BKN011/// BKN018/// //////CB 10/09 Q0998")
    assert r["summary"].startswith("Mostly cloudy with light rain, 50°F (10°C)")
    assert "wind from the west at 23 mph" in r["summary"]
    assert r["pressure_hpa"] == 998
    assert any("cumulonimbus" in c["text"] for c in r["clouds"])


def test_gusts_negative_dewpoint_and_wind_chill():
    r = decode("METAR PANC 210953Z 35010G18KT 10SM FEW040 BKN075 03/M06 A2944 RMK AO2 SLP970 T00331056")
    assert "wind from the north at 12 mph, gusting to 21 mph" in r["summary"]
    assert r["dewpoint_c"] == pytest.approx(-5.6)
    assert round(r["feels_like_f"]) == 30


def test_trend_group_is_not_parsed_as_current_wind():
    r = decode("METAR RJTT 211030Z 20019KT 9999 FEW020 27/20 Q1007 TEMPO 22024G36KT")
    assert r["wind"]["direction"] == 200
    assert r["wind"]["gust_mph"] is None


def test_thunderstorm_low_visibility_fraction():
    r = decode("METAR KXYZ 211053Z 18012G25KT 150V210 1 1/2SM +TSRA VV005 M02/M04 A2990")
    assert r["weather"] == ["thunderstorms with heavy rain"]
    assert r["visibility"]["miles"] == 1.5
    assert r["wind"]["varies"] == (150, 210)
    assert r["summary"].startswith("Thunderstorms with heavy rain, 28°F")
    assert "visibility 1 1/2 miles" in r["summary"]
    assert r["icon"] == "⛈️"


def test_variable_wind_and_cavok():
    r = decode("METAR LFPG 211030Z VRB03KT CAVOK 22/12 Q1020 NOSIG")
    assert r["summary"] == "Clear skies, 72°F (22°C), variable winds at 3 mph."
    assert any("No significant change" in n for n in r["notes"])


@pytest.mark.parametrize("group, expected", [
    ("-SHRA", "light rain showers"),
    ("FZRA", "freezing rain"),
    ("BCFG", "patches of fog"),
    ("VCSH", "showers nearby"),
    ("-RASN", "light rain and snow"),
    ("BLSN", "blowing snow"),
    ("+FC", "tornado or waterspout"),
])
def test_weather_phrases(group, expected):
    r = decode(f"METAR KXYZ 211053Z 00000KT 5SM {group} OVC010 01/00 A3000")
    assert r["weather"] == [expected]


@pytest.mark.parametrize("vis, expected", [
    ("P6SM", "More than 6 miles"),
    ("M1/4SM", "Less than 1/4 mile"),
    ("1SM", "1 mile"),
    ("0800", "0.5 miles (800 m)"),
])
def test_visibility(vis, expected):
    r = decode(f"METAR KXYZ 211053Z 00000KT {vis} OVC010 01/00 A3000")
    assert r["visibility"]["text"] == expected


def test_compass_names():
    assert compass_name(0) == "north"
    assert compass_name(360) == "north"
    assert compass_name(185) == "south"
    assert compass_name(230) == "southwest"


def test_garbage_does_not_crash():
    r = decode("METAR KXYZ nonsense ??? 123")
    assert r["summary"]
    assert r["station"] == "KXYZ"
