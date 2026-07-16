# Advise Stage Director (Talking Head Pipeline)

## When to Use

The predict stage has scored every rendered variant of the video. Your job is
to rank those variants and present the ranking plus a per-variant advisor pack
to the operator, who selects exactly one variant to post through OpenMontage's
own human-approval gate. You never build or simulate a second approval flow.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Prior artifacts | variant_predictions | The per-variant predictions produced by the predict stage |
| External CLI | va advisor at E:\Video AI\cli.py (its own venv) | Ranks the variants and writes one advisor pack per variant |
| Approval | OpenMontage's existing human-approval gate | The operator approves exactly one variant here |

## Process

### Step 1: Rank the variants

Using the short code the predict stage recorded, run this exact command (one
line; keep the venv path):

    E:\Video AI\.venv\Scripts\python.exe E:\Video AI\cli.py advise-variants --short-code SHORT_CODE

This prints a ranking grouped by platform, ordered by predicted percentile,
with ties and low-confidence groups flagged as relative ordering only, and
writes one advisor pack JSON per variant.

### Step 2: Present to the operator

Present the printed ranking and the per-variant advisor packs to the operator.
The operator selects ONE variant to post. Route that selection through
OpenMontage's own human-approval gate.

### Step 3: Record the post (owned by this stage's instruction)

After the operator approves one variant and the publish stage publishes it via
the registered Instagram or TikTok publisher tool, record the returned
permalink and post time IMMEDIATELY, before anything else, by running (one line;
substitute the values):

    E:\Video AI\.venv\Scripts\python.exe E:\Video AI\cli.py posted SHORT_CODE --at POST_TIME_ISO --permalink PERMALINK --variant-id VARIANT_ID

VARIANT_ID is the id of the exact variant the operator approved and posted; the
predict stage ranking (Step 1) printed each variant's id, so pass the approved
one here. This marks which sibling was posted so the learning loop attributes
the realized actuals to the right edit. For a single-variant video it can be
omitted (the loop auto-attributes). For TikTok the publisher tool returns no
permalink, so the operator supplies the post URL from the app. That posted
command anchors the loop: the Slice C scheduler picks the posted variant up
automatically at T+7 and T+14. A publish without a recorded posted row is a
loop-closure failure, not a cosmetic omission.

### Step 4: Self-Evaluate

| Criterion | Question |
|-----------|----------|
| Grouping | Is the ranking grouped by platform and ordered by predicted percentile? |
| Honesty | Are ties and low-confidence groups flagged as relative ordering only? |
| Operator choice | Did the operator, not the system, select the single variant to post? |
| Loop anchor | After the publish, was va posted run with the returned permalink and post time? |

### Step 5: Submit

Validate the variant_ranking record and persist via checkpoint.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After the
ranking is presented and review passes: checkpoint with
`status="awaiting_human"`, present the ranking and the advisor packs (the
operator picks one variant), and END YOUR TURN. Do not start the publish stage
in the same response. Approval is per-gate; an earlier "go ahead" does not cover
this gate. The operator's single selection is the only variant that proceeds to
publish.
