# TAM / Whitespace List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A separate script `tam_build.py` that builds a source-backed master list of government organisations in NL/BE/DE, cuts it per core product x country from a business-filled template, matches CRM accounts to it (rules first, Opus 5.5 for the rest) and writes one Power BI-ready Excel.

**Architecture:** New package `tam/` with one module per responsibility: country source loaders return a common `SourceBundle` (entities, memberships, aliases, status); `master.py` merges them and computes member-sum populations; `classify.py` and `matching.py` use a shared AI wrapper with a hard cost cap; `template.py`, `tam_rows.py`, `output.py` handle the business-facing files. `tam_build.py` is the thin CLI. Steps 1, 1b and 2 are not changed.

**Tech Stack:** Python 3.10+, pandas, openpyxl, requests, rapidfuzz, anthropic (already in venv), pydantic (already pulled in by anthropic), pytest (new, dev only).

**Spec:** `doc/specs/2026-10-26-tam-whitespace-design.md`

## Revision note

Revised 2026-10-27 after an independent Opus 5.5 review of spec + plan. Main
changes: DE population sums are computed from ALL Gemeinden by ARS prefix
(alias Gemeinden included); memberships carry a `membership_type` and only
`cooperation` rows are exported; pass 1 only matches within kinds compatible
with the CRM `detected_type`; correct commercial literal
(`commercieel_of_overig`); per-Land Verband rules (BW members keep their own
administration); GV parsing on Satzart + Textkennzeichen with newest-Stichtag
selection; stable ids (DE AGS, fixed hand-table ids); KvK/KBO on municipalities;
better pass-2 candidates; corrected Anthropic call shape and per-batch error
handling; CRM input is the fresh export `input_crm_27-10-2026.csv`.

## Global Constraints

- Model `claude-opus-5-5`; prices used for cost tracking: input $4.00, output $20.00, cache write $5.00, cache read $0.20 per million tokens.
- Cost cap default $50 per run (`--max-cost`).
- No company, product or customer names in tracked files, commit messages or docs. Company allow-list and ignore list live in `tam_config.json` (gitignored); a placeholder `tam_config.example.json` is committed.
- Network calls use a generic User-Agent `get-populations-tam/1.0 (+https://github.com/Golden-VS/get-populations)`; never an email address.
- Code comments mostly Dutch, log messages Dutch (repo convention). No em-dashes in user-facing text or docs.
- Never invent populations, members, successors or entities. Missing source data = empty population / no row, plus a run-log line.
- `*.xlsx`, `*.csv`, `logs/`, `reference/` stay gitignored. Test fixtures are synthetic and written as `.xml`, `.nt`, `.json` or built in `tmp_path`.
- One scoped commit per task, pushed (user's workflow). Commit messages end with the session attribution lines.
- Do not modify `step1_classify.py`, `step1b_segment.py`, `step2_enrich.py`. Importing helpers from them (`normalize`, `sparql_query`, `setup_file_logging`, `discover_cbs_gebieden_table`) is allowed.

## Review Focus

1. A source that is unreachable or changed format: the run continues with the other sources, the affected kinds are missing, and the run log and console say so loudly. (Task 9 test `test_failed_source_does_not_abort`.)
2. A CRM account whose name matches two entities (DE has ~486 duplicate Gemeinde names): pass 1 must NOT pick one; it goes to pass 2 with both as candidates. (Task 14 test `test_ambiguous_exact_name_not_matched_in_pass1`.)
3. A typo in the template (`segments` or `excluded_kinds` value not on the fixed list): the run stops before any download or AI call with a message naming sheet row and value. (Task 12 test `test_unknown_segment_value_stops_with_row_number`.)
4. Re-running next year must give the same `entity_id` for the same organisation, independent of row order. (Task 2 test `test_entity_id_is_deterministic`.)
5. Hitting the cost cap mid-run: caches are saved, unprocessed items stay unclassified/unmatched with a clear reason, and the output is still written. (Task 10 test `test_cap_stops_before_exceeding`, Task 15 test `test_cap_reached_leaves_rest_unmatched`.)

---

## File structure

```
tam/__init__.py
tam/config.py          vaste lijsten, kinds, statussen, prijzen, paden
tam/entities.py        kolomschema's, SourceBundle, id-helpers, populatie-sommen
tam/sources/__init__.py
tam/sources/common.py  SourceCache (download + cache + offline), SourceStatus
tam/sources/nl.py      CBS gemeenten/provincies, OO-register, NL-handrijen
tam/sources/be.py      Wikidata gemeenten/provincies, OP-dump, W/B-bronnen
tam/sources/de.py      Destatis GV, FEU-Zweckverbaende
tam/sources/aliases.py voorgangers (Wikidata P1366)
tam/hand_tables.py     handtabellen met bron-URL per rij
tam/master.py          samenvoegen, populaties, validatie
tam/ai.py              Claude-wrapper, CostTracker, cap
tam/classify.py        samenwerkingen -> detailed segment
tam/template.py        template maken/lezen/valideren, productregels
tam/tam_rows.py        TAM-rijen per definitie
tam/matching.py        CRM-scope, kandidaten, pass 1, pass 2, overrides
tam/output.py          Excel-uitvoer + run log
tam_build.py           CLI
tests/...              pytest, synthetische fixtures
```

Shared data shapes (defined in Task 2, used everywhere):

- `ENTITY_COLUMNS = ['entity_id','name','match_name','country','kind','segment','detailed_segment','region','postcode','population','population_method','population_source','population_date','official_ids','source','source_date']`
  - `match_name` = name used for matching (DE: official name cut at the first comma, so `Kassel, Stadt` -> `Kassel`; others = name). `postcode` = DE Gemeinde PLZ from the GV file, else empty.
- `MEMBERSHIP_COLUMNS = ['entity_id','member_entity_id','member_kind','membership_type','join_date']`
  - `membership_type`: `cooperation` (GR/vereniging/zone/Verband members; exported to the `Memberships` sheet, Power BI marks these members as covered), `territorial` (province/Kreis/Land/RB -> municipality; population only, never exported), `same_as` (AGB -> its gemeente; never exported).
- `ALIAS_COLUMNS = ['alias_name','country','entity_id','reason']`
- `population_method` values: `own`, `sum of members`, `same as municipality`, `country total`, `unknown`. A loader may already fill `population` for a `sum of members` row (DE does its sums inside `parse_gv`); master only computes sums for rows whose population is still empty.
- `official_ids`: `;`-joined `scheme:value`, schemes `kvk`, `kbo`, `oin`, `tooi`, `ars`, `nis`, `cbs`.
- `region`: human context for matching (NL gemeente -> provincie, DE Gemeinde -> Kreis, DE Kreis -> Land, BE gemeente -> provincie).

---

### Task 1: Package scaffold, fixed lists, dev tooling

**Files:**
- Create: `tam/__init__.py`, `tam/config.py`, `tests/__init__.py`, `tests/test_config.py`, `tam_config.example.json`, `pytest.ini`
- Modify: `.gitignore` (add `tam_config.json`, `tam_template*.xlsx` is already covered by `*.xlsx`)

**Interfaces:**
- Produces in `tam/config.py`:
  - `MODEL = 'claude-opus-5-5'`, `PRICES_PER_MTOK = {'input': 4.0, 'output': 20.0, 'cache_write': 5.0, 'cache_read': 0.20}`, `DEFAULT_MAX_COST = 50.0`
  - `SEGMENTS: list[str]` = the five government segments of the existing step 1b vocabulary: `Local government`, `Regional government`, `National government`, `Inter-municipal cooperation`, `Public safety & emergency`
  - `DETAILED_SEGMENTS: dict[str, list[str]]` = spec section 5 verbatim (segment -> detailed values, incl. `County-level city`)
  - `KIND_TO_SEGMENT: dict[str, tuple[str, str | None]]` kind -> (segment, detailed); `None` detailed = classified later (cooperations). Kinds: `nl_gemeente, nl_stadsdeel, nl_openbaar_lichaam, nl_provincie, nl_waterschap, nl_veiligheidsregio, nl_samenwerking, nl_land_caribisch, nl_ministerie, nl_rijksorganisatie, be_gemeente, be_provincie, be_gewest, be_agb, be_district, be_politiezone, be_hulpverleningszone, be_samenwerking, be_welzijnsvereniging, be_intercommunale, be_fod, de_gemeinde, de_kreisfreie_stadt, de_stadtstaat, de_bezirk, de_gemeindeverband, de_landkreis, de_regierungsbezirk, de_hoeherer_kommunalverband, de_bundesland, de_it_zweckverband, de_zweckverband, de_bundesministerium`
  - `IN_TAM_STATUSES = ['yes', 'no - below cutoff', 'no - excluded kind', 'unknown - population missing']`
  - `COUNTRIES = ['NL', 'BE', 'DE']`; `CRM_COUNTRY_TO_TAM = {'NL':'NL','BE':'BE','DE':'DE','AW':'NL','CW':'NL','SX':'NL','BQ':'NL'}`
  - `REFERENCE_DIR = Path('reference/tam')`, `CACHE_MAX_AGE_DAYS = 365`, `USER_AGENT` (Global Constraints value)
  - `def all_detailed() -> set[str]`
- `tam_config.example.json`: `{"companies": ["Company A", "Company B", "Company C"], "ignore_core_products": ["_Other", "Undefined", "Non-product family"]}`

- [ ] **Step 1:** `venv/bin/pip install pytest` and add `pytest.ini` with `[pytest]\ntestpaths = tests`.
- [ ] **Step 2: Write failing tests** in `tests/test_config.py`:
  - `test_detailed_values_unique_across_segments`: flattening `DETAILED_SEGMENTS` gives no duplicates.
  - `test_kind_mapping_uses_known_values`: every `KIND_TO_SEGMENT` segment is in `SEGMENTS`, every non-None detailed is in `DETAILED_SEGMENTS[segment]`.
  - `test_county_level_city_present`: `'County-level city' in DETAILED_SEGMENTS['Local government']`.
- [ ] **Step 3:** Run `venv/bin/pytest tests/test_config.py -v`, expect ImportError FAIL.
- [ ] **Step 4:** Implement `tam/config.py`.
- [ ] **Step 5:** Run tests, expect PASS. Commit `tam: package scaffold and fixed segment lists`, push.

### Task 2: Entity model and population rules

**Files:**
- Create: `tam/entities.py`, `tests/test_entities.py`

**Interfaces:**
- Consumes: `tam.config.KIND_TO_SEGMENT`
- Produces:
  - `ENTITY_COLUMNS`, `MEMBERSHIP_COLUMNS`, `ALIAS_COLUMNS` (see File structure)
  - `@dataclass SourceStatus(name: str, ok: bool, rows: int, source_date: str, message: str)`
  - `@dataclass SourceBundle(entities: pd.DataFrame, memberships: pd.DataFrame, aliases: pd.DataFrame, status: list[SourceStatus], extras: dict = field(default_factory=dict))` with `@staticmethod empty() -> SourceBundle` and `def merge(self, other) -> SourceBundle` (concatenates frames and status; `extras` values that are DataFrames are concatenated per key, dicts are updated). Known extras keys: `municipal_population: dict[str,int]` (every municipality id incl. non-entities -> population), `id_patches: DataFrame[entity_id, official_ids]`.
  - `def make_entity_id(country: str, scheme: str, code: str) -> str` returns `f'{country}-{scheme.upper()}-{code}'`, code stripped and upper-cased. Hand-table rows carry a fixed `id` field in the table itself (never derived from the name); SPW rows use the SPW sheet's own row key if it has one, else a slug, and the run log lists SPW ids that disappeared since the previous run.
  - `def slugify(text: str) -> str` (lowercase ascii, `-` separated, uses `step2_enrich.normalize`)
  - `def new_entity(**fields) -> dict` fills segment/detailed from `KIND_TO_SEGMENT[kind]`, defaults missing columns to `''`/`None`.
  - `def apply_member_population(entities: pd.DataFrame, memberships: pd.DataFrame, municipal_population: dict[str, int]) -> tuple[pd.DataFrame, list[str]]`: for rows with `population_method == 'sum of members'` AND empty population, population = sum over distinct members found in `municipal_population` (a dict of municipality id -> population that includes municipalities that are NOT entities, e.g. DE Gemeinden inside an Amt; built by master from loader extras, see Task 9). Members not in the dict (provinces, waterschappen) are ignored. Zero resolvable members -> population NaN and method `unknown`; returns warnings for unresolved municipality-like ids.
  - `def apply_country_totals(entities, municipal_population: dict[str, int]) -> pd.DataFrame`: rows with method `country total` get the sum of that country's entries in `municipal_population` (ids start with `NL-`, `BE-`, `DE-`).

- [ ] **Step 1: Write failing tests:**
  - `test_entity_id_is_deterministic`: `make_entity_id('NL','GM','gm0363') == 'NL-GM-GM0363'`; `make_entity_id('DE','HAND','Bezirk Mitte') == make_entity_id('DE','HAND','bezirk  mitte')`.
  - `test_sum_counts_distinct_municipal_members_only`: entity X with members GM1 (pop 100), GM1 again, PV1 (province, pop 1000, not in the dict), GM2 (pop 50) -> X.population == 150, method `sum of members`.
  - `test_sum_includes_non_entity_municipalities`: member `DE-AGS-07131001` present only in `municipal_population` (not an entity) is counted.
  - `test_prefilled_population_not_recomputed`.
  - `test_no_resolvable_members_gives_unknown`: members only unknown ids -> population NaN, method `unknown`, one warning naming the ids.
  - `test_country_total`: two NL gemeenten 100+200 and a ministry with `country total` -> 300.
- [ ] **Step 2:** Run, expect FAIL.
- [ ] **Step 3:** Implement `tam/entities.py`.
- [ ] **Step 4:** Run, expect PASS. Commit `tam: entity model and population rules`, push.

### Task 3: Download cache

**Files:**
- Create: `tam/sources/__init__.py`, `tam/sources/common.py`, `tests/test_sources_common.py`

**Interfaces:**
- Produces: `class SourceCache(refresh: bool = False, offline: bool = False, base_dir: Path = REFERENCE_DIR)` with
  - `def fetch(self, name: str, url: str, *, params: dict | None = None, suffix: str = '', max_age_days: int = CACHE_MAX_AGE_DAYS) -> Path`: returns cached file if fresh (mtime) unless `refresh`; `offline` never downloads (missing file -> `FileNotFoundError`); downloads stream to `<name><suffix>.part` then rename (no half files); `User-Agent` = `USER_AGENT`; timeout 300 s.
  - `def sparql(self, name: str, query: str) -> pd.DataFrame`: cached as `<name>.json` (raw bindings) and flattened to a DataFrame of string values; uses `step2_enrich.sparql_query(query, USER_AGENT)`.

- [ ] **Step 1: Failing tests** (monkeypatch `requests.get`):
  - `test_fresh_cache_not_redownloaded`: second fetch within max age does not call `requests.get`.
  - `test_refresh_forces_download`.
  - `test_offline_missing_file_raises`.
  - `test_partial_download_not_left_behind`: `requests.get` raising mid-stream leaves no `<name>` file.
- [ ] **Step 2-4:** Run fail, implement, run pass. Commit `tam: cached source downloads`, push.

### Task 4: NL municipalities and provinces (CBS)

**Files:**
- Create: `tam/sources/nl.py` (CBS part), `tests/test_sources_nl.py`

**Interfaces:**
- Consumes: `SourceCache`, `new_entity`, `make_entity_id`, `step2_enrich.discover_cbs_gebieden_table`
- Produces: `def load_nl_cbs(cache: SourceCache) -> SourceBundle` with kinds `nl_gemeente` (id `NL-GM-<GMxxxx>`, `official_ids` `cbs:GMxxxx`, region = provincie name, method `own`) and `nl_provincie` (id `NL-PV-<PVxx>`, method `sum of members`, memberships to every gemeente in it). Also returns `def parse_cbs_gebieden(records: list[dict], keys: dict) -> pd.DataFrame` (pure, tested).

- [ ] **Step 1: Inspect the real source.** Run `discover_cbs_gebieden_table` and GET `<table>/DataProperties`; find the keys for gemeente code (`Code` under group "Codes en namen van gemeenten"), gemeente name, province code + name, Inwonertal. Write the observed key titles into the module docstring. (Resolve by Title like `step2_enrich._cbs_resolve_keys`, never hard-code `Naam_2`.)
- [ ] **Step 2: Failing tests** on `parse_cbs_gebieden` with two synthetic records: name suffix `"Groningen (gemeente)"` becomes `Groningen`; codes are trimmed (`"GM0014    "` -> `GM0014`); population int.
- [ ] **Step 3:** Implement; provinces get no own population (sum in master).
- [ ] **Step 4:** Live check: `venv/bin/python -c "from tam.sources.common import SourceCache; from tam.sources.nl import load_nl_cbs; b=load_nl_cbs(SourceCache()); print(b.entities.kind.value_counts())"` -> `nl_gemeente 342`, `nl_provincie 12`.
- [ ] **Step 5:** Tests pass. Commit `tam: NL gemeenten and provinces from CBS`, push.

### Task 5: NL register of government organisations (OO export)

**Files:**
- Modify: `tam/sources/nl.py`; Create: `tests/fixtures/oo_mini.xml`, extend `tests/test_sources_nl.py`

**Interfaces:**
- Consumes: Task 4 gemeente ids (TOOI `gm0363` -> `NL-GM-GM0363`)
- Produces: `def parse_oo_export(xml_path: Path, run_date: date) -> SourceBundle` and `def load_nl_oo(cache) -> SourceBundle` (downloads `https://organisaties.overheid.nl/archive/exportOO.xml`, ~38 MB, parse with `xml.etree.ElementTree.iterparse` and clear elements to keep memory low).
  - Active GR = no end date or end date > run_date.
  - Entity per linked `regionaalSamenwerkingsorgaan` (id `NL-SO-<so code>`, fallback `NL-OO-<systeemId>` when the body has no TOOI code); several GRs linking to the same body are merged (union of members). GRs without a linked body produce no entity (spec 4.1). Kind: `nl_veiligheidsregio` when the body name starts with `Veiligheidsregio` or equals `VGGM`/`Veiligheids- en Gezondheidsregio Gelderland-Midden`; else `nl_samenwerking`. Method `sum of members`. `official_ids` from body KvK, OIN, TOOI.
  - Memberships from `deelnemers` TOOI URIs (`membership_type cooperation`): `gemeente/gmXXXX` -> `NL-GM-GMXXXX` (`member_kind nl_gemeente`), `provincie/pvXX` -> `NL-PV-PVXX`, `waterschap/wsXXXX` -> waterschap entity id; keep `join_date`.
  - Gemeente organisations in the export: return their KvK / OIN / TOOI as an `id_patches` DataFrame (`entity_id, official_ids`) on the bundle (`SourceBundle.extras['id_patches']`), so master can attach KvK numbers to the CBS gemeente entities (`NL-GM-*`).
  - Waterschappen (21 active): kind `nl_waterschap`, id `NL-WS-<tooi code>`, population from `step2_enrich.NL_WATERSCHAP_INWONERS` by normalized name (method `own`, source = that table's `bron_url`), else `unknown`.
  - National: organisations of type Ministerie (kind `nl_ministerie`) and Zelfstandig bestuursorgaan / Agentschap / Adviescollege-free set chosen after inspecting the type list (kind `nl_rijksorganisatie`), method `country total`, id `NL-OO-<systeemId>`.
- [ ] **Step 1: Inspect the real export.** Download once, print the distinct organisation `types`, the element paths for GR end date, deelnemers, linked body, body identifiers. Record them in the module docstring. Decide the national type set (log it in the docstring).
- [ ] **Step 2:** Write `tests/fixtures/oo_mini.xml` with the real element structure: 2 active GRs linking to one body (members gm0001, gm0002 + gm0002, pv20), 1 ended GR, 1 GR without body, 1 veiligheidsregio body, 1 waterschap, 1 ministerie.
- [ ] **Step 3: Failing tests:** `test_ended_gr_skipped`, `test_gr_without_body_skipped`, `test_two_grs_same_body_merged_members_deduplicated` (members {GM0001, GM0002, PV20}), `test_veiligheidsregio_kind`, `test_waterschap_population_from_table`, `test_ministerie_country_total`.
- [ ] **Step 4:** Implement; run tests pass.
- [ ] **Step 5:** Live check prints counts: active GR-bodies ~350-360, veiligheidsregio 25, waterschap 21. If veiligheidsregio != 25, list the names and fix the rule before continuing.
- [ ] **Step 6:** Commit `tam: NL cooperations, waterschappen and national bodies from OO register`, push.

### Task 6: NL hand rows and BE sources

**Files:**
- Create: `tam/hand_tables.py`, `tam/sources/be.py`, `tests/fixtures/op_mini.nt`, `tests/test_sources_be.py`, `tests/test_hand_tables.py`
- Modify: `tam/sources/nl.py` (add `load_nl_hand`)

**Interfaces:**
- Produces:
  - `hand_tables.py`: dicts with per-row `population`, `peildatum`, `bron_url` (same shape as `NL_WATERSCHAP_INWONERS`): `NL_OPENBARE_LICHAMEN` (Bonaire, Sint Eustatius, Saba; CBS), `NL_LANDEN_CARIBISCH` (Aruba, Curacao, Sint Maarten; their statistics offices), `BE_GEWESTEN` (Vlaams Gewest, Waals Gewest, Brussels Hoofdstedelijk Gewest, Duitstalige Gemeenschap, Federatie Wallonie-Brussel; Statbel; Vlaamse Gemeenschap = Vlaams Gewest institution, one row), `BE_FOD` (names only, method `country total`), `BE_HULPVERLENINGSZONES_WB` (zone -> member commune names, from the civieleveiligheid.be zone PDF), `BE_INTERCOMMUNALES_BXL` (names). Each row has `bron_url`; a row whose population cannot be sourced has `population: None`.
  - `def load_nl_hand() -> SourceBundle` (stadsdelen from `step2_enrich.NL_STADSDEEL_INWONERS` deduplicated per `bron_url`, openbare lichamen, Caribbean countries).
  - `def load_be_wikidata(cache) -> SourceBundle`: SPARQL for current Belgian municipalities (instance of Q493522, no P576) with P1567 NIS code, P1082 latest population + date, province; and provinces (Q83116) with NIS code. Ids `BE-NIS-<code>`; provinces method `sum of members`. Use the Wikipedia-title label fallback pattern from `step2_enrich._sparql_population_template`.
  - `def parse_op_dump(nt_path: Path, gemeenten: pd.DataFrame) -> SourceBundle` and `def load_be_op(cache, gemeenten) -> SourceBundle`: stream the N-Triples line by line (no rdflib); keep active organisations of classes politiezone, hulpverleningszone, AGB, district, opdrachthoudende/dienstverlenende/projectvereniging, welzijnsvereniging; members via `org:Membership`; map member gemeenten to `BE-NIS-*` by normalized name (log unresolved); id `BE-KBO-<10 digits>`; AGB method `same as municipality` with one `same_as` membership to its gemeente. Gemeente organisations in the dump: their KBO numbers go into `extras['id_patches']` keyed on the matching `BE-NIS-*` id.
  - `def load_be_wb(cache, gemeenten, flemish_nis: set[str]) -> SourceBundle`: W/B police zones from `step2_enrich.BE_POLITIEZONE_GEMEENTEN` excluding every zone with ANY Flemish member (Flemish zones come from OP); the run log lists the W/B zone count so a shortfall (table has 173 of ~176) is visible, fire zones from `BE_HULPVERLENINGSZONES_WB`, Walloon intercommunales from the SPW cadastre xlsx (sheet/columns found in Step 1; intercommunales only, not SLSP housing), Brussels intercommunales from the hand table, Gewesten and FOD's. Ids `BE-HAND-*` / `BE-SPW-*`; intercommunales method `unknown`.
- [ ] **Step 1: Inspect real sources.** Download the OP dump (locate via the `datasets` URL in spec 4.2), list the RDF classes and predicates used for type, status, name, KBO identifier, membership; write them in the module docstring. Open the SPW xlsx and note sheet and column names. Fetch the fire-zone PDF and transcribe the 14 Walloon zones + Brussels into `BE_HULPVERLENINGSZONES_WB` with members; look up Statbel figures for `BE_GEWESTEN` and official figures for the Caribbean/BES rows. Every value gets its `bron_url`; skip what cannot be sourced.
- [ ] **Step 2: Failing tests:** `op_mini.nt` with one active politiezone (2 member gemeenten), one inactive projectvereniging, one AGB, one welzijnsvereniging: `test_op_inactive_skipped`, `test_op_members_mapped_to_nis`, `test_op_agb_same_as_municipality`. `test_hand_tables_every_row_has_source` (every dict row has non-empty `bron_url`). `test_wb_police_excludes_zones_with_any_flemish_member`.
- [ ] **Step 3:** Implement; tests pass.
- [ ] **Step 4:** Live counts: `be_gemeente` 560-570 (print exact), `be_provincie` 10, `be_politiezone` (OP active + W/B) ~170-180, `be_hulpverleningszone` 35. Investigate any count outside the range before committing.
- [ ] **Step 5:** Commit `tam: BE sources and hand tables`, push.

### Task 7: DE sources (Destatis GV, FEU, hand tables)

**Files:**
- Create: `tam/sources/de.py`, `tests/test_sources_de.py`
- Modify: `tam/hand_tables.py` (DE tables)

**Interfaces:**
- Produces:
  - `def parse_gv(df: pd.DataFrame, stichtag: str) -> SourceBundle` (pure; `df` = the GV sheet with columns normalised to `satzart, textkennzeichen, land, rb, kreis, vb, gem, name, population, plz`) and `def load_de_gv(cache) -> SourceBundle`. The download URL has no year: fetch all four `AuszugGV<1-4>QAktuell.xlsx`, read each file's Stichtag (Gebietsstand) from the header, use the newest; record it as `source_date`.
  - Parsing facts (verify in Step 1, they come from the reviewer): `satzart` 10 Land, 20 RB, 30 Region (BW, ignore), 40 Kreis, 50 Gemeindeverband, 60 Gemeinde. The Kreis/Gemeinde/Verband kind is in `textkennzeichen` (Kreis: 41 kreisfreie Stadt, 42 Stadtkreis, 43 Kreis, 44 Landkreis, 45 Regionalverband; Verband: 50 = `verbandsfreie Gemeinde` placeholder, 58 = erfuellende Gemeinde, others = Verband types; Gemeinde 60-67, 63 = gemeindefreies Gebiet).
  - Ids (stable across Verband reorganisations): Gemeinde and kreisfreie Stadt `DE-AGS-<8-digit AGS = land+rb+kreis+gem>`; Kreis `DE-AGS-<5>`; Land `DE-AGS-<2>`; RB `DE-AGS-<3>`; Verband `DE-ARS-<9-digit Verband key>`. `official_ids` `ars:<12-digit ARS>` for Gemeinden.
  - **Population sums are computed here, from ALL Gemeinden by key prefix** (alias Gemeinden included): Land, RB, Kreis, Verband rows get population filled and method `sum of members`. Territorial memberships (`membership_type territorial`) are still emitted for Kreis/Land/RB -> Gemeinde entities for audit, but never exported. `extras['municipal_population']` = every Gemeinde (incl. Verband members) `DE-AGS-<8>` -> population, plus city-state Land ids.
  - Kreisfreie Staedte: one entity kind `de_kreisfreie_stadt` (the Gemeinde), not also a Kreis entity.
  - City-states: Berlin (11) and Hamburg (02) Land row -> `de_stadtstaat` (State), population = the Land's Gemeinde; no separate Gemeinde/Kreis entity. Bremen (04): Land row -> `de_stadtstaat` with population of Stadt Bremen ONLY (Bremerhaven has its own administration); Bremerhaven -> `de_kreisfreie_stadt`.
  - Landkreise (Satzart 40, Textkennzeichen 43/44/45) -> `de_landkreis`. Bundeslaender (Satzart 10, not 02/04/11) -> `de_bundesland`. Regierungsbezirke: Satzart 20 only for Land 05, 06, 08, 09 -> `de_regierungsbezirk` (exactly 19).
  - Gemeindeverbaende, per-Land rule table `VERBAND_RULES` in `de.py` (verify each line against the Land's Kommunalverfassung or Destatis notes; cite the URL in a comment):
    - Amt (SH, MV, BB), Samtgemeinde (NI), Verbandsgemeinde (RP, ST), Verwaltungsgemeinschaft (BY, TH), Verwaltungsverband (SN): the Verband is the entity (`de_gemeindeverband`, `Municipal federation`), its member Gemeinden are aliases (reason `member of <Verband>`), population = sum of members.
    - Textkennzeichen 58 (erfuellende Gemeinde, TH) and Verwaltungsgemeinschaft in SN: the erfuellende Gemeinde is the entity (`de_gemeinde`) with population = sum of the whole Verband (it serves all of them; my call, spec 3.4 "represented population"); other members are aliases (reason `administered by <Gemeinde>`); no Verband entity. Identify the erfuellende Gemeinde from Textkennzeichen 58 / the GV data, not from name heuristics.
    - BW Gemeindeverwaltungsverband and vereinbarte Verwaltungsgemeinschaft: member Gemeinden keep their own Rathaus and staff, so every member Gemeinde stays an entity (`de_gemeinde`, own population); a Gemeindeverwaltungsverband also becomes an entity (own staff, population = sum); a vereinbarte VG does not.
    - Any Verband type not in the table -> Verband entity + member Gemeinden stay entities, and a WARNING lists the type so the table can be extended.
  - Gemeinden not in any Verband (or under a placeholder) -> `de_gemeinde`, method `own`, `region` = Kreis name, `postcode` = GV PLZ, `match_name` = name cut at the first comma. Gemeindefreie Gebiete (63) are skipped.
  - `def load_de_feu(cache) -> SourceBundle`: both FEU lists, rows whose name contains `zweckverband` (case-insensitive), dedupe by FEU id, kind `de_zweckverband`, id `DE-FEU-<id>`, method `unknown`; drop rows that match an IT hand-table entry by normalized name. Step 1 also checks whether FEU ids look stable (same id format in the 2025 list if still downloadable); if not stable, use `DE-FEU-<slug of name + Land>` and note it.
  - `hand_tables.py` DE (each row with fixed `id` and `bron_url`): `DE_BEZIRKE` (12 Berlin + 7 Hamburg, populations from Amt fuer Statistik Berlin-Brandenburg / Statistikamt Nord), `DE_HOEHERE_KOMMUNALVERBAENDE` (name -> member Kreis/kreisfreie Stadt AGS list; population = sum over all Gemeinden under those keys, computed with `municipal_population`), `DE_IT_ZWECKVERBAENDE` (name -> member AGS list only where an official page lists them, else empty -> population unknown), `DE_BUNDESMINISTERIEN` (names, `country total`). `def load_de_hand(municipal_population: dict) -> SourceBundle`.
- [ ] **Step 1: Inspect the real GV xlsx.** Find header rows, column positions, the Stichtag cell, Satzart/Textkennzeichen distribution; confirm the facts above (16 x 10, 19 usable RB, 401 Kreise, 10,747 Gemeinden, Verband types per Land, which rows carry Textkennzeichen 58). Note them in the module docstring. Correct the rule table where the data disagrees.
- [ ] **Step 2: Failing tests** with a synthetic GV frame: `test_kreisfreie_stadt_single_entity`; `test_city_states_and_bremerhaven` (Bremen population excludes Bremerhaven); `test_regierungsbezirke_only_four_laender`; `test_amt_members_become_aliases_and_amt_population_is_sum`; `test_landkreis_population_includes_amt_members` (Kreis with one verbandsfreie Gemeinde 1,000 and an Amt with two members 300+200 -> 1,500); `test_erfuellende_gemeinde_population_is_whole_verband`; `test_bw_gvv_members_stay_entities`; `test_verbandsfreie_placeholder_skipped`; `test_gemeinde_id_uses_8_digit_ags`; `test_match_name_cut_at_comma` (`Kassel, Stadt` -> `Kassel`); `test_feu_dedup_and_it_excluded`.
- [ ] **Step 3:** Implement; tests pass.
- [ ] **Step 4:** Live checks printed: sum of `municipal_population` for DE between 83.0M and 84.0M; `de_bundesland 13` + `de_stadtstaat 3`; `de_regierungsbezirk 19`; `de_landkreis 294`; `de_kreisfreie_stadt` (print exact, expected 104); counts per Verband type; every one of the 10,747 Gemeinden is an entity or an alias.
- [ ] **Step 5:** Commit `tam: DE sources from Destatis and hand tables`, push.

### Task 8: Predecessor aliases

**Files:**
- Create: `tam/sources/aliases.py`, `tests/test_aliases.py`

**Interfaces:**
- Produces: `def load_predecessors(cache, entities: pd.DataFrame, aliases: pd.DataFrame) -> SourceBundle` (aliases only): one SPARQL per country for dissolved municipalities (P576 present) with P1366 "replaced by" whose successor has the code we key on (NL P382 CBS code, BE P1567 NIS, DE P439 AGS). Alias row `alias_name = predecessor label`, `entity_id` = successor's entity id, `reason = 'predecessor, merged <year>'`. A successor that is not an entity but is itself an alias (e.g. a DE Gemeinde inside an Amt) resolves through the alias table to that alias's entity; successors found nowhere are skipped and counted. Chains (A -> B -> C) are followed to the current entity, max depth 5.
  - Plus a pure helper `def resolve_chain(edges: dict[str, str], current: set[str]) -> dict[str, str]`.
- [ ] **Step 1: Failing tests:** `test_chain_resolved_to_current` (A->B, B->C, C current -> A->C, B->C); `test_cycle_does_not_hang`.
- [ ] **Step 2-3:** Implement, tests pass, live run prints alias counts per country (NL expect >100, includes Bussum -> Gooise Meren).
- [ ] **Step 4:** Commit `tam: predecessor aliases for merged municipalities`, push.

### Task 9: Master list assembly

**Files:**
- Create: `tam/master.py`, `tests/test_master.py`

**Interfaces:**
- Consumes: all `load_*` functions above.
- Produces: `def build_master(cache: SourceCache, loaders: list[tuple[str, Callable]] | None = None) -> SourceBundle`:
  - Runs loaders in dependency order (CBS, OO, NL hand, BE Wikidata, BE OP, BE W/B, DE GV, DE FEU, DE hand, predecessors). Each loader call is wrapped: exception -> `SourceStatus(ok=False, message=str(e))`, logged at ERROR, run continues. Loaders that need an earlier result receive it (BE OP needs BE gemeenten); if that earlier one failed, they are skipped with status `ok=False, message='overgeslagen: <dependency> ontbreekt'`.
  - Then: merge `extras['municipal_population']` from all bundles (NL/BE: built from the `nl_gemeente` / `be_gemeente` entities; DE: from `parse_gv`); apply `extras['id_patches']` (append ids to `official_ids`); `apply_member_population`; `apply_country_totals`; `same as municipality` fill via `same_as` memberships; validation: unique `entity_id` (duplicates -> ERROR log, keep first), every membership `entity_id` exists, kinds in `KIND_TO_SEGMENT`, every alias `entity_id` exists.
  - Default `loaders=None` means the real list; tests inject fakes.
- [ ] **Step 1: Failing tests:** `test_failed_source_does_not_abort` (one fake loader raises; result has the others' entities and a status with `ok=False`); `test_dependent_loader_skipped_when_dependency_failed`; `test_duplicate_entity_id_logged_and_dropped`; `test_id_patches_attach_kvk_to_gemeente`.
- [ ] **Step 2-3:** Implement, tests pass. Live: `build_master(SourceCache())` prints entity counts per country x kind and the status list; all sources ok.
- [ ] **Step 4:** Commit `tam: master list assembly`, push.

### Task 10: AI wrapper with cost cap

**Files:**
- Create: `tam/ai.py`, `tests/test_ai.py`

**Interfaces:**
- Produces:
  - `class CostCapReached(Exception)`, `class AIRefusal(Exception)`
  - `class CostTracker(max_cost: float)`: `spent: float`; `def add_usage(self, usage) -> float` (uses `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `None` -> 0, prices from config); `def check_room(self, estimated_next: float) -> None` raises `CostCapReached` if `spent + estimated_next > max_cost`.
  - `def estimate_cost(n_items: int, batch_size: int, in_tokens_per_batch: int, out_tokens_per_batch: int) -> float`
  - `def call_parsed(client, tracker: CostTracker, *, system: str, user: str, output_model, estimated_cost: float, effort: str = 'medium')`: `tracker.check_room(estimated_cost)`; `client.messages.parse(model=MODEL, max_tokens=16000, system=[{'type':'text','text':system,'cache_control':{'type':'ephemeral'}}], messages=[{'role':'user','content':user}], output_format=output_model, output_config={'effort': effort}, extra_body={'fallbacks': 'default'}, extra_headers={'anthropic-beta': 'server-side-fallback-2026-07-01'})`. Do NOT put `output_config` in `extra_body` (it would replace the schema `parse` builds). Add usage to the tracker first (fallback turns may bill at another model's rate; accepted undercount, noted in the docstring); then check `stop_reason == 'refusal'` -> `AIRefusal` BEFORE touching `parsed_output`; return `response.parsed_output`. No `thinking` parameter (Opus 5.5 adaptive by default). `output_model` must be a `BaseModel` wrapper (e.g. `class Batch(BaseModel): items: list[Item]`), never a bare `list[...]`.
  - `class AIBatchError(Exception)`: `call_parsed` wraps `anthropic.APIError` (after the SDK's own retries) and pydantic `ValidationError` into it, so callers can mark one batch failed and continue.
- [ ] **Step 1: Failing tests** with a fake client object: `test_usage_cost_math` (1M input + 1M output = $24.00); `test_cap_stops_before_exceeding` (cap $1, spent $0.90, estimate $0.20 -> `CostCapReached`, fake client never called); `test_refusal_raises`; `test_api_error_wrapped_as_batch_error`.
- [ ] **Step 2-3:** Implement, tests pass.
- [ ] **Step 4: One live smoke call** (costs cents): parse a tiny Pydantic model with `ANTHROPIC_API_KEY` set. Confirm the parsed object comes back (schema not lost) and `usage` is populated. If the installed SDK rejects the native `output_config` kwarg next to `output_format`, upgrade `anthropic` in the venv and note it. If the fallback beta is rejected, drop `fallbacks` and the header and record that.
- [ ] **Step 5:** Commit `tam: Claude wrapper with cost tracking and cap`, push.

### Task 11: Cooperation classification

**Files:**
- Create: `tam/classify.py`, `tests/test_classify.py`

**Interfaces:**
- Consumes: master entities, `call_parsed`, `CostTracker`
- Produces: `def classify_cooperations(entities: pd.DataFrame, client, tracker, *, use_ai: bool, cache_path: Path = REFERENCE_DIR / 'classify_cache.csv', batch_size: int = 25) -> tuple[pd.DataFrame, dict]` returns entities with `detailed_segment` filled for every row whose `KIND_TO_SEGMENT` detailed is `None`, plus stats `{rule, cached, ai, unclassified}`.
  - Rules first. By kind: `de_gemeindeverband` -> Municipal federation, `be_welzijnsvereniging` -> Welfare association, `de_zweckverband` -> Special-purpose association, `de_it_zweckverband` -> IT cooperation. By normalized name: contains `omgevingsdienst` -> Environmental agency, `ggd` -> Public health service (GGD), `belasting` -> Tax cooperation.
  - Remaining rows to AI in batches: input per item = number, name, country, kind, member count; output Pydantic `list[{volgnummer:int, detailed_segment: Literal[Inter-municipal cooperation values]}]`; missing numbers in the answer -> those items unclassified.
  - Cache CSV `entity_id,name,detailed_segment,bron,datum`; valid while name unchanged; saved after every batch.
  - `use_ai=False`, `CostCapReached` -> remaining rows get `Other joint arrangement` and are counted as `unclassified` (run log lists them). `AIRefusal` / `AIBatchError` -> only that batch's rows get `Other joint arrangement` + `unclassified`; the next batches still run.
- [ ] **Step 1: Failing tests** (fake `call_parsed` via monkeypatch): `test_rules_before_ai` (an `Omgevingsdienst X` never reaches the fake); `test_cache_hit_skips_ai`; `test_name_change_invalidates_cache`; `test_no_ai_marks_other_joint_arrangement`; `test_answer_missing_item_left_unclassified`; `test_failed_batch_does_not_stop_next_batch`.
- [ ] **Step 2-3:** Implement; system prompt (Dutch/English mix like step 1b) lists the Inter-municipal cooperation values with one-line meanings. Tests pass.
- [ ] **Step 4:** Commit `tam: classify cooperations into detailed segments`, push.

### Task 12: Template (make, update, read, validate)

**Files:**
- Create: `tam/template.py`, `tests/test_template.py`

**Interfaces:**
- Produces:
  - `def load_products(path: Path, config: dict) -> tuple[pd.DataFrame, list[dict]]`: first sheet; columns `Company`, `Sales Unit`, `Core Product Family`; keep `Company in config['companies']`, drop `config['ignore_core_products']`; per `(company, core_product)` pick the sales unit with most rows (tie: alphabetical); returns unique `(company, sales_unit, core_product)` rows and a list of strays `{company, core_product, sales_unit, rows}`.
  - `def make_template(products: pd.DataFrame, path: Path, *, update: bool = False) -> int`: sheets `tam_definitions` (columns spec 7, one row per product x `COUNTRIES`), `match_overrides` (`accountid, entity_id, reason`), `lists` (segments and detailed values, plus a note that multi-value cells use `;`; no Excel data validation since cells hold several values). Existing file without `update` -> `FileExistsError`; with `update` open the workbook with openpyxl and append only missing (company, core_product, country) rows to `tam_definitions`, leaving every other cell and the `match_overrides` sheet untouched. Returns rows added.
  - `@dataclass TamDefinition(company, sales_unit, core_product, country, segments: list[str], excluded_kinds: list[str], min_population: int | None, notes: str)`
  - `def read_template(path: Path) -> tuple[list[TamDefinition], pd.DataFrame]` (definitions with non-empty segments, overrides frame). Validation errors collected and raised together as `TemplateError` listing `tam_definitions rij <excel row>: onbekende waarde '<v>' in <column>`; also checks country in `COUNTRIES`, min_population integer >= 0, override entity_id format.
- [ ] **Step 1: Failing tests** (build product xlsx in `tmp_path`): `test_company_filter_and_ignore_list`; `test_stray_assigned_to_main_sales_unit`; `test_make_refuses_overwrite`; `test_update_keeps_filled_rows_overrides_and_adds_new`; `test_unknown_segment_value_stops_with_row_number` (message contains `rij 3` and the bad value); `test_empty_segments_row_skipped`.
- [ ] **Step 2-3:** Implement, tests pass.
- [ ] **Step 4:** Commit `tam: input template`, push.

### Task 13: TAM rows

**Files:**
- Create: `tam/tam_rows.py`, `tests/test_tam_rows.py`

**Interfaces:**
- Produces: `def build_tam_rows(entities: pd.DataFrame, definitions: list[TamDefinition], match_counts: dict[str, int]) -> pd.DataFrame` with columns `company, sales_unit, core_product, country, entity_id, name, detailed_segment, population, in_tam, in_tam_reason, matched_accounts`. Status order: excluded kind first, then (min_population set and population missing) unknown, then below cutoff, else yes. `in_tam_reason` e.g. `inwoners 7.512 < 10.000`, `uitgesloten soort: City district`. No `min_population` -> population missing still `yes`.
- [ ] **Step 1: Failing tests:** `test_status_order` (excluded + small -> `no - excluded kind`); `test_unknown_population_with_cutoff`; `test_no_cutoff_unknown_population_is_yes`; `test_only_selected_segments_and_country`.
- [ ] **Step 2-3:** Implement, tests pass. Commit `tam: TAM rows per definition`, push.

### Task 14: CRM scope, candidates, pass 1, overrides

**Files:**
- Create: `tam/matching.py`, `tests/test_matching.py`

**Interfaces:**
- Produces:
  - `def load_crm(path: Path) -> pd.DataFrame` (read with `dtype=str` so `cx_kvknummer` keeps leading zeros) and `def crm_in_scope(crm: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]` -> (in_scope, out_of_scope_gov):
    - `detected_country` in `CRM_COUNTRY_TO_TAM`; add `tam_country`.
    - Drop confidently commercial: `detected_type == 'commercieel_of_overig'` and `Segment (category) == 'Commercial'` and `segment_confidence == 'high'` (the literal step 1 emits; there is no `commercieel`).
    - Add `priority`: `gov` when `Segment (category)` in {Governmental, Unknown, Non-profit} or `detected_type` is a government type, else `other`.
    - `out_of_scope_gov`: accounts with `detected_country == 'OTHER'` and `Segment (category) == 'Governmental'`; they go to `CRM unmatched` with reason `land buiten scope`.
  - `TYPE_TO_KINDS: dict[str, set[str]]` in `matching.py`, detected_type -> compatible entity kinds: `gemeente_nl`->{nl_gemeente}; `stadsdeel`,`deelgemeente`->{nl_stadsdeel, be_district}; `provincie_nl`->{nl_provincie}; `waterschap`->{nl_waterschap}; `veiligheidsregio`->{nl_veiligheidsregio}; `omgevingsdienst`,`samenwerking`,`samenwerking_nl`,`belastingsamenwerking`,`ggd`,`stadsregio`->{nl_samenwerking}; `ministerie`,`rijksoverheid`->{nl_ministerie, nl_rijksorganisatie}; `land`->{nl_land_caribisch, nl_openbaar_lichaam}; `gemeente_be`,`ocmw`->{be_gemeente}; `agb`->{be_agb}; `politiezone`->{be_politiezone}; `hulpverleningszone`->{be_hulpverleningszone}; `intercommunale`->{be_samenwerking, be_intercommunale, be_welzijnsvereniging}; `provincie_be`->{be_provincie}; `fod_be`->{be_fod}; `gemeinde_de`->{de_gemeinde, de_kreisfreie_stadt, de_stadtstaat, de_bezirk, de_gemeindeverband}; `landkreis`,`landratsamt`->{de_landkreis}; `verbandsgemeinde`,`amt`,`verwaltungsgemeinschaft`->{de_gemeindeverband, de_gemeinde}; `zweckverband`->{de_zweckverband, de_it_zweckverband}. Types not in the dict (`onbekend`, `commercieel_of_overig`, `stadtwerke`, `caw`, ...) -> empty set.
  - `def normalize_company_number(value, country: str) -> str | None`: NL 8 digits (strip spaces, keep leading zeros); BE strip `BE`, dots, spaces, pad 9 -> 10 digits with leading 0; DE -> None.
  - `def crm_name_key(row) -> str`: `canonical_name` if filled else `name`, stripped of prefixes `gemeente, stad, stadt, landkreis, kreis, provincie, province, commune de, ville de, ocmw, cpas, samtgemeinde, verbandsgemeinde, amt, markt` (case-insensitive), then `normalize`.
  - `def build_name_index(entities, aliases) -> dict[tuple[str, str], list[tuple[str, str, str]]]`: `(country, normalize(match_name))` -> list of `(entity_id, kind, reason)`; entity names reason `same name`; alias rows reason from the alias row and `kind` = the target entity's kind.
  - `def pass1(crm_scope, entities, index) -> tuple[pd.DataFrame, pd.DataFrame]`: (matched, rest). Order:
    1. company number equal to an entity `official_ids` kvk/kbo -> `match_pass='rule'`, reason `KvK/KBO-nummer`.
    2. name-key hits filtered to `TYPE_TO_KINDS[detected_type]`; for types with an empty set, use the raw `normalize(name)` (no prefix stripping) against all kinds. Exactly one hit -> match, reason from index.
    3. Several hits and country DE: keep hits whose entity `postcode` equals the CRM postcode, else whose first 3 PLZ digits equal; exactly one left -> match, reason `naam + postcode`.
    4. Otherwise -> rest. Confidence `high` for 1-3.
  - `def candidates(row, entities_by_country, index, k=10) -> list[dict]`: always includes every exact name-key / alias hit (any kind), then top-k by `fuzz.token_set_ratio` on prefix-stripped normalized names (entity `match_name` + alias names); floor 75 for `priority == 'gov'`, 90 for `other`; DE candidates sorted by PLZ closeness after score; max 15. Each dict `{entity_id, name, kind, region, postcode, score, via}` where `via` is `naam` or the alias text (`alias: Bussum, predecessor, merged 2016`).
  - `def apply_overrides(matches: pd.DataFrame, overrides: pd.DataFrame, entity_ids: set[str]) -> tuple[pd.DataFrame, list[str]]`: override wins (`match_pass='override'`), empty `entity_id` = force no match; unknown `entity_id` -> warning, ignored.
  - Output frame columns everywhere: `entity_id, accountid, crm_name, match_pass, match_reason, confidence`.
- [ ] **Step 1: Failing tests:** `test_scope_excludes_other_and_confident_commercial` (uses `commercieel_of_overig`); `test_other_country_governmental_listed_out_of_scope`; `test_kind_filter_blocks_wrong_kind` (`Veiligheidsregio Zeeland` with canonical `Zeeland` does NOT match province Zeeland; `Politiezone Gent` does not match gemeente Gent; `Stadtwerke Bonn` does not match Bonn in pass 1); `test_de_same_name_resolved_by_postcode`; `test_cx_kvknummer_leading_zero_kept`; `test_caribbean_maps_to_nl`; `test_be_company_number_normalised` (`'BE 0123.456.789'` and `'123456789'` -> `'0123456789'`); `test_kvk_match_wins`; `test_alias_match_reason` (CRM `Gemeente Bussum` -> Gooise Meren with reason `predecessor, merged 2016`); `test_ocmw_account_matches_gemeente` (`OCMW Gent` -> `BE-NIS-44021`); `test_ambiguous_exact_name_not_matched_in_pass1`; `test_override_forces_no_match`.
- [ ] **Step 2-3:** Implement, tests pass. Commit `tam: CRM scope, candidates and rule-based matching`, push.

### Task 15: Pass 2 (AI matching) and match cache

**Files:**
- Modify: `tam/matching.py`; extend `tests/test_matching.py`

**Interfaces:**
- Produces: `def pass2(rest: pd.DataFrame, entities, aliases, client, tracker, *, use_ai: bool, cache_path: Path = REFERENCE_DIR / 'match_cache.csv', batch_size: int = 20) -> tuple[pd.DataFrame, pd.DataFrame, dict]` -> (matched, unmatched, stats). Unmatched frame columns: `accountid, crm_name, tam_country, best_candidate, best_score, reason` (`geen kandidaat boven drempel`, `AI: geen passende organisatie`, `AI overgeslagen (--no-ai)`, `kostenplafond bereikt`, `AI weigerde`).
  - Accounts without any candidate never go to AI. Batches are ordered `priority == 'gov'` first, so if the cap is reached it hits `other` accounts last.
  - Prompt per account: number, CRM name, `detected_type`, address/postcode/city, country; candidates as `id | name | kind | region | postcode | via`. System prompt states the matching rules: an OCMW/CPAS or a department belongs to its gemeente; a DE Ortsgemeinde account belongs to its Amt/Verband (given as alias candidates); a predecessor municipality belongs to its successor; commercial companies (Stadtwerke, GmbH, B.V., NV) are `none` unless they are the public body itself. Output Pydantic `list[{volgnummer:int, entity_id: str, reason: str, confidence: Literal['high','medium','low']}]`, `entity_id` = a supplied id or `none`. An id not in that account's candidate list -> treated as `none` and logged.
  - Cache CSV `accountid, name, candidate_hash, entity_id, reason, confidence, datum`; `candidate_hash` = sha1 of sorted candidate ids; reused only when name and hash equal; saved after every batch.
- [ ] **Step 1: Failing tests** (fake `call_parsed`): `test_no_candidate_no_ai_call`; `test_ai_choice_outside_candidates_rejected`; `test_cache_reused_when_name_and_candidates_same`; `test_cap_reached_leaves_rest_unmatched` (fake raises `CostCapReached` on 2nd batch; first batch matched, others unmatched with reason `kostenplafond bereikt`, cache file contains batch 1); `test_failed_batch_marked_and_next_batch_runs` (`AIBatchError` on batch 1 -> reason `AI-fout`); `test_gov_priority_batches_first`.
- [ ] **Step 2-3:** Implement, tests pass. Commit `tam: AI matching pass with cache`, push.

### Task 16: Output workbook and run log

**Files:**
- Create: `tam/output.py`, `tests/test_output.py`

**Interfaces:**
- Produces: `def write_output(path: Path, *, tam: pd.DataFrame, matches: pd.DataFrame, entities: pd.DataFrame, memberships: pd.DataFrame, unmatched: pd.DataFrame, run_log: list[tuple[str, str]]) -> list[Path]`: sheets in order `TAM`, `CRM matches`, `Entities`, `Memberships`, `CRM unmatched`, `Run log`; `official_ids` kept as text; header row frozen, autofilter on. `Memberships` gets only `membership_type == 'cooperation'` rows, with the cooperation's `detailed_segment` added as a column so Power BI can choose which cooperation kinds make members covered. Returns written paths.
  - `def check_known_detailed(values: set[str], path: Path = REFERENCE_DIR / 'known_detailed.json') -> set[str]`: returns values not seen in earlier runs, then stores the union.
  - `def build_run_log(**facts) -> list[tuple[str, str]]`: sections inputs/versions, per-source status, counts per country x kind, per definition counts per `in_tam` status, population-unknown counts, AI calls/cache hits/spend, product strays, new detailed values.
- [ ] **Step 1: Failing tests:** `test_sheet_order_and_names`; `test_only_cooperation_memberships_exported` (territorial and same_as rows absent); `test_new_detailed_value_reported`.
- [ ] **Step 2-3:** Implement, tests pass. Commit `tam: output workbook and run log`, push.

### Task 17: CLI

**Files:**
- Create: `tam_build.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes everything above.
- Produces CLI (spec section 9):
  - `--make-template [--update] [--products doc/Product_Categories_Business_Units_Core_Products_CRM2.xlsx] [--config tam_config.json] [--template tam_template.xlsx]`
  - `--template tam_template.xlsx [--crm step1b_segmented.xlsx] [--output tam_<YYYY-MM-DD>.xlsx] [--refresh-cache] [--offline] [--dry-run] [--no-ai] [--max-cost 50]`
  - Order of a run: read+validate template (stop on `TemplateError` before anything else), check `ANTHROPIC_API_KEY` unless `--no-ai`/`--dry-run`, `setup_file_logging('tam_build')`, `build_master`, classification rules + cache only, load CRM, scope, pass 1, overrides, candidates; THEN print the AI estimate for both remaining classification items and pass-2 accounts against the cap. `--dry-run` stops here (no AI call at all, no output file). Otherwise: AI classification, pass 2, TAM rows, write output, print summary (counts per definition and `in_tam` status, spend, matches by pass, unmatched count, failed sources, output path).
  - `classify_cooperations` therefore gets a `rules_only: bool` mode returning the rows still needing AI.
  - Missing `tam_config.json` -> clear error pointing at `tam_config.example.json`.
- [ ] **Step 1: Failing tests:** `test_make_template_end_to_end` (synthetic products xlsx + config in `tmp_path`, `main(['--make-template', ...])` creates the file with 3 x products rows); `test_template_error_exits_before_master` (monkeypatched `build_master` must not be called; exit code 2); `test_dry_run_writes_no_output` (fake master, fake CRM, `--no-ai --dry-run`).
- [ ] **Step 2-3:** Implement, tests pass. Full suite `venv/bin/pytest -q` green.
- [ ] **Step 4:** Commit `tam: tam_build.py CLI`, push.

### Task 18: Documentation

**Files:**
- Modify: `doc/MANUAL.md` (new section "TAM / whitespace-lijst"), regenerate `doc/MANUAL.pdf` with `venv/bin/python tools/md_to_pdf.py doc/MANUAL.md doc/MANUAL.pdf`, `CHECKPOINT.md` (feature status, new files, open points: OP dump licence, deferred list from spec 12), `doc/PROJECT_OVERVIEW.md` (one paragraph)

- [ ] **Step 1:** MANUAL section: what it does, prerequisites (fresh CRM export + steps 1/1b, `tam_config.json`, API key), `--make-template` then filling rules (segments `;`, excluded kinds, cut-off), `--dry-run`, real run, reading the output (sheets, `in_tam`, `match_pass`, CRM unmatched review, overrides), cost cap, yearly refresh with `--refresh-cache`, Power BI notes from spec 11 (factor, churn phase 2). Generic placeholders only, no em-dashes.
- [ ] **Step 2:** Render PDF; grep docs for company/product names (must be none) and for `—`.
- [ ] **Step 3:** Commit `docs: TAM manual section and checkpoint`, push.

### Task 19: First real run (gated on the user)

- [ ] **Step 1:** Fresh CRM export: already received (see Step 2).
- [ ] **Step 2:** The user delivered it on 2026-10-27: `input_crm_27-10-2026.csv` in the repo root (6,092 accounts; 29 new, 6 renamed vs `full_input.csv`). Run step 1 (`--input input_crm_27-10-2026.csv --output step1_classified.xlsx`) and step 1b (`--input step1_classified.xlsx --output step1b_segmented.xlsx`); step 1b bills only new or renamed accounts. Step 1b keeps its current model (deferred change).
- [ ] **Step 3:** `tam_build.py --make-template`; fill one smoke-test definition from the first case discussed with the user (that core product, NL, segments `Local government; Inter-municipal cooperation`, excluded kinds `City district; Waste management; Recreation authority; Environmental agency; Procurement cooperation; Social employment & work`, min 10,000) only as a smoke definition, and tell the user the business fills the rest.
- [ ] **Step 4:** `--dry-run`, report the estimate; then the real run with `--refresh-cache`.
- [ ] **Step 5:** Sanity checks reported to the user: NL TAM `yes` count (expected around 500 per the user), spend, number of CRM matches by pass, size of CRM unmatched, any failed source. Do not commit outputs.
