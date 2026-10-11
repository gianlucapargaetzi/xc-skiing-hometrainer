import pytest

from Utils import chat_notify


class FakeResponse:
    def __init__(self, status=200, text='{"ok": true}'):
        self.status_code, self.text = status, text


@pytest.fixture
def configured(monkeypatch):
    values = {"TRACKING_DEVICE_ID": "52", "TRACKING_SK": "geheim"}
    monkeypatch.setattr(chat_notify, "get_credential", lambda name, default=None: values.get(name, default))
    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw))
        return FakeResponse()
    monkeypatch.setattr(chat_notify.requests, "post", fake_post)
    return calls


def test_not_configured_sends_nothing(monkeypatch):
    monkeypatch.setattr(chat_notify, "get_credential", lambda name, default=None: default)
    monkeypatch.setattr(chat_notify.requests, "post", lambda *a, **k: pytest.fail("darf nicht senden"))
    assert chat_notify.configured() is False
    assert chat_notify.send("x") is False and chat_notify.send_image("x.png") is False


def test_text_message_is_json_with_secret_only_in_query(configured, capsys):
    assert chat_notify.start_text() == "Training gestartet. Folge mir unter:\nhttps://tracking.gps-live.ch/s/geheim"
    assert chat_notify.send(chat_notify.start_text(), "Jürg") is True
    url, kw = configured[0]
    assert url == chat_notify.DEFAULT_CHAT_URL
    assert kw["params"] == {"device_id": "52", "sk": "geheim"}
    assert kw["json"] == {"text": chat_notify.start_text(), "name": "Jürg"}
    assert "geheim" not in capsys.readouterr().out          # der Secret-Link steht nie im Log


def test_image_is_multipart_with_name_and_file(configured, tmp_path):
    png = tmp_path / "zusammenfassung.png"
    png.write_bytes(b"\x89PNG....")
    assert chat_notify.send_image(png, "Jürg") is True
    url, kw = configured[0]
    assert url == chat_notify.DEFAULT_MEDIA_URL and kw["data"] == {"name": "Jürg"}
    name, _, mime = kw["files"]["file"]
    assert (name, mime) == ("zusammenfassung.png", "image/png")
    assert chat_notify.send_image(tmp_path / "fehlt.png") is False
    # mit Bildunterschrift
    assert chat_notify.send_image(png, "Jürg", "Training beendet.\n13.17 km") is True
    assert configured[1][1]["data"] == {"name": "Jürg", "text": "Training beendet.\n13.17 km"}


def test_rejected_and_unreachable_are_reported_not_raised(configured, monkeypatch, tmp_path):
    monkeypatch.setattr(chat_notify.requests, "post", lambda *a, **k: FakeResponse(404, "Not Found"))
    assert chat_notify.send("x") is False
    png = tmp_path / "a.png"; png.write_bytes(b"x")
    assert chat_notify.send_image(png) is False

    def boom(*a, **k):
        raise chat_notify.requests.ConnectionError("kein Netz")
    monkeypatch.setattr(chat_notify.requests, "post", boom)
    assert chat_notify.send("x") is False and chat_notify.send_image(png) is False
