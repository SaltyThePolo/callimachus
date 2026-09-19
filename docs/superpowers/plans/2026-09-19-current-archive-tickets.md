# Approved implementation tickets

Status: breakdown approved by the user; tickets published with native sub-issue and blocking relationships.

Source: [published execution specification](https://github.com/SaltyThePolo/callimachus/issues/16). Each slice delivers observable behavior with synthetic tests. No general cleanup prerequisite is needed.

## 1. Import complete meetings into readable current-only folders

Published ticket: [Import complete meetings into readable current-only folders](https://github.com/SaltyThePolo/callimachus/issues/17).

Blocked by: none.

Deliver a full local CLI import of complete synthetic/source meetings into flat date/time/title folders with three Markdown files. Include readiness, configurable UTC-default timezone, stable identity, current-file updates, renames, collisions, source-deletion retention, and configurable destination restoration disabled by default. Incomplete source updates preserve current content. State survives process restart. Existing archives require explicit migration rather than automatic conversion during sync.

Verify the result through repeated CLI imports, source edits, destination deletions, and restart with synthetic fixtures.

## 2. Synchronize the current-only archive directly to Drive

Published ticket: [Synchronize the current-only archive directly to Drive](https://github.com/SaltyThePolo/callimachus/issues/18).

Blocked by: Import complete meetings into readable current-only folders.

Deliver the same behavior through the Drive API without a permanent local content mirror. Reuse stable remote IDs, persist deletion intent, update and rename current objects, and distinguish interrupted first publication from user deletion. Ordinary retries converge after partial upload or an ambiguous response. Manual folder restructuring reports unsupported state instead of repairing it. Keep operational metadata outside visible meeting folders.

Verify through the existing fake Drive boundary and an explicitly selected live validation sample when ready; compare downloaded contents and ensure repeated sync does not duplicate objects.

## 3. Automatically import full history and subsequent updates

Published ticket: [Automatically import full history and subsequent updates](https://github.com/SaltyThePolo/callimachus/issues/19).

Blocked by: Synchronize the current-only archive directly to Drive.

Deliver all available source history and recurring five-minute synchronization for either destination. Partition capped searches, exhaust pagination, retain stable IDs across windows, revisit older meetings for updates, and catch up after process downtime through ordinary scans. Retry transient failures and expose actionable local status without notification integrations. Reject overlapping writers and avoid false success or deletion inference on provider failure.

Verify from synthetic source search through final destination state, including capped history, delayed readiness, old-meeting edits, and a failed pass followed by recovery.

## 4. Run and authorize Callimachus through Docker

Published ticket: [Run and authorize Callimachus through Docker](https://github.com/SaltyThePolo/callimachus/issues/20).

Blocked by: Automatically import full history and subsequent updates.

Deliver one documented container/Compose workflow with persistent private state, automatic restart, desktop login startup, and a separate browser-based OAuth setup command using loopback callbacks. Document the headless-server tunnel workflow. Test expired credentials after cold start and fix only the integration gaps needed for unattended renewal. Keep credentials outside images/build contexts and callback ports off the watcher.

Verify container recreation, callback binding/state validation, failed/revoked refresh behavior, and supported-host smoke tests. No claim of validated cross-platform behavior before those checks run.

## 5. Convert existing archives with verified cleanup

Published ticket: [Convert existing archives with verified cleanup](https://github.com/SaltyThePolo/callimachus/issues/21).

Blocked by: Synchronize the current-only archive directly to Drive.

Deliver explicit preview and migration of existing local and Drive archives to the readable layout. Preserve current contents, identity, and source-deleted meetings. Make conversion restartable, verify before cleanup, preserve attached audio, and stop cleanup on corrupt or unknown data. Keep destructive cleanup separate from preview and conversion review.

Verify end-to-end on synthetic legacy archives and interruption scenarios. Live conversion requires reviewing the actual preview; this ticket does not grant automatic deletion of old user data.

## Dependencies

The main path is 1 → 2 → 3 → 4. Migration (5) depends on 2 and can be developed once both destinations support the new layout; it does not need to wait for Docker packaging. Real archive migration should occur only when the intended replacement runtime is ready.
