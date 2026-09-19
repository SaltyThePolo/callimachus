# Callimachus

Callimachus concerns the preservation of meeting materials collected by Wispr Flow.

## Language

**Meeting**: The conversation to which a recording, transcript, and notes belong.

**Recording**: The original captured meeting audio, distinct from a transcript or audio metadata.

**Transcript**: The textual rendering of what was said during the meeting.

**Notes**: The personal written notes attached to the meeting, distinct from the summary and the transcript.

**Summary**: The source-generated recap of the meeting, distinct from the personal notes.

**Meeting archive**: The preserved collection of a meeting's current materials, one readable folder per meeting.

**Registry**: The private operational state that ties each meeting to its folder and records publication and deletion intent. It is never part of the archive.
_Avoid_: manifest, index, metadata file

**Pending**: A meeting whose source text is not yet publishable (summary or transcript missing, or retrieval incomplete); its existing archive is left untouched.
_Avoid_: partial, incomplete

**Suppressed**: A meeting whose folder the archive owner deleted; the archive respects that and does not recreate it unless restoration is enabled.
_Avoid_: skipped, ignored

**Destination**: The location selected to store meeting archives, locally or in Google Drive.
