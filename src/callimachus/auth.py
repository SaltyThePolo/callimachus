# Copyright (C) 2026 Mattia Riviera
# SPDX-License-Identifier: AGPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero
# General Public License for more details.

"""Explicit browser login; background commands never prompt for authorization."""

import asyncio
import json
import secrets
import time
import webbrowser
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from .errors import UserError
from .fs import atomic_write

WISPR_URL = "https://api.wisprflow.ai/connect/mcp"
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
WISPR_PORT, DRIVE_PORT = 8765, 8766  # fixed loopback callback ports, also for container setup


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
        # The SDK forgets expiry across processes; keep it next to the token so a cold start
        # refreshes an expired access token instead of demanding a new browser login.
        data = json.loads(tokens.model_dump_json())
        if tokens.expires_in:
            data["expires_at"] = time.time() + tokens.expires_in
        atomic_write(self.root / "wispr-token.json", json.dumps(data).encode())

    def expires_at(self) -> float | None:
        path = self.root / "wispr-token.json"
        return json.loads(path.read_text()).get("expires_at") if path.exists() else None

    async def get_client_info(self):
        return self.read("wispr-client.json", OAuthClientInformationFull)

    async def set_client_info(self, client_info):
        atomic_write(self.root / "wispr-client.json", client_info.model_dump_json().encode())


class Callback:
    """Loopback OAuth callback; bind may be 0.0.0.0 inside a container whose port is published
    on the host loopback, while the advertised redirect URI stays 127.0.0.1."""

    def __init__(self, port=WISPR_PORT, bind="127.0.0.1"):
        self.port, self.bind = port, bind
        self.expected_state = None

    async def __aenter__(self):
        self.result = asyncio.get_running_loop().create_future()
        self.server = await asyncio.start_server(self.handle, self.bind, self.port, limit=8192)
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
        print(f"Open this URL in your browser to authorize Wispr:\n{url}", flush=True)
        webbrowser.open(url)  # best effort; the printed URL is the supported path

    async def receive(self):
        return await asyncio.wait_for(self.result, timeout=300)


def wispr_provider(storage: TokenFiles, callback: Callback | None) -> OAuthClientProvider:
    async def login_required(*args):
        raise UserError("Wispr authorization expired; run callimachus login wispr")

    provider = OAuthClientProvider(
        server_url=WISPR_URL,
        client_metadata=OAuthClientMetadata(
            client_name="Callimachus",
            redirect_uris=[f"http://127.0.0.1:{WISPR_PORT}/callback"],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=storage,
        redirect_handler=callback.redirect if callback else login_required,
        callback_handler=callback.receive if callback else login_required,
    )
    # The SDK forgets expiry across processes; restore it so an expired access token is
    # refreshed before the first request instead of triggering a browser login.
    provider.context.token_expiry_time = storage.expires_at()
    return provider


@asynccontextmanager
async def connect_wispr(state: Path, interactive=False, bind="127.0.0.1"):
    storage = TokenFiles(state)
    if not interactive and await storage.get_tokens() is None:
        raise UserError("Wispr credentials missing; run callimachus login wispr")
    async with AsyncExitStack() as stack:
        callback = await stack.enter_async_context(Callback(bind=bind)) if interactive else None
        client = await stack.enter_async_context(
            httpx.AsyncClient(
                auth=wispr_provider(storage, callback), timeout=60, follow_redirects=True
            )
        )
        read, write, _ = await stack.enter_async_context(
            streamable_http_client(WISPR_URL, http_client=client)
        )
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        yield session


def drive_service(
    state: Path, client_file: Path | None = None, interactive=False, bind="127.0.0.1"
):
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
        credentials = flow.run_local_server(
            host="127.0.0.1",
            bind_addr=bind,
            port=DRIVE_PORT,
            open_browser=True,  # best effort; the flow prints the URL for the host browser
            timeout_seconds=300,
        )
        atomic_write(path, credentials.to_json().encode())
    return build("drive", "v3", credentials=credentials, cache_discovery=False)
