# Predict Stage Director (Talking Head Pipeline)

## When to Use

The compose stage has produced one or more rendered variants (a render_report,
plus the edit_decisions behind each variant). Your job is to score every
rendered variant against the channel baseline by calling the va predictor CLI,
reusing OpenMontage's transcript rather than re-transcribing. This stage never
posts and never approves; it only records a version-stamped prediction per
variant.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Prior artifacts | render_report, edit_decisions | The rendered variants and the edit choices behind each |
| Prior artifacts (optional) | script, final_review | Transcript segments and the compose review |
| Transcript | The transcript in project state (script stage) | Reused by the predictor; never re-transcribed |
| External CLI | va predictor at E:\Video AI\cli.py (its own venv) | Scores each variant and records the variant row |

The predictor runs as a subprocess and reads real files, so anything you pass
by path (edit decisions, transcript) must be written to disk first, never held
in memory.

## Process

### Step 1: Resolve the platform

Read the target platform from the brief (instagram or tiktok). The same source
footage keeps one short code across its variants; the CLI assigns it.

### Step 2: Write the transcript to a JSON file

Take the transcript from project state (produced by the script stage; the
transcriber also writes a <stem>_transcript.json file next to the input media).
Write it to a JSON file on disk, for example TRANSCRIPT_JSON. If the run's
checkpoint directory is not writable, write it under E:\Video AI\data\media\.
Do not rely on in-memory JSON. If no transcript exists in project state, omit
the --transcript flag and the predictor falls back to its own whisper.

### Step 3: For each rendered variant, write its edit decisions and score it

For each variant with a render path RENDER and the OpenMontage project
reference PROJECT_REF, write the edit choices OpenMontage recorded for it (cuts,
transitions, broll, caption_style, music_removal_applied, render_runtime) to a
JSON file EDITS_JSON, then run this exact command (one line; substitute the
values; keep the venv path):

    E:\Video AI\.venv\Scripts\python.exe E:\Video AI\cli.py predict record-variant --video "RENDER" --platform PLATFORM --project-ref "PROJECT_REF" --edit-decisions "EDITS_JSON" --transcript "TRANSCRIPT_JSON" --caption "CAPTION" --hashtags "HASHTAGS" --post-time "POST_TIME_ISO"

Record the printed short code (all variants of one source share it) and the
printed variant id. Repeat for every rendered variant.

### Step 4: Self-Evaluate

| Criterion | Question |
|-----------|----------|
| Coverage | Did every rendered variant get exactly one prediction row linked to its variant id? |
| Honesty | For seed or provisional regimes, is the band shown with its low-confidence label and never presented as certain? (The CLI already labels confidence.) |
| Transcript reuse | Did the predictor reuse the project-state transcript rather than re-transcribing? |

### Step 5: Submit

Record the short code and the per-variant ids in project state so the advise
stage can rank them. This stage does not post and does not approve.
