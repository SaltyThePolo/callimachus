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
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock, Timeout

from .archive import atomic_write, canonical
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


async def sync(config, args):
    if config.destination == "drive":
        store = DriveStore(drive_service(config.state), config.state, config.google_folder)
        registry = config.state / "drive-registry.json"
    else:
        store, registry = LocalStore(config.archive), config.state / "registry.json"
    archive = CurrentArchive(store, registry, config.timezone, config.restore)
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
    """One synchronization pass; the local archive directory is protected by its own lock."""
    try:
        if config.destination == "drive":
            return asyncio.run(sync(config, args))
        config.archive.mkdir(parents=True, exist_ok=True, mode=0o700)
        with FileLock(str(config.archive / ".writer.lock"), timeout=0):
            return asyncio.run(sync(config, args))
    except Exception as exc:
        record_status(config, False, describe_error(exc))
        raise


def describe_error(exc) -> str:
    # SDK exception groups can contain URLs, credentials or meeting content.
    # Only expose our actionable ValueErrors; never dump remote response bodies.
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            if isinstance(child, (UserError, BaseExceptionGroup)):
                return describe_error(child)
    if isinstance(exc, Timeout):
        return "Another Callimachus process holds the lock; wait for its pass or stop it"
    if isinstance(exc, UserError):
        return str(exc)
    return (
        f"{type(exc).__name__}. Check connectivity, credentials and archive access; "
        "retry sync after resolving the problem."
    )


def report_error(exc):
    print(f"Error: {describe_error(exc)}", file=sys.stderr)


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
                status_file = config.state / "status.json"
                if status_file.exists():
                    status = json.loads(status_file.read_text())
                    print(f"last_pass={'ok' if status['ok'] else 'failed'} at {status['time']}")
                    print(f"  {status.get('summary') or status.get('error')}")
                print(f"destination={config.destination}")
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
