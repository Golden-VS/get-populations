# CRM Population Enrichment - Project Checkpoint

> Handoff document for continuing this project in a fresh Claude Code session.
> Last updated: 2026-06-05

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
**Status: COMPLETE.** Output `step1_classified.xlsx` (6,004 records,
9 added columns). NOT in this repo (lives on user's Windows machine). Per
the previous CHECKPOINT: 2,253 records will get a population lookup;
989 explicitly empty; 2,762 leave-empty.

The classifier output is the input to step 2.

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

## Session summary (commits on `main`)

Run `git log --oneline` to see the latest. As of this checkpoint:

| Commit | Topic |
|---|---|
| `017aa56` | Add `data_leeftijd_jaren` column for staleness visibility |
| `3b307cf` | BE politiezones: aggregation via 173/176 zones from NL Wikipedia |
| `3f69e18` | BE provincies Q-ID fix: `Q364356` -> `Q83116` (10 items, full P1082) |
| `c3ad5e4` | Amsterdam stadsdelen: hardcoded values from NL Wikipedia infoboxes |
| `5b31121` | NL waterschap: treat as aggregation, STUB mapping |
| `9bd404e` | Skip dissolved entities in SPARQL template (FILTER NOT EXISTS P576) |
| `e87c951` | Initial baseline (prior CHECKPOINT + step2_enrich.py + .gitignore) |

---

## Reference sources: current state

Measured 2026-05-11 unless noted. `dissolved filter` = the global
`FILTER NOT EXISTS { ?item wdt:P576 ?dissolved }` added in `9bd404e`.

| Name | Q-ID | Active items | With P1082 | Status |
|---|---|---|---|---|
| `nl_gemeenten` | Q2039348 | 1,316 (was 1,575) | most | OK but over-counts (NL has ~342 current). User wants historical kept (intentional, see notes below). |
| `nl_provincies` | Q134390 | 12 | 12 | OK. |
| `be_gemeenten` | Q493522 | 565 (was 581) | full | OK, clean match. |
| `be_provincies` | **Q83116** (was Q364356) | 10 | 10 | FIXED this session. |
| `de_gemeinden` | Q262166 | 346 | most | UNDER-COUNTS. Germany has ~10,000 Gemeinden. Likely needs subclass walking (`wdt:P31/wdt:P279*`) or per-Bundesland Q-IDs. NOT YET FIXED. |
| `de_landkreise` | Q106658 | 44 | most | UNDER-COUNTS. Germany has ~294 Landkreise. NOT YET FIXED. |
| `de_verbandsgemeinden` | Q253019 | (fails) | n/a | STILL FAILING with truncated-JSON / 502 errors. NOT YET INVESTIGATED. |
| `caribbean_countries` | (hardcoded VALUES) | 4 | 4 | OK. |

### Sources REMOVED from `REFERENCE_SOURCES` this session

These are NOT fetched from Wikidata anymore; they're handled by inline
tables instead:

| Old source | Why removed | Replacement |
|---|---|---|
| `nl_waterschappen` | Wikidata has 0 P1082 for any of 23 active items (Q702081) | `NL_WATERSCHAP_GEMEENTEN` aggregation (STUB, see below) |
| `nl_stadsdelen` | Wikidata has 0 P1082 for 8 Amsterdam boroughs (Q15079751) | `NL_STADSDEEL_INWONERS` direct-value table |
| `be_politiezones` | Wikidata has 0 P1082 for 176 zones (Q2621126) | `BE_POLITIEZONE_GEMEENTEN` aggregation (173/176 from NL Wikipedia) |

---

## Inline mapping tables in `step2_enrich.py`

| Table | Type | Status |
|---|---|---|
| `NL_VEILIGHEIDSREGIO_GEMEENTEN` | sum-of-gemeenten | partial (5 regions populated) - PRE-EXISTING |
| `NL_OMGEVINGSDIENST_GEMEENTEN` | sum-of-gemeenten | partial (5 diensten populated) - PRE-EXISTING |
| `NL_WATERSCHAP_GEMEENTEN` | sum-of-gemeenten | **STUB** - 21 keys, all empty lists (`5b31121`) |
| `NL_STADSDEEL_INWONERS` | direct value | **POPULATED** - 8 Amsterdam stadsdelen, both `X` and `Amsterdam-X` keys, peildatums 2020-2022 from NL Wikipedia infoboxes (`c3ad5e4`) |
| `BE_POLITIEZONE_GEMEENTEN` | sum-of-gemeenten | **POPULATED** - 173/176 zones extracted from NL Wikipedia list (`3b307cf`) |

`enrich_record` dispatches by `detected_type`:
- `veiligheidsregio`, `omgevingsdienst`, `waterschap` -> aggregate NL gemeenten
- `stadsdeel`, `deelgemeente` -> direct lookup in `NL_STADSDEEL_INWONERS`
- `politiezone` -> aggregate BE gemeenten via `BE_POLITIEZONE_GEMEENTEN`
- Everything else -> direct fuzzy match against the appropriate Wikidata
  reference list per `TYPE_TO_REFERENCE`.

---

## Open work items (priority order)

### 1. Waterschap mapping data source (BLOCKING DECISION)

`NL_WATERSCHAP_GEMEENTEN` ships as a stub. The user has 20-30 waterschap
records in the CRM and they are "important large accounts" -> accuracy
matters. The user does NOT want to fill the table manually.

Wikipedia/Wikidata investigation (done in session) showed:
- No overview page with member-gemeenten lists.
- Individual articles describe geography in prose, not structured lists.
  Only Rijnland mentions a population number ("1,3 miljoen", 2019).
- Infoboxes only carry `oppervlakte` (area), not gemeenten.
- Wikidata: 0 of 342 NL gemeenten link to any active waterschap.
- Wikipedia categories: contain pump stations and historic structures,
  not member gemeenten.

**Proposed: CBS Wijken en buurten integration.** CBS publishes the
official gemeente <-> waterschap correspondence as part of their open
data. New fetcher needed (OData API). ~Half day of work. Authoritative
and refreshable. Bonus: same fetcher unblocks the deferred "CBS upgrade
for fresher NL gemeente data" item.

**Alternative: PDOK geometric intersection** (gemeente polygons +
waterschap polygons). Adds `geopandas` / `shapely` dependency.

**User has NOT yet picked an option.** Next session should ask which
path they want to take, then execute it.

### 2. DE Verbandsgemeinden (`Q253019`) failing entirely

Truncated-JSON / 502 errors. NOT investigated this session.
Suggested approach (from prior CHECKPOINT): test with `LIMIT 10` first
to see what's actually being returned. Possible alternatives: `Q272946`
or split by Bundesland.

### 3. DE Gemeinde under-count

`Q262166` returns 346 items; Germany has ~10,000 Gemeinden. Likely
needs subclass walking (`wdt:P31/wdt:P279*`) or per-Bundesland Q-IDs.
The class hierarchy is complex (different subtypes per Bundesland).

### 4. Fill `NL_WATERSCHAP_GEMEENTEN` once data source is chosen (depends on #1).

### 5. NL gemeenten over-count - user wants historical KEPT (design decision)

CHECKPOINT-prior framing was "filter to current only". User reconsidered
during this session: if the CRM has an old gemeente name, look up that
old gemeente's last-known population (not the new merged entity).
Reasoning: the CRM names are what they are; honest staleness with a
correct peildatum beats silent re-mapping to a different population.

Current code already does this for ~99% of cases: most historical NL
gemeenten don't have `P576` set in Wikidata, so the dissolved filter
doesn't exclude them. The `data_leeftijd_jaren` column (added in
`017aa56`) surfaces stale matches per row.

NOT YET DONE but discussed: per-source dissolved filter (off for
`nl_gemeenten`, on for `be_gemeenten`) so that even `P576`-tagged old
NL gemeenten survive and can be matched. Would require capturing the
dissolution date in the dataframe and adding an `is_historisch`
column. Optional polish; revisit if user wants more visibility.

### 6. v2 aggregation tables (deferred)

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
`- step2_enrich.py                <- main script

NOT in this repo (excluded by .gitignore):
- step1_classified.xlsx           (real CRM data; on user's Windows machine)
- step2_enriched.xlsx             (output)
- reference/*.csv                 (Wikidata cache; rebuilt on first run)
- .claude/                        (local Claude Code settings)
- venv/                           (Python virtualenv)
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
```

No exotic packages. Python 3.10+. If we go with the CBS / PDOK path for
waterschap (open item #1), one of these will be added:
- CBS path: no new packages (uses `requests` for OData).
- PDOK path: `geopandas` + `shapely`.

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

1. **Resolve open item #1**: ask the user to pick CBS vs PDOK vs
   accept-the-stub for `NL_WATERSCHAP_GEMEENTEN`. Then execute that
   choice.
2. **Investigate `de_verbandsgemeinden` (Q253019) failure** (item #2).
   Probably the simplest remaining "broken Q-ID" type problem to close.
3. **DE Gemeinde under-count** (item #3). More involved - the German
   class hierarchy requires research.
4. **Per-source dissolved filter for `nl_gemeenten`** (item #5).
   Optional polish; keep deferred unless user asks.
5. **v2 aggregation tables** (item #6). User-driven prioritization.

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
