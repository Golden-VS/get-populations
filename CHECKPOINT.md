# CRM Population Enrichment - Project Checkpoint

> Handoff document for continuing this project in a fresh Claude Code session.
> Last updated: 2026-06-11

---

## Repository and environment

- **GitHub repo**: https://github.com/Golden-VS/get-populations (owner: Golden-VS).
- **Local working copy**: `/opt/cardano/cnode/claude-code/get-populations/` on
  this machine (Linux, user `cardano`). Git is initialized, `origin` points
  to the GitHub repo via SSH. Pushes authenticate via `~/.ssh/id_ed25519`
  as GitHub user `Golden-VS`. `gh` CLI is NOT installed.
- **Git author config**: `user.email = pixel.mastery@gmail.com`,
  `user.name = Vahid Shypoorchian` (set globally). SSH key authenticates as
  Golden-VS for push. Commits show that author email; GitHub attributes them
  to Golden-VS via the push.
- **Excluded from git via `.gitignore`**: `step1_classified.xlsx` (real CRM
  data, ~6,000 records), other `.xlsx` outputs, `.claude/`, `reference/`
  cache, `venv/`, common Python/editor noise.

---

## Project goal

Yearly recurring task: populate the `cx_population` field for ~6,004 CRM
accounts (Dynamics 365). The accounts are:
- **Government entities** in NL, BE, DE, and the Caribbean (Aruba, Curacao,
  Sint Maarten, Caribisch Nederland) that need their inhabitant count
  filled from authoritative sources.
- **Commercial entities** that should have an empty population field.
- **Obsolete/marked entries** (with "niet gebruiken" / "do not use" in the
  name) that should be skipped but keep their old value.

The output drives reporting on customer reach and territory size.

---

## Two-step pipeline

### Step 1: Classify (`step1_classify.py`)
**Status: COMPLETE; now IN THIS REPO** (since `f5687a8`, 2026-06-11; was
Windows-only before). Input is `full_input.csv` straight from the DWH
(SSMS "Save Results As" on [INT].[Account] WHERE statecode = 0; UTF-8 BOM
and literal "NULL" strings handled). Current export: 6,118 records.
Note vintage quirks vs older copies: emits 'samenwerking_nl' (older data
had 'samenwerking'); downstream accepts both. Output feeds step 1b.

### Step 1b: Segment (`step1b_segment.py`) - NEW since 2026-06-10
**Status: FINISHED; full production run COMPLETED 2026-06-11** (cache
covers all 6,118 records; re-runs are cache-only and free). Also added:
'Segment (category)' column (Governmental/Non-profit/Commercial/Unknown,
derived from Segment via SEGMENT_TO_CATEGORY + DTYPE_CATEGORY_OVERRIDES)
and websearch idempotency (already-websearched weak results are not
re-billed on re-runs; --refresh-segments forces a redo).

Adds "Segment" and "Segment (detailed)" columns to the step1 output.
Two layers:
1. Deterministic: `TYPE_TO_SEGMENT` maps all 26 government/utility
   detected_types to a (segment, detailed) pair. Free.
2. Claude API (Anthropic SDK, default `claude-opus-4-7`, adaptive thinking,
   structured outputs via `messages.parse` + Pydantic enum, prompt-cached
   system prompt): classifies `onbekend` / `commercieel_of_overig` /
   `gemeente_unclear` records (~3.7k) in batches of 25 using name, country,
   city, address and the weak businesstype hint. A step1 "voorlopige
   typering" hint is passed per record; known-commercial records can never
   come back "Unknown" (fall back to segment `Commercial (other)`).
3. Optional `--web-search` second pass: weak classifications (Unknown /
   Commercial (other) / low confidence, including weak cached results) are
   re-done in batches of 5 with the server-side `web_search_20260209` tool.

Results cached in `segment_cache.csv` (gitignored - contains account names)
keyed on accountid, invalidated on name change; cache saved per batch so
interrupted runs resume. Override table supported. Taxonomy: 23 segments
(government by administrative level + NACE-aligned commercial).
Requires `pip install anthropic` and `ANTHROPIC_API_KEY`. User purchased
$50 API credits (June 2026). Operator instructions: `doc/MANUAL.md`.

### Step 2: Enrich (`step2_enrich.py`)
**Status: HEAVILY REVISED in this session.** Pipeline robust to per-source
failures. Several previously-broken sources now produce results.

Key features (carried forward, unchanged):
- Caches reference data in `reference/*.csv` (365-day cache).
- Heartbeat log every 10s during long SPARQL queries.
- Per-source try/except; partial failure does not abort the run.
- Status report at end of fetch phase.
- Override table support (account_id, population_override, reden).
- "niet gebruiken" marker triggers skip.
- Flags: `--test-mode`, `--offline`, `--refresh-cache`.

---

## Session summary

Run `git log --oneline` for the full history. Highlights (newest first):

| Commit | Topic |
|---|---|
| `f6798e1` | CBS Gebieden fetcher: fresh NL numbers + auto veiligheidsregio mapping |
| `6df26d4` | DE Verbandsgemeinden: direct-value table (Wikidata unusable) |
| `7d8bf9f` | DE Landkreise via district key P440 (44 -> 288) |
| `2cc4378` | DE Gemeinden via AGS key P439, chunked per Bundesland (346 -> 11,418) |
| `f5687a8` | step1_classify.py into repo + type-name harmonization |
| `b036aba` | Timestamped file logging for all steps (logs/) |
| `6e9febc` | Segment (category) column in step1b |
| `56c63fe` | step1b_segment.py: Segment columns (Claude API) |
| `1764a9a` | Waterschap direct values, sum-validated |
| `9bd404e`..`017aa56` | earlier: dissolved filter, stadsdelen, BE provincies/politiezones, staleness column |

---

## Reference sources: current state

Measured 2026-05-11 unless noted. `dissolved filter` = the global
`FILTER NOT EXISTS { ?item wdt:P576 ?dissolved }` added in `9bd404e`.

| Name | Q-ID | Active items | With P1082 | Status |
|---|---|---|---|---|
| `nl_gemeenten` | Q2039348 + CBS merge | 342 CBS (current, fresh) + ~800 Wikidata (historical names) | yes | OK. CBS rows win for current gemeenten (qid `CBS-86247NED` in bron); Wikidata rows keep historical names matchable (intentional). |
| `nl_provincies` | Q134390 | 12 | 12 | OK. |
| `be_gemeenten` | Q493522 | 565 (was 581) | full | OK, clean match. |
| `be_provincies` | **Q83116** (was Q364356) | 10 | 10 | FIXED this session. |
| `de_gemeinden` | AGS key **P439** (was Q262166), chunked per Bundesland | 11,418 | all | FIXED `2cc4378` (2026-06-11). Was 346: per-Bundesland subclasses made P31 useless. ~130k statements total, hence 16 chunks. |
| `de_landkreise` | district key **P440** minus P439 (was Q106658) | 288 | all | FIXED `7d8bf9f` (2026-06-11). P439-exclusion keeps kreisfreie Staedte out (they live in de_gemeinden). Labels prefix-stripped via strip_name_prefix_re. |
| `de_verbandsgemeinden` | REMOVED `6df26d4` | n/a | n/a | Root cause: Q253019 is 'Ortsteil' (70k items!), never the VG class. Correct Q23006 has 13/112 with P1082 and garbage memberships. Now a direct-value table (see below). |
| `caribbean_countries` | (hardcoded VALUES) | 4 | 4 | OK. |

### Sources REMOVED from `REFERENCE_SOURCES` this session

These are NOT fetched from Wikidata anymore; they're handled by inline
tables instead:

| Old source | Why removed | Replacement |
|---|---|---|
| `nl_waterschappen` | Wikidata has 0 P1082 for any of 23 active items (Q702081) | `NL_WATERSCHAP_INWONERS` direct-value table (POPULATED, see below) |
| `nl_stadsdelen` | Wikidata has 0 P1082 for 8 Amsterdam boroughs (Q15079751) | `NL_STADSDEEL_INWONERS` direct-value table |
| `be_politiezones` | Wikidata has 0 P1082 for 176 zones (Q2621126) | `BE_POLITIEZONE_GEMEENTEN` aggregation (173/176 from NL Wikipedia) |
| `de_verbandsgemeinden` | Q253019 was 'Ortsteil' (wrong class); real class Q23006 has 13/112 with P1082, fragmentary memberships | `DE_VERBANDSGEMEINDE_INWONERS` direct-value table (15 CRM VGs, DE Wikipedia infoboxes, peildatum 2024) |

---

## Inline mapping tables in `step2_enrich.py`

| Table | Type | Status |
|---|---|---|
| `NL_VEILIGHEIDSREGIO_GEMEENTEN` | sum-of-gemeenten | FALLBACK ONLY since `f6798e1`: the complete 25-region mapping is auto-built from CBS at run time |
| `NL_OMGEVINGSDIENST_GEMEENTEN` | sum-of-gemeenten | partial (5 diensten populated) - PRE-EXISTING |
| `DE_VERBANDSGEMEINDE_INWONERS` | direct value | **POPULATED** (`6df26d4`) - 15 CRM VGs from DE Wikipedia infoboxes, peildatum 2024; 17/17 CRM records resolve incl. one typo via fuzzy |
| `NL_WATERSCHAP_INWONERS` | direct value | **POPULATED** (`1764a9a`) - 21 waterschappen, websearched from own sites/Wikipedia 2026-06-11, sum-validated at 98% of NL population. Replaced the never-filled NL_WATERSCHAP_GEMEENTEN stub |
| `NL_STADSDEEL_INWONERS` | direct value | **POPULATED** - 8 Amsterdam stadsdelen, both `X` and `Amsterdam-X` keys, peildatums 2020-2022 from NL Wikipedia infoboxes (`c3ad5e4`) |
| `BE_POLITIEZONE_GEMEENTEN` | sum-of-gemeenten | **POPULATED** - 173/176 zones extracted from NL Wikipedia list (`3b307cf`) |

`enrich_record` dispatches by `detected_type`:
- `veiligheidsregio`, `omgevingsdienst` -> aggregate NL gemeenten
- `waterschap` -> direct lookup in `NL_WATERSCHAP_INWONERS`
- `stadsdeel`, `deelgemeente` -> direct lookup in `NL_STADSDEEL_INWONERS`
- `politiezone` -> aggregate BE gemeenten via `BE_POLITIEZONE_GEMEENTEN`
- Everything else -> direct fuzzy match against the appropriate Wikidata
  reference list per `TYPE_TO_REFERENCE`.

---

## Open work items (priority order)

### 1. Waterschap populations - RESOLVED (`1764a9a`, 2026-06-11)

Final approach: direct values in `NL_WATERSCHAP_INWONERS`, websearched
per waterschap from own websites/Wikipedia, validated by the sum check
(21 waterschappen tile the country: 17.73M vs ~18.1M NL inhabitants).

Investigation that led here (so nobody re-treads it):
- Wikidata: 0 P1082; 0 gemeente->waterschap links.
- Wikipedia: prose only, no structured member lists, infoboxes only
  have area.
- CBS: NO waterschap classification anywhere (boundaries don't follow
  gemeente borders) - all 8 CBS waterschap tables are financial.
- WAVES (waves.databank.nl, Unie van Waterschappen): data exists behind
  a JS dashboard; no fetchable API found; main site 403s bots.
- Aggregator overheidinnederland.nl publishes provably wrong inhabitant
  numbers (2.8-3.5M per waterschap) - never use it.

Refresh strategy: re-check the source URLs every 1-2 years; numbers
drift ~1%/yr at most.

### 1b. CBS "Gebieden in Nederland" fetcher - RESOLVED (`f6798e1`, 2026-06-11)

Built: `fetch_cbs_gebieden()` auto-discovers the newest yearly edition
in the CBS catalog (no manual table-ID switch), resolves per-edition
field names via DataProperties, merges 342 current-gemeente populations
into nl_gemeenten (CBS wins, Wikidata keeps historical names) and
auto-builds the complete 25-region veiligheidsregio mapping. CBS outage
degrades gracefully to Wikidata + inline table. Alias "'s-Gravenhage"
-> "Den Haag" included. The `ggd` v2 type could reuse the same table
(GGD-regio column exists) - still open under item 5.

### 2. DE Verbandsgemeinden - RESOLVED (`6df26d4`, 2026-06-11)

Root cause: Q253019 was 'Ortsteil' (70k items), never the VG class -
hence the truncated responses. Correct class Q23006 is unusable (13/112
with P1082; P150/P131 memberships fragmentary, partial sums would be
confidently wrong). Now: `DE_VERBANDSGEMEINDE_INWONERS` direct-value
table, 15 CRM VGs from DE Wikipedia infoboxes (Landesamt figures,
peildatum 2024). 17/17 CRM records resolve. New VGs in future exports
show "niet in tabel" in proces -> add one dict line.

### 3. DE Gemeinde under-count - RESOLVED (`2cc4378`, 2026-06-11)

Q262166 found 346 because each Bundesland has its own subclasses.
Now fetched via the AGS municipality key (P439), chunked per Bundesland
(first two AGS digits; ~130k statements total would truncate in one
response): 11,418 municipalities with population. de_landkreise
similarly fixed via P440-minus-P439 (`7d8bf9f`): 288 districts,
label prefixes stripped. Duplicate municipality names across states
(486 names, 55 CRM records affected) are RESOLVED via postal-code
disambiguation (`04dc15a`, 2026-06-12): P281 postcodes fetched per
gemeinde (98% coverage), fuzzy_match picks the candidate whose postcode
matches the CRM record's; 52/52 resolvable cases hit exact 5/5, the 3
records without a CRM postcode are flagged "LET OP" in proces.

### 4. NL gemeenten over-count - user wants historical KEPT (design decision)

CHECKPOINT-prior framing was "filter to current only". User reconsidered
during this session: if the CRM has an old gemeente name, look up that
old gemeente's last-known population (not the new merged entity).
Reasoning: the CRM names are what they are; honest staleness with a
correct peildatum beats silent re-mapping to a different population.

Current code already does this for ~99% of cases: most historical NL
gemeenten don't have `P576` set in Wikidata, so the dissolved filter
doesn't exclude them. The `data_leeftijd_jaren` column (added in
`017aa56`) surfaces stale matches per row.

KNOWN EDGE (found 2026-06-11 while testing CBS): gemeenten that ARE
P576-tagged (e.g. Bussum, dissolved 2016) get excluded and can then
fuzzy-FALSE-POSITIVE onto a similar current name ("Bussum" -> Brunssum,
score >=85). Candidate fixes: higher threshold for nl_gemeenten, or
keep P576 rows with an is_historisch flag. Low priority - review output
rows where proces shows a fuzzy (non-100) score.

NOT YET DONE but discussed: per-source dissolved filter (off for
`nl_gemeenten`, on for `be_gemeenten`) so that even `P576`-tagged old
NL gemeenten survive and can be matched. Would require capturing the
dissolution date in the dataframe and adding an `is_historisch`
column. Optional polish; revisit if user wants more visibility.

### 5. v2 aggregation tables (deferred)

Still unsupported (returns "vereist mapping-tabel (volgt in v2)"):
- `samenwerking_nl` (~23 records: GR/GRSK/ISD/RSD/RUD/Werkplein/etc.)
- `belastingsamenwerking` (~5 records)
- `hulpverleningszone` (BE fire/medical zones)
- `ggd` (NL GGD regions)
- `stadsregio`
- `amt` (DE)
- `verwaltungsgemeinschaft` (DE)

Each needs `{region_name: [member_gemeente_names, ...]}` per the same
pattern as `NL_VEILIGHEIDSREGIO_GEMEENTEN`. User will prioritize which
to build.

---

## Output schema additions

`data_leeftijd_jaren` (int or None): years between run date and
`peildatum_inwoners`. High values (5+) flag stale population data.
Helper: `data_leeftijd_jaren(peildatum_str)` at module level. Added
in `017aa56`. Slotted between `peildatum_inwoners` and `bron` in the
output column order.

All other output columns unchanged from prior CHECKPOINT.

---

## SPARQL template change (commit `9bd404e`)

`_sparql_population_template()` now includes:

```sparql
FILTER NOT EXISTS { ?item wdt:P576 ?dissolved }
```

Measured 2026-05-11 effect:
- `be_gemeenten`: 581 -> 565 (matches reality).
- `nl_gemeenten`: 1,575 -> 1,316 (partial; many historical NL gemeenten
  lack `P576`).

If we decide to keep historical NL gemeenten in the dataset (see open
item #5), this filter would become per-source (off for `nl_gemeenten`,
on for `be_gemeenten`).

---

## User context and preferences

- Dutch native speaker. Code comments mostly Dutch where intent;
  English for standard library / pandas terms.
- Avoid em-dashes (the typographic - character) in user-facing output.
- For coding tasks: deliver one step at a time when there are multiple,
  so user can test/validate before continuing.
- Casual but technically precise. Don't be blindly agreeable.
- `cx_businesstype` is unreliable; name + address are authoritative.
- User runs Windows / PowerShell / Python 3.13.3, venv in project folder.
- User wants commits scoped narrowly and pushed individually for review.
- User prefers REUSING existing patterns over adding new HTTP sources
  unless accuracy requires it.

---

## File layout (in this repo)

```
get-populations/
|- .gitignore
|- CHECKPOINT.md                  <- this file
|- step1b_segment.py              <- segmentation (Segment columns, Claude API)
|- step2_enrich.py                <- population enrichment
`- doc/
   |- PROJECT_OVERVIEW.md         <- non-technical summary
   `- MANUAL.md                   <- operator runbook (living document)

NOT in this repo (excluded by .gitignore: *.xlsx, segment_cache.csv):
- step1_classified.xlsx           (real CRM data; also runs on Linux now)
- step1b_segmented.xlsx           (segmentation output)
- step2_enriched.xlsx             (enrichment output)
- segment_cache.csv               (classification cache, contains account names)
- reference/*.csv                 (Wikidata cache; rebuilt on first run)
- .claude/                        (local Claude Code settings)
- venv/                           (Python virtualenv, exists on Linux server)
```

`step1_classify.py` and the Windows setup README (`step2_README.md`) live
on the user's machine but are NOT in this repo (so the user's local
workspace has more files than git).

---

## Dependencies

```
pandas
openpyxl
requests
rapidfuzz
anthropic     (step1b only; needs ANTHROPIC_API_KEY)
```

No exotic packages. Python 3.10+. A future CBS fetcher (open item #1b)
needs no new packages (plain OData via `requests`).

---

## How to test / continue

### To re-run after a Q-ID fix
1. Delete the affected CSV from `reference/` so it gets re-downloaded.
2. Run with full command (not `--offline`):
   ```
   python step2_enrich.py --input step1_classified.xlsx --output test.xlsx \
       --test-mode --user-agent "user@example.com"
   ```
3. Check the "Status per bron" report at the end.

### Test mode discipline
Always run with `--test-mode` first (100 records) before doing a full run.

### To test a Wikidata candidate Q-ID directly
Paste the SPARQL from `_sparql_population_template()` with the candidate
Q-ID into https://query.wikidata.org/. Check:
- Completes in <60 seconds.
- Returns expected count.
- Items have `P1082` statements.

A faster shell-side check used during this session:
```sh
UA='get-populations/1.0 (you@example.com)'
curl -sG 'https://query.wikidata.org/sparql' \
  -H 'Accept: application/sparql-results+json' \
  -H "User-Agent: $UA" \
  --data-urlencode 'query=SELECT (COUNT(DISTINCT ?item) AS ?n) WHERE {
    ?item wdt:P31 wd:Q83116 .
    FILTER NOT EXISTS { ?item wdt:P576 ?d }
  }'
```

### To extract structured data from a Wikipedia article (pattern used
this session for `BE_POLITIEZONE_GEMEENTEN`)
Use the Wikipedia API for raw wikitext, not WebFetch (WebFetch's
summarization hallucinated tail entries):
```sh
curl -sG 'https://nl.wikipedia.org/w/api.php' \
  --data-urlencode 'action=parse' \
  --data-urlencode 'page=Lijst van politiezones in Belgie' \
  --data-urlencode 'prop=wikitext' \
  --data-urlencode 'format=json' \
  --data-urlencode 'redirects=true' \
  -o raw.json
```
Then parse `data['parse']['wikitext']['*']` in Python. Top-level bullets
starting with `* ` are current entries; nested `** ` and `<s>...</s>`
strikethrough are historical (skip them).

---

## What to do next (in priority order)

All "broken source" items are now RESOLVED (waterschap, stadsdelen,
BE provincies/politiezones, DE gemeinden/landkreise/verbandsgemeinden,
CBS fetcher). Remaining:

1. **Run the full step 2 chain** on the fresh export:
   `step2_enrich.py --input step1b_segmented.xlsx --output
   final_enriched.xlsx --user-agent "..."` (test-mode first), then
   review with the user: proces misses, data_leeftijd outliers,
   previous_population diffs. See doc/MANUAL.md section 5.
2. **v2 aggregation tables** (~70 records: samenwerking_nl,
   belastingsamenwerking, omgevingsdienst 5/30, amt,
   verwaltungsgemeinschaft; `ggd` could reuse the CBS table's GGD-regio
   column). User-driven prioritization.
3. **Optional polish**: P576 fuzzy false-positive edge (item #4),
   Dynamics 365 import section in the manual. (DE name collisions:
   solved via postcode, `04dc15a`.)

---

## Decisions made this session (for context)

- Treat `waterschap`, `stadsdeel`/`deelgemeente`, and `politiezone` as
  separate code paths from the standard Wikidata reference-list lookup,
  because Wikidata has 0 `P1082` coverage for all three classes.
- For `politiezone`: reuse existing `aggregate_sum` pattern with
  `be_gemeenten` (have to pass `ref_data` through `enrich_record` so the
  branch can pick out `be_gemeenten`; done).
- For `stadsdeel`: simple direct-value table since stadsdelen are
  *subdivisions* of one gemeente, not aggregations of multiple.
- Mapping-table sources DURING THIS SESSION: NL Wikipedia article
  wikitext via the Wikipedia API (`action=parse&prop=wikitext`). Do NOT
  rely on WebFetch's summarization for large tables - it hallucinates.
- For waterschap, the same Wikipedia approach FAILED (no structured
  member-gemeenten lists exist there) - which is why open item #1 is
  blocked on the user's choice between CBS / PDOK / accept-stub.
