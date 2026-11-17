# TAM workflow: who does what

Short version of the yearly TAM / whitespace cycle, as agreed on 2026-11-09
(factors simplified on 2026-11-17).
Technical details: `doc/MANUAL.md` section 7.

## The file

`tam_template.xlsx` is the input. It is shared with the business and has these tabs:

| Tab | What it is for |
|---|---|
| `instructies` | Guide for the business (Dutch) |
| `tam_definitions` | One row per core product per country. The business fills in `segments`, `excluded_kinds`, `regions` (Belgium only) and `min_population` |
| `factors` | Fill-in list: one row per product x country x kind. Filter on your sales unit and fill in the yellow cells (the yellow ones are the kinds that are in your TAM) |
| `match_overrides` | Manual corrections of CRM links |
| `lists` | Reference: all segments and kinds |

The tool never writes into the shared template. Changes to its layout are made
by hand in the shared file, so nothing the business typed gets lost.

## The cycle

1. **Template**: the shared template exists and the business works in it.
2. **Business fills in** the `tam_definitions` tab (which organisations belong
   to the market of each product per country) and, in the same file, the
   yellow cells of the `factors` tab (filter on their sales unit).
3. **Upload**: the template is uploaded to the machine that runs the tool
   (any time, also when only partly filled in).
4. **Free check** (`tam_build.py --dry-run`): finds typos and unknown values
   (with row numbers and the value probably meant), estimates the AI cost and
   lists kinds inside a TAM that still have no factor.
5. **Real run** (`tam_build.py`, yearly with `--refresh-cache`): writes
   `tam_<date>.xlsx`. A missing factor counts as 0 in Power BI, never as 1.
6. **Review together**: low-confidence CRM links (sheet `CRM matches`) and
   `CRM unmatched` filtered on Governmental / Unknown. Corrections go into the
   `match_overrides` tab, then run again.
7. **Power BI**: `tam_<date>.xlsx` goes to the BI side. Value per organisation
   = population x ARPU per inhabitant x `factor` (already in the TAM sheet).

## Changing the layout of the shared template

The tool never writes into the shared template. Small layout changes (a
column, a row in `lists`, instruction text) are made by hand in the shared
file. A change that needs formulas (like the `factors` list) is done by a
one-time swap: upload the latest version, the tool rebuilds it with
`--make-template --update` (keeping every entry), and the shared file is
replaced right away while nobody is editing it.

## One-time changes to the shared template (2026-11-09)

- Column `regions` after `country_name` in `tam_definitions`, BE rows filled
  with `Vlaanderen; Brussel; Wallonie` (done).
- `lists` tab: row "Local government / Municipal social services (OCMW) / BE".
- `factors` tab copied in from the local template.
- `instructies` tab: rows for `regions` and for the `factors` tab.

## Swap of 2026-11-17

The shared template was replaced by `tam_template_nieuw.xlsx`, built from the
upload of 2026-11-17 with the new `factors` list (1,708 rows, existing factors
carried over) and the corrected typos in rows 70 and 71 (`Special-purpose
association`, `Police zone`).

