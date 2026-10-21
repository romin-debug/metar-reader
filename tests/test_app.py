import pytest

import app as metar_app

SAMPLE = {
    "icaoId": "KJFK",
    "name": "New York/JF Kennedy Intl, NY, US",
    "rawOb": "METAR KJFK 210951Z 02014KT 10SM FEW250 11/02 A3023 RMK AO2 SLP236 T01060022",
}


@pytest.fixture
def client():
    metar_app.app.testing = True
    return metar_app.app.test_client()


def test_home_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"METAR Reader" in resp.data


def test_three_letter_code_prefers_us_station(client, monkeypatch):
    requested = []

    def fake_fetch(ids):
        requested.append(ids)
        return [SAMPLE]

    monkeypatch.setattr(metar_app, "fetch_metar", fake_fetch)
    resp = client.get("/?code=jfk")
    assert requested == [["KJFK", "PJFK", "CJFK"]]
    html = resp.get_data(as_text=True)
    assert "Mostly clear, 51°F (11°C), wind from the north-northeast at 16 mph." in html
    assert "JF Kennedy" in html


def test_unknown_station(client, monkeypatch):
    monkeypatch.setattr(metar_app, "fetch_metar", lambda ids: [])
    html = client.get("/?code=ZZZZ").get_data(as_text=True)
    assert "No current weather report found" in html


def test_invalid_input(client, monkeypatch):
    monkeypatch.setattr(metar_app, "fetch_metar", lambda ids: pytest.fail("should not fetch"))
    html = client.get("/?code=<script>").get_data(as_text=True)
    assert "3- or 4-character airport code" in html
    assert "<script>" not in html


def test_service_down(client, monkeypatch):
    def boom(ids):
        raise metar_app.MetarError("Couldn't reach the aviation weather service right now.")

    monkeypatch.setattr(metar_app, "fetch_metar", boom)
    html = client.get("/?code=KJFK").get_data(as_text=True)
    assert "Couldn&#39;t reach" in html
