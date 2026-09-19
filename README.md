# Callimachus

**Give your meetings a lasting home.**

Callimachus is a Python CLI that archives finalized **Wispr Flow Notetaker** meetings to a local directory and, optionally, directly to **Google Drive through its API**.

It reads notes, summaries and full paginated transcripts, preserves immutable revisions, and can run continuously. It does not require an LLM or a Google Drive desktop client.

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

`sync` runs once. `watch` polls every five minutes by default while the process is running. Stop with Ctrl+C. It does not install a background service or launch at login. The machine must remain awake and connected.

Wispr login opens your browser, listens on `127.0.0.1:8765` for up to five minutes, and stores authorization locally. Your account needs Notetaker/MCP access. No Wispr API key is required. A pre-existing ChatGPT/Codex connection does not authorize this standalone client. See [Wispr’s remote MCP setup](https://docs.wisprflow.ai/articles/9551372685-connect-an-mcp-client-to-wispr-flow-remote-mcp-server).

## Google Drive API setup

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

By default, login creates a private **Callimachus** folder in your Drive and prints its link. The app requests the `drive.file` scope, which limits access to files available to this OAuth app. It never changes sharing permissions.

`CALLIMACHUS_GOOGLE_DRIVE_FOLDER_ID` optionally selects an existing folder **already accessible to this OAuth app**. Merely pasting an arbitrary folder ID does not grant access under `drive.file`; leaving this setting blank is the supported simplest setup. A Google Picker flow is not included.

Google OAuth setup follows the [official Python quickstart](https://developers.google.com/workspace/drive/api/quickstart/python). In external testing mode, refresh tokens can expire after seven days for these scopes; production consent configuration or reauthorization may be needed. See [Google’s OAuth token-expiration guidance](https://developers.google.com/identity/protocols/oauth2#expiration).

## What gets archived

```text
archive/
  meetings/
    <sha256-of-meeting-id>/
      latest.json
      revisions/
        <revision-hash>/
          metadata.json
          notes.md
          summary.md
          transcript.txt       # when available
          recording.m4a        # when supplied; original extension retained
```

The same structure is uploaded to Drive. Metadata includes the meeting title, source ID, timestamps, attendees, source link, checksums, and missing artifacts. Hash-based paths avoid collisions and unsafe filenames; human-readable meeting details remain in metadata.

Identical input reuses the existing revision. Changed content creates another revision. Old revisions remain intact, and deletion in Wispr does not delete your archive. `latest.json` points to the current revision and is published only after the revision files have been saved or uploaded. Drive delivery keeps the local staging archive. Each pass first retries all staged revisions, including history whose source meeting has since changed or been deleted, before reading new source content.

Partial archives are preserved by default so available text is not lost while another artifact is unavailable. Missing transcript, summary, or recording is reported in metadata. An empty personal-notes section is valid. Set `CALLIMACHUS_REQUIRE_COMPLETE=true` to make `sync` or `watch` exit with code 2 when any archived meeting is incomplete; the available data is still saved and uploaded.

## Add a recording

Use the original Wispr meeting ID from an archive’s `metadata.json`:

```sh
uv run callimachus attach-audio '<meeting-id>' '/path/to/recording.m4a'
uv run callimachus sync
```

The command copies the file into private local state. Subsequent syncs include it in the meeting archive and Drive delivery. Supported extensions: `.wav`, `.mp3`, `.m4a`, `.mp4`, `.ogg`, `.webm`, `.flac`, `.aac`. This is a manual association, not automatic extraction from Wispr.

Wispr documents that uploaded audio is deleted after processing and local audio is retained for approximately 24 hours. Preserve audio through a supported export path if one is available to you. See the [integration research](docs/research/wispr-integration.md).

## Configuration

All runtime settings are documented in [`.env.example`](.env.example). Environment variables override values in the dotenv file. Relative paths resolve from the working directory; use absolute paths when scheduling the tool.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CALLIMACHUS_DESTINATION` | `local` | `local` or direct API `drive` |
| `CALLIMACHUS_ARCHIVE_DIR` | `./archive` | Local archive, retained in Drive mode too |
| `CALLIMACHUS_STATE_DIR` | `./.callimachus` | Credentials, attached audio, locks and Drive IDs |
| `CALLIMACHUS_POLL_INTERVAL` | `300` | Poll interval in seconds, minimum 60 |
| `CALLIMACHUS_REQUIRE_COMPLETE` | `false` | Exit code 2 for partial archives |
| `CALLIMACHUS_GOOGLE_CLIENT_SECRET_FILE` | unset | Downloaded desktop OAuth JSON |
| `CALLIMACHUS_GOOGLE_DRIVE_FOLDER_ID` | unset | Optional folder accessible to this OAuth app |

For an alternate dotenv file, put the option before the command:

```sh
uv run callimachus --env-file /absolute/path/callimachus.env sync
uv run callimachus doctor
```

`doctor` checks local credential-file presence; it does not verify remote authorization. `sync` exits 0 after successful delivery (including partial archives by default), 1 on configuration/access/integrity/transfer errors, and 2 for strict completeness failure. Ctrl+C exits 130. `watch` logs operational error categories and retries with increasing delay, up to one hour; credentials requiring fresh consent must be renewed with `login`. Locks are released between polling passes, allowing login and audio attachment while the watcher sleeps. If a pass is active, retry the command after that pass. Strict completeness mode stops the watcher with exit code 2 on incomplete archives.

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
