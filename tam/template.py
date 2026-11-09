"""Invoersjabloon (tam_template.xlsx): aanmaken, bijwerken, lezen en valideren."""
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from openpyxl import Workbook, load_workbook

from tam.config import COUNTRIES, COUNTRY_NAMES, DETAILED_SEGMENTS, SEGMENTS, all_detailed
from tam.regions import BE_REGIONS, canonical_region, join_regions
from tam.xlsx_util import autofit_columns, sync_tables, write_instructions

DEF_COLUMNS = ['company', 'sales_unit', 'core_product', 'country', 'country_name', 'regions',
               'segments', 'excluded_kinds', 'min_population', 'notes']
# Landen met een regions-kolom en de standaardwaarde (alles aan; business haalt weg)
REGION_COUNTRIES = {'BE': BE_REGIONS}
OVERRIDE_COLUMNS = ['accountid', 'entity_id', 'reason']
FACTOR_SHEET = 'factors'
FACTOR_COLUMNS = ['sales_unit', 'core_product', 'country', 'detailed_segment', 'factor', 'notes']
FACTOR_KEYS = ['sales_unit', 'core_product', 'country']
ALWAYS_IGNORED = ['_Other', 'Undefined']
ENTITY_ID_RE = re.compile(r'^(' + '|'.join(COUNTRIES) + r')-[A-Z]+-.+$')


class TemplateError(ValueError):
    """Ongeldige waarden in het sjabloon; bericht bevat alle problemen."""


@dataclass
class TamDefinition:
    company: str
    sales_unit: str
    core_product: str
    country: str
    segments: list[str]
    excluded_kinds: list[str]
    min_population: int | None
    notes: str
    regions: list[str] = field(default_factory=list)   # leeg = het hele land
    factors: dict[str, float] = field(default_factory=dict)   # detailed_segment -> factor


def load_products(path: Path, config: dict) -> tuple[pd.DataFrame, list[dict]]:
    raw = pd.read_excel(path, sheet_name=0)[['Company', 'Sales Unit', 'Core Product Family']]
    raw.columns = ['company', 'sales_unit', 'core_product']
    raw = raw.dropna()
    ignore = set(ALWAYS_IGNORED) | set(config.get('ignore_core_products', []))
    raw = raw[raw['company'].isin(config['companies']) & ~raw['core_product'].isin(ignore)]
    counts = (raw.groupby(['company', 'core_product', 'sales_unit']).size()
              .reset_index(name='rows'))
    counts = counts.sort_values(['company', 'core_product', 'rows', 'sales_unit'],
                                ascending=[True, True, False, True])
    main = counts.drop_duplicates(['company', 'core_product'])
    strays = [{'company': r.company, 'core_product': r.core_product,
               'sales_unit': r.sales_unit, 'rows': int(r.rows)}
              for r in counts.drop(main.index).itertuples()]
    df = (main[['company', 'sales_unit', 'core_product']]
          .sort_values(['company', 'sales_unit', 'core_product']).reset_index(drop=True))
    return df, strays


# Naslag voor het blad 'lists': per detailed segment de landen en wat eronder valt.
DETAILED_HELP = {
    'Municipality': ('NL, BE, DE', 'Gemeente / commune / Gemeinde (in DE: verbandsfrei, '
                     'erfuellende Gemeinde of BW-lid van een GVV)'),
    'County-level city': ('DE', 'Kreisfreie Stadt / Stadtkreis (gemeente met Kreis-taken)'),
    'City district': ('NL, BE, DE', 'Stadsdeel Amsterdam, district Antwerpen, Bezirk Berlijn/Hamburg'),
    'Island authority': ('BQ', 'Openbaar lichaam Bonaire, Sint Eustatius, Saba'),
    'Municipal autonomous agency': ('BE', 'Autonoom gemeentebedrijf (AGB)'),
    'Municipal social services (OCMW)': ('BE', 'OCMW / CPAS / ÖSHZ, een per gemeente (in '
                                         'Vlaanderen sinds 2019 geintegreerd, maar eigen '
                                         'rechtspersoon en apart klant)'),
    'District administration': ('SR', 'Districtscommissariaat (10 districten Suriname)'),
    'State': ('DE', 'Bundesland, incl. stadstaten Berlijn, Hamburg, Bremen'),
    'Region / Community': ('BE', 'Gewest of Gemeenschap'),
    'Province': ('NL, BE', 'Provincie'),
    'Administrative district': ('DE', 'Regierungsbezirk (Bezirksregierung)'),
    'County': ('DE', 'Landkreis / Kreis'),
    'Higher municipal association': ('DE', 'Bezirk (Beieren), Landschaftsverband (NRW), LWV Hessen e.d.'),
    'Water authority': ('NL', 'Waterschap / hoogheemraadschap'),
    'Ministry': ('NL, DE, AW, CW, SX, SR', 'Ministerie / Bundesministerium'),
    'National agency': ('NL, BQ, SR', 'Rijksorganisatie (agentschap, ZBO, inspectie), Rijksdienst '
                        'Caribisch Nederland, regering Suriname'),
    'Federal public service': ('BE', 'FOD / POD'),
    'Country government (Caribbean)': ('AW, CW, SX', 'Regering van Aruba, Curacao, Sint Maarten'),
    'Safety region': ('NL', 'Veiligheidsregio'),
    'Police zone': ('BE', 'Politiezone / zone de police'),
    'Emergency services zone': ('BE', 'Hulpverleningszone / zone de secours'),
    'Municipal federation': ('DE', 'Amt, Samtgemeinde, Verbandsgemeinde, Verwaltungsgemeinschaft, '
                             'Gemeindeverwaltungsverband'),
    'Shared service organization': ('NL, BE', 'Ambtelijke werkorganisatie / shared service center '
                                    '(bv. Samenwerking Kempengemeenten)'),
    'IT cooperation': ('NL, BE, DE', 'ICT-samenwerking, kommunaler IT-Zweckverband'),
    'Tax cooperation': ('NL, BE', 'Belastingsamenwerking (heffing en invordering, WOZ)'),
    'Environmental agency': ('NL, BE', 'Omgevingsdienst'),
    'Public health service (GGD)': ('NL', 'GGD'),
    'Social employment & work': ('NL, BE', 'Werkbedrijf, sociale werkvoorziening, participatiebedrijf'),
    'Waste management': ('NL, BE', 'Afvalsamenwerking / afvalintercommunale'),
    'Recreation authority': ('NL, BE', 'Recreatieschap'),
    'Procurement cooperation': ('NL, BE', 'Inkoopsamenwerking'),
    'Transport authority': ('NL, BE', 'Vervoerregio, OV- of mobiliteitssamenwerking'),
    'Regional cooperation': ('NL, BE', 'Regionale samenwerking van gemeenten (bv. regio, '
                             'streekverband)'),
    'Welfare association': ('BE', 'Welzijnsvereniging (Vlaanderen)'),
    'Special-purpose association': ('DE', 'Zweckverband (water, afval, scholen e.d.)'),
    'Other joint arrangement': ('NL, BE', 'Overige samenwerking (archief, bedrijventerrein, '
                                'haven, jeugd e.d.)'),
}
# Een lichte vulkleur per segment, zodat de groepen in het blad meteen opvallen.
_SEGMENT_FILLS = ['DDEBF7', 'E2EFDA', 'FFF2CC', 'FCE4D6', 'EDE7F6']


# Tekst van het instructieblad (eerste tabblad), voor de business die het template invult.
INSTRUCTIONS = [
    ('TAM-template: zo vul je het in', None),
    (None, None),
    ('Wat is dit?', 'Per kernproduct en land leg je vast welke overheidsorganisaties tot de '
     'TAM (Total Addressable Market) horen. Het programma tam_build.py maakt daar de TAM-lijst '
     'van en koppelt die aan de CRM-accounts.'),
    (None, None),
    ('Tabblad tam_definitions', 'Een rij per kernproduct per land. Vul alleen de rijen in waarvoor '
     'je een TAM wilt; rijen met een lege kolom segments worden overgeslagen. De kolommen '
     'company, sales_unit, core_product, country (landcode) en country_name (land) zijn al '
     'ingevuld: niet wijzigen. De landcodes staan uitgelegd onderaan tabblad lists.'),
    ('  regions', 'Alleen voor BE, vooraf ingevuld met Vlaanderen; Brussel; Wallonie. Haal '
     'de gewesten weg die niet bij de TAM van dit product horen, bv. alleen Vlaanderen. '
     'Organisaties in een weggehaald gewest krijgen status "no - excluded region". Federale '
     'diensten (FOD/POD) vallen nooit weg. Leeg = heel Belgie. Bij andere landen leeg laten.'),
    ('  segments', 'Verplicht. Een of meer hoofdsegmenten, gescheiden door ; (puntkomma). '
     'Gebruik de namen uit kolom A van tabblad lists, bijvoorbeeld: '
     'Local government; Inter-municipal cooperation'),
    ('  excluded_kinds', 'Optioneel. Soorten organisaties (detailed segments) die binnen die '
     'segmenten toch NIET meetellen, gescheiden door ;. Gebruik waarden uit kolom B van tabblad '
     'lists, bijvoorbeeld: City district; Waste management; Recreation authority'),
    ('  min_population', 'Optioneel. Minimaal aantal inwoners (een heel getal, bv. 10000). '
     'Organisaties met minder inwoners krijgen status "no - below cutoff"; organisaties zonder '
     'bekend inwonertal krijgen "unknown - population missing" zodat Power BI zelf kan kiezen. '
     'Leeg = geen ondergrens.'),
    ('  notes', 'Optioneel. Vrije tekst; wordt meegenomen naar de uitvoer.'),
    (None, None),
    ('Tabblad factors', 'Prijsfactor per soort organisatie: welk deel van het gemeentelijke '
     'bedrag per inwoner betaalt deze soort voor een kernproduct in een land (bv. 0,1 = 10%). '
     'Power BI rekent: inwoners x ARPU per inwoner x factor. Een rij per regel; een lege '
     'sales_unit, core_product of country betekent "alle". Vooraf staat er een rij per detailed '
     'segment met die drie kolommen leeg: vul daar de standaardfactor in (Municipality = 1 '
     'per definitie). Wijkt een sales unit, product of land af, voeg dan een rij toe met '
     'sales_unit, '
     'core_product en/of country ingevuld; zo gaat "Product X / Province = 0,3" voor de '
     'standaard "Province = 0,1". Volgorde bij meerdere passende rijen: een rij met '
     'core_product wint, daarna een rij met sales_unit, daarna een rij met country. Een rij '
     'met meerdere kolommen ingevuld (bv. sales_unit en country) gaat voor een rij met '
     'alleen een van die kolommen.'),
    ('  sales_unit', 'Optioneel. Leeg = alle sales units. Anders exact zoals in '
     'tam_definitions.'),
    ('  core_product', 'Optioneel. Leeg = alle kernproducten. Anders exact zoals in '
     'tam_definitions.'),
    ('  country', 'Optioneel. Landcode (NL, BE, DE, AW, CW, SX, BQ, SR). Leeg = alle landen.'),
    ('  detailed_segment', 'Verplicht. Een waarde uit kolom B van tabblad lists, bv. Province.'),
    ('  factor', 'Een getal van 0 of meer, bv. 1 voor gemeenten, 0,1 voor provincies. Leeg = '
     'deze rij telt (nog) niet mee.'),
    ('  notes', 'Optioneel. Vrije tekst, bv. waar de factor op gebaseerd is.'),
    (None, 'Een soort zonder passende rij krijgt in de uitvoer een lege factor; het Run log '
     'telt hoeveel TAM-rijen (in_tam yes) nog geen factor hebben. Dezelfde combinatie twee '
     'keer invullen geeft een foutmelding.'),
    (None, None),
    ('Tabblad lists', 'Naslag: een rij per detailed segment, met ernaast het hoofdsegment '
     'waartoe het hoort, de landen waar het voorkomt en wat eronder valt. Filter kolom A '
     '(segment) op jouw segment om te zien welke soorten je kunt uitsluiten. Niets invullen.'),
    (None, None),
    ('Tabblad match_overrides', 'Handmatige correcties van de CRM-koppeling, alleen als een '
     'account aan de verkeerde (of geen) organisatie gekoppeld is. Een override wint altijd van '
     'de regels en de AI en kost geen AI-budget.'),
    ('  accountid', 'Het CRM-account (te vinden op het blad CRM matches of CRM unmatched van de '
     'uitvoer).'),
    ('  entity_id', 'De juiste organisatie (te vinden op het blad Entities van de uitvoer). '
     'Leeg laten = dit account hoort bij geen enkele organisatie.'),
    ('  reason', 'Optioneel. Waarom de correctie nodig is.'),
    (None, None),
    ('Daarna', 'Sla het bestand op en laat tam_build.py draaien (eerst met --dry-run voor de '
     'kostenschatting). Onbekende waarden worden gemeld met het rijnummer, voordat er iets '
     'gedownload of uitgegeven wordt.'),
]


def _instructions_sheet(wb: Workbook) -> None:
    """(Her)bouw het instructieblad als eerste tabblad en maak het actief."""
    write_instructions(wb, INSTRUCTIONS)


def _fit_columns(wb: Workbook) -> None:
    """Kolombreedtes zo dat 80% van de waarden past (instructieblad heeft vaste breedtes);
    eventuele Excel-tabellen meteen gelijktrekken met het blad."""
    for ws in wb.worksheets:
        if ws.title != 'instructies':
            sync_tables(ws)
            autofit_columns(ws)


def _lists_sheet(wb: Workbook) -> None:
    """(Her)bouw het hulpblad 'lists': een rij per detailed segment met het segment
    ernaast, de landen en wat eronder valt. Bij --update vervangen zodat nieuwe waarden
    erin staan. Het blad is alleen naslag, niet ingevuld."""
    from openpyxl.styles import Font, PatternFill

    if 'lists' in wb.sheetnames:
        del wb['lists']
    ws = wb.create_sheet('lists')
    ws.append(['segment', 'detailed_segment', 'landen', 'wat valt eronder'])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for i, segment in enumerate(SEGMENTS):
        fill = PatternFill('solid', fgColor=_SEGMENT_FILLS[i % len(_SEGMENT_FILLS)])
        for detailed in DETAILED_SEGMENTS[segment]:
            landen, uitleg = DETAILED_HELP.get(detailed, ('', ''))
            ws.append([segment, detailed, landen, uitleg])
            for cell in ws[ws.max_row]:
                cell.fill = fill
    last = ws.max_row
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f'A1:D{last}'
    ws.append([])
    ws.append(['segments: alleen de segmentnamen uit kolom A. excluded_kinds: waarden uit kolom B '
               'die binnen die segmenten vallen.'])
    ws.append(['Meerdere waarden in een cel: scheiden met ; (puntkomma).'])
    ws.append([])
    ws.append(['landcode', 'land'])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
    for code in COUNTRIES:
        ws.append([code, COUNTRY_NAMES[code]])


SORT_COLUMNS = ['company', 'sales_unit', 'core_product', 'country']


def _sort_definitions(ws) -> None:
    """Sorteer de rijen van tam_definitions op company, sales_unit, core_product en als
    laatste country (A-Z, hoofdletterongevoelig). Hele rijen schuiven mee, dus ingevulde
    waarden blijven bij hun product en land."""
    header = [c.value for c in ws[1]]
    idx = [header.index(c) for c in SORT_COLUMNS if c in header]
    rows = [list(r) for r in ws.iter_rows(min_row=2, values_only=True)]
    rows = [r for r in rows if any(v not in (None, '') for v in r)]

    def key(r):
        return tuple(str(r[i]).strip().casefold() if r[i] is not None else '' for i in idx)

    rows.sort(key=key)
    ws.delete_rows(2, ws.max_row)
    for r in rows:
        ws.append(r)


def _ensure_country_name(ws) -> None:
    """Oud template (zonder country_name): kolom direct na 'country' invoegen en vullen."""
    header = [c.value for c in ws[1]]
    if 'country_name' in header or 'country' not in header:
        return
    col = header.index('country') + 2          # 1-based positie direct na 'country'
    ws.insert_cols(col)
    ws.cell(1, col).value = 'country_name'
    for row in range(2, ws.max_row + 1):
        code = ws.cell(row, col - 1).value
        ws.cell(row, col).value = COUNTRY_NAMES.get(str(code).strip(), '') if code else None


def _default_regions(country) -> str | None:
    regions = REGION_COUNTRIES.get(str(country).strip()) if country else None
    return join_regions(regions) if regions else None


def _ensure_regions(ws) -> None:
    """Template zonder regions: kolom direct na 'country_name' invoegen en BE-rijen vullen
    met alle gewesten (zelfde betekenis als leeg: heel Belgie)."""
    header = [c.value for c in ws[1]]
    if 'regions' in header or 'country_name' not in header:
        return
    col = header.index('country_name') + 2     # 1-based positie direct na 'country_name'
    country_col = header.index('country') + 1
    ws.insert_cols(col)
    ws.cell(1, col).value = 'regions'
    for row in range(2, ws.max_row + 1):
        ws.cell(row, col).value = _default_regions(ws.cell(row, country_col).value)


# Gemeente = 1 per definitie: de ARPU is het bedrag per inwoner dat gemeenten betalen
_FACTOR_PRESET = {'Municipality': (1, 'per definitie: ARPU per inwoner komt van gemeenten')}


def _ensure_factors_sheet(wb) -> None:
    """Tabblad factors direct na tam_definitions, als het er nog niet is, vooraf gevuld met een
    standaardregel (sales_unit/core_product/country leeg) per detailed segment; factor leeg behalve
    Municipality. Een bestaand tabblad met regels blijft ongemoeid; een leeg (alleen kopregel)
    wordt gevuld."""
    from openpyxl.styles import Font

    if FACTOR_SHEET in wb.sheetnames:
        ws = wb[FACTOR_SHEET]
        if any(any(v not in (None, '') for v in r) for r in ws.iter_rows(min_row=2, values_only=True)):
            return
        ws.delete_rows(1, ws.max_row)
    else:
        ws = wb.create_sheet(FACTOR_SHEET, wb.sheetnames.index('tam_definitions') + 1)
    ws.append(FACTOR_COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for segment in SEGMENTS:
        for detailed in DETAILED_SEGMENTS[segment]:
            factor, note = _FACTOR_PRESET.get(detailed, (None, None))
            ws.append([None, None, None, detailed, factor, note])
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f'A1:F{ws.max_row}'


def _product_rows(products: pd.DataFrame):
    for r in products.itertuples():
        for country in COUNTRIES:
            yield [r.company, r.sales_unit, r.core_product, country, COUNTRY_NAMES[country],
                   _default_regions(country), None, None, None, None]


def make_template(products: pd.DataFrame, path: Path, *, update: bool = False) -> int:
    path = Path(path)
    if path.exists() and not update:
        raise FileExistsError(f'{path} bestaat al; gebruik update om rijen toe te voegen')
    if not path.exists():
        wb = Workbook()
        ws = wb.active
        ws.title = 'tam_definitions'
        ws.append(DEF_COLUMNS)
        rows = list(_product_rows(products))
        for row in rows:
            ws.append(row)
        _sort_definitions(ws)
        _ensure_factors_sheet(wb)
        wb.create_sheet('match_overrides').append(OVERRIDE_COLUMNS)
        _lists_sheet(wb)
        _instructions_sheet(wb)
        _fit_columns(wb)
        wb.save(path)
        return len(rows)
    wb = load_workbook(path)
    ws = wb['tam_definitions']
    _ensure_country_name(ws)
    _ensure_regions(ws)
    # Op kolomnaam, niet op positie: de business kan kolommen verschoven of toegevoegd hebben
    header = [c.value for c in ws[1]]
    key_idx = [header.index(c) for c in ('company', 'core_product', 'country')]
    existing = {tuple(r[i] for i in key_idx) for r in ws.iter_rows(min_row=2, values_only=True)}
    added = 0
    for row in _product_rows(products):
        values = dict(zip(DEF_COLUMNS, row))
        if (values['company'], values['core_product'], values['country']) not in existing:
            ws.append([values.get(h) for h in header])
            added += 1
    _sort_definitions(ws)
    _ensure_factors_sheet(wb)
    _lists_sheet(wb)
    _instructions_sheet(wb)
    _fit_columns(wb)
    wb.save(path)
    return added


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == ''


def _split(v) -> list[str]:
    return [] if _blank(v) else [p.strip() for p in str(v).split(';') if p.strip()]


def _number(v) -> float | None:
    """Getal uit een cel; tekst met komma als decimaalteken ('0,1') mag ook. None = ongeldig."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace(',', '.'))
    except ValueError:
        return None


def _read_factors(path: Path, definitions: pd.DataFrame, errors: list[str]) -> list[dict]:
    """Regels uit tabblad factors (ontbrekend tabblad = geen regels), gevalideerd."""
    try:
        df = pd.read_excel(path, sheet_name=FACTOR_SHEET, dtype=object)
    except ValueError:   # oud template zonder tabblad factors
        return []
    df = df.reindex(columns=FACTOR_COLUMNS)

    def known(column):
        return {str(v).strip() for v in definitions.get(column, pd.Series(dtype=object))
                if not _blank(v)}

    units, products = known('sales_unit'), known('core_product')
    rules, seen = [], {}
    for idx, row in df.iterrows():
        xl = idx + 2
        if _blank(row.get('factor')):
            continue   # nog niet ingevuld: regel telt niet mee (zoals een lege segments-rij)
        rule = {c: '' if _blank(row.get(c)) else str(row.get(c)).strip()
                for c in FACTOR_KEYS + ['detailed_segment']}

        def bad(value, column):
            errors.append(f"factors rij {xl}: onbekende waarde '{value}' in {column}")

        if rule['sales_unit'] and rule['sales_unit'] not in units:
            bad(rule['sales_unit'], 'sales_unit')
        if rule['core_product'] and rule['core_product'] not in products:
            bad(rule['core_product'], 'core_product')
        if rule['country'] and rule['country'] not in COUNTRIES:
            bad(rule['country'], 'country')
        if not rule['detailed_segment']:
            errors.append(f'factors rij {xl}: detailed_segment ontbreekt')
        elif rule['detailed_segment'] not in all_detailed():
            bad(rule['detailed_segment'], 'detailed_segment')
        raw = row.get('factor')
        factor = _number(raw)
        if factor is None or factor < 0 or factor != factor:
            bad(raw, 'factor')
        key = tuple(rule[c] for c in FACTOR_KEYS + ['detailed_segment'])
        if key in seen:
            errors.append(f"factors rij {xl}: dubbele regel voor "
                          f"{' / '.join(k or '(alle)' for k in key)} (ook in rij {seen[key]})")
        else:
            seen[key] = xl
        if factor is not None:
            rules.append({**rule, 'factor': factor})
    return rules


def resolve_factors(rules: list[dict], d: TamDefinition) -> dict[str, float]:
    """detailed_segment -> factor voor een definitie: de meest specifieke passende regel
    (ingevuld core_product gaat voor sales_unit, dat gaat voor country)."""
    best: dict[str, tuple] = {}
    values = {'sales_unit': d.sales_unit, 'core_product': d.core_product, 'country': d.country}
    for r in rules:
        if any(r[c] and r[c] != values[c] for c in FACTOR_KEYS):
            continue
        rank = (bool(r['core_product']), bool(r['sales_unit']), bool(r['country']))
        if r['detailed_segment'] not in best or rank > best[r['detailed_segment']][0]:
            best[r['detailed_segment']] = (rank, r['factor'])
    return {seg: f for seg, (_, f) in best.items()}


def read_template(path: Path) -> tuple[list[TamDefinition], pd.DataFrame]:
    errors: list[str] = []
    defs: list[TamDefinition] = []
    df = pd.read_excel(path, sheet_name='tam_definitions', dtype=object)
    seen: dict[tuple, int] = {}   # (company, core_product, country) -> eerste Excel-rij
    for idx, row in df.iterrows():
        xl = idx + 2
        segments = _split(row.get('segments'))
        if not segments:
            continue
        key = tuple('' if _blank(row.get(c)) else str(row.get(c)).strip()
                    for c in ('company', 'core_product', 'country'))
        if key in seen:
            # M4: dubbele definitie zou TAM-rijen dubbel tellen
            errors.append(f"tam_definitions rij {xl}: dubbele definitie voor {' / '.join(key)} "
                          f"(ook in rij {seen[key]})")
        else:
            seen[key] = xl
        excluded = _split(row.get('excluded_kinds'))

        def bad(value, column):
            errors.append(f"tam_definitions rij {xl}: onbekende waarde '{value}' in {column}")

        for s in segments:
            if s not in SEGMENTS:
                bad(s, 'segments')
        for k in excluded:
            if k not in all_detailed():
                bad(k, 'excluded_kinds')
        country = str(row.get('country')).strip()
        if country not in COUNTRIES:
            bad(country, 'country')
        minpop = None
        mp = row.get('min_population')
        if not _blank(mp):
            try:
                f = float(mp)
                if f != int(f) or f < 0:
                    raise ValueError
                minpop = int(f)
            except (ValueError, TypeError, OverflowError):
                bad(mp, 'min_population')
        regions = []
        for r in _split(row.get('regions')):
            canon = canonical_region(r)
            if country not in REGION_COUNTRIES:
                errors.append(f"tam_definitions rij {xl}: regions alleen voor "
                              f"{', '.join(REGION_COUNTRIES)}, niet voor {country}")
                break
            if canon is None or canon not in REGION_COUNTRIES[country]:
                bad(r, 'regions')
            elif canon not in regions:
                regions.append(canon)
        notes = '' if _blank(row.get('notes')) else str(row['notes'])
        defs.append(TamDefinition(str(row['company']), str(row['sales_unit']),
                                  str(row['core_product']), country, segments, excluded,
                                  minpop, notes, regions))
    rules = _read_factors(path, df, errors)
    for d in defs:
        d.factors = resolve_factors(rules, d)
    overrides = pd.read_excel(path, sheet_name='match_overrides', dtype=str)
    overrides = overrides.reindex(columns=OVERRIDE_COLUMNS)
    for idx, eid in overrides['entity_id'].items():
        if not _blank(eid) and not ENTITY_ID_RE.match(str(eid).strip()):
            errors.append(f"match_overrides rij {idx + 2}: onbekende waarde '{eid}' in entity_id")
    if errors:
        raise TemplateError('\n'.join(errors))
    overrides['entity_id'] = overrides['entity_id'].fillna('').str.strip()
    return defs, overrides
