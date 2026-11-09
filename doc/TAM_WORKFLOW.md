# TAM workflow: who does what

Short version of the yearly TAM / whitespace cycle, as agreed on 2026-11-09.
Technical details: `doc/MANUAL.md` section 7.

## The file

`tam_template.xlsx` is the input. It is shared with the business and has these tabs:

| Tab | What it is for |
|---|---|
| `instructies` | Guide for the business (Dutch) |
| `tam_definitions` | One row per core product per country. The business fills in `segments`, `excluded_kinds`, `regions` (Belgium only) and `min_population` |
| `factors` | Price factor per kind of organisation (default row per kind; extra rows where a sales unit, product or country differs) |
| `match_overrides` | Manual corrections of CRM links |
| `lists` | Reference: all segments and kinds |

The tool never writes into the shared template. Changes to its layout are made
by hand in the shared file, so nothing the business typed gets lost.

## The cycle

1. **Template**: the shared template exists and the business works in it.
2. **Business fills in** the `tam_definitions` tab (which organisations belong
   to the market of each product per country).
3. **Upload**: when the business is done, the template is uploaded to the
   machine that runs the tool.
4. **Free check** (`tam_build.py --dry-run`): finds typos and unknown values
   (with row numbers), estimates the AI cost, and writes `factors_todo.xlsx`.
5. **Missing factors?** If `factors_todo.xlsx` lists kinds without a factor,
   pass it to the business. They fill in the `factors` tab of the shared
   template (the default row of each listed kind), and the template is
   uploaded again. Back to step 4. Only kinds inside a TAM need a factor; a
   missing factor counts as 0 in Power BI, never as 1.
6. **Real run** (`tam_build.py`, yearly with `--refresh-cache`): costs a few
   dollars of AI and writes `tam_<date>.xlsx`.
7. **Review together**: low-confidence CRM links (sheet `CRM matches`) and
   `CRM unmatched` filtered on Governmental / Unknown. Corrections go into the
   `match_overrides` tab, then run again.
8. **Power BI**: `tam_<date>.xlsx` goes to the BI side. Value per organisation
   = population x ARPU per inhabitant x `factor` (the factor is already in the
   TAM sheet).

## One-time changes to the shared template (2026-11-09)

- Column `regions` after `country_name` in `tam_definitions`, BE rows filled
  with `Vlaanderen; Brussel; Wallonie` (done).
- `lists` tab: row "Local government / Municipal social services (OCMW) / BE".
- `factors` tab copied in from the local template.
- `instructies` tab: rows for `regions` and for the `factors` tab.
