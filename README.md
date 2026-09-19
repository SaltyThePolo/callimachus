# Callimachus

**Give your meetings a lasting home.**

Callimachus is a Python CLI that archives finalized **Wispr Flow Notetaker** meetings to a local directory or directly to **Google Drive through its API**, as readable per-meeting folders that stay current with Wispr.

It reads notes, summaries and full paginated transcripts into readable per-meeting folders, keeps them current with Wispr, and can run continuously. It does not require an LLM or a Google Drive desktop client.

> **Early release.** The archive, CLI, OAuth flows and Drive uploader are implemented and covered by automated tests. Wispr response shapes have been checked through an authenticated connector; this standalone client's OAuth and end-to-end cloud delivery still need validation with your account.
>
> **Audio limitation:** the available Wispr MCP catalog does not expose a supported recording download. Callimachus can archive audio you supply with `attach-audio`, but cannot yet retrieve the original recording automatically. Missing recordings are always marked explicitly.

## Quick start

Requires **Python 3.11+** and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/SaltyThePolo/callimachus.git
cd callimachus
uv sync --locked
cp .env.example .env
```

Edit `.env`, then authorize Wispr from an interactive desktop:

```sh
uv run callimachus login wispr
uv run callimachus sync
uv run callimachus watch
```

`sync` runs once. `watch` polls every five minutes by default while the process is running; passes are serialized, a slow pass never overlaps the next one, and a second Callimachus process is rejected while a pass holds the lock. Stop with Ctrl+C. It does not install a background service or launch at login. The machine must remain awake and connected.

Discovery starts from all available history, with no cutoff to choose. When Wispr caps a search, the start-time window is split and each part is paginated; stable meeting IDs prevent duplicates across parts. A window that cannot be split further is reported as incomplete discovery instead of being silently truncated. `--since` and `--until` remain available to narrow a pass manually. Every pass revisits every meeting: entries whose `modified_at` matches the archived snapshot are counted as `unchanged` and not fetched again, so edits to old meetings and meetings that became ready later are picked up on the next pass. A failed search or a failed pass never marks anything as deleted.

Wispr login prints an authorization URL, opens it in your browser when one is available, listens on `127.0.0.1:8765` for up to five minutes, and stores authorization locally. Google login uses `127.0.0.1:8766` the same way. Your account needs Notetaker/MCP access. No Wispr API key is required. A pre-existing ChatGPT/Codex connection does not authorize this standalone client. See [Wispr’s remote MCP setup](https://docs.wisprflow.ai/articles/9551372685-connect-an-mcp-client-to-wispr-flow-remote-mcp-server).

## Google Drive API setup

For step-by-step console instructions, see [Get the Google Drive desktop OAuth JSON](docs/google-drive-oauth-setup.md).

1. Create a Google Cloud project and enable the **Google Drive API**.
2. Configure its OAuth consent screen and add yourself as a test user if the app is in testing mode.
3. Create an OAuth client with application type **Desktop app**. Download its JSON into `credentials/google-client.json` (ignored by Git).
4. Set these values in `.env`:

```dotenv
CALLIMACHUS_DESTINATION=drive
CALLIMACHUS_GOOGLE_CLIENT_SECRET_FILE=./credentials/google-client.json
```

5. Authorize Google and run the archiver:

```sh
uv run callimachus login drive
uv run callimachus sync
uv run callimachus watch
```

By default, login creates a private **Callimachus** folder in your Drive and prints its link. Meeting folders are created inside it with the same readable layout as the local destination; Drive mode keeps no local copy of the meeting content, only credentials and the private registries under `CALLIMACHUS_STATE_DIR`. Each object keeps a stable Drive ID across updates and renames, so links to a meeting folder survive source edits.

Drive has no transaction spanning the three files. If a sync is interrupted between uploads, a folder can briefly hold a mix of old and new files; the meeting is marked synchronized only after all three writes succeed, and the next sync completes it. Folders or files you trash in Drive stay trashed unless `CALLIMACHUS_RESTORE_DELETED=true`, in which case fresh objects are created. Manually renaming or moving a Callimachus folder inside Drive is unsupported and reported as an error until you restore it or trash it. The app requests the `drive.file` scope, which limits access to files available to this OAuth app. It never changes sharing permissions.

`CALLIMACHUS_GOOGLE_DRIVE_FOLDER_ID` optionally selects an existing folder **already accessible to this OAuth app**. Merely pasting an arbitrary folder ID does not grant access under `drive.file`; leaving this setting blank is the supported simplest setup. A Google Picker flow is not included.

Google OAuth setup follows the [official Python quickstart](https://developers.google.com/workspace/drive/api/quickstart/python). In external testing mode, refresh tokens can expire after seven days for these scopes; production consent configuration or reauthorization may be needed. See [Google’s OAuth token-expiration guidance](https://developers.google.com/identity/protocols/oauth2#expiration).

## Run it in Docker

A local source build and one Compose file run the watcher unattended on macOS, Windows or Linux with a maintained Docker runtime. No prebuilt Callimachus image or Docker Hub account is required. Private state (credentials, registries, status) lives in the mounted `.callimachus/` directory, so replacing the container keeps identity, deletion intent and authorization. In Drive mode the archive mount stays unused: there is no local mirror.

```sh
cp .env.example .env            # edit destination and Drive settings; Compose reads it
mkdir -p .callimachus archive credentials
docker compose build
docker compose run --rm --service-ports setup login wispr
docker compose run --rm --service-ports setup login drive   # Drive mode only
docker compose up -d
docker compose run --rm setup doctor
```

Setup is a separate, interactive command: it prints an authorization URL to open in the host browser and listens for the callback inside the container, published only on the host loopback (`127.0.0.1:8765` for Wispr, `127.0.0.1:8766` for Google). The redirect URI stays on `127.0.0.1`, the OAuth `state` is validated and PKCE is retained; the listener closes when setup finishes. The watcher publishes no ports and never opens a browser: expired access tokens are refreshed with the stored refresh token on a cold start, rotated tokens are saved atomically, and revoked consent makes the pass fail with an actionable `login` message in `status.json`.

On a headless server, run the setup command over SSH with a loopback tunnel, then open the printed URL in your local browser:

```sh
ssh -L 8765:127.0.0.1:8765 -L 8766:127.0.0.1:8766 user@server
```

`restart: unless-stopped` brings the watcher back whenever the Docker runtime starts. Enable the runtime at login or boot: Docker Desktop → Settings → General → *Start Docker Desktop when you sign in* on macOS and Windows, `systemctl enable docker` on Linux. Do not add a launchd or systemd unit for the container itself; a second supervisor competes with Docker's restart policy.

The image contains only the application and its dependencies. `.dockerignore` is a whitelist, so environment files, credentials, state and archives never enter the build context; mount them at run time. The container runs as `CALLIMACHUS_UID:CALLIMACHUS_GID` (default `1000:1000`) so the mounted state and archive stay readable on the host; on Linux set them to your `id -u` and `id -g` in `.env`, and create `.callimachus/` and `archive/` before the first start so Docker does not create them as root.

Build and start locally with `docker compose up --build -d`. CI runs the Python checks; it does not build or publish Docker images, including on releases. Docker Hub secrets are not used.

## What gets archived

The local destination is a flat collection of readable folders, one per meeting, named after the meeting start in the configured timezone (`CALLIMACHUS_TIMEZONE`, default `UTC`):

```text
archive/
  2026-09-19 10-00 - Weekly planning/
    notes.md
    summary.md
    transcript.md
  2026-09-19 10-00 - Weekly planning (2)/    # a different meeting with the same name
```

Only complete text is published: a finalized meeting with a nonempty summary and transcript and fully retrieved notes (empty personal notes are valid). Meetings still being processed by Wispr are reported as `pending`; any previously archived files stay untouched until the update is complete. Audio never gates text import. Set `CALLIMACHUS_REQUIRE_COMPLETE=true` to make `sync` or `watch` exit with code 2 while any meeting is pending.

Wispr is authoritative for content: source edits overwrite the current files, and title, start-time or timezone changes rename the folder. Unsafe filename characters are normalized and same-name meetings get a numeric suffix. Deleting a meeting in Wispr never deletes its archive.

Deleting a file or folder in the archive is respected: it is recorded in the private registry and not recreated, even after source edits, renames or restarts (`suppressed` in the sync output). Set `CALLIMACHUS_RESTORE_DELETED=true` to recreate deleted material from the source on the next sync. Manually renaming or moving folders is unsupported; the application treats a missing folder as deleted.

Technical state (meeting identity, folder names, publication and deletion markers) lives in `CALLIMACHUS_STATE_DIR/registry.json` for the local destination and `drive-registry.json` plus `drive-objects.json` for Drive, never inside the archive. **Back it up with the archive**: it holds your deletion intent, and losing it is not a supported silent reset. Archives created by earlier versions in the `meetings/<hash>/revisions` layout are detected and must be migrated explicitly before syncing into the same directory.

## Add a recording

Use the original Wispr meeting ID:

```sh
uv run callimachus attach-audio '<meeting-id>' '/path/to/recording.m4a'
uv run callimachus sync
```

The command copies the file into private local state. The readable layout is text-only: attached audio is kept privately and never deleted, but not published to either destination. Supported extensions: `.wav`, `.mp3`, `.m4a`, `.mp4`, `.ogg`, `.webm`, `.flac`, `.aac`. This is a manual association, not automatic extraction from Wispr.

Wispr documents that uploaded audio is deleted after processing and local audio is retained for approximately 24 hours. Preserve audio through a supported export path if one is available to you. See the [integration research](docs/research/wispr-integration.md).

## Configuration

All runtime settings are documented in [`.env.example`](.env.example). Environment variables override values in the dotenv file. Relative paths resolve from the working directory; use absolute paths when scheduling the tool.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CALLIMACHUS_DESTINATION` | `local` | `local` or direct API `drive` |
| `CALLIMACHUS_ARCHIVE_DIR` | `./archive` | Local archive; unused in Drive mode |
| `CALLIMACHUS_STATE_DIR` | `./.callimachus` | Credentials, registry, attached audio, locks and Drive IDs |
| `CALLIMACHUS_TIMEZONE` | `UTC` | IANA timezone used in folder names |
| `CALLIMACHUS_RESTORE_DELETED` | `false` | Recreate files and folders you deleted from the archive |
| `CALLIMACHUS_POLL_INTERVAL` | `300` | Poll interval in seconds, minimum 60 |
| `CALLIMACHUS_REQUIRE_COMPLETE` | `false` | Exit code 2 while any meeting is pending |
| `CALLIMACHUS_GOOGLE_CLIENT_SECRET_FILE` | unset | Downloaded desktop OAuth JSON |
| `CALLIMACHUS_GOOGLE_DRIVE_FOLDER_ID` | unset | Optional folder accessible to this OAuth app |
| `CALLIMACHUS_OAUTH_BIND` | `127.0.0.1` | Callback listener address for `login`; `0.0.0.0` inside a container |

For an alternate dotenv file, put the option before the command:

```sh
uv run callimachus --env-file /absolute/path/callimachus.env sync
uv run callimachus doctor
```

`doctor` checks local credential-file presence and prints the outcome of the last pass from `CALLIMACHUS_STATE_DIR/status.json` (time, ok or failed, counts or error category); it does not verify remote authorization. The status file never contains meeting text or tokens. `sync` exits 0 after successful delivery (including partial archives by default), 1 on configuration/access/integrity/transfer errors, and 2 for strict completeness failure. Ctrl+C exits 130. `watch` logs operational error categories and retries with increasing delay, up to one hour; credentials requiring fresh consent must be renewed with `login`. Locks are released between polling passes, allowing login and audio attachment while the watcher sleeps. If a pass is active, retry the command after that pass. Strict completeness mode stops the watcher with exit code 2 on incomplete archives.

Run only one writer per archive and Drive destination. Local locks prevent concurrent use of the same state/archive directories; they do not coordinate separate machines. Do not delete the state directory during a sync, and keep it private. Custom archive or credential locations should be outside this Git repository.

## History and large accounts

Every pass scans the selected date window, including earlier meetings, to pick up edits. Unfinalized meetings are skipped. Text is read until the provider’s continuation markers are exhausted. If the meeting changes during pagination, the pass fails and can be retried; no mixed revision is published.

Wispr caps a search at 1,000 results. Callimachus reports a cap instead of silently declaring a complete backup. Narrow the window when necessary:

```sh
uv run callimachus sync --since 2026-09-01T00:00:00+02:00 --until 2026-10-01T00:00:00+02:00
```

Bounds apply to meeting start times; `since` is inclusive and `until` exclusive. Large archives may need longer polling intervals. There is no automatic historical partitioning or provider webhook in this release.

## Offline smoke test and development

Try the complete local archival path with synthetic data, without account access:

```sh
uv run callimachus sync --input examples/meeting.json
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

Keep `CALLIMACHUS_DESTINATION=local` for the offline test. `--input` accepts a list of normalized meetings with `id`, `title`, timezone-aware `start`, `notes`, `summary`, and `transcript` (string or null), plus optional `end`, `modified_at`, `share_link`, and `attendees`. Input files must be trusted local files. Date filters are for the Wispr source, not JSON imports.

Tests use synthetic data and a fake Google API boundary; they do not access your accounts. Credentials, recordings and personal meeting content must never be submitted in issues or fixtures. See the [decision map](https://github.com/SaltyThePolo/callimachus/issues/1) for remaining integration validation.

A software license has not been selected yet; this repository currently makes no open-source license grant.

## Why “Callimachus”?

Callimachus — Callimaco in Italian — was a Greek poet and scholar from Cyrene who worked in Alexandria in the third century BCE. His *Pinakes*, a bibliographic work in 120 books, organized the literary holdings associated with the Library of Alexandria. His poetry includes hymns, epigrams, and the *Aetia*.

The name is a nod to that work of preserving and organizing knowledge: giving conversations an archive where they can be found again. See [AGNI / Boston University’s profile of Callimachus](https://agnionline.bu.edu/about/our-people/authors/callimachus/).

---

Callimachus is an independent project and is not affiliated with Wispr or Google.
