# Callimachus

**Give your meetings a lasting home.**

Callimachus is a planned tool for automatically archiving meeting recordings, transcripts, and notes from **Wispr Flow Notetaker** into a folder you control — locally or on Google Drive.

> **Status: design and integration research.** This repository currently contains the project documentation and configuration proposal. There is no runnable application yet. Automatic ingestion and audio export must be validated before implementation.

## Intended workflow

1. Wispr Flow captures a meeting and prepares its transcript and notes.
2. Callimachus detects that the meeting artifacts are ready through a supported integration, still to be selected.
3. It collects the available recording, transcript, and notes into a single meeting archive.
4. It writes the archive to your chosen destination and tracks the result so retries do not create duplicates.

A proposed archive layout:

```text
archive/
  2026/
    09/
      2026-09-19_project-review_<meeting-id>/
        recording.<original-extension>
        transcript.md
        notes.md
        metadata.json
```

The recording retains its original format. The stable meeting ID distinguishes meetings with the same title. Metadata is intended to record the source identity, meeting time, archive time, and availability of each artifact. Missing audio must be explicit; a notes-only export must not be presented as a complete archive. Exact completeness and update policies remain open decisions.

## Integration feasibility

Wispr documents a remote MCP integration for reading notes, summaries, and transcripts. It uses browser authorization rather than a manually configured API key. These are documented capabilities, not yet tested by Callimachus.

**Original audio is the main unresolved dependency.** Wispr states that uploaded audio is deleted after processing and local audio is retained for approximately 24 hours. A supported audio-download interface, unattended credential renewal, and a reliable completion signal have not been established by this research. Audio metadata is not the recording itself.

See the [integration research](docs/research/wispr-integration.md) and [Define the Callimachus meeting archive](https://github.com/SaltyThePolo/callimachus/issues/1) for evidence and the next validation steps.

Official references: [remote MCP setup](https://docs.wisprflow.ai/articles/9551372685-connect-an-mcp-client-to-wispr-flow-remote-mcp-server) and [privacy and storage](https://docs.wisprflow.ai/articles/4497184932-Notetaker:-privacy-and-security-overview).

## Storage destinations

| Destination | Proposed behavior | Configuration |
| --- | --- | --- |
| Local folder | Write meeting archives to a directory you choose. | Archive directory |
| Google Drive desktop folder | Write to an existing local Drive folder; the Drive client handles cloud synchronization. | Archive directory inside your Drive folder |
| Google Drive API | Upload directly without requiring the desktop client. | Authentication and parent folder; pending a design decision |

Local write success and successful cloud synchronization are different outcomes. Drive API support and the first release's Drive mode are not decided yet.

## Configuration proposal

Start from the tracked template:

```sh
cp .env.example .env
```

Edit `.env` for your environment. This prepares a configuration file only: there is no install or run command yet, and no program currently reads these variables.

| Variable | Purpose | Example |
| --- | --- | --- |
| `CALLIMACHUS_ARCHIVE_DIR` | Local destination, optionally inside a Google Drive desktop folder. | `./archive` |
| `CALLIMACHUS_TIMEZONE` | Timezone proposed for archive date organization. | `Europe/Rome` |
| `CALLIMACHUS_LOG_LEVEL` | Proposed operational log verbosity. | `info` |

The template also reserves a commented Drive parent-folder setting for a possible API integration. Wispr endpoints, tokens, polling intervals, and Google authentication settings will be added once the supported integration is established; no speculative credentials are required today.

Keep meeting content and credentials outside version control. The supplied `.gitignore` excludes local configuration, archive data, and credentials stored in the documented private directories. Custom archive locations should be outside this repository.

## Development and contributions

The next step is to validate Wispr access and agree on archive completeness, updates, and Drive delivery. Follow the [GitHub issues](https://github.com/SaltyThePolo/callimachus/issues) for research and design decisions. Stack, packaging, installation, and automated tests will be documented when implementation begins.

Use synthetic meeting data in examples, issues, and future tests. Please discuss substantial implementation work in an issue first while the integration is being selected.

A software license has not been selected yet; this repository currently makes no open-source license grant.

## Why “Callimachus”?

Callimachus — Callimaco in Italian — was a Greek poet and scholar from Cyrene who worked in Alexandria in the third century BCE. His *Pinakes*, a bibliographic work in 120 books, organized the literary holdings associated with the Library of Alexandria. His poetry includes hymns, epigrams, and the *Aetia*.

The name is a nod to that work of preserving and organizing knowledge: giving conversations an archive where they can be found again. See [AGNI / Boston University’s profile of Callimachus](https://agnionline.bu.edu/about/our-people/authors/callimachus/).

---

Callimachus is an independent project and is not affiliated with Wispr or Google.
