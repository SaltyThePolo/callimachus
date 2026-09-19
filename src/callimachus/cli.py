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

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from filelock import FileLock, Timeout

from . import migrate
from .auth import connect_wispr, drive_service
from .config import Config
from .current import CurrentArchive, LocalStore
from .drive import DriveStore
from .errors import UserError
from .fs import atomic_write, canonical
from .models import Meeting
from .wispr import WisprSource, decode_result


class VersionAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        print(
            f"Callimachus {version('callimachus-archive')} — Copyright (C) 2026 Mattia Riviera. "
            "License AGPLv3. This is free software with ABSOLUTELY NO WARRANTY."
        )
        parser.exit()


def parser():
    root = argparse.ArgumentParser(description="Archive Wispr Flow meetings locally or to Drive")
    root.add_argument("--version", action=VersionAction, nargs=0, help="Show version and license")
    root.add_argument("--env-file", type=Path, default=Path(".env"))
    commands = root.add_subparsers(dest="command", required=True)
    auth = commands.add_parser("login", help="Authorize an account in your browser")
    auth.add_argument("service", choices=["wispr", "drive"])
    auth.set_defaults(func=login)
    commands.add_parser(
        "doctor", help="Check local setup without accessing meeting content"
    ).set_defaults(func=doctor)
    convert = commands.add_parser(
        "migrate", help="Preview or convert a legacy revision archive to readable folders"
    )
    convert.add_argument("--apply", action="store_true", help="Convert (preview is the default)")
    convert.add_argument(
        "--cleanup", action="store_true", help="After --apply, remove verified legacy directories"
    )
    convert.set_defaults(func=migrate_command)
    for name in ("sync", "watch"):
        cmd = commands.add_parser(
            name, help="Archive once" if name == "sync" else "Continuously archive"
        )
        cmd.add_argument("--since", help="Inclusive ISO datetime with timezone")
        cmd.add_argument("--until", help="Exclusive ISO datetime with timezone")
        cmd.add_argument(
            "--input", type=Path, help="Import a normalized JSON meeting list instead of MCP"
        )
        cmd.set_defaults(func=run_sync if name == "sync" else watch)
    return root


def validate_dates(args):
    parsed = []
    for name in ("since", "until"):
        raw = getattr(args, name, None)
        if raw:
            message = f"--{name} requires an ISO datetime with timezone"
            try:
                value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                raise UserError(message) from None
            if value.tzinfo is None:
                raise UserError(message)
            parsed.append(value)
    if len(parsed) == 2 and parsed[0] >= parsed[1]:
        raise UserError("--since must precede --until")


async def meetings(config, args, skip):
    if args.input:
        try:
            data = json.loads(args.input.read_text(encoding="utf-8"))
        except ValueError:
            raise UserError("Input file is not valid JSON") from None
        if not isinstance(data, list):
            raise UserError("Input must be a JSON list of normalized meetings")
        for item in data:
            if not isinstance(item, dict):
                raise UserError("Each input meeting must be an object")
            meeting = Meeting(**item)
            if not skip(meeting.id, meeting.modified_at):
                yield meeting
        return
    async with connect_wispr(config.state) as session:

        async def call(name, arguments):
            return decode_result(await session.call_tool(name, arguments))

        async for meeting in WisprSource(call).meetings(args.since, args.until, skip):
            yield meeting


def current_archive(config):
    if config.destination == "drive":
        store = DriveStore(drive_service(config.state), config.state, config.google_folder)
        registry = config.state / "drive-registry.json"
    else:
        store, registry = LocalStore(config.archive), config.state / "registry.json"
    return CurrentArchive(store, registry, config.timezone, config.restore)


def process_lock(config):
    return FileLock(str(config.state / "process.lock"), timeout=0)


@contextmanager
def archive_lock(config):
    """Single writer for the local archive directory; Drive mode has no local archive."""
    if config.destination == "drive":
        yield
        return
    config.archive.mkdir(parents=True, exist_ok=True, mode=0o700)
    with FileLock(str(config.archive / ".writer.lock"), timeout=0):
        yield


async def sync(config, args):
    archive = current_archive(config)
    archive.reconcile()
    counts = {"imported": 0, "unchanged": 0, "pending": 0, "suppressed": 0}

    def skip(meeting_id, modified_at):
        if archive.unchanged(meeting_id, modified_at):
            counts["unchanged"] += 1
            return True
        return False

    async for meeting in meetings(config, args, skip):
        counts[archive.publish(meeting)] += 1
    summary = " ".join(f"{k}={v}" for k, v in counts.items())
    print(f"{summary} destination={config.destination}", flush=True)
    record_status(config, True, summary)
    return 2 if counts["pending"] and config.require_complete else 0


def record_status(config, ok, detail):
    """Local diagnostics for unattended operation; never contains meeting text or tokens."""
    status = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ok": ok}
    status["summary" if ok else "error"] = detail
    atomic_write(config.state / "status.json", canonical(status))


def run_sync(config, args):
    """One synchronization pass under the process lock; the local archive has its own writer lock."""
    with process_lock(config):
        try:
            with archive_lock(config):
                if config.destination == "local" and (config.archive / "meetings").is_dir():
                    raise UserError(
                        "Legacy revision archive detected; run `callimachus migrate` before syncing here"
                    )
                return asyncio.run(sync(config, args))
        except Exception as exc:
            record_status(config, False, describe_error(exc))
            raise


def user_errors(exc):
    if isinstance(exc, BaseExceptionGroup):
        return [message for child in exc.exceptions for message in user_errors(child)]
    return [str(exc)] if isinstance(exc, UserError) else []


def describe_error(exc) -> str:
    # SDK exception groups can contain URLs, credentials or meeting content.
    # Only expose our actionable UserErrors; never dump remote response bodies.
    if isinstance(exc, BaseExceptionGroup) and (found := user_errors(exc)):
        return "; ".join(found)
    if isinstance(exc, Timeout):
        return "Another Callimachus process holds the lock; wait for its pass or stop it"
    if isinstance(exc, UserError):
        return str(exc)
    return (
        f"{type(exc).__name__}. Check connectivity, credentials and archive access; "
        "retry sync after resolving the problem."
    )


def report_error(exc, state=None):
    print(f"Error: {describe_error(exc)}", file=sys.stderr)
    # Opt-in full traceback goes to a local file only; stderr never carries response bodies.
    if state and os.environ.get("CALLIMACHUS_DEBUG") == "1":
        (state / "last-error.log").write_text("".join(traceback.format_exception(exc)))


def watch(config, args):
    delay = config.interval
    while True:
        try:
            result = run_sync(config, args)
            if result == 2:
                return 2
            delay = config.interval
        except Exception as exc:
            report_error(exc, config.state)
            delay = min(max(delay * 2, config.interval), 3600)
        time.sleep(delay)


def doctor(config, args):
    with process_lock(config):
        for service in ("wispr", "drive"):
            token = config.state / f"{service}-token.json"
            print(f"{service}_credentials={'present' if token.exists() else 'missing'}")
        status_file = config.state / "status.json"
        if status_file.exists():
            status = json.loads(status_file.read_text())
            print(f"last_pass={'ok' if status['ok'] else 'failed'} at {status['time']}")
            print(f"  {status.get('summary') or status.get('error')}")
        print(f"destination={config.destination}")
    return 0


async def check_wispr_tools(config):
    async with connect_wispr(config.state, interactive=True, bind=config.oauth_bind) as session:
        names, cursor = set(), None
        while True:
            tools = await session.list_tools(cursor=cursor)
            names.update(t.name for t in tools.tools)
            if not tools.nextCursor:
                break
            cursor = tools.nextCursor
        if not {"search_meetings", "get_meeting"} <= names:
            raise UserError("Wispr account does not expose required meeting tools")


def login(config, args):
    with process_lock(config):
        if args.service == "wispr":
            asyncio.run(check_wispr_tools(config))
        else:
            service = drive_service(
                config.state, config.google_client, interactive=True, bind=config.oauth_bind
            )
            folder = DriveStore(service, config.state, config.google_folder).root()
            print(f"Drive archive: https://drive.google.com/drive/folders/{folder}")
        print("Authorization saved locally.")
    return 0


def migrate_command(config, args):
    with process_lock(config), archive_lock(config):
        return migrate.run(
            config.archive, current_archive(config), args.apply, args.apply and args.cleanup
        )


def main():
    args = parser().parse_args()
    # Restrict new files; silence only the SDK loggers that can include response bodies.
    os.umask(0o077)
    logging.getLogger().setLevel(logging.WARNING)
    for name in ("mcp", "httpx", "googleapiclient"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    state = None
    try:
        config = Config.load(args.env_file)
        config.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        state = config.state
        validate_dates(args)
        return args.func(config, args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        report_error(exc, state)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
