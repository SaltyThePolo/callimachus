import os

import httpx
import pytest
from mcp.shared.auth import OAuthToken

from callimachus.auth import Callback, TokenFiles


async def test_tokens_are_private_and_survive_restart(tmp_path):
    store = TokenFiles(tmp_path)
    await store.set_tokens(OAuthToken(access_token="synthetic", token_type="Bearer"))
    assert (await TokenFiles(tmp_path).get_tokens()).access_token == "synthetic"
    assert os.stat(tmp_path / "wispr-token.json").st_mode & 0o777 == 0o600


async def test_callback_rejects_wrong_state_then_accepts_valid_code():
    async with Callback(0) as callback:
        callback.expected_state = "expected"
        async with httpx.AsyncClient() as client:
            wrong = await client.get(callback.url, params={"code": "fake", "state": "wrong"})
            assert wrong.status_code == 400
            right = await client.get(callback.url, params={"code": "valid", "state": "expected"})
            assert right.status_code == 200
        assert await callback.receive() == ("valid", "expected")


async def test_noninteractive_auth_never_opens_browser(tmp_path):
    from callimachus.auth import connect_wispr

    with pytest.raises(ValueError, match="login wispr"):
        async with connect_wispr(tmp_path, interactive=False):
            pass


def test_drive_login_recovers_revoked_refresh_token(tmp_path, monkeypatch):
    import googleapiclient.discovery
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    from callimachus.auth import drive_service

    class Expired:
        expired = True
        refresh_token = "synthetic"

        def refresh(self, request):
            raise RefreshError("revoked")

    class Valid:
        valid = True

        def to_json(self):
            return '{"synthetic": true}'

    class Flow:
        def run_local_server(self, **kwargs):
            return Valid()

    token = tmp_path / "drive-token.json"
    token.write_text("{}")
    client = tmp_path / "client.json"
    client.write_text("{}")
    monkeypatch.setattr(Credentials, "from_authorized_user_file", lambda *args: Expired())
    monkeypatch.setattr(InstalledAppFlow, "from_client_secrets_file", lambda *args: Flow())
    monkeypatch.setattr(googleapiclient.discovery, "build", lambda *args, **kwargs: "authorized")
    assert drive_service(tmp_path, client, interactive=True) == "authorized"
    assert "synthetic" in token.read_text()
