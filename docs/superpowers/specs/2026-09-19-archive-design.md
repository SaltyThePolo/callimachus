# Callimachus initial implementation

The user has authorized implementation now and selected the Google Drive API.

Python 3.11+ CLI: `login wispr`, `login drive`, `sync`, `watch`, `attach-audio`, and `doctor`. Wispr uses the official MCP SDK with browser OAuth, stored credentials and refresh support. Read `search_meetings` and `get_meeting`, page all results and text ranges, and only archive finalized meetings. Do not send any meeting text to another LLM.

Persist content-addressed immutable revisions under `meetings/<sha256-meeting-id>/revisions/<sha256-content>/`, then atomically publish `latest.json`. Include notes, complete summary, transcript, metadata and supplied audio. A missing transcript or audio is explicit in metadata. Preserve previous revisions; never propagate source deletion. A second identical run must reuse the same revision. Lock each local store for the entire sync to prevent concurrent writers. Cloud uploads publish the manifest last, and reuse files by deterministic IDs/properties on retries. Drive API uses desktop OAuth and drive.file access to an app-created root folder; existing folders require access granted to this OAuth app. Local staging remains after cloud delivery.

No verified Wispr audio-download interface exists. Provide `attach-audio` for a user-supplied file and automatically include it on subsequent syncs. This does not fulfill automatic original-audio retrieval: keep that limitation visible. Archive partial text by default rather than lose it, with a strict completeness option that exits unsuccessfully when artifacts are missing.

Credentials stay in an ignored state directory with owner-only permissions. Log counts and failure categories, never meeting text or tokens. Store no real meeting fixtures in the repository. Runtime can process real meetings only after the user's own local OAuth setup. This session may inspect the available connector's response structure without publishing private content.

Validate archive persistence, duplicate suppression, revision recovery, paginated text, malformed response handling, Drive resumable upsert and manifest ordering, OAuth callback state, and CLI errors with synthetic data. Live account-specific delivery requires configured OAuth credentials; report this separately from automated test results.
