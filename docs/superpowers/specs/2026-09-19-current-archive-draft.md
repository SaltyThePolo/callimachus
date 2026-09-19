# Current-only meeting archive — planning draft

Status: product behavior confirmed by the user. The [execution specification](2026-09-19-current-archive-spec.md) translates these requirements into implementation and validation work. No migration or runtime changes have been authorized by this confirmation alone.

This document derives requirements from the ongoing [Callimachus decision map](https://github.com/SaltyThePolo/callimachus/issues/1). GitHub decision tickets remain the canonical record. The earlier initial-implementation design describes existing behavior, not the target agreed during this interview.

## 1. User-approved behavior

### Readable archive

Source: [Choose readable meeting folders and naming rules](https://github.com/SaltyThePolo/callimachus/issues/13).

Each meeting has one folder directly beneath the archive root:

```text
Callimachus/
  2026-09-19 14-30 - Example meeting/
    notes.md
    summary.md
    transcript.md
```

- Folder pattern: `YYYY-MM-DD HH-mm - Meeting title`. No nested year/month/day folders and no visible revision hierarchy.
- The archive timezone is configurable and defaults to UTC.
- Changing the configured timezone renames existing folders consistently.
- A Wispr title change renames the existing meeting folder rather than creating another archive.
- Distinct meetings with colliding names receive minimal numeric suffixes, such as `(2)` and `(3)`. Repeated synchronization of the same meeting does not allocate another suffix.
- Three separate Markdown files contain notes, summary, and transcript. The English filenames above are a proposed implementation convention, not separately approved user wording.

### Readiness and updates

Source: [Choose the archive completeness and update policy](https://github.com/SaltyThePolo/callimachus/issues/3).

- Wait for notes, summary, and transcript before initial publication; original audio is not required.
- Intentionally empty personal notes are valid. A missing or failed notes response is not evidence that notes are empty.
- Wispr is the source of truth for content. Source edits update the current archive files; no permanent previous versions are retained by Callimachus.
- While a source update is still processing, keep the last successfully archived contents until the new required materials are ready.
- Editing file contents directly in the destination is not an independent authoring workflow; Wispr content may replace those edits.
- Provider-managed file history is distinct from a Callimachus revision directory; this plan does not promise to control Google's internal retention behavior.

### Automatic operation

Source: [Choose automatic import and unattended operation](https://github.com/SaltyThePolo/callimachus/issues/14).

- Docker is the deployment format for Windows, Linux, and macOS, with the same application behavior on a desktop or always-on server.
- One active machine synchronizes a given archive. Concurrent multi-host writers are out of scope.
- Start automatically. On a Mac, startup after user login is sufficient; pre-login execution is not required.
- Check for new and updated meetings every five minutes under normal operation.
- Initial import includes all available meetings, without a user-selected cutoff.
- Retry temporary failures automatically. No email, Telegram, or other notification-service integration is required.
- Do not add a dedicated offline mode or durable offline content queue. Retry failed work through normal synchronization.

### Destination ownership and storage

Source: [Choose archive migration and destination edit behavior](https://github.com/SaltyThePolo/callimachus/issues/15).

- Deleting a meeting from Wispr does not delete its archive. Preserve its last successfully archived contents.
- Restoration of deleted destination files and whole meeting folders is configurable and **disabled by default**.
- With restoration disabled, later source updates must not recreate deleted destination material.
- Manual moves or renames of archive folders are unsupported and the user's responsibility. Do not build an automatic repair/reconciliation feature for them.
- In Drive mode, retain only temporary local meeting content needed for transfer, not a permanent full local content archive. Operational state is separate from meeting content.
- The existing local-only destination is not removed by this Drive-specific storage decision.
- Convert the existing archive to the new structure rather than starting a separate archive. This planning choice does not execute migration or authorize immediate deletion of old data.

## 2. Proposed minimal engineering choices

These are proposals for the buildable specification, not additional user decisions already made.

### Identity, names, and deletion tracking

Keep stable source IDs, remote file IDs, last applied content fingerprints, and deletion markers in private operational state. IDs identify meetings internally but are not the visible navigation scheme. Distinguish files never successfully published from files deleted after successful publication; a failed first upload is not a user deletion.

Use the meeting start timestamp for the name, converted through the configured timezone. Keep naming deterministic, sanitize characters incompatible with supported filesystems, and handle empty or overlong titles without exposing IDs as the default folder name. Proposed behavior: source start-time corrections update the existing name just as title corrections do.

Store minimal original timing and identity metadata even when source meetings disappear, so timezone changes can still rename retained archives. Keep technical state outside the three user-facing Markdown files. Renames must respect suppressed/deleted folders.

### Container operation

Provide one image and a small Compose configuration. Persist credentials and operational state outside the container's writable layer. Mount the archive directory for local-only mode; use disposable transfer storage for Drive mode. Do not bake credentials, downloaded OAuth JSON, or meeting content into the image or build context.

Configure restart behavior and document host Docker startup separately; a container cannot start while its runtime is stopped. Provide an explicit setup/login command that works with a host browser and also has a documented path for a headless server. This needs validation before choosing callback bindings and ports.

Use basic local/container logs and a status check for actionable failures; keep meeting text and tokens out of diagnostics. Do not add a dashboard or notification service.

### Retrieval and publication

Reuse the existing Wispr and Drive integration boundaries where possible. Discover all available history, account for search caps without silently reporting a complete import, and revisit older meetings for updates. Restarted synchronization must recover missed source meetings without duplicates.

Read a coherent, complete source snapshot before attempting publication. Do not delete the valid current content while waiting for source processing. Failed writes must remain retryable and must not be reported as success.

A multi-file Drive update is not assumed to be a single atomic operation. The implementation plan must state the observable behavior during interrupted uploads and verify recovery using minimal private bookkeeping, without introducing permanent revisions or an offline queue.

When destination restoration is enabled, recovery can use source data that is still available. With no permanent local content backup, do not promise restoration after both source and destination copies are gone.

### Migration

Inspect the existing archive and produce a conversion preview before mutations. Resolve its current manifests, preserve current text, convert the transcript to Markdown, and map stable meeting identities to readable folders.

Validate converted content and resumability before removing obsolete revision structures or permanent staging copies. Historical source-deleted meetings must not disappear during conversion. Detect any attached audio and preserve it pending an explicit disposition; excluding audio from new import requirements is not permission to destroy existing recordings.

Destructive cleanup is a separate, reviewable execution step. No migration occurs during planning.

## 3. Acceptance scenarios for the eventual implementation

| Scenario | Required result |
| --- | --- |
| Initial startup with available history | All eligible meetings are discovered; search caps do not silently truncate the import. |
| Source summary or transcript not ready | No first archive is published; a later poll can import it. |
| Empty personal notes, ready summary/transcript | Three Markdown files are produced; the notes file can be empty. |
| Identical meeting observed again | Same folder and files; no duplicate or revision directory. |
| Source content changes | Replace current content once ready; keep existing content during source processing. |
| Title or configured timezone changes | Rename the existing folder without duplicating it or restoring a deleted folder. |
| Two distinct meetings map to one name | Separate stable folders with readable numeric suffixes. |
| Source meeting disappears | Keep its existing archive. |
| Destination file/folder deleted, restoration disabled | Leave it deleted, including after later source updates and container restarts. |
| Restoration explicitly enabled | Restore recoverable missing content without claiming recovery of unavailable data. |
| Transient retrieval/upload failure | Do not claim success; retry normally without adding an offline queue. |
| Container recreated | Credentials and identity/deletion state survive; no full local Drive mirror is retained. |
| Existing archive conversion | Preserve verified current contents, including source-deleted meetings; no unreviewed destructive cleanup. |

## 4. Evidence and remaining technical validation

Source: [Validate Wispr access with a sample meeting](https://github.com/SaltyThePolo/callimachus/issues/5).

Existing native-client validation established browser authorization, immediate noninteractive credential reuse, paginated retrieval of a user-selected meeting, and byte-for-byte Drive upload verification. It did not establish Docker OAuth, Windows/Linux/macOS container startup, credential renewal after expiry, or the new current-only publication behavior. The selected live meeting was not independently confirmed synthetic; no private sample details belong in public fixtures or this document.

Before treating the specification as implementation-ready, settle the engineering checks for Docker OAuth and persistent state, source readiness signals, complete historical discovery, and interrupted multi-file replacement. Use synthetic fixtures for automated tests. Retain an explicit distinction between proposed behavior, automated checks, and live account validation.

## 5. Handoff order

1. Review this consolidated product behavior with the user, one question at a time if changes are needed.
2. Resolve the remaining technical checks and turn the draft into a buildable specification.
3. Split the specification into dependency-linked implementation tickets: current archive model, Drive updates, automatic Docker operation, then migration.
4. Implement and validate those tickets only after planning agreement; execute any destructive migration cleanup as a separate reviewed step.
