import json

import pytest

from pkb.config import Settings, load_settings
from pkb.oauth import get_valid_token


def test_load_settings_builds_token_from_env(monkeypatch):
    monkeypatch.setenv("X_CLIENT_ID", "client")
    monkeypatch.setenv("X_ACCESS_TOKEN", "access")
    monkeypatch.setenv("X_REFRESH_TOKEN", "refresh")
    monkeypatch.setenv("X_EXPIRES_IN", "7200")
    monkeypatch.setenv("X_TOKEN_OBTAINED_AT", "123")

    settings = load_settings()

    assert settings.env_token == {
        "access_token": "access",
        "token_type": "bearer",
        "refresh_token": "refresh",
        "expires_in": 7200,
        "obtained_at": 123,
    }


def test_load_settings_accepts_token_json(monkeypatch):
    monkeypatch.setenv("X_TOKEN_JSON", json.dumps({"access_token": "json-access", "refresh_token": "json-refresh"}))

    settings = load_settings()

    assert settings.env_token == {"access_token": "json-access", "refresh_token": "json-refresh"}


def test_get_valid_token_uses_env_token_when_token_file_is_missing(tmp_path):
    settings = Settings(
        client_id="client",
        client_secret=None,
        redirect_uri="http://127.0.0.1:8765/callback",
        data_dir=tmp_path,
        env_token={"access_token": "env-access"},
    )

    assert get_valid_token(settings)["access_token"] == "env-access"


def test_get_valid_token_explains_missing_token_configuration(tmp_path):
    settings = Settings(
        client_id="client",
        client_secret=None,
        redirect_uri="http://127.0.0.1:8765/callback",
        data_dir=tmp_path,
    )

    with pytest.raises(ValueError, match="X_TOKEN_JSON or X_ACCESS_TOKEN"):
        get_valid_token(settings)
