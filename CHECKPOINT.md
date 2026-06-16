# CRM Population Enrichment - Project Checkpoint

> Handoff document for continuing this project in a fresh Claude Code session.
> Last updated: 2026-06-16

---

## Repository and environment

- **GitHub repo**: https://github.com/Golden-VS/get-populations (owner: Golden-VS).
- **Local working copy**: `/opt/cardano/cnode/claude-code/get-populations/` on
  this Linux box (user `cardano`). `origin` points to the GitHub repo via SSH;
  pushes authenticate via `~/.ssh/id_ed25519` as GitHub user `Golden-VS`.
  `gh` CLI is NOT installed.
- **Git author config**: `user.email = pixel.mastery@gmail.com`,
  `user.name = Vahid Shypoorchian` (global). No company-identifying info in
  the repo (see "Privacy" below).
- **`.gitignore` excludes**: `*.xlsx`, `*.csv` (all data + the DWH export +
  caches), `logs/`, `.claude/`, `reference/`, `venv/`. So NO customer data,
  account names, or run logs are ever pushed.
- **Runs on Linux** in a `venv`. The pipeline scripts are pure Python; first
  step-2 run downloads Wikidata/CBS reference data into `reference/` (cached).

### Privacy (important, 2026-06-16)
The repo must NOT be linkable to the customer's company. Verified clean:
no company name in any tracked file, the committed PDF, any commit message,
or commit author/email (only `pixel.mastery@gmail.com`). The company name +
real emails appear ONLY in the two gitignored local data files
(`full_input.csv`, `segment_cache.csv`) which are never pushed. Keep it that
way: never hardcode the company name/email; the MANUAL uses generic example
values (`jan.jansen@yourcompany.nl`).

---

## Project goal

Yearly recurring task: for ~6,100 CRM accounts (Dynamics 365), add a
**Segment** (organisation type) and a **population** (`cx_population`) for the
government bodies among them. Accounts span NL, BE, DE and the Caribbean
(Aruba/Curacao/Sint Maarten/Caribisch Nederland). Commercial accounts get no
population. The output drives reporting on customer reach / territory size and
is imported back into Dynamics.

---

## Pipeline (three chained scripts, all in the repo)

Raw DWH export (`full_input.csv`, SSMS `SELECT * FROM [INT].[Account] WHERE
statecode = 0`, UTF-8 BOM, literal "NULL" handled)
-> `step1_classify.py`  -> `step1_classified.xlsx`  (+ detected_type/country)
-> `step1b_segment.py`  -> `step1b_segmented.xlsx`  (+ Segment columns)
-> `step2_enrich.py`    -> `final_enriched.xlsx`    (+ population columns)

**Order matters**: step 2's input must be step 1b's OUTPUT so all columns
accumulate into one final file. Each script writes a timestamped log to
`logs/`. Operator runbook: `doc/MANUAL.md` (+ rendered `doc/MANUAL.pdf`).

### Step 1: Classify (`step1_classify.py`)
COMPLETE, in repo. Name/address-based regex classifier -> `detected_type`
(30 types), `detected_country`, `canonical_name`, confidence, proces. Free,
instant, no network. CLI `--input/--output`. Note: this copy emits
`samenwerking_nl` where an older vintage emitted `samenwerking`; downstream
accepts both.

### Step 1b: Segment (`step1b_segment.py`)
FINISHED; full production run completed (cache covers all records). Adds
`Segment`, `Segment (detailed)`, `Segment (category)`
(Governmental/Non-profit/Commercial/Unknown), confidence, bron.
- Layer 1: `TYPE_TO_SEGMENT` maps the 26 government/utility detected_types
  deterministically (free).
- Layer 2: Claude API (`claude-opus-4-7`, adaptive thinking, structured
  outputs via `messages.parse` + Pydantic enum, prompt-cached system prompt)
  classifies onbekend/commercieel/gemeente_unclear (~3.7k) in batches of 25;
  known-commercial can never return "Unknown" (-> `Commercial (other)`).
- Optional `--web-search`: weak results (Unknown/Commercial(other)/low conf)
  re-done with the server-side `web_search_20260209` tool. Idempotent -
  already-websearched results are NOT re-billed on re-runs (`--refresh-segments`
  forces a redo).
- Cache `segment_cache.csv` keyed on accountid, invalidated on name change,
  saved per batch (interrupted runs resume). Override table supported.
- Needs `ANTHROPIC_API_KEY` (API billed separately from any Claude.ai sub).
  Customer bought $50 API credits.

### Step 2: Enrich (`step2_enrich.py`)
RUN on the real export; the bugs that surfaced during that run are all fixed
(see Session summary). Effectively production-ready; remaining gaps are the
deferred v2 aggregation types (small record counts).
- Reference data cached in `reference/*.csv` (365-day cache), per-source
  try/except, heartbeat logs, "Status per bron" report.
- `--test-mode`, `--offline`, `--refresh-cache`, `--overrides`, `--user-agent`.

---

## Session summary (newest first)

Run `git log --oneline` for the complete list.

| Commit | Topic |
|---|---|
| `53bac56` | md_to_pdf: ordered lists + nested code blocks (fixes step-0 PDF rendering) |
| `0053c51` | MANUAL: fresh-box setup (~/get-populations, full deps), de-dup source sections, add `doc/MANUAL.pdf` + `tools/md_to_pdf.py` |
| `aab2a4b` | MANUAL: lead with what-it-does intro + per-account-type source table |
| `6a5e6e5` | Dissolved NL/BE gemeenten resolve to frozen last-known pop (Zwijndrecht BE case) |
| `63fa4bd` | Wikipedia-title fallback for label-less reference rows (Zottegem case) |
| `2d4c4c6` | `population_gewijzigd` review column (gewijzigd/gelijk/leeg) |
| `9bf8961` | Fix crash on NaN date in aggregate_sum (cached-CSV roundtrip) |
| `1997e6b` | Strict (>=92) name match for gemeente lookups; no weak-fuzzy overwrite |
| `04dc15a` | DE same-name municipalities disambiguated via postal code (P281) |
| `f6798e1` | CBS Gebieden fetcher: fresh NL numbers + auto veiligheidsregio mapping |
| `6df26d4` | DE Verbandsgemeinden direct-value table (Q253019 was 'Ortsteil') |
| `7d8bf9f` | DE Landkreise via district key P440 (44 -> 288) |
| `2cc4378` | DE Gemeinden via AGS key P439, chunked per Bundesland (346 -> 11,418) |
| `f5687a8` | step1_classify.py into repo + type-name harmonization |
| `b036aba` | Timestamped file logging for all steps |
| earlier | step1b segment columns; waterschap/stadsdelen/politiezone tables; BE provincies fix; dissolved filter; staleness column |

---

## How each account type gets its population (step 2)

`enrich_record` dispatches by `detected_type`:

| Type(s) | Method | Source |
|---|---|---|
| `gemeente_nl` | direct fuzzy match | CBS current-year (merged into nl_gemeenten) + Wikidata historical fallback |
| `gemeente_be` | direct fuzzy match | Wikidata `be_gemeenten` (Q493522) |
| `ocmw`, `agb` | match to their gemeente | Wikidata `be_gemeenten` |
| `gemeinde_de` | direct fuzzy match + **postcode tiebreak** | Wikidata via AGS key P439 (chunked per Bundesland) |
| `provincie_nl` / `provincie_be` | direct | Wikidata `nl_provincies` (Q134390) / `be_provincies` (Q83116) |
| `landkreis`, `landratsamt` | direct / match to Landkreis | Wikidata via district key P440 |
| `land` (Caribbean) | direct | Wikidata country totals (hardcoded VALUES) |
| `veiligheidsregio` | sum of member gemeenten | mapping auto-built from CBS (25 regions); inline table is fallback |
| `omgevingsdienst` | sum of member gemeenten | `NL_OMGEVINGSDIENST_GEMEENTEN` (partial, 5/~30) |
| `politiezone` | sum of member gemeenten | `BE_POLITIEZONE_GEMEENTEN` (173/176, from NL Wikipedia) |
| `waterschap` | direct value | `NL_WATERSCHAP_INWONERS` (21, own websites; sum-validated ~98% of NL) |
| `stadsdeel`, `deelgemeente` | direct value | `NL_STADSDEEL_INWONERS` (8 Amsterdam, NL Wikipedia) |
| `verbandsgemeinde` | direct value | `DE_VERBANDSGEMEINDE_INWONERS` (15 CRM VGs, DE Wikipedia, peildatum 2024) |
| `NO_POPULATION_TYPES` | none (stays empty) | commercieel, ministerie, rijksoverheid, stadtwerke, intercommunale, caw, zweckverband, fod_be |
| `UNSUPPORTED_AGGREGATION` | none yet (keeps old value) | samenwerking(_nl), belastingsamenwerking, hulpverleningszone, ggd, stadsregio, amt, verwaltungsgemeinschaft |

### Reference sources (Wikidata/CBS), measured 2026-06-12
| Name | Key | Items | Notes |
|---|---|---|---|
| `nl_gemeenten` | Q2039348 + CBS merge | 342 CBS (fresh, qid `CBS-86247NED`) + ~800 Wikidata historical | CBS wins for current; Wikidata keeps historical names matchable |
| `nl_gemeenten_historisch` | Q2039348 + P576 EXISTS | 242 | dissolved NL gemeenten, exact-name-only fallback |
| `be_gemeenten` | Q493522 | 559 | label fallback applied (see below) |
| `be_gemeenten_historisch` | Q493522 + P576 EXISTS | 22 | dissolved BE gemeenten, exact-name-only fallback |
| `nl_provincies` / `be_provincies` | Q134390 / Q83116 | 12 / 10 | OK |
| `de_gemeinden` | AGS P439, 16 Bundesland chunks | 11,418 | also fetches P281 postcodes (98%) for same-name tiebreak |
| `de_landkreise` | P440 minus P439 | 288 | "Landkreis "/"Kreis " prefix stripped from labels |
| `caribbean_countries` | hardcoded VALUES | 4 | OK |

---

## Robustness fixes applied during the real step-2 run (2026-06-12)

1. **NaN date crash** (`9bf8961`): empty `date` from a cached CSV reads back
   as NaN (float, truthy) and crashed year-slicing in `aggregate_sum`. Guard
   now requires a non-empty string. (Trigger: Merelbeke-Melle, a 2025-merged
   BE gemeente with no peildatum.)
2. **Label-less reference rows** (`63fa4bd`): Wikidata items with no label in
   our language chain make the label service return the bare Q-ID as the name
   -> the row exists but is unmatchable. Both SPARQL templates now also fetch
   the Wikipedia article title (nl/de wiki) and `parse_sparql_to_dataframe`
   substitutes it. Rescued 5 BE (incl. Zottegem, Charleroi) + 28 DE rows.
3. **DE same-name disambiguation** (`04dc15a`): 486 German municipality names
   recur; `fuzzy_match` now takes the CRM postcode and picks the candidate
   whose P281 postcode best-prefix-matches. 52/52 CRM collisions resolved at
   5/5; unresolved ones get a "LET OP" proces marker.
4. **Strict gemeente matching** (`1997e6b`): gemeente lists are complete, so a
   missing name = doesn't exist -> keep old CRM value (NOT a weak fuzzy match).
   STRICT_MATCH_TYPES require score >=92. Blocked 6 real wrong matches
   (Bussum->Brunssum, Winschoten->Linschoten, Hoeselt->Herselt x2, etc.).
   92-99 matches carry a "LET OP" marker.
5. **Dissolved-gemeente fallback** (`6a5e6e5`): when the current list misses,
   try `*_historisch` companion with EXACT name only -> dissolved gemeenten
   (Bussum, Zwijndrecht BE) get their frozen last-known population, bron marked
   "opgeheven gemeente", while the Brunssum fuzzy trap stays closed.

---

## Output columns added (step 2)

- `previous_population` - old CRM value before this run.
- `population_gewijzigd` - `gewijzigd` / `gelijk` / `leeg` (numeric compare
  of cx_population vs previous_population). run_log tab shows the total.
- `data_leeftijd_jaren` - years between run date and peildatum (high = stale).
- `bron`, `proces`, `peildatum_inwoners`, `match_score`, `invuldatum`.
  `cx_population` is updated in place (CRM-import-ready); never blanked.
- Review filters: `proces` "geen match"/"niet in" = misses; `proces` "LET OP"
  = unresolved name collision / non-exact match; `population_gewijzigd` =
  what would change in the CRM.

---

## Open work items

All "broken source" items are RESOLVED. Remaining:

1. **Final review of `final_enriched.xlsx`** with the user (the run works; was
   iterating on individual "geen match" cases - Zottegem, Zwijndrecht - which
   are now fixed). Suggested: after a clean run, the user filters `proces` on
   "geen match" / "LET OP" and pastes the remaining names for one-pass triage.
2. **v2 aggregation tables** (~70 records, keep old value today):
   `samenwerking(_nl)`, `belastingsamenwerking`, `hulpverleningszone`,
   `ggd` (could reuse the CBS table's GGD-regio column - cheap), `stadsregio`,
   `amt`, `verwaltungsgemeinschaft`. Each needs `{region: [gemeenten]}` like
   `NL_VEILIGHEIDSREGIO_GEMEENTEN`. User-driven priority.
3. **Manual: Dynamics 365 import section** (placeholder exists in MANUAL).
4. **Optional**: `omgevingsdienst` mapping is only 5/~30 filled.

---

## Tooling / docs

- `doc/MANUAL.md` - operator runbook. Opens with "what this does" + a
  per-account-type source table, then step 0 (DWH export) -> setup -> steps
  1/1b/2 -> corrections -> yearly refresh -> maintenance playbook.
- `doc/MANUAL.pdf` - rendered "marked up" view, regenerate with:
  `python tools/md_to_pdf.py doc/MANUAL.md doc/MANUAL.pdf`
- `tools/md_to_pdf.py` - pure-Python markdown->PDF (markdown + reportlab, no
  system libs). Handles headings, pipe tables, fenced code, ordered/unordered
  lists incl. code nested in list items.
- `doc/PROJECT_OVERVIEW.md` - non-technical one-pager.

### Dependencies
Runtime: `pandas openpyxl anthropic requests rapidfuzz`. PDF tooling
(dev only): `markdown reportlab` (+ `pypdf` for verification). Python 3.10+.

---

## User context and preferences

- Dutch native speaker. Code comments mostly Dutch; English for stdlib/pandas.
- Avoid em-dashes in user-facing output.
- Deliver/commit one scoped change at a time, push individually for review.
- Don't be blindly agreeable; be technically precise.
- `cx_businesstype` is unreliable; name + address are authoritative.
- Prefers reusing existing patterns over new HTTP sources unless accuracy
  requires it.
- Municipality accuracy matters most: 85% of revenue comes from municipalities,
  so gemeente correctness was prioritized (strict matching, postcode tiebreak,
  dissolved fallback all driven by that).
- The pipeline runs on this Linux box; the MANUAL is written so a fresh box
  can be set up from scratch (`git clone` into `~/get-populations`).

---

## Useful recipes

### Re-run a single reference source after a fix
Delete its `reference/<name>.csv`, then run step 2 (not `--offline`); only
that source re-downloads. Transient Wikidata 502s auto-retry.

### Test a Wikidata candidate quickly (shell)
```sh
UA='get-populations/1.0 (you@example.com)'
curl -sG 'https://query.wikidata.org/sparql' \
  -H 'Accept: application/sparql-results+json' -H "User-Agent: $UA" \
  --data-urlencode 'query=SELECT (COUNT(DISTINCT ?item) AS ?n) WHERE {
    ?item wdt:P31 wd:Q83116 . FILTER NOT EXISTS { ?item wdt:P576 ?d } }'
```

### Extract a Wikipedia list as wikitext (NOT WebFetch - it hallucinates tails)
```sh
curl -sG 'https://nl.wikipedia.org/w/api.php' \
  --data-urlencode 'action=parse' --data-urlencode 'page=...' \
  --data-urlencode 'prop=wikitext' --data-urlencode 'format=json' \
  --data-urlencode 'redirects=true' -o raw.json
```
Top-level `* ` bullets = current; nested `** ` / `<s>` = historical (skip).

### Standing offer to the user
After a step-2 run, they paste remaining "geen match" / "LET OP" account
names; triage each as (a) fixable source pattern, (b) genuinely no data ->
overrides file, or (c) dissolved/obsolete -> keep-old-value is correct.
