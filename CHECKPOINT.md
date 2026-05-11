# CRM Population Enrichment - Project Checkpoint

> Handoff document for continuing this project in Claude Code or a new chat session.
> Last updated: 2026-05-11

---

## Project goal

Yearly recurring task: populate the `cx_population` field for ~6,004 CRM accounts
(Dynamics 365). The accounts are a mix of:

- **Government entities** in NL, BE, DE, and the Caribbean (Aruba, Curaçao,
  Sint Maarten, Caribisch Nederland) that need their inhabitant count filled
  from authoritative sources
- **Commercial entities** that should have an empty population field
- **Obsolete/marked entries** (with "niet gebruiken" / "do not use" in the name)
  that should be skipped but keep their old value

The output drives reporting on customer reach and territory size.

---

## Two-step pipeline

### Step 1: Classify (`step1_classify.py`)
**Status: COMPLETE and validated by user.**

Reads the raw CRM export, classifies each record by:
- `detected_country` (NL/BE/DE/AW/CW/SX/BQ/OTHER) - derived from `cx_address1_country`
  with name-prefix overrides (e.g. "Gemeinde X" forces DE regardless of address)
- `detected_type` (one of 30 categories like `gemeente_nl`, `ocmw`, `landkreis`,
  `samenwerking_nl`, `commercieel_of_overig`, `onbekend`, etc.)
- `canonical_name` (the entity name stripped of its type prefix, e.g.
  "Gemeente Amsterdam" -> "Amsterdam")
- `classification_confidence` (high/medium/low/none)
- `classification_proces` (human-readable explanation in Dutch)

Output: `step1_classified.xlsx` (6,004 records, 9 added columns) and
`step1_review_sample.xlsx` (135 stratified samples, 5 per detected_type).

#### Step 1 result distribution
- **Will get population lookup in step 2**: 2,253 records (DE 885, BE 771,
  NL 579, AW 12, CW 3, OTHER 3)
- **Explicitly empty** (commercial, ministry, FOD, etc.): 989 records
- **Unknown, leave empty**: 2,762 records (mostly Dutch commercial entities
  that don't match any government pattern)

#### Key classification rules
- **Name wins over everything.** `cx_businesstype` is treated as a weak hint
  only. If the name doesn't match a government pattern, the record is
  classified as `onbekend` regardless of what `cx_businesstype` says.
- Records with "niet gebruiken" / "do not use" / "obsolete" / "deprecated"
  in the name are processed by step 2 but skipped from lookup (old value
  preserved).
- Caribbean records with government keywords (overheid, ministerie,
  bevolking, bestuur, etc.) get classified as `land` and receive the
  country's total population in step 2.
- NL aggregation types caught (each is sum-of-member-gemeenten):
  `veiligheidsregio`, `omgevingsdienst`, `samenwerking_nl` (GR/GRSK/ISD/
  RSD/RUD/Werkplein/Werkbedrijf/Werkvoorzieningschap/Samenwerkingsverband),
  `belastingsamenwerking`, `ggd`, `stadsregio`

### Step 2: Enrich (`step2_enrich.py`)
**Status: PARTIALLY WORKING.** Pipeline is robust to per-source failures
but several reference data sources return empty or fail. Needs Q-ID fixes
and v2 aggregation mapping tables.

Reads `step1_classified.xlsx`, fetches reference data from Wikidata SPARQL,
fuzzy-matches each classified record to its reference entity, writes
enriched Excel with 4 tabs: `accounts`, `draaitabel_aantallen`,
`draaitabel_inwoners`, `run_log`.

Key features:
- Caches reference data in `reference/*.csv` (cache age 365 days)
- Heartbeat logger during long SPARQL queries (every 10s "still working")
- Per-source try/except (one bad source doesn't crash the pipeline)
- Status report at end of fetch phase (OK/leeg/GEFAALD per source)
- Old `cx_population` value preserved if no new match
- Optional override table support (account_id, population_override, reden)
- "niet gebruiken" marker triggers skip
- `--test-mode` for first 100 records, `--offline` for cache-only,
  `--refresh-cache` to force redownload

---

## Current state of step 2 (as of last user test)

User ran on Windows with Python 3.13.3, venv, on full dataset in --test-mode.

### Working reference sources (5 of 11)
| Source | Q-ID | Records returned | Notes |
|---|---|---|---|
| `nl_gemeenten` | Q2039348 | 1,402 unique | TOO MANY - NL has only ~342 current gemeenten. Q2039348 includes historical merged gemeenten. Consider filtering by `MINUS { ?item wdt:P576 ?dissolved }` |
| `nl_provincies` | Q134390 | 12 | Correct, NL has 12 provinces |
| `be_gemeenten` | Q493522 | 581 | Close to BE's 565 current municipalities |
| `de_gemeinden` | Q262166 | 346 | TOO FEW - Germany has 10,000+ Gemeinden. Q-ID is for a specific subclass |
| `de_landkreise` | Q106658 | 44 | TOO FEW - Germany has ~294 Landkreise. Q-ID is probably a specific subclass |
| `caribbean_countries` | hardcoded VALUES { Q21203, Q25279, Q26273, Q1462 } | 4 | Correct |

### Empty sources (Q-IDs need fixing)
| Source | Current Q-ID | Status | Investigation needed |
|---|---|---|---|
| `nl_waterschappen` | Q702081 (just updated, not yet tested) | Was Q1232456 returning 0; user hasn't tested new Q-ID yet | Many waterschappen don't have P1082 in Wikidata. May need to compute as sum-of-gemeenten or fall back to CBS Statline |
| `nl_stadsdelen` | Q1908768 | 0 records | Verify Q-ID. Amsterdam stadsdelen are the main use case. Possibly Q15936437 ("stadsdeel of Amsterdam") |
| `be_provincies` | Q364356 | 0 records | Verify Q-ID. BE has 10 provinces. Possibly Q83116 ("province of Belgium") |
| `be_politiezones` | Q15074734 | 0 records | Verify Q-ID. BE has 196 politiezones |

### Failing source
| Source | Q-ID | Failure | Hypothesis |
|---|---|---|---|
| `de_verbandsgemeinden` | Q253019 | All 3 retries fail with truncated JSON (502 Bad Gateway then JSON parse errors at chars 687K and 1.7M) | Response is unexpectedly massive. Q253019 might match millions of items, not the ~250 Verbandsgemeinden expected. Or Wikidata returns a too-large response that gets truncated mid-stream. Maybe try Q272946 or other |

---

## Open work items (priority order)

### 1. Fix Q-IDs for empty/failing reference sources

For each broken Q-ID, the investigation pattern is:
1. Find a known example entity (e.g. "Hoogheemraadschap van Rijnland" for
   waterschap, "Provincie Antwerpen" for BE provincie)
2. Look up its `instance of` (P31) on Wikidata
3. Verify by running the SPARQL on query.wikidata.org with the candidate Q-ID
4. Check expected count matches reality

Specifically:
- **NL waterschap**: Q702081 just set, needs validation. Many waterschappen
  may lack P1082 (population). If so: either drop from automatic lookup, or
  build a mapping table waterschap -> member gemeenten and sum.
- **NL stadsdeel**: Amsterdam currently has 8 stadsdelen. Try Q15936437
  ("stadsdeel of Amsterdam") or Q377699 (broader stadsdeel class).
- **BE provincie**: Try Q83116 ("province of Belgium").
- **BE politiezone**: Try Q3596043 or search for an example BE police zone
  on Wikidata to confirm.
- **DE Verbandsgemeinde**: The truncated-JSON pattern suggests the query
  matches too much. Test with `LIMIT 10` first to confirm. Possible
  alternatives: Q272946.
- **NL gemeente filter**: 1,402 results suggests historical gemeenten
  included. Add `FILTER NOT EXISTS { ?item wdt:P576 ?dissolved }` (dissolved
  date) to the SPARQL template. But test first - may not break Wikidata's
  60s timeout because it's a simpler filter.
- **DE Gemeinde**: Q262166 returns only 346 - way too few. The class
  hierarchy is complex (Germany has multiple subtypes per Bundesland).
  Likely need `wdt:P31/wdt:P279*` to walk the subclass tree, OR use Q262166
  combined with explicit subtypes.

### 2. Aggregation mapping tables (currently stubbed as "v2")

Step 2 has inline mapping tables for two NL aggregation types:
- `NL_VEILIGHEIDSREGIO_GEMEENTEN` (5 regions populated, all 25 needed)
- `NL_OMGEVINGSDIENST_GEMEENTEN` (5 dienst populated, all ~30 needed)

These return empty with proces="vereist mapping-tabel (volgt in v2)" for now:
- `samenwerking_nl` (~23 records, all the GR/GRSK/ISD/etc.)
- `belastingsamenwerking` (~5 records)
- `hulpverleningszone` (BE fire/medical zones)
- `ggd` (NL GGD regions)
- `stadsregio`
- `amt` (DE)
- `verwaltungsgemeinschaft` (DE)

Each needs a mapping `{region_name: [member_gemeente_names, ...]}` so step 2
can sum populations. Source data can come from Wikipedia infoboxes or each
region's own website. User will validate which of these are worth doing.

### 3. NL gemeenten too many records

`nl_gemeenten.csv` has 1,402 records but NL has 342 current gemeenten. The
Q-ID Q2039348 catches both current and former gemeenten. The fuzzy matching
on `canonical_name` is usually OK with this (current names don't typically
collide with historical), but it's not ideal.

Possible fix in `_sparql_population_template`:
```sparql
?item wdt:P31 wd:Q2039348 .
FILTER NOT EXISTS { ?item wdt:P576 ?dissolved }   # no dissolution date
?item p:P1082 ?stmt .
...
```

Verify this doesn't break the 60-second timeout. Should be cheaper than the
old population-NOT-EXISTS filter.

---

## File layout

```
crm-population/
├── step1_classify.py             # Step 1 classifier (COMPLETE)
├── step1_classified.xlsx          # Full output of step 1, input to step 2
├── step1_review_sample.xlsx       # Stratified sample for QA
├── step2_enrich.py                # Step 2 enricher (IN PROGRESS)
├── step2_README.md                # User-facing Windows setup guide
├── reference/                     # Cache of Wikidata reference data
│   ├── nl_gemeenten.csv          # downloaded on user's laptop
│   ├── nl_provincies.csv
│   ├── be_gemeenten.csv
│   ├── de_gemeinden.csv
│   ├── de_landkreise.csv
│   └── caribbean_countries.csv
└── venv/                          # User's Python virtual environment
```

On user's machine: `C:\Users\<user>\Documents\crm-population\`

---

## Key technical decisions

### Why Wikidata over CBS Statline / Statbel / Destatis
Single endpoint, no auth, multi-country in one tool. User accepted possible
1-2 year data lag. A future v2 could swap NL queries to CBS for fresher
data, since CBS publishes monthly. Code is structured so REFERENCE_SOURCES
is the single config point.

### Why fuzz.ratio over fuzz.WRatio
Initial tests with WRatio at threshold 80 produced false positives like
"OCMW Alken" -> "Halen" (common substring). fuzz.ratio is pure Levenshtein
distance, much stricter. Current thresholds:
- `FUZZY_HIGH_THRESHOLD = 92` (high-confidence match)
- `FUZZY_LOW_THRESHOLD = 85` (below this = no match)

These were tuned against the mock test data and may need adjustment when
running on full real Wikidata data.

### Why SPARQL "fetch all, dedupe in Python" instead of FILTER NOT EXISTS
Initial query used `FILTER NOT EXISTS` to grab only the most recent
population per item. This is O(n^2) and hit Wikidata's hard 60-second
query timeout for large sets like NL gemeenten. Now the query grabs all
population statements (cheap) and `deduplicate_keep_latest()` picks the
most recent date per qid in pandas (also cheap, runs in milliseconds for
thousands of rows).

### Why per-source try/except
First user run crashed mid-way through downloading the 11 reference
sources. Now each source has its own try/except so a single failure (bad
Q-ID, server error, malformed response) doesn't kill the whole pipeline.
Final status report shows OK/empty/failed per source.

### Population value parsing
Wikidata sometimes returns population values in unexpected formats:
`'7225'`, `'7225.0'`, `'7.225e3'`, even `'7.225'` (rare data quality
issue). The `parse_population()` helper tries `int()` first, falls back
to `float()` + round, returns `None` on parse failure. No crash on bad
data.

### Output column conventions
- `cx_population`: new value if found, else preserved old value
- `previous_population`: snapshot of old value before this run (for diff
  analysis)
- `peildatum_inwoners`: year (string) of the population's reference date
- `bron`: source identifier, e.g. `"Wikidata Q1234 (nl_gemeenten)"` or
  `"eerdere CRM-waarde"` or `"override-tabel"`
- `proces`: human-readable Dutch explanation
- `match_score`: fuzzy match score 0-100 (only for direct matches, null
  for aggregations and preserved-old-value)
- `invuldatum`: ISO date of this run

---

## How to test / continue

### To test a Q-ID candidate locally without internet
1. Manually create a CSV in `reference/<source>.csv` with columns
   `name,population,date,qid`
2. Run with `--offline` flag
3. Verify matching works for known records

### To test a real Wikidata query
Browse to https://query.wikidata.org/ and paste the query from
`_sparql_population_template()` with the candidate Q-ID. Check:
- Query completes in <60 seconds (Wikidata's hard timeout)
- Returns expected count of items
- Items have P1082 statements

### To re-run after Q-ID fix
1. Delete the affected CSVs from `reference/` so they get re-downloaded
2. Run with full command (not `--offline`):
   ```
   python step2_enrich.py --input step1_classified.xlsx --output test.xlsx \
     --test-mode --user-agent "user@example.com"
   ```
3. Read the "Status per bron" report at the end

### Test mode discipline
Always run with `--test-mode` first (100 records) before doing a full run
(6,004 records). Saves time and doesn't waste Wikidata queries.

---

## User context and preferences

- Dutch native speaker. Code comments mostly Dutch where they explain
  intent, English where they're standard library / pandas terms.
- Avoid em-dashes (the typographic — character) in any user-facing output.
- For coding tasks: deliver one step at a time when there are multiple,
  so user can test before continuing.
- Casual but technically precise tone. Don't be blindly agreeable.
- User explicitly stated `cx_businesstype` field is unreliable; name +
  address are authoritative.
- User runs on Windows with PowerShell, Python 3.13.3, venv in project
  folder. Other devs may use macOS/Linux.

---

## Dependencies

```
pandas
openpyxl
requests
rapidfuzz
```

No exotic packages. Python 3.10+ required (uses f-strings and modern
type hints in places).

---

## Known limitations / future work

1. **Aggregation mapping tables** for `samenwerking_nl`,
   `belastingsamenwerking`, `hulpverleningszone`, `ggd`, `stadsregio`,
   `amt`, `verwaltungsgemeinschaft` - need building from authoritative
   sources.
2. **CBS Statline fallback for NL** would give fresher data than Wikidata
   for NL gemeenten/provincies/waterschappen.
3. **Statbel for BE police zones** has direct population data per
   politiezone, more reliable than Wikidata.
4. **Manual review queue**: any record with match_score between 85 and
   92 should ideally go to a review queue. Currently they get applied
   automatically with a medium confidence marker.
5. **Override table workflow**: documented but not yet exercised by user.
   First real run will determine if format/UX is right.
6. **Yearly run automation**: currently a manual process. Could be a
   scheduled task on a server.

---

## What I'd do next if I were continuing

1. **Investigate the 5 broken reference sources** (one at a time):
   - Test candidate Q-IDs in query.wikidata.org GUI first
   - Once confirmed, update `REFERENCE_SOURCES` in `step2_enrich.py`
   - Tell user to delete the affected CSV from `reference/` and re-run

2. **Address the DE Verbandsgemeinden truncated JSON**:
   - Test with `LIMIT 10` to see what's actually being returned
   - May need to filter the query, or split by Bundesland

3. **Filter NL gemeenten to current only**:
   - Add `FILTER NOT EXISTS { ?item wdt:P576 ?dissolved }` to SPARQL
   - Confirm it doesn't blow the 60s timeout
   - Verify count drops to ~342

4. **Once all reference sources are stable**, run full 6,004 records
   and have user review:
   - Records with match_score 85-92 (medium confidence)
   - Records still empty after enrichment
   - Aggregation result quality for veiligheidsregio/omgevingsdienst

5. **Then build v2 aggregation mappings** for the unsupported types
   based on what user prioritizes.
