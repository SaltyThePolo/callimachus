import argparse
import asyncio
import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from filelock import FileLock

from .auth import connect_wispr, drive_service
from .config import Config
from .current import CurrentArchive, LocalStore
from .drive import DriveStore
from .errors import UserError
from .models import Meeting
from .wispr import WisprSource, decode_result


def parser():
    root = argparse.ArgumentParser(description="Archive Wispr Flow meetings locally or to Drive")
    root.add_argument("--env-file", type=Path, default=Path(".env"))
    commands = root.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login", help="Authorize an account in your browser")
    login.add_argument("service", choices=["wispr", "drive"])
    commands.add_parser("doctor", help="Check local setup without accessing meeting content")
    attach = commands.add_parser(
        "attach-audio", help="Associate your own audio file with a meeting"
    )
    attach.add_argument("meeting_id")
    attach.add_argument("file", type=Path)
    for name in ("sync", "watch"):
        cmd = commands.add_parser(
            name, help="Archive once" if name == "sync" else "Continuously archive"
        )
        cmd.add_argument("--since", help="Inclusive ISO datetime with timezone")
        cmd.add_argument("--until", help="Exclusive ISO datetime with timezone")
        cmd.add_argument(
            "--input", type=Path, help="Import a normalized JSON meeting list instead of MCP"
        )
    return root


def validate_dates(args):
    parsed = []
    for name in ("since", "until"):
        raw = getattr(args, name, None)
        if raw:
            try:
                value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if value.tzinfo is None:
                    raise UserError()
            except ValueError:
                raise UserError(f"--{name} requires an ISO datetime with timezone") from None
            parsed.append(value)
    if len(parsed) == 2 and parsed[0] >= parsed[1]:
        raise UserError("--since must precede --until")


def attach_audio(config, meeting_id, source):
    if source.suffix.lower() not in {
        ".wav",
        ".mp3",
        ".m4a",
        ".mp4",
        ".ogg",
        ".webm",
        ".flac",
        ".aac",
    }:
        raise UserError("Unsupported recording extension")
    if not source.is_file() or source.stat().st_size == 0:
        raise UserError("Recording must be a nonempty local file")
    key = hashlib.sha256(meeting_id.encode()).hexdigest()
    folder = config.state / "audio" / key
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = folder / ("recording" + source.suffix.lower())
    fd, pending = tempfile.mkstemp(dir=folder, prefix=".pending-")
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as stream:
            shutil.copyfileobj(stream, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(pending, target)
        for old in folder.glob("recording.*"):
            if old != target:
                old.unlink()
    finally:
        Path(pending).unlink(missing_ok=True)
    print("Recording attached. Run sync to publish the next revision.")


async def meetings(config, args):
    if args.input:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise UserError("Input must be a JSON list of normalized meetings")
        for item in data:
            if not isinstance(item, dict):
                raise UserError("Each input meeting must be an object")
            yield Meeting(**item)
        return
    async with connect_wispr(config.state) as session:

        async def call(name, arguments):
            return decode_result(await session.call_tool(name, arguments))

        async for meeting in WisprSource(call).meetings(args.since, args.until):
            yield meeting


async def sync(config, args):
    if config.destination == "drive":
        store = DriveStore(drive_service(config.state), config.state, config.google_folder)
        registry = config.state / "drive-registry.json"
    else:
        store, registry = LocalStore(config.archive), config.state / "registry.json"
    archive = CurrentArchive(store, registry, config.timezone, config.restore)
    archive.reconcile()
    counts = {"imported": 0, "pending": 0, "suppressed": 0}
    async for meeting in meetings(config, args):
        counts[archive.publish(meeting)] += 1
    summary = " ".join(f"{k}={v}" for k, v in counts.items())
    print(f"{summary} destination={config.destination}", flush=True)
    return 2 if counts["pending"] and config.require_complete else 0


def run_sync(config, args):
    """One synchronization pass; the local archive directory is protected by its own lock."""
    if config.destination == "drive":
        return asyncio.run(sync(config, args))
    config.archive.mkdir(parents=True, exist_ok=True, mode=0o700)
    with FileLock(str(config.archive / ".writer.lock"), timeout=0):
        return asyncio.run(sync(config, args))


def report_error(exc):
    # SDK exception groups can contain URLs, credentials or meeting content.
    # Only expose our actionable ValueErrors; never dump remote response bodies.
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            if isinstance(child, (UserError, BaseExceptionGroup)):
                report_error(child)
                return
    if isinstance(exc, UserError):
        print(f"Error: {exc}", file=sys.stderr)
    else:
        print(
            f"Error: {type(exc).__name__}. Check connectivity, credentials and archive access; "
            "retry sync after resolving the problem.",
            file=sys.stderr,
        )


def watch(config, args):
    delay = config.interval
    while True:
        try:
            with FileLock(str(config.state / "process.lock"), timeout=0):
                result = run_sync(config, args)
            if result == 2:
                return 2
            delay = config.interval
        except Exception as exc:
            report_error(exc)
            delay = min(max(delay * 2, config.interval), 3600)
        time.sleep(delay)


def main():
    args = parser().parse_args()
    # Restrict new files; suppress SDK diagnostics that can include response bodies.
    os.umask(0o077)
    logging.disable(logging.CRITICAL)
    try:
        config = Config.load(args.env_file)
        validate_dates(args)
        config.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        if args.command == "watch":
            return watch(config, args)
        with FileLock(str(config.state / "process.lock"), timeout=0):
            if args.command == "doctor":
                for service in ("wispr", "drive"):
                    print(
                        f"{service}_credentials={'present' if (config.state / (service + '-token.json')).exists() else 'missing'}"
                    )
                print(f"destination={config.destination}; local staging is retained")
                return 0
            if args.command == "login":
                if args.service == "wispr":

                    async def login():
                        async with connect_wispr(config.state, interactive=True) as session:
                            names, cursor = set(), None
                            while True:
                                tools = await session.list_tools(cursor=cursor)
                                names.update(t.name for t in tools.tools)
                                if not tools.nextCursor:
                                    break
                                cursor = tools.nextCursor
                            if not {"search_meetings", "get_meeting"} <= names:
                                raise UserError(
                                    "Wispr account does not expose required meeting tools"
                                )

                    asyncio.run(login())
                else:
                    service = drive_service(config.state, config.google_client, interactive=True)
                    folder = DriveStore(service, config.state, config.google_folder).root()
                    print(f"Drive archive: https://drive.google.com/drive/folders/{folder}")
                print("Authorization saved locally.")
                return 0
            if args.command == "attach-audio":
                attach_audio(config, args.meeting_id, args.file)
                return 0
            return run_sync(config, args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        report_error(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
