# Manual - Running the Account Enrichment Steps

*Living document. We extend this manual as new steps are added.*
*Last updated: 10 June 2026*

This manual describes how to run the **segmentation** step (step1b), which
adds the "Segment" and "Segment (detailed)" columns to the account list.

---

## 0. One-time setup (already done on the Linux server)

```bash
cd /opt/cardano/cnode/claude-code/get-populations

# create Python environment and install dependencies (once)
python3 -m venv venv
source venv/bin/activate
pip install pandas openpyxl anthropic
```

Set the Anthropic API key (from console.anthropic.com, where the credits live):

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

To avoid retyping it every session, store it once in your shell profile:

```bash
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.bashrc
```

Before every working session, activate the environment first:

```bash
cd /opt/cardano/cnode/claude-code/get-populations
source venv/bin/activate
```

---

## 1. Test run (100 accounts)

Always do this first after any change to the script or the input file.

```bash
python step1b_segment.py \
    --input step1_classified.xlsx \
    --output step1b_test.xlsx \
    --test-mode --web-search
```

- Takes a few minutes, costs well under $1.
- Open `step1b_test.xlsx` and check the columns "Segment",
  "Segment (detailed)", `segment_confidence` and `segment_bron`.
- Pay extra attention to rows with confidence `low` and segment
  `Commercial (other)` or `Unknown`.

## 2. Full run (all ~6,000 accounts)

```bash
python step1b_segment.py \
    --input step1_classified.xlsx \
    --output step1b_segmented.xlsx \
    --web-search
```

- Takes roughly 1 to 1.5 hours. Progress is logged per batch.
- Estimated cost: $15 to $25 including web searches (covered by the $50
  credit purchase).
- Safe to interrupt: results are saved to `segment_cache.csv` after every
  batch. Re-running the same command resumes where it stopped and does not
  pay twice for accounts already classified.
- At the end the log prints a count per segment. Sanity-check that
  distribution (e.g. roughly 1,500 municipalities, no giant "Unknown" bucket).

## 3. Corrections

If a segment is wrong, do not edit the output Excel by hand (it would be
overwritten on the next run). Instead, add a row to a corrections file,
for example `overrides_segment.xlsx`, with these columns:

| accountid | segment_override | segment_detailed_override | reden |
|---|---|---|---|
| (CRM guid) | IT & software | Software vendor | manually verified |

Then re-run with:

```bash
python step1b_segment.py \
    --input step1_classified.xlsx \
    --output step1b_segmented.xlsx \
    --web-search --overrides overrides_segment.xlsx
```

Overrides always win over the automatic classification and cost nothing.

## 4. Next year's run (yearly refresh)

1. Make a fresh CRM export and run step 1 (classification) on it, producing
   a new `step1_classified.xlsx`.
2. Copy that file to this folder and run the same full-run command as in
   section 2 (plus `--overrides ...` if you have a corrections file).
3. Thanks to `segment_cache.csv`, only **new accounts and accounts whose
   name changed** are sent to the AI. Everything else comes from the cache.
   Expected cost: a few dollars at most, usually cents.

Do **not** delete `segment_cache.csv`; it is the memory of all previous
classifications. If you ever want to force a complete re-classification
(for example after a major change to the segment list), run once with
`--refresh-segments` and expect full-run costs again.

## Useful options

| Option | What it does |
|---|---|
| `--test-mode` | Only the first 100 accounts |
| `--web-search` | Second pass with web lookup for weak classifications (recommended) |
| `--offline` | No API calls: mapping table + cache only |
| `--model <id>` | Use a different Claude model (default `claude-opus-4-7`) |
| `--overrides <file>` | Apply a manual corrections file |
| `--refresh-segments` | Ignore the cache, classify everything again |

---

## Future steps (to be added to this manual)

- Running the population enrichment (step 2)
- Importing the result columns into Dynamics 365
