# Readable current-only archives with automatic Docker operation

Published specification: https://github.com/SaltyThePolo/callimachus/issues/16

## Problem Statement

The current archive exposes opaque IDs and immutable revision directories, retains unnecessary history and a permanent local Drive mirror, and requires manually running a foreground watcher. The user needs a readable collection of current meeting materials that updates automatically on one desktop or server.

The product behavior was confirmed after the [Callimachus decision-map interview](https://github.com/SaltyThePolo/callimachus/issues/1). This specification authorizes neither live migration nor deletion. Implementation tickets are a separate handoff.

## Solution

Import complete meeting text into one readable folder per meeting, named `YYYY-MM-DD HH-mm - Meeting title`, containing `notes.md`, `summary.md`, and `transcript.md`. Keep the current contents synchronized with Wispr without a user-facing version history. Use a configurable timezone, default UTC.

Run the same application in Docker on Windows, Linux, or macOS, with automatic startup and a five-minute normal polling interval. A Drive destination retains only temporary local transfer content; the local-only destination remains supported. Private operational state persists independently of container replacement.

## User Stories

1. As an archive owner, I want dates, times, and meeting titles in folder names so that I can find meetings without decoding IDs.
2. As an archive owner, I want a flat collection of meeting folders so that I do not navigate nested date directories.
3. As a reader, I want three separate Markdown files so that I can open notes, summary, or transcript independently.
4. As a reader, I want only current materials so that I do not navigate historical revisions.
5. As an archive owner, I want to configure the timezone, defaulting to UTC, so that host settings do not change archive naming.
6. As an archive owner, I want title and timezone changes to rename existing folders so that names remain meaningful without duplicates.
7. As an archive owner, I want rare name collisions distinguished with numeric suffixes so that different meetings are not merged.
8. As a reader, I want import to wait for the required text so that unfinished source processing is not presented as a completed meeting.
9. As a reader, I want empty personal notes to be valid so that a meeting without manual notes can still be archived.
10. As an archive owner, I want audio availability not to block text import so that unsupported audio retrieval does not stall the archive.
11. As a Wispr user, I want source edits to update current archived files so that Wispr remains authoritative.
12. As a reader, I want the old contents retained while Wispr processes an update so that the archive remains usable.
13. As an archive owner, I want source-deleted meetings retained so that deletion in Wispr does not erase my archive.
14. As an archive owner, I want deleted destination files and folders left deleted by default, even after source edits, so that my destination deletion is respected.
15. As an archive owner, I want configurable restoration so that I can choose to recover missing destination material when recoverable.
16. As an operator, I want all available history imported initially so that I do not choose a historical cutoff manually.
17. As an operator, I want automatic checks every five minutes so that new and updated meetings are imported without manual commands.
18. As an operator, I want one Docker deployment format so that the application behaves consistently on my Mac or another host.
19. As a Mac user, I want automatic startup after login so that I do not open a terminal to begin synchronization.
20. As an operator, I want credentials and deletion tracking to survive container replacement so that restarts do not require consent or recreate deleted content unnecessarily.
21. As a Drive user, I want no permanent full local mirror so that the archive does not occupy both storage locations.
22. As an operator, I want ordinary retries and local diagnostics so that transient failures do not require notification-service integrations.
23. As an existing user, I want conversion of my current archive so that I keep existing materials in the new organization.
24. As a contributor to a public repository, I want only synthetic fixtures and generic setup instructions committed so that credentials and meeting content remain private.

## Implementation Decisions

### Reuse existing boundaries

Keep the current meeting model, source adapter, local destination, Drive destination, CLI orchestration, and OAuth libraries. Refactor only where required for current-file updates and persistent identity. Do not add a plugin system, an external database, or a queue service.

Persist a versioned private registry with stable meeting IDs, destination IDs or paths, original start timestamp, last source title, successful publication markers, and explicit destination-deletion markers. Use existing atomic state-writing and single-writer lock patterns. A failed first creation must never be mistaken for a user deletion. Persist allocated Drive IDs before creation to recover an ambiguous response without duplicates.

### Readable current content

Use meeting start time in the configured IANA timezone. Validate the timezone before network or archive changes. Source start-time corrections follow the same rename rule as title corrections. Store enough metadata to apply timezone changes to retained meetings no longer available in Wispr.

Use the three English Markdown filenames described above. Do not place a manifest or revision directory in the user-facing meeting folder. Keep technical metadata in operational state. Render transcript text as readable Markdown without asking an LLM to rewrite it.

Normalize unsupported filename characters, strip invalid trailing characters, bound component length, and use a neutral fallback for an empty title. Allocate numeric collision suffixes deterministically and persist the result; compare names conservatively for case-insensitive filesystems. Never use a human-readable name as meeting identity.

### Readiness and history discovery

A publishable snapshot requires a finalized meeting, successfully retrieved notes (which may be empty), a nonempty summary, an available nonempty transcript, exhausted continuation markers, and no observed source modification during retrieval. This is the observable provider contract, not a claim that no future refinement can occur. Later source changes are picked up normally. Missing fields are errors, not empty notes.

Begin history discovery without a user cutoff. If the provider caps a search, partition the start-time window and paginate each partition; retain an open historical lower bound rather than inventing a earliest allowed meeting date. Avoid overlap duplicates using stable IDs. If provider limits cannot be partitioned further, report incomplete discovery instead of claiming full coverage. Test boundary timestamps and dense windows.

Revisit historical meetings for edits; do not use a new-meetings-only cursor that misses older updates. A cycle is serialized. After a cycle, wait the normal five-minute interval; a slow cycle never spawns an overlapping one. Restarted operation discovers missed work through normal source scans.

### Destination changes

Wispr overwrites current contents for non-deleted destination files. Deleting a source meeting does not remove its archive. With restoration disabled, record destination file/folder deletions and suppress recreation through source edits, title changes, timezone changes, and restarts. With restoration enabled, clear applicable suppression only after successful recovery from available data.

Manual destination folder moves or renames are unsupported: detect/report a mismatch where possible, without restoring the old name/location or creating a duplicate. This is distinct from application-managed renames requested by source or timezone changes.

Loss of the operational registry is not a supported silent reset: document that it contains deletion intent. Recover positively identifiable app-owned objects where possible and otherwise require an explicit recovery action rather than claiming deletion preferences are intact.

### Drive transfer and interruption

Reuse the selected app-scoped Drive API authorization. Update stable file IDs with complete individual payloads; do not delete existing files before replacement. Generate the complete source snapshot before starting writes. Mark a meeting synchronized only after all intended writes are verified. Use temporary transfer files and remove them after use; no durable content backlog or permanent full mirror.

Drive does not supply a single transaction spanning the three ordinary files. A source-processing wait leaves old contents untouched, but an interrupted transfer may temporarily leave a mixture of complete old/new files. Record only enough pending-operation metadata to detect incomplete publication, then converge on the next normal source sync. Do not promise instantaneous three-file visibility or introduce permanent revisions to imitate it. If the source becomes unavailable mid-recovery, preserve the available destination files and report incomplete publication rather than deleting them or claiming success.

This distinction follows the per-file [Drive upload API](https://developers.google.com/workspace/drive/api/guides/manage-uploads); [batch requests](https://developers.google.com/workspace/drive/api/guides/performance) remain separate operations and do not establish a transaction. It is an implementation limitation, not a new product feature.

### Docker and OAuth

Distribution is source-based: Compose builds the application image locally. The user withdrew Docker Hub/prebuilt-image distribution; do not add CI or release image builds/pushes. Container smoke checks remain part of implementation validation. No Docker Hub credentials are required by the application or CI.

Provide a minimal Linux container image and Compose setup, with persistent private operational state and an optional host-mounted local archive. Exclude credentials, state, meeting content, and local environment files from build context as well as Git. Use restart-unless-stopped behavior and document enabling the host runtime at login/boot; do not combine competing host process supervisors with Docker's restart policy. See [Docker restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/).

Interactive setup runs separately from the watcher and prints an authorization link for the host browser. Use fixed callback ports for the setup invocation, host-loopback publishing, and a container listener reachable through that mapping. Keep the OAuth redirect URI on loopback, validate state, retain PKCE, and close the listener after setup. Do not expose callback ports on the always-running watcher. For a headless server, document a loopback SSH tunnel to the setup callback rather than a public callback endpoint.

The installed Google OAuth library already separates the advertised callback host from its listener binding and allows disabling browser opening. Apply the same separation to the existing Wispr callback. Verify the actual Google and Wispr flows in the container; changing bindings alone is not evidence of live success. Docker documents [loopback port publishing](https://docs.docker.com/engine/network/port-publishing/); require a maintained runtime and test the effective binding.

Use the existing SDK refresh mechanisms, preserving rotated tokens atomically. Specifically test cold-process expired credentials, not just refresh during one long-lived connection: inspection of the installed MCP implementation shows that startup loads stored tokens without restoring its in-memory expiry timestamp, and its unauthorized-response path can enter full authorization. If this prevents unattended restart, add the smallest expiry/discovery adaptation needed around the SDK rather than implementing a second OAuth stack. Revoked consent produces a local actionable login-required status; background operation never opens a browser.

### Migration

Run migration explicitly with the watcher stopped and the same single-writer protection. Preview affected meetings, current content, target names, conflicts, and cleanup candidates. Convert the current revision only, including retained meetings absent from Wispr. Preserve identity and accessible Drive links where feasible; do not promise all old links survive a layout conversion.

Maintain resumable migration progress and verify content before removing obsolete directories or staging copies. Never delete attached audio merely because text-only import no longer requires it. Unknown files, corrupt manifests, and unverifiable content block cleanup of the affected item. Destructive cleanup requires review of the concrete migration result, not a blanket planning approval.

## Testing Decisions

Test observable behavior at the highest existing useful boundary: CLI/sync with synthetic source responses and the existing fake Drive service. Extend the existing archive, source pagination, authentication, and Drive retry tests rather than creating a parallel testing framework.

- Verify readable names, three Markdown files, readiness, repeatability, source edits, title/timezone changes, and rare collisions.
- Verify source deletion retention and destination deletion suppression across process restart, with restoration both disabled and enabled.
- Inject upload failure after individual files and loss of a successful response; verify stable IDs, no false success, and convergence on retry.
- Exercise full historical discovery, caps, pagination, source snapshot changes, and failed searches without interpreting them as deletions.
- Verify callback state and binding, expired-token cold startup, rotated refresh persistence, noninteractive reauthorization failure, and container recreation with persistent state.
- Verify migration from synthetic old archives, including source-deleted meetings, partial legacy snapshots, attached recordings, and interrupted conversion. Cleanup must not proceed after failed verification.
- Smoke-test Docker startup and loopback setup on supported hosts before claiming cross-platform validation. Never put real meeting content or credentials in tests or logs.

## Out of Scope

- Permanent Callimachus revision history, opaque archive navigation, and a full local Drive mirror.
- Audio retrieval as a requirement for text import; deleting existing recordings is also excluded.
- Notification services, a dashboard, offline delivery queues, and concurrent multi-host writers.
- Repairing manual folder restructuring or propagating Wispr deletions into archive deletion.
- Guarantees of multi-file Drive transactions, recovery when all content copies are gone, or unattended login after consent has been revoked.

## Further Notes

Previously verified: native browser login, immediate credential reuse, paginated live text retrieval, and byte-for-byte Drive delivery of a user-selected sample. These results concern the old runtime, not the new layout or container flow.

Current planning verification: inspected the installed OAuth SDKs, existing source/destination behavior, and official Docker/Drive documentation. Docker's client is present in this workspace but no daemon is reachable. No container or post-expiry account test was run during this planning pass. Keep live validation evidence in [Validate Wispr access with a sample meeting](https://github.com/SaltyThePolo/callimachus/issues/5).

Do not close the entire Wayfinder map merely because this specification exists. Product confirmation, implementation completion, and account/platform validation are separate states.
