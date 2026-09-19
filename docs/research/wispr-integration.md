# Wispr Notetaker integration research

Checked: 2026-09-19. Scope: official public documentation, not a live authenticated integration test.

## Finding

Text archiving has a documented integration route through remote MCP. Automatic preservation of the original audio remains unverified and is a gating decision for Callimachus. Do not advertise a complete audio/transcript/notes backup yet.

## Verified documentation

### Remote MCP

The server is `https://api.wisprflow.ai/connect/mcp` (no trailing slash). Setup uses browser authorization; users do not supply an API key or token. Current documentation supports Google, Apple, Microsoft and enterprise SSO sign-ins, but says email/password cannot complete authorization. Setup must finish within five minutes.

Meeting summaries, notes and transcripts are readable. Access is read-only. Transcripts need explicit requests, and long notes/transcripts arrive in portions. Search matches titles, notes and summaries, not transcript text. Flow need not remain open for cloud reads. Expired access requires reconnection; repeated queries may be throttled. Account and organization access/cloud policies apply.

Source: [Connect an MCP client to Wispr Flow](https://docs.wisprflow.ai/articles/9551372685-connect-an-mcp-client-to-wispr-flow-remote-mcp-server).

### Audio and retention

Uploaded audio is removed from Wispr servers when processing ends, including failed processing. Local audio is retained for approximately 24 hours after finalization. Transcripts persist by default, unless meeting deletion or a configured retention period removes them. Titles, notes and summaries have a different lifecycle and remain until meeting deletion. These facts establish a preservation deadline, not a supported extraction interface.

Source: [Notetaker privacy and security overview](https://docs.wisprflow.ai/articles/4497184932-Notetaker:-privacy-and-security-overview).

### Completion and export

Summary generation usually takes 2–5 minutes, with longer waits possible. Short recordings may need manual generation. A completed summary does not prove the refined transcript is ready. Resuming and updating a meeting can replace earlier content. The summary guide documents Copy to Markdown as including notes, summary, attendees, Brief, chat and transcript.

Source: [Flow Summaries in Notetaker](https://docs.wisprflow.ai/articles/1422535682-flow-summaries-in-notetaker-beta).

The retention guide describes that same clipboard export more narrowly as notes followed by a Summary section. Therefore verify exported content with a real sample before treating clipboard Markdown as a complete transcript backup. Retention windows can be imposed by an administrator; the dictation local-storage setting does not govern meeting transcripts.

Source: [Control meeting-data retention](https://docs.wisprflow.ai/articles/1761520520-Control-how-long-Notetaker-keeps-your-meeting-data).

### Separate transcription API

Wispr publishes a voice interface API for converting submitted audio into text over REST or WebSocket. Its API-key authentication is not evidence that Notetaker archive retrieval accepts an API key.

Source: [Voice Interface API introduction](https://api-docs.wisprflow.ai/introduction).

## Not established by the reviewed documentation

- A supported audio-download endpoint, export button, or stable local-audio filesystem contract.
- A completion webhook or push notification suitable for an archiver.
- Exact MCP tool names, input/output schemas, pagination guarantees, stable recording IDs, change cursors or readiness fields.
- Unattended credential renewal and its required storage for a custom background client.
- Whether this user's account currently exposes the required tools and permissions.

Absence from this review does not prove a capability does not exist. Search snippets included older, conflicting MCP content; current opened documentation was preferred. In particular, do not infer audio download from the word “recording” in calendar-link documentation.

## Proposed next decision gate

With an authorized account, inspect the MCP tool catalog and one completed meeting. Validate full transcript pagination, notes/summary separation, stable IDs, updates, readiness, authentication renewal and throttling. Request a supported audio-export route from Wispr if the catalog lacks one. Until that is verified, choose explicitly whether audio is mandatory for the first release or whether a clearly labelled text-only first version is acceptable. Do not silently redefine the user's requested archive.

Polling with retry/backoff and per-artifact states is a candidate design, not a verified Wispr feature. A separately supplied audio file is another possible input, not automatic recovery of Wispr's recording. No account data, tokens or recordings were accessed in this research.
