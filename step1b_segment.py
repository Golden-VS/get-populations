"""
step1b_segment.py
==================
Voegt twee kolommen toe aan de step1-output: "Segment" en "Segment (detailed)".

Segment       = hoog niveau accounttype (Local government, Healthcare, Automotive, ...)
Segment       (detailed) = verfijning binnen het segment (Municipality, Hospital, ...)

TWEE LAGEN:
1. Deterministisch: detected_type uit step1 wordt 1-op-1 gemapt naar een
   (segment, detailed) paar via TYPE_TO_SEGMENT. Gratis, geen API nodig.
   Dekt alle overheids-typen (~2.3k records).
2. Claude API: records met detected_type 'onbekend', 'commercieel_of_overig'
   of 'gemeente_unclear' (~3.7k records) worden in batches van 25 naar de
   Claude API gestuurd (naam + land + adres) en geclassificeerd binnen een
   vaste segmentenlijst. Resultaten worden gecachet in segment_cache.csv
   zodat een herrun alleen nieuwe/gewijzigde accounts classificeert.

GEBRUIK:
    # API-key instellen (eenmalig per shell)
    #   Windows PowerShell:  $env:ANTHROPIC_API_KEY = "sk-ant-..."
    #   Linux/macOS:         export ANTHROPIC_API_KEY="sk-ant-..."

    # Test eerst op 100 records
    python step1b_segment.py --input step1_classified.xlsx \\
        --output step1b_segmented.xlsx --test-mode

    # Volledige run (gebruikt cache, classificeert alleen wat nog ontbreekt)
    python step1b_segment.py --input step1_classified.xlsx \\
        --output step1b_segmented.xlsx

    # Met websearch-ronde: zwakke classificaties (Unknown / Commercial (other) /
    # confidence low) gaan in een tweede pass met de web_search tool, zodat
    # Claude de organisatie echt kan opzoeken (naam + adres)
    python step1b_segment.py --input step1_classified.xlsx \\
        --output step1b_segmented.xlsx --web-search

    # Offline: alleen mapping + cache, geen API-calls
    python step1b_segment.py --input step1_classified.xlsx \\
        --output step1b_segmented.xlsx --offline

    # Cache negeren en alles opnieuw classificeren
    python step1b_segment.py --input step1_classified.xlsx \\
        --output step1b_segmented.xlsx --refresh-segments

    # Met override-tabel (kolommen: accountid, segment_override,
    # segment_detailed_override, reden)
    python step1b_segment.py --input ... --output ... --overrides overrides_segment.xlsx

DEPENDENCIES:
    pip install pandas openpyxl anthropic

UITVOER-KOLOMMEN (toegevoegd):
    - Segment:             hoofdsegment uit de vaste lijst
    - Segment (detailed):  verfijning (vast voor overheid, kort vrij label
                           voor commercieel)
    - segment_confidence:  high/medium/low
    - segment_bron:        'mapping detected_type', 'Claude <model>', 'cache',
                           'override-tabel' of leeg
    - segment_invuldatum:  datum van classificatie
"""

import argparse
import logging
import os
import time
from datetime import date
from pathlib import Path
from typing import List, Literal

import pandas as pd

# ============================================================================
# CONFIG
# ============================================================================

SEGMENT_CACHE = Path('segment_cache.csv')
DEFAULT_MODEL = 'claude-opus-4-7'
BATCH_SIZE = 25
RUN_DATE = date.today().isoformat()

# Records met deze markers zijn door CRM-gebruikers gemarkeerd als obsolete.
SKIP_NAME_MARKERS = ['niet gebruiken', 'do not use', 'obsolete', 'deprecated']

# detected_type-waarden die naar de Claude-laag gaan i.p.v. de mapping
CLAUDE_TYPES = {'onbekend', 'commercieel_of_overig', 'gemeente_unclear'}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('segment')


# ============================================================================
# SEGMENTEN-TAXONOMIE
# ============================================================================
# Hoofdsegmenten. Overheid op bestuursniveau (eigen indeling, want NACE/SBI
# gooit alle overheid op een hoop), commercieel geinspireerd op NACE-secties.

SEGMENTS = [
    # Overheid
    'Local government',
    'Regional government',
    'National government',
    'Inter-municipal cooperation',
    'Public safety & emergency',
    # Industrie / commercieel (NACE-achtig)
    'Agriculture & food',
    'Automotive',
    'Construction & real estate',
    'Consulting & professional services',
    'Education & research',
    'Energy & utilities',
    'Financial services & insurance',
    'Healthcare & social care',
    'Hospitality, travel & leisure',
    'IT & software',
    'Logistics & transport',
    'Manufacturing & industry',
    'Media & marketing',
    'Non-profit & associations',
    'Retail & wholesale',
    'Telecom',
    # Vangnetten
    'Commercial (other)',   # zeker commercieel, branche onbekend of past niet in de lijst
    'Unknown',              # helemaal niets vast te stellen
]

# Laag 1: deterministische mapping van detected_type -> (Segment, detailed).
# Sleutels zijn de werkelijke waarden uit step1_classified.xlsx.
TYPE_TO_SEGMENT = {
    'gemeente_nl':             ('Local government',            'Municipality'),
    'gemeente_be':             ('Local government',            'Municipality'),
    'gemeinde_de':             ('Local government',            'Municipality'),
    'stadsdeel':               ('Local government',            'City district'),
    'deelgemeente':            ('Local government',            'City district'),
    'ocmw':                    ('Local government',            'Municipal social services (OCMW)'),
    'agb':                     ('Local government',            'Municipal autonomous agency (AGB)'),
    'provincie_nl':            ('Regional government',         'Province'),
    'provincie_be':            ('Regional government',         'Province'),
    'landkreis':               ('Regional government',         'County (Landkreis)'),
    'landratsamt':             ('Regional government',         'County (Landkreis)'),
    'waterschap':              ('Regional government',         'Water authority'),
    'ministerie':              ('National government',         'Ministry'),
    'rijksoverheid':           ('National government',         'National agency'),
    'veiligheidsregio':        ('Public safety & emergency',   'Safety region'),
    'politiezone':             ('Public safety & emergency',   'Police zone'),
    'samenwerking':            ('Inter-municipal cooperation', 'Municipal partnership'),
    'samenwerking_nl':         ('Inter-municipal cooperation', 'Municipal partnership'),
    'belastingsamenwerking':   ('Inter-municipal cooperation', 'Tax partnership'),
    'omgevingsdienst':         ('Inter-municipal cooperation', 'Environmental agency'),
    'intercommunale':          ('Inter-municipal cooperation', 'Intermunicipal company'),
    'zweckverband':            ('Inter-municipal cooperation', 'Special-purpose association'),
    'verbandsgemeinde':        ('Inter-municipal cooperation', 'Municipal federation'),
    'amt':                     ('Inter-municipal cooperation', 'Municipal federation'),
    'verwaltungsgemeinschaft': ('Inter-municipal cooperation', 'Municipal federation'),
    'stadtwerke':              ('Energy & utilities',          'Municipal utility (Stadtwerke)'),
    'caw':                     ('Healthcare & social care',    'Welfare organization'),
    # Types die step1_classify.py KAN produceren maar die niet in de huidige
    # dataset voorkwamen. Toegevoegd zodat een toekomstige export ze direct
    # een segment geeft i.p.v. "niet in TYPE_TO_SEGMENT".
    'ggd':                     ('Healthcare & social care',    'Public health service (GGD)'),
    'stadsregio':              ('Inter-municipal cooperation', 'Urban region (stadsregio)'),
    'hulpverleningszone':      ('Public safety & emergency',   'Emergency services zone'),
    'fod_be':                  ('National government',         'Federal public service (FOD)'),
    'land':                    ('National government',         'Country government (Caribbean)'),
}


# ============================================================================
# CLAUDE API (laag 2)
# ============================================================================

SYSTEM_PROMPT = f"""Je bent een CRM-data-analist. Je classificeert zakelijke accounts
(bedrijven en organisaties) in een vast segmentenschema op basis van naam, land en adres.

De accounts komen uit een CRM met klanten in vooral Nederland, Belgie en Duitsland,
maar er zitten ook accounts uit andere landen tussen. Namen kunnen Nederlands, Frans,
Duits of Engels zijn.

KIES VOOR ELK ACCOUNT:
1. "segment": exact een waarde uit deze lijst:
{chr(10).join('   - ' + s for s in SEGMENTS)}

2. "segment_detailed": een korte verfijning (1-4 woorden, Engels, Title Case).
   Gebruik waar mogelijk een van deze gangbare labels, of een vergelijkbaar label:
   - Local government: Municipality, City district, Municipal social services (OCMW)
   - Regional government: Province, County (Landkreis), Water authority
   - National government: Ministry, National agency
   - Healthcare & social care: Hospital, Elderly care, Mental health (GGZ), Childcare,
     Public health service (GGD), Welfare organization, Disabled care, Home care
   - Education & research: University, Vocational school (ROC/MBO), Primary education,
     Secondary education, Research institute, School board
   - IT & software: Software vendor, IT services, Hosting & cloud, Cybersecurity
   - Automotive: Car dealership, Garage & repair, Leasing, Parts supplier
   - Consulting & professional services: Management consulting, Engineering, Legal,
     Accounting, HR & recruitment, Architecture
   - Energy & utilities: Energy supplier, Grid operator, Water company, Waste management
   - Financial services & insurance: Bank, Insurer, Pension fund, Payments
   - Logistics & transport: Freight & haulage, Public transport, Postal & parcel,
     Warehousing
   - Manufacturing & industry: Food processing, Machinery, Chemicals, Metal, Printing
   - Retail & wholesale: Supermarket, Specialty retail, Wholesale, E-commerce
   - Non-profit & associations: Trade association, Charity, Religious organization,
     Housing corporation, Sports club
   - Hospitality, travel & leisure: Hotel, Restaurant & catering, Travel agency,
     Recreation
   - Media & marketing: Marketing agency, Publisher, Broadcasting
   - Construction & real estate: Contractor, Real estate agency, Property management,
     Installation (HVAC/electro)
   - Agriculture & food: Farming, Horticulture, Food trade

3. "confidence": high / medium / low.
   - high   = naam maakt het type vrijwel zeker
   - medium = goede aanwijzing maar niet eenduidig
   - low    = gok op basis van zwakke signalen

REGELS:
- De NAAM is leidend. Land en adres zijn context.
- Als de naam een overheidsorganisatie suggereert (gemeente, Stadt, commune, ministry,
  politie, fire department, ...), kies dan het juiste overheidssegment, ook al staat
  het account tussen commerciele records.
- Woningcorporaties (woningstichting, wonen, wooncorporatie) -> Non-profit & associations
  / Housing corporation.
- Zorginstellingen (zorggroep, verpleeghuis, thuiszorg, GGZ, ziekenhuis) ->
  Healthcare & social care.
- Elke account heeft een "voorlopige typering" uit een eerdere regelgebaseerde stap:
  * "commercieel": vrijwel zeker een commercieel bedrijf, alleen de branche is nog
    onbekend. Kies dan NOOIT "Unknown". Als de branche niet te bepalen is, kies
    "Commercial (other)" met segment_detailed "Commercial (unspecified)".
  * "mogelijk gemeente": kan een gemeente zijn; weeg dat mee.
  * "onbekend": geen voorinformatie.
- Het veld "businesstype" is een onbetrouwbaar CRM-veld. Maar als de naam niets
  prijsgeeft, mag je het gebruiken om een segment te kiezen (confidence dan
  maximaal medium).
- Alleen als naam, adres en businesstype samen niets opleveren EN de voorlopige
  typering "onbekend" is: segment "Unknown", segment_detailed "Unknown",
  confidence low.
- Geef voor ELK account in de invoer precies een classificatie terug, met het
  juiste volgnummer."""

# Extra instructie voor de websearch-ronde (zwakke classificaties, tweede pass)
SEARCH_INSTRUCTIONS = """
EXTRA - WEBSEARCH-RONDE: voor deze accounts leverde naam + adres alleen geen
duidelijke classificatie op. Je hebt nu een web_search tool. Gebruik per account
maximaal 2 gerichte zoekopdrachten (bijvoorbeeld bedrijfsnaam + plaats, of
bedrijfsnaam + adres zoals "CDI Hurst House") om te achterhalen wat de
organisatie doet. Baseer je classificatie op wat je vindt. Vind je niets
bruikbaars, val dan terug op de standaardregels hierboven."""


# Vertaling van detected_type naar de "voorlopige typering" in het prompt
DTYPE_TO_HINT = {
    'commercieel_of_overig': 'commercieel',
    'gemeente_unclear':      'mogelijk gemeente',
    'onbekend':              'onbekend',
}


def build_user_message(batch_records):
    """Bouwt de genummerde accountlijst voor een batch."""
    lines = []
    for i, rec in enumerate(batch_records, start=1):
        parts = [f"{i}. naam: {rec['name']}"]
        if rec.get('country'):
            parts.append(f"land: {rec['country']}")
        if rec.get('city'):
            parts.append(f"plaats: {rec['city']}")
        if rec.get('address'):
            parts.append(f"adres: {rec['address']}")
        if rec.get('businesstype'):
            parts.append(f"businesstype (onbetrouwbaar): {rec['businesstype']}")
        hint = DTYPE_TO_HINT.get(rec.get('dtype', ''), 'onbekend')
        parts.append(f"voorlopige typering: {hint}")
        lines.append(' | '.join(parts))
    return 'Classificeer deze accounts:\n\n' + '\n'.join(lines)


def make_models():
    """
    Pydantic-modellen voor structured outputs. In een functie zodat het
    importeren van dit script niet hard faalt als anthropic/pydantic ontbreken
    (bv. bij --offline runs op een machine zonder de SDK).
    """
    from pydantic import BaseModel

    SegmentLiteral = Literal[tuple(SEGMENTS)]  # type: ignore[valid-type]

    class AccountSegment(BaseModel):
        volgnummer: int
        segment: SegmentLiteral
        segment_detailed: str
        confidence: Literal['high', 'medium', 'low']

    class SegmentBatch(BaseModel):
        classifications: List[AccountSegment]

    return SegmentBatch


def classify_batch(client, model, batch_records, segment_batch_model,
                   web_search=False):
    """
    Stuurt een batch accounts naar de Claude API en geeft een lijst dicts
    terug (volgnummer -> classificatie). Met web_search=True krijgt Claude
    de server-side websearch-tool en extra zoekinstructies (gebruikt voor
    de tweede ronde met zwakke classificaties). Gooit exception bij
    API-fouten; de aanroeper vangt die per batch af.
    """
    system_text = SYSTEM_PROMPT + (SEARCH_INSTRUCTIONS if web_search else '')
    kwargs = {}
    if web_search:
        # max_uses begrenst het aantal zoekopdrachten per request
        # (~2 per account bij kleine batches).
        kwargs['tools'] = [{
            'type': 'web_search_20260209',
            'name': 'web_search',
            'max_uses': 2 * len(batch_records),
        }]

    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        thinking={'type': 'adaptive'},
        system=[{
            'type': 'text',
            'text': system_text,
            # Prompt caching: systemprompt is identiek voor alle batches
            # (binnen dezelfde ronde).
            'cache_control': {'type': 'ephemeral'},
        }],
        messages=[{'role': 'user', 'content': build_user_message(batch_records)}],
        output_format=segment_batch_model,
        **kwargs,
    )
    parsed = response.parsed_output

    by_volgnummer = {c.volgnummer: c for c in parsed.classifications}
    expected = set(range(1, len(batch_records) + 1))
    missing = expected - set(by_volgnummer)
    if missing:
        raise ValueError(f'Claude-antwoord mist volgnummers: {sorted(missing)}')

    results = []
    for i in range(1, len(batch_records) + 1):
        c = by_volgnummer[i]
        results.append({
            'segment': c.segment,
            'segment_detailed': c.segment_detailed.strip(),
            'confidence': c.confidence,
        })
    return results


# ============================================================================
# CACHE
# ============================================================================
# segment_cache.csv: accountid,name,segment,segment_detailed,confidence,bron,invuldatum
# Sleutel = accountid. Als de naam in het CRM wijzigt, wordt het record
# opnieuw geclassificeerd (naamswijziging kan ander type betekenen).

def load_cache(path=SEGMENT_CACHE):
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str).fillna('')
    return {
        r['accountid']: {
            'name': r['name'],
            'segment': r['segment'],
            'segment_detailed': r['segment_detailed'],
            'confidence': r['confidence'],
            'bron': r['bron'],
            'invuldatum': r['invuldatum'],
        }
        for _, r in df.iterrows()
    }


def save_cache(cache, path=SEGMENT_CACHE):
    rows = [{'accountid': k, **v} for k, v in cache.items()]
    pd.DataFrame(rows).to_csv(path, index=False)


# ============================================================================
# OVERRIDES
# ============================================================================

def load_overrides(path):
    """Override-tabel: accountid, segment_override, segment_detailed_override, reden."""
    if not path or not Path(path).exists():
        return {}
    df = pd.read_excel(path) if str(path).endswith('.xlsx') else pd.read_csv(path)
    df.columns = [c.lower().strip() for c in df.columns]
    if 'accountid' not in df.columns or 'segment_override' not in df.columns:
        log.warning(f'Override-bestand {path}: verwachte kolommen ontbreken. Overslaan.')
        return {}
    out = {}
    for _, r in df.iterrows():
        out[str(r['accountid'])] = {
            'segment': r['segment_override'] if pd.notna(r['segment_override']) else None,
            'segment_detailed': r.get('segment_detailed_override', '') if pd.notna(r.get('segment_detailed_override', '')) else '',
            'reden': r.get('reden', '') if pd.notna(r.get('reden', '')) else '',
        }
    log.info(f'Overrides geladen: {len(out)} records')
    return out


# ============================================================================
# HELPERS
# ============================================================================

def name_is_marked_obsolete(name):
    if not isinstance(name, str):
        return False
    low = name.lower()
    return any(m in low for m in SKIP_NAME_MARKERS)


def clean(s, max_len=120):
    """Veldwaarde plat en kort maken voor het prompt."""
    if not isinstance(s, str):
        return ''
    return ' '.join(s.split())[:max_len]


# ============================================================================
# MAIN
# ============================================================================

def parse_args():
    p = argparse.ArgumentParser(description='Voegt Segment-kolommen toe aan step1-output.')
    p.add_argument('--input',            required=True, help='step1_classified.xlsx')
    p.add_argument('--output',           required=True, help='uitvoer-Excel pad')
    p.add_argument('--overrides',        default=None, help='Optioneel: override-Excel/CSV')
    p.add_argument('--test-mode',        action='store_true', help='Alleen eerste 100 records')
    p.add_argument('--offline',          action='store_true', help='Alleen mapping + cache, geen API')
    p.add_argument('--refresh-segments', action='store_true', help='Cache negeren, alles opnieuw')
    p.add_argument('--model',            default=DEFAULT_MODEL, help=f'Claude-model (default {DEFAULT_MODEL})')
    p.add_argument('--batch-size',       type=int, default=BATCH_SIZE, help=f'Accounts per API-call (default {BATCH_SIZE})')
    p.add_argument('--web-search',       action='store_true',
                   help='Tweede ronde met websearch voor zwakke classificaties '
                        '(Unknown / Commercial (other) / confidence low). '
                        'Kost ~$10 per 1000 zoekopdrachten extra.')
    return p.parse_args()


def main():
    args = parse_args()

    log.info(f'Input: {args.input}')
    df = pd.read_excel(args.input)
    log.info(f'Ingelezen: {len(df)} records')

    if args.test_mode:
        df = df.head(100)
        log.info(f'Test-modus: ingekort tot {len(df)} records')

    cache = {} if args.refresh_segments else load_cache()
    log.info(f'Cache: {len(cache)} eerder geclassificeerde accounts')
    overrides = load_overrides(args.overrides) if args.overrides else {}

    # Resultaatkolommen
    n = len(df)
    col_segment = [''] * n
    col_detailed = [''] * n
    col_confidence = [''] * n
    col_bron = [''] * n
    col_datum = [''] * n

    # ------------------------------------------------------------------
    # Laag 1: deterministische mapping + verzamelen van Claude-werk
    # ------------------------------------------------------------------
    claude_queue = []     # list van (row_idx, record_dict) - nog te classificeren
    layer2_records = {}   # row_idx -> record_dict (alle laag-2 records, ook cached;
                          # nodig om zwakke resultaten in de websearch-ronde opnieuw
                          # aan te bieden)
    n_mapped = n_skipped = n_cached = 0

    for idx, row in enumerate(df.itertuples(index=False)):
        rec = row._asdict() if hasattr(row, '_asdict') else dict(zip(df.columns, row))
        accountid = str(rec.get('accountid') or '')
        name = rec.get('name') or ''
        dtype = rec.get('detected_type') or ''

        if name_is_marked_obsolete(name):
            col_bron[idx] = 'niet-gebruiken-marker, overgeslagen'
            n_skipped += 1
            continue

        if dtype in TYPE_TO_SEGMENT:
            seg, det = TYPE_TO_SEGMENT[dtype]
            col_segment[idx] = seg
            col_detailed[idx] = det
            col_confidence[idx] = 'high'
            col_bron[idx] = f'mapping detected_type ({dtype})'
            col_datum[idx] = RUN_DATE
            n_mapped += 1
            continue

        if dtype in CLAUDE_TYPES or dtype == '':
            record = {
                'accountid': accountid,
                'name': clean(name),
                'country': clean(rec.get('detected_country') or rec.get('cx_address1_country') or '', 40),
                'city': clean(rec.get('cx_address3_city') or '', 60),
                'address': clean(rec.get('address1_composite') or '', 120),
                'businesstype': clean(rec.get('cx_businesstype') or '', 60),
                'dtype': dtype,
            }
            layer2_records[idx] = record
            # Cache vergelijkt op de geschoonde naam (zelfde vorm als opgeslagen)
            cached = cache.get(accountid)
            if cached and cached['name'] == clean(name):
                col_segment[idx] = cached['segment']
                col_detailed[idx] = cached['segment_detailed']
                col_confidence[idx] = cached['confidence']
                col_bron[idx] = f"cache ({cached['bron']})"
                col_datum[idx] = cached['invuldatum']
                n_cached += 1
                continue
            claude_queue.append((idx, record))
        else:
            # Onbekend detected_type dat niet in de mapping staat: signaleren
            col_bron[idx] = f'detected_type "{dtype}" niet in TYPE_TO_SEGMENT'

    log.info(f'Laag 1 klaar: {n_mapped} gemapt, {n_cached} uit cache, '
             f'{n_skipped} overgeslagen (marker), {len(claude_queue)} voor Claude')

    # ------------------------------------------------------------------
    # Laag 2: Claude API in batches (ronde 1 zonder, ronde 2 met websearch)
    # ------------------------------------------------------------------
    def run_batches(queue, batch_size, web_search, label):
        """Draait classify_batch over een queue en werkt kolommen + cache bij."""
        bron_label = f'Claude {args.model}' + (' + websearch' if web_search else '')
        batches = [queue[i:i + batch_size] for i in range(0, len(queue), batch_size)]
        log.info(f'{label}: {len(queue)} records in {len(batches)} batches '
                 f'van max {batch_size} (model {args.model})')
        n_classified = n_failed = 0
        for b_i, batch in enumerate(batches, start=1):
            records = [r for _, r in batch]
            start = time.time()
            try:
                results = classify_batch(client, args.model, records,
                                          segment_batch_model, web_search=web_search)
            except Exception as e:
                log.warning(f'  batch {b_i}/{len(batches)} GEFAALD: {e}')
                n_failed += len(batch)
                continue
            for (idx, rec), res in zip(batch, results):
                col_segment[idx] = res['segment']
                col_detailed[idx] = res['segment_detailed']
                col_confidence[idx] = res['confidence']
                col_bron[idx] = bron_label
                col_datum[idx] = RUN_DATE
                cache[rec['accountid']] = {
                    'name': rec['name'],
                    'segment': res['segment'],
                    'segment_detailed': res['segment_detailed'],
                    'confidence': res['confidence'],
                    'bron': bron_label,
                    'invuldatum': RUN_DATE,
                }
            n_classified += len(batch)
            # Cache na elke batch wegschrijven: crash-bestendig, herrun pakt
            # alleen het restant op.
            save_cache(cache)
            duration = time.time() - start
            log.info(f'  batch {b_i}/{len(batches)} klaar in {duration:.0f}s '
                     f'({n_classified}/{len(queue)})')
        log.info(f'{label} klaar: {n_classified} geclassificeerd, {n_failed} gefaald')

    def is_weak(idx):
        """Zwakke classificatie: kandidaat voor de websearch-ronde."""
        return (col_segment[idx] in ('Unknown', 'Commercial (other)', '')
                or col_confidence[idx] == 'low')

    needs_api = bool(claude_queue)
    if args.web_search and not args.offline:
        needs_api = needs_api or any(is_weak(i) for i in layer2_records)

    if needs_api and args.offline:
        log.info(f'Offline-modus: {len(claude_queue)} records blijven ongeclassificeerd')
    elif needs_api:
        if not os.environ.get('ANTHROPIC_API_KEY'):
            log.error('ANTHROPIC_API_KEY niet gezet. Zet de variabele of draai met --offline.')
            raise SystemExit(1)

        import anthropic
        client = anthropic.Anthropic()
        segment_batch_model = make_models()

        # Ronde 1: zonder websearch, grote batches
        if claude_queue:
            run_batches(claude_queue, args.batch_size, web_search=False,
                        label='Claude-classificatie (ronde 1)')

        # Ronde 2: zwakke resultaten opnieuw, nu met websearch in kleine
        # batches. Pakt ook zwakke resultaten uit de cache van eerdere runs.
        if args.web_search:
            pass2_queue = [(idx, layer2_records[idx])
                           for idx in sorted(layer2_records) if is_weak(idx)]
            if pass2_queue:
                run_batches(pass2_queue, min(5, args.batch_size), web_search=True,
                            label='Websearch-ronde (ronde 2)')
            else:
                log.info('Websearch-ronde: geen zwakke classificaties, overgeslagen')

    # ------------------------------------------------------------------
    # Overrides (hoogste prioriteit)
    # ------------------------------------------------------------------
    n_overridden = 0
    if overrides:
        accountids = df['accountid'].astype(str).tolist()
        for idx, aid in enumerate(accountids):
            if aid in overrides:
                o = overrides[aid]
                if o['segment']:
                    col_segment[idx] = o['segment']
                    col_detailed[idx] = o['segment_detailed']
                    col_confidence[idx] = 'high'
                    col_bron[idx] = f"override-tabel ({o['reden']})" if o['reden'] else 'override-tabel'
                    col_datum[idx] = RUN_DATE
                    n_overridden += 1
        log.info(f'Overrides toegepast: {n_overridden}')

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    df['Segment'] = col_segment
    df['Segment (detailed)'] = col_detailed
    df['segment_confidence'] = col_confidence
    df['segment_bron'] = col_bron
    df['segment_invuldatum'] = col_datum

    df.to_excel(args.output, index=False)
    log.info(f'Geschreven: {args.output} ({len(df)} records)')

    # Samenvatting per segment
    log.info('=== Verdeling per Segment ===')
    counts = df['Segment'].replace('', '(leeg)').value_counts()
    for seg, cnt in counts.items():
        log.info(f'  {seg}: {cnt}')


if __name__ == '__main__':
    main()
