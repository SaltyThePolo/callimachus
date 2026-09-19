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


async def drive_flow(provider, tmp_path):
    """First request the provider issues for a plain MCP call after a cold start."""
    request = httpx.Request("POST", "https://api.wisprflow.ai/connect/mcp", json={})
    flow = provider.async_auth_flow(request)
    return await flow.__anext__()


async def test_cold_start_refreshes_an_expired_token_before_the_first_request(tmp_path):

    from mcp.shared.auth import OAuthClientInformationFull

    from callimachus.auth import wispr_provider

    store = TokenFiles(tmp_path)
    await store.set_client_info(
        OAuthClientInformationFull(
            client_id="synthetic-client", redirect_uris=["http://127.0.0.1:8765/callback"]
        )
    )
    await store.set_tokens(
        OAuthToken(access_token="stale", token_type="Bearer", refresh_token="r1", expires_in=3600)
    )
    (tmp_path / "wispr-token.json").write_text(
        (tmp_path / "wispr-token.json").read_text().replace('"expires_at": ', '"expires_at": -')
    )  # the stored expiry is now in the past
    first = await drive_flow(wispr_provider(TokenFiles(tmp_path), None), tmp_path)
    assert first.url.path.endswith("/token") and b"grant_type=refresh_token" in first.content
    assert b"stale" not in first.headers.get("authorization", "").encode()


async def test_cold_start_uses_a_still_valid_token_directly(tmp_path):
    from mcp.shared.auth import OAuthClientInformationFull

    from callimachus.auth import wispr_provider

    store = TokenFiles(tmp_path)
    await store.set_client_info(
        OAuthClientInformationFull(
            client_id="synthetic-client", redirect_uris=["http://127.0.0.1:8765/callback"]
        )
    )
    await store.set_tokens(
        OAuthToken(access_token="fresh", token_type="Bearer", refresh_token="r1", expires_in=3600)
    )
    first = await drive_flow(wispr_provider(TokenFiles(tmp_path), None), tmp_path)
    assert first.url.path.endswith("/mcp") and first.headers["authorization"] == "Bearer fresh"


async def test_callback_can_bind_all_interfaces_while_advertising_loopback(monkeypatch, capsys):
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda url: False)  # no browser in a container
    async with Callback(0, bind="0.0.0.0") as callback:
        assert callback.server.sockets[0].getsockname()[0] == "0.0.0.0"
        assert callback.url.startswith("http://127.0.0.1:")
        await callback.redirect("https://auth.example/authorize?state=abc")
    assert "https://auth.example/authorize?state=abc" in capsys.readouterr().out
