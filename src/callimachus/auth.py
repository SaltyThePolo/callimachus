"""Explicit browser login; background commands never prompt for authorization."""

import asyncio
import secrets
import webbrowser
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from .archive import atomic_write
from .errors import UserError

WISPR_URL = "https://api.wisprflow.ai/connect/mcp"
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class TokenFiles:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def read(self, name, model):
        path = self.root / name
        return model.model_validate_json(path.read_text()) if path.exists() else None

    async def get_tokens(self):
        return self.read("wispr-token.json", OAuthToken)

    async def set_tokens(self, tokens):
        atomic_write(self.root / "wispr-token.json", tokens.model_dump_json().encode())

    async def get_client_info(self):
        return self.read("wispr-client.json", OAuthClientInformationFull)

    async def set_client_info(self, client_info):
        atomic_write(self.root / "wispr-client.json", client_info.model_dump_json().encode())


class Callback:
    def __init__(self, port=8765):
        self.port = port
        self.expected_state = None

    async def __aenter__(self):
        self.result = asyncio.get_running_loop().create_future()
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", self.port, limit=8192)
        port = self.server.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}/callback"
        return self

    async def __aexit__(self, *args):
        self.server.close()
        await self.server.wait_closed()

    async def handle(self, reader, writer):
        status, body = "400 Bad Request", "Invalid authorization callback."
        try:
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            method, target, _ = header.split(b"\r\n", 1)[0].decode().split(" ")
            parsed = urlparse(target)
            params = parse_qs(parsed.query)
            state = params.get("state", [""])[0]
            code = params.get("code", [""])[0]
            if (
                method == "GET"
                and parsed.path == "/callback"
                and code
                and self.expected_state
                and secrets.compare_digest(state, self.expected_state)
                and not self.result.done()
            ):
                self.result.set_result((code, state))
                status, body = "200 OK", "Callimachus authorized. You may close this window."
        except (
            ValueError,
            UnicodeError,
            asyncio.TimeoutError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ):
            pass
        finally:
            message = body.encode()
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: text/plain\r\n"
                f"Content-Length: {len(message)}\r\nConnection: close\r\n\r\n".encode()
                + message
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

    async def redirect(self, url):
        self.expected_state = parse_qs(urlparse(url).query)["state"][0]
        print("Opening Wispr authorization in your browser…", flush=True)
        if not webbrowser.open(url):
            raise UserError("Cannot open browser; run login wispr from an interactive desktop")

    async def receive(self):
        return await asyncio.wait_for(self.result, timeout=300)


@asynccontextmanager
async def connect_wispr(state: Path, interactive=False):
    storage = TokenFiles(state)
    if not interactive and await storage.get_tokens() is None:
        raise UserError("Wispr credentials missing; run callimachus login wispr")

    async def login_required(*args):
        raise UserError("Wispr authorization expired; run callimachus login wispr")

    async with AsyncExitStack() as stack:
        callback = await stack.enter_async_context(Callback()) if interactive else None
        auth = OAuthClientProvider(
            server_url=WISPR_URL,
            client_metadata=OAuthClientMetadata(
                client_name="Callimachus",
                redirect_uris=["http://127.0.0.1:8765/callback"],
                token_endpoint_auth_method="none",
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
            ),
            storage=storage,
            redirect_handler=callback.redirect if callback else login_required,
            callback_handler=callback.receive if callback else login_required,
        )
        client = await stack.enter_async_context(
            httpx.AsyncClient(auth=auth, timeout=60, follow_redirects=True)
        )
        read, write, _ = await stack.enter_async_context(
            streamable_http_client(WISPR_URL, http_client=client)
        )
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        yield session


def drive_service(state: Path, client_file: Path | None = None, interactive=False):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    path = state / "drive-token.json"
    credentials = (
        Credentials.from_authorized_user_file(str(path), DRIVE_SCOPES) if path.exists() else None
    )
    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            atomic_write(path, credentials.to_json().encode())
        except RefreshError:
            if not interactive:
                raise UserError(
                    "Google authorization expired; run callimachus login drive"
                ) from None
            credentials = None
    if not credentials or not credentials.valid:
        if not interactive:
            raise UserError("Google credentials missing or expired; run callimachus login drive")
        if client_file is None or not client_file.is_file():
            raise UserError("Set CALLIMACHUS_GOOGLE_CLIENT_SECRET_FILE to your desktop OAuth JSON")
        flow = InstalledAppFlow.from_client_secrets_file(str(client_file), DRIVE_SCOPES)
        credentials = flow.run_local_server(port=0, timeout_seconds=300)
        atomic_write(path, credentials.to_json().encode())
    return build("drive", "v3", credentials=credentials, cache_discovery=False)
