# CRM Account Enrichment - What We Built and Where We Stand

*Last updated: 10 June 2026*

## What is this project?

Our CRM contains about 6,000 accounts: municipalities, provinces, police zones,
hospitals, commercial companies and more, spread over the Netherlands, Belgium,
Germany and beyond. Two pieces of information were missing or unreliable for
most of them:

1. **What kind of organisation is this?** (the "Segment" of the account)
2. **How many inhabitants does it serve?** (for government bodies, the
   population number that drives our reach and territory reporting)

We built a set of small programs that fill in this information automatically,
so it no longer has to be maintained by hand.

## What we built

**1. Account recognition (finished earlier).** A program reads the account list
and recognises government organisations by their name: "Gemeente Amsterdam" is a
Dutch municipality, "Politiezone Antwerpen" is a Belgian police zone, and so on.
About 2,300 accounts are recognised this way with high certainty.

**2. Segmentation (FINISHED).** Every account now receives two new columns:
**Segment** (for example: Local government, Healthcare, Automotive, IT &
software) and **Segment (detailed)** (for example: Municipality, Hospital, Car
dealership). It works in two stages:

- Accounts already recognised in step 1 get their segment directly from a
  fixed translation table. Free and instant.
- The remaining ~3,700 accounts (mostly commercial companies) are read by
  **Claude, an AI model**. It looks at the name, country and address and picks
  a segment from a fixed list of 23 options, with a confidence score. For
  companies it cannot identify from the name alone, it can **search the web**
  (name plus address), the same way a person would Google them.

Every result is remembered. The next time we run the program, only new or
renamed accounts are processed, so yearly maintenance is fast and nearly free.
Manual corrections are possible and always win over the automatic result.

**3. Population numbers (largely working).** For government accounts, the
program looks up inhabitant counts from Wikidata, a free public database. Where
that database has gaps (water authorities, city districts, Belgian police
zones), we built smart workarounds, such as adding up the populations of the
municipalities each police zone covers. A few data sources are still being
finished.

## How we will populate it

1. ~~Test run on 100 accounts~~ - done, results reviewed and improved.
2. **Full run on all 6,004 accounts** - next step. Takes roughly one hour and
   produces an Excel file with the new columns.
3. **Review** - we check a sample, correct any mistakes via the corrections
   table, and re-run (re-runs only touch what changed).
4. **Load into the CRM** - the reviewed columns are imported into Dynamics 365.

## Costs

The AI classification uses Anthropic's paid service. We purchased **$50 of
credits**, which comfortably covers the first full run (estimated $15 to $25,
including web searches for the hard cases) and leaves room for re-runs and
corrections. After that, yearly refreshes only process new accounts and are
expected to cost a few dollars at most.

## What is next

- Run the full segmentation batch and review the results.
- Finish the last population data sources (water authorities, German
  municipality types).
- Agree on a fixed yearly moment to refresh both segments and population
  numbers.
