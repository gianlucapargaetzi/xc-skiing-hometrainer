import json

import pytest

from Utils import strava_client as sc


@pytest.fixture
def tokdir(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "TOKENS_DIR", tmp_path / "strava_tokens")
    monkeypatch.setattr(sc, "LEGACY_TOKENS_FILE", tmp_path / "strava_tokens.json")
    return tmp_path


def _tokens(aid, first="Anna"):
    return {"access_token": "a", "refresh_token": "r", "expires_at": 4_000_000_000,
            "athlete": {"id": aid, "firstname": first, "lastname": "Test"}, "scope": "read,activity:write"}


def test_tokens_are_stored_per_athlete(tokdir):
    sc._save(_tokens(1)); sc._save(_tokens(2, "Beat"))
    assert sc.load_tokens(1)["athlete"]["firstname"] == "Anna"
    assert sc.load_tokens(2)["athlete"]["firstname"] == "Beat"
    assert sc.load_tokens(None) is None and sc.load_tokens(3) is None
    assert oct(sc.tokens_path(1).stat().st_mode & 0o777) == "0o600"


def test_status_and_token_per_profile(tokdir):
    sc._save(_tokens(1))
    assert sc.status(1) == {"connected": True, "athlete": "Anna Test", "can_upload": True}
    assert sc.status(None)["connected"] is False           # Profil ohne Strava-Konto
    assert sc.status(2)["connected"] is False              # anderes Konto nicht verbunden
    assert sc.valid_access_token(1) == "a"
    with pytest.raises(sc.StravaError):
        sc.valid_access_token(2)


def test_migrate_legacy_file(tokdir):
    (tokdir / "strava_tokens.json").write_text(json.dumps(_tokens(42)))
    assert sc.migrate_legacy_tokens() == 42
    assert sc.load_tokens(42)["refresh_token"] == "r"
    assert not (tokdir / "strava_tokens.json").exists()
    assert sc.migrate_legacy_tokens() is None
