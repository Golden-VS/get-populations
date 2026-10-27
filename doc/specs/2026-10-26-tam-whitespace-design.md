# TAM / whitespace list: design

Status: draft for review, 2026-10-26.

## 1. Intent

The business wants to know, per core product and per country, how much revenue
it could still win. Power BI already holds recurring contract revenue (ARR) per
CRM account. What is missing is the denominator: a complete list of every
organisation that could buy a given core product (the Total Addressable Market,
TAM), with its represented population, and for each one the CRM account(s) it
corresponds to.

With that list Power BI can split the TAM into:

- **black space**: TAM organisations that already pay recurring revenue for the
  core product;
- **white space**: TAM organisations that do not, valued as
  `population x ARPU per inhabitant x factor per kind of organisation`.

This feature builds that list. It reuses this repo's conventions (pandas/Excel
in and out, cached reference data, timestamped logs, override sheets, Claude
API with structured outputs) but is a separate script; it does not change
steps 1, 1b or 2.

## 2. Goals, non-goals, anti-goals

**Goals**
- A complete, source-backed list of government organisations in NL, BE and DE
  (the "master list"), each with a stable id, kind, segment and represented
  population.
- Per TAM definition (core product x country) a row per in-scope organisation
  with an explicit `in_tam` status.
- Each relevant CRM account matched to the organisation it belongs to, with a
  reason and confidence, using AI where names do not match literally.
- One Excel output that Power BI loads directly.

**Non-goals (this version)**
- Non-governmental segments (healthcare, education, utilities, commercial).
- Computing black/white space, ARPU or euro values. That is Power BI's job.
- Changing step 1b labels or step 2 sources (deferred, see section 12).

**Anti-goals (would make this a failure even if it runs)**
- Organisations invented or dropped by an AI. The list comes from official
  registers; the AI never creates entities or member lists.
- Silently dropped organisations. Anything in a selected segment stays on the
  list with a status saying why it is or is not in the TAM.
- Guessed populations. No source means `population unknown`, flagged.
- A paying customer shown as white space because its contract sits on a
  duplicate, old or sub-organisation account.

## 3. Core concepts

### 3.1 What counts as a TAM entity (the user's rule)

> A TAM entity is an organisation with its own staff and offices that can hold
> its own licence.

Consequences:

| Case | Entities | Why |
|---|---|---|
| Province + municipality of the same name | 2 | separate organisations |
| DE kreisfreie Stadt (e.g. a city that is also a Kreis) | 1 | one administration does both |
| Berlin, Hamburg | 1 (Land) + their Bezirke | each Bezirksamt has own staff and citizen offices |
| Bremen | 1 (Land/Stadt Bremen) + Bremerhaven | Bremerhaven has its own administration |
| Shared service organisation + its members | separate | the cooperation has its own staff |
| Dissolved / merged municipality | 0 | only appears as a CRM alias of its successor |
| BE OCMW / CPAS | 0 | the municipality buys; OCMW accounts count toward their gemeente |
| DE Gemeinde inside an Amt / Verbandsgemeinde / Samtgemeinde / Verwaltungsgemeinschaft | 0 | administered by the Gemeindeverband; its accounts count toward that Verband |

"Counts toward" means: the CRM account is matched to the buying entity, with a
match reason saying why (predecessor, OCMW of, member of Verband). That keeps
revenue on such accounts in the black space.

Exception the builder must handle: DE Gemeinden that are members of a
Verwaltungsgemeinschaft but act as its "erfuellende Gemeinde" (Thueringen,
BW vereinbarte VG) DO have an administration; they are entities themselves and
their Verband is not a separate entity. Use the Destatis Verband type to tell.

### 3.2 Master list

One table of all TAM entities across NL, BE, DE, independent of products.
Columns:

| Column | Meaning |
|---|---|
| `entity_id` | stable id, `<CC>-<scheme>-<code>`, from an official code (see 4) |
| `name` | official name |
| `country` | NL / BE / DE |
| `segment` | one of the fixed segment list (existing step 1b vocabulary) |
| `detailed_segment` | one of the fixed detailed list (section 5) |
| `population` | represented population, integer or empty |
| `population_method` | `own`, `sum of members`, `unknown` |
| `population_source`, `population_date` | source name and reference date |
| `member_ids` | `entity_id`s of member organisations used for the sum (`;`-separated) |
| `official_ids` | e.g. KvK, KBO, OIN, ARS, TOOI (for audit and matching) |
| `source`, `source_date` | which register produced the row |

`entity_id` must be identical across yearly runs for the same organisation.

### 3.3 TAM definition (input template)

One row = one core product in one country. See section 7.

### 3.4 Represented population

- Own population where the register has it (municipalities, provinces,
  Laender via sum, etc.).
- Otherwise the sum of distinct member municipalities' populations. Only
  municipality-level members count toward the sum (a GR whose members include a
  province does not add the province's population).
- No members known -> population empty, `population_method = unknown`.
- No deduplication between levels: a province and its municipalities both carry
  their population. The per-kind ARPU factor in Power BI handles the difference
  (section 11).

## 4. Entity catalogue and sources

Researched 2026-10-26. URLs were verified to resolve on that date.

### 4.1 Netherlands

| Kind | ~Count | Segment -> detailed | Population | Source |
|---|---|---|---|---|
| Gemeente | 342 | Local government -> Municipality | own | CBS (existing step 2 loader) |
| Amsterdam stadsdeel | 8 | Local government -> City district | own | existing `NL_STADSDEEL_INWONERS` |
| Openbaar lichaam Bonaire/St. Eustatius/Saba | 3 | Local government -> Island authority | own | CBS / existing Caribbean data |
| Provincie | 12 | Regional government -> Province | own | existing loader |
| Waterschap | 21 | Regional government -> Water authority | own | existing `NL_WATERSCHAP_INWONERS` |
| Veiligheidsregio | 25 | Public safety & emergency -> Safety region | sum of members | OO register (members) |
| Gemeenschappelijke regeling (all forms) | ~438 active | Inter-municipal cooperation -> classified (section 5) | sum of members | OO register |
| Aruba / Curacao / Sint Maarten | 3 | National government -> Country government (Caribbean) | own | existing loader |
| Ministerie, agentschap, ZBO | 100+ | National government -> Ministry / National agency | country total | OO register |

**OO register** = Register van Overheidsorganisaties, nightly bulk XML
`https://organisaties.overheid.nl/archive/exportOO.xml` (CC-BY 4.0). Sections
`organisaties` and `gemeenschappelijkeRegelingen`. Active GR = no end date or end
date after run date (438 on 2026-10-26). Each GR lists `deelnemers` with TOOI
URIs (`tooi/id/gemeente/gm0363` = CBS code GM0363). The linked
`regionaalSamenwerkingsorgaan` record carries KvK, RSIN, OIN, TOOI `so####`.
81 active GRs have no linked body (regeling zonder meer / centrumgemeente):
these have no own staff and are NOT entities under 3.1, except where the
register links them to a body. GGD's and veiligheidsregio's appear as GRs; one
veiligheidsregio (VGGM) is named differently, so match by member set or TOOI.

`entity_id`: `NL-GM-<code>` gemeente, `NL-PV-<code>` provincie,
`NL-WS-<tooi>` waterschap, `NL-SO-<tooi so-code>` cooperation body,
`NL-GR-<systeemId>` only when no body code exists, `NL-OO-<systeemId>` other.

### 4.2 Belgium

| Kind | ~Count | Segment -> detailed | Population | Source |
|---|---|---|---|---|
| Gemeente / commune | 565 (post-2025 mergers) | Local government -> Municipality | own | Statbel if reachable, else existing Wikidata `be_gemeenten`; must reflect 2025 Flemish mergers |
| Provincie | 10 | Regional government -> Province | own | existing loader |
| Gewest / Gemeenschap | 5-6 | Regional government -> Region / Community | own | hand table with Statbel figures, source cited per row |
| AGB | ~160 FL | Local government -> Municipal autonomous agency | = its gemeente | OP dump (W/B RCA's not covered in v1, see below) |
| Politiezone / zone de police | ~176 | Public safety & emergency -> Police zone | sum of members | FL: OP dump; W/B: existing `BE_POLITIEZONE_GEMEENTEN` |
| Hulpverleningszone / zone de secours | ~34 | Public safety & emergency -> Emergency services zone | sum of members | FL: OP dump; W/B: hand table (14 Walloon zones + Brussels SIAMU/DBDMH), members from the civieleveiligheid.be zone PDF |
| Opdrachthoudende / dienstverlenende / projectvereniging | ~140 FL | Inter-municipal cooperation -> classified (section 5) | sum of members | OP dump |
| Welzijnsvereniging | ~58 FL | Inter-municipal cooperation -> Welfare association | sum of members | OP dump |
| Intercommunale (Wallonia, Brussels) | ~81 + ~9 | Inter-municipal cooperation -> classified | unknown | Wallonia: SPW cadastre xlsx (`https://interieur.wallonie.be/files/documents/institutionnel/cadastre-2026-interco-et-slsp.xlsx`, intercommunales only, not the housing companies); Brussels: hand table (~9) |
| FOD / POD | ~20 | National government -> Federal public service | country total | hand table |

Excluded entirely: OCMW / CPAS, verenigingen van OCMW's, worship bodies. Antwerp districts (in the OP dump) have their own staff and
offices and are included as City district.

**OP dump** = Agentschap Binnenland OrganisatiePortaal PublicCacheGraphDump,
daily N-Triples (~155 MB). Locate via
`GET https://organisaties.abb.vlaanderen.be/datasets?filter[subject]=http://data.lblod.info/datasets/delta-producer/dumps/PublicCacheGraphDump&sort=-release-date&include=distributions`,
then the distribution's file download. Members are `org:Membership` links;
identifiers: KBO on nearly all, OVO on most. Licence not stated in the dump
metadata: the builder records this in the run log and MANUAL as an open point.
Interlokale verenigingen are not in it (no legal personality, so not entities).

**No KBO open data in v1** (user decision 2026-10-27). KBO needs a registered
account and would add no members or populations; its only gains are
Walloon/Brussels régies communales autonomes (a few dozen, unlikely buyers,
missing in v1) and official enterprise numbers on W/B rows. Flemish rows get
their KBO number from the OP dump anyway. Possible later addition (legal-form
codes 413 politiezone, 414 intercommunale, 418 AGB/RCA, 422
hulpverleningszone).

`entity_id`: `BE-NIS-<code>` gemeente/provincie, `BE-KBO-<number>` where a KBO
number is known (OP dump), `BE-SPW-<slug>` for SPW-list intercommunales,
`BE-HAND-<slug>` for hand-table rows.

### 4.3 Germany

| Kind | ~Count | Segment -> detailed | Population | Source |
|---|---|---|---|---|
| Gemeinde (verbandsfrei or erfuellende Gemeinde) | ~3,400 | Local government -> Municipality | own | Destatis GV |
| Kreisfreie Stadt / Stadtkreis | 107 incl. Berlin, Hamburg | Local government -> County-level city (city-states Berlin, Hamburg, Bremen: Regional government -> State) | own | Destatis GV |
| Berlin / Hamburg Bezirk | 12 + 7 | Local government -> City district | own | hand table from Amt fuer Statistik Berlin-Brandenburg / Statistikamt Nord |
| Gemeindeverband (Amt, Samtgemeinde, Verbandsgemeinde, Verwaltungsgemeinschaft, Verwaltungsverband) | ~1,160 | Inter-municipal cooperation -> Municipal federation | sum of members | Destatis GV |
| Landkreis (incl. Kreis, Regionalverband Saarbruecken) | 294 | Regional government -> County | sum of members | Destatis GV |
| Regierungsbezirk | 19 | Regional government -> Administrative district | sum of members | Destatis GV (code 20; filter out non-authority rows, real count 19) |
| Hoeherer Kommunalverband (Bezirke Bayern, Landschaftsverbaende NRW, LWV Hessen, ...) | ~12 | Regional government -> Higher municipal association | sum of member Kreise | hand table, members cited |
| Bundesland | 16 | Regional government -> State | sum of members | Destatis GV |
| Kommunaler IT-Zweckverband / IT-Dienstleister | ~25 | Inter-municipal cooperation -> IT cooperation | sum of members where officially published, else unknown | hand table, members only from official sources |
| Other Zweckverband | ~2,500 | Inter-municipal cooperation -> Special-purpose association | unknown | Destatis FEU lists, rows with "Zweckverband" in the name |
| Bundesministerium | ~15 | National government -> Ministry | country total | hand table |

**Destatis GV** = Gemeindeverzeichnis quarterly extract
`https://www.destatis.de/DE/Themen/Laender-Regionen/Regionales/Gemeindeverzeichnis/Administrativ/Archiv/GVAuszugQ/AuszugGV<Q>QAktuell.xlsx?__blob=publicationFile`
(free reuse with attribution). Rows are typed by Satzart (10 Land, 20 RB,
40-45 Kreis kinds, 50 Gemeindeverband, 60-67 Gemeinde). Population is on
Gemeinde rows only; every higher level is a sum by ARS prefix. Code-50 rows
labelled "verbandsfreie Gemeinde" are placeholders, not entities.
Gemeindefreie Gebiete are not entities. The builder picks the newest quarter
available.

**Destatis FEU lists** (`liste-extrahaushalte-<year>-xlsx.xlsx`,
`liste-sonstige-FEU-<year>-xlsx.xlsx` under
`.../Fonds-Einrichtungen-Unternehmen/Methoden/Downloads/`): name, level, Land,
id. No members, no ARS.

`entity_id`: `DE-ARS-<ars>` for anything in GV, `DE-FEU-<id>` for Zweckverbaende,
`DE-HAND-<slug>` for hand-table rows.

### 4.4 Hand tables

Hand tables (BE Gewesten, FOD's, DE Bezirke, Hoehere Kommunalverbaende,
IT-Zweckverbaende, Bundesministerien) live in code like the existing
`NL_WATERSCHAP_INWONERS`, one row per entity with a source URL and date per
row. Never fill a population or member list without a cited official source;
leave it empty instead (population unknown).

## 5. Fixed detailed-segment list (TAM side)

The TAM output only uses values from this list. It is the join key for the
per-kind ARPU factor in Power BI, so values must not be renamed between runs.
New values may be added; the run log lists any value that is new since the
previous output.

- Local government: Municipality; County-level city; City district; Island
  authority; Municipal autonomous agency
- Regional government: State; Region / Community; Province; Administrative
  district; County; Higher municipal association; Water authority
- National government: Ministry; National agency; Federal public service;
  Country government (Caribbean)
- Public safety & emergency: Safety region; Police zone; Emergency services zone
- Inter-municipal cooperation: Municipal federation; Shared service
  organization; IT cooperation; Tax cooperation; Environmental agency; Public
  health service (GGD); Social employment & work; Waste management; Recreation
  authority; Procurement cooperation; Transport authority; Regional
  cooperation; Welfare association; Special-purpose association; Other joint
  arrangement

County-level city is separate from Municipality so a product can include or
exclude the 107 DE kreisfreie Staedte on their own and Power BI can give them
their own ARPU factor.

GGD's are Inter-municipal cooperation here (step 1b currently files them under
Healthcare; that is a CRM-side label and not used by this feature).

Where the kind is fixed by the source (all of 4.x except cooperations), the
detailed segment is set deterministically. Cooperations (NL GRs, FL
verenigingen, W/B intercommunales) are classified by Opus 5.5 into one of the
Inter-municipal cooperation values, from name + legal form + member count,
with a structured-output enum (same pattern as `step1b_segment.py`). Results are
cached by `entity_id` and only re-classified when the name changes.

## 6. CRM matching

**CRM input**: `step1b_segmented.xlsx` (default; `--crm` to override). It has
`accountid`, `name`, address/postcode, `detected_type`, `detected_country`,
`canonical_name`, `Segment`, `Segment (category)`.

**Scope**: every account whose `detected_country` is NL, BE, DE, a Caribbean
code (AW, CW, SX, BQ; matched against NL entities). Accounts with
`detected_country = OTHER` (foreign, ~145) are out of scope. EXCEPT accounts that are confidently commercial
(`detected_type = commercieel` and `Segment (category) = Commercial` and high
segment confidence). Non-profit and utility/IT-labelled accounts stay in scope,
because step 1b files many cooperations there. Cost stays low because pass 2
only receives accounts that have at least one candidate above a fuzzy-score
floor; accounts without any plausible candidate are left unmatched without an
AI call.

**Direction**: each CRM account gets at most one entity. An entity can have
many accounts.

**Candidates per account**: entities in the same country, ranked by fuzzy
name similarity (rapidfuzz, as in step 2) plus postcode proximity, plus alias
candidates:
- predecessors of merged municipalities (NL: `nl_gemeenten_historisch` plus
  successor relation; BE: 2025 merger list; DE: Destatis Gebietsaenderungen or
  Wikidata P1366). The builder picks the successor source per country; it must
  be official or Wikidata, never AI-generated.
- OCMW/CPAS -> its gemeente; DE member Gemeinde -> its Gemeindeverband.

**Pass 1 (no AI)**: exact match on official id if the CRM has it in
`cx_kvknummer` (checked 2026-10-27: ~1,090 NL accounts hold an 8-digit KvK,
~340 BE accounts a 10-digit enterprise number, normalise `BE`/dots/leading 0;
DE values are not usable ids), or exact normalised name + same kind + postcode agreement, or
a unique alias hit. Confidence `high`, reason states the rule.

**Pass 2 (Opus 5.5, `claude-opus-5-5`)**: remaining accounts in batches, each
with its top ~10 candidates. The model returns one candidate id or `none`,
a short reason (e.g. "predecessor municipality, merged 2016", "department of",
"duplicate account") and confidence high/medium/low. Structured output; the
model can only pick from the supplied candidate ids. Cached per `accountid`,
invalidated when the account name or the candidate set changes.

**Overrides**: sheet `match_overrides` in the template file:
`accountid, entity_id (empty = no match), reason`. Overrides win over both
passes and are reported in the run log.

## 7. Input template

File `tam_template.xlsx`, generated by `tam_build.py --make-template` from the
first tab of the product mapping workbook (`--products`, default the workbook
in `doc/`).

**Product rules**: keep rows whose `Company` is in a configured allow-list (the
three in-scope companies; the list lives in a small local config file that is
gitignored, so no company names enter the repo). Drop `Core Product Family`
values `_Other`, `Undefined`, and a configurable ignore list (currently one
non-product family). A core product appearing under several sales units is
assigned to the sales unit with the most product lines; the strays are listed
in the run log.

**Sheet `tam_definitions`**, pre-filled one row per core product x country
(NL, BE, DE):

| Column | Filled by | Meaning |
|---|---|---|
| `company`, `sales_unit`, `core_product`, `country` | app | key |
| `segments` | business | `;`-separated values from the fixed segment list |
| `excluded_kinds` | business | `;`-separated detailed segments to leave out |
| `min_population` | business | integer; empty = no cut-off |
| `notes` | business | free text, copied to output |

Rows with empty `segments` are skipped. Sheet `lists` holds the allowed values
and Excel data validation is applied where practical. Unknown values stop the
run with a message naming the row and value.

**Sheet `match_overrides`**: see section 6.

`--make-template` refuses to overwrite an existing template; with `--update`
it appends rows for new core products and leaves filled rows untouched.

## 8. Output

`tam_<YYYY-MM-DD>.xlsx`, sheets:

**`TAM`**: one row per (template row x entity in the selected segments).
Kept narrow so it stays well under Excel's row limit: `company, sales_unit,
core_product, country, entity_id, name, detailed_segment, population, in_tam,
in_tam_reason, matched_accounts (count)`. Other entity attributes live in
`Entities` (join on `entity_id`). If the TAM sheet would exceed 1,000,000 rows
the app also writes it as `tam_<date>_TAM.csv` and says so in the run log.

`in_tam` values:
- `yes`
- `no - below cutoff`
- `no - excluded kind`
- `unknown - population missing` (cut-off set but no population)

**`CRM matches`**: one row per matched account: `entity_id, accountid,
crm_name, match_pass (rule/ai/override), match_reason, confidence`. Product
independent; Power BI joins ARR -> accountid -> entity_id -> TAM.

**`Entities`**: the full master list (section 3.2), for audit and for Power BI
if it prefers a separate dimension.

**`Memberships`**: long format, one row per (cooperation `entity_id`, member
`entity_id`), with `member_kind` and `join_date` where the register has it.
Decided by the user: when a cooperation holds the licence, its member
organisations count as covered (black space). Power BI uses this sheet to
mark members of a paying cooperation as covered. Direct memberships only; the
app does not chain cooperations of cooperations.

**`CRM unmatched`**: governmental/unknown CRM accounts in NL/BE/DE without an
entity, with the best candidate and why it was rejected. Purpose: spot paying
customers missing from the TAM.

**`Run log`**: inputs and versions, per-source status and dates, counts per
country x kind, per template row counts per `in_tam` status, population-unknown
counts, AI calls and cached hits, product strays, new detailed-segment values.

Output, caches and logs are gitignored (`*.xlsx`, `*.csv`, `logs/`).

## 9. Running

```
python tam_build.py --make-template [--products ...]
python tam_build.py --template tam_template.xlsx [--crm step1b_segmented.xlsx]
                    [--refresh-cache] [--offline] [--dry-run] [--no-ai]
```

- **Before the first real run** (and each yearly run): ask the user for a fresh
  CRM account export (`full_input.csv`; accounts were added in 2026), then
  re-run step 1 and step 1b so `step1b_segmented.xlsx` covers the new accounts
  (step 1b only bills the new/renamed accounts thanks to its cache).
- Runs at most once a year. Register downloads cached under `reference/`;
  `--refresh-cache` forces fresh downloads (the yearly run should use it).
- `--dry-run`: build master list and pass-1 matches, print how many items would
  go to the AI, no API calls.
- `--no-ai`: skip pass 2 and AI classification; affected rows get
  `Other joint arrangement` / unmatched, flagged.
- Per-source try/except with a status-per-source report, like step 2. A failed
  source does not abort the run but is loud in the run log.
- Timestamped log in `logs/` via the existing logging helper.
- **Cost cap**: before any AI call the app estimates the run's cost from
  item counts and token sizes (Opus 5.5: $4 / $20 per million input / output
  tokens) and prints it. It tracks actual spend from `response.usage` during
  the run and stops cleanly (caches saved, resumable) before passing the cap.
  Default cap $50 per run (user decision), `--max-cost` to change it.
- `ANTHROPIC_API_KEY` required unless `--no-ai`. AI caches (classification,
  matches) are CSVs keyed as described, saved per batch so interrupted runs
  resume.

## 10. Constraints

- Python 3.10+, existing venv deps (`pandas openpyxl anthropic requests
  rapidfuzz`); an N-Triples parser may be added (e.g. `rdflib`) or a streaming
  line parser written, builder's choice.
- Model: `claude-opus-5-5`.
- Privacy: no company, product or customer names in tracked files, commits or
  docs. Examples use placeholders.
- Code comments mostly Dutch (repo convention); no em-dashes in user-facing
  text.
- New register loaders are written as reusable functions so step 2 can adopt
  them later (CHECKPOINT open item 5).

## 11. For the business (outside this project)

- White space value in Power BI = `population x municipal ARPU per inhabitant x
  factor per detailed segment` (e.g. a province pays ~10% of the municipal rate
  per inhabitant). The business defines and maintains the factor table in
  Power BI, keyed on `detailed_segment`.
- Rows with `in_tam = unknown - population missing` have no euro value; Power
  BI decides how to show them.
- Black space uses recurring revenue only (`Billing Type = Recurring`), applied
  in Power BI.
- **Phase 2, winnable per year** (from the user's meeting, 2026-10-27): the
  share of white space that can realistically be won per year is estimated
  with the average churn rate from Power BI. Assumption: competitors' churn
  equals ours, so with 10% churn (a customer stays ~10 years) about 10% of the
  white space comes up for grabs each year:
  `winnable per year = white space value x churn rate`. Known simplification:
  it ignores that the winnable share shrinks as market share grows. Computed
  in Power BI; the app needs nothing extra for it. Suggestion for the
  business: use the churn rate of the same core product (and country if
  available), since churn differs per product.

## 12. Deferred

- Step 2 upgrade to the official registers (CHECKPOINT open item 5).
- KBO open data for Walloon/Brussels régies and official W/B ids.
- Step 1b: move to Opus 5.5 and to the fixed detailed-segment list.
- Non-governmental segments.
- Members (and so population) for Walloon/Brussels intercommunales and
  non-IT Zweckverbaende.

## 13. Left to the builder

- Parsing details of each register, quarter selection, cache layout.
- Exact fuzzy thresholds and candidate count for pass 2, batch size.
- Prompt wording for classification and matching.
- Whether `Entities` and `TAM` share code paths with step 2's reference
  loaders now or later, as long as the loaders are reusable.
