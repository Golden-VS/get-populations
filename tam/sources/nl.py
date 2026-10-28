"""Nederlandse bronnen voor de TAM/whitespace-lijstbouwer: CBS gemeenten en provincies.

CBS OData-tabel 'Gebieden in Nederland' (editie 2026 = 86247NED). Het tabel-id wisselt
jaarlijks; de nieuwste editie wordt gezocht met step2_enrich.discover_cbs_gebieden_table.
Offline (of als de catalogus onbereikbaar is) wordt de nieuwste gecachte editie
hergebruikt (bestanden reference/tam/nl_cbs_<jaar>_<tabelid>_{typed,props}.json).

Waargenomen veldtitels in DataProperties (editie 2026; veldnamen lopen per jaar uiteen
en worden daarom op titel opgezocht, nooit hard-coded):
  groep 'Codes en namen van gemeenten': Code (Code_1, 'GM1680    ' met spaties),
                                        Naam (Naam_2, 'Aa en Hunze   ...' met spaties)
  groep 'Provincies':                   Code (Code_28, 'PV22      '), Naam (Naam_29, 'Drenthe')
  groep 'Statistische gegevens':        Inwonertal (Inwonertal_56)
Namen kunnen een disambiguerend suffix hebben ('Groningen (gemeente)', 'Beek (L.)').

Register van overheidsorganisaties (OO-export, bulk-XML, nachtelijk ververst):
https://organisaties.overheid.nl/archive/exportOO.xml (~38 MB), schema oo/export/2.6.13,
namespace https://organisaties.overheid.nl/static/schema/oo/export/2.6.13. Geinspecteerd op
2026-10-27 (timestamp 2026-10-26). Wortel overheidsorganisaties, drie secties:
  organisaties/organisatie            4544 records, attributen systeemId, resourceIdentifierTOOI
                                      (kan ontbreken), resourceIdentifierOWMS; kinderen naam,
                                      types/type (meerdere mogelijk), eindDatum, identificatiecodes/
                                      resourceIdentifier[@naam = KVK-nummer | OIN | rsin |
                                      resourceIdentifierTOOI | Organisatiecode | systeemId ...]
  gemeenschappelijkeRegelingen/regeling   1196 GR'en; datumUitwerkingtreding = einddatum (leeg =
                                      actief; 438 actief), regionaalSamenwerkingsorgaan
                                      (@systeemId verwijst naar een organisatie; 81 actieve GR'en
                                      hebben geen orgaan), deelnemendeOrganisaties/
                                      deelnemendeOrganisatie (@resourceIdentifierTOOI, naam,
                                      toetredingsDatum). Deelnemers zonder TOOI zijn oude
                                      (opgeheven) gemeenten en worden overgeslagen.
  gemeenschappelijkeRegelingenGrensoverschrijdend/regeling   15 stuks, genegeerd.
Per regeling staat het doel in regeling/doel (direct kind, meestal CDATA; 1094 van 1196) en
draagt regionaalSamenwerkingsorgaan de OWMS-URI van het orgaan (@resourceIdentifierOWMS, laatste
padstuk soms leesbaar, bv. 'Sociale_Dienst_Oost-Achterhoek', soms een afkorting). Beide gaan per
orgaan als beschrijving naar extras['coop_descriptions'] (unie over de actieve GR'en, ingekort)
voor de classificatie.
Het regionaalSamenwerkingsorgaan-record (type 'Regionaal samenwerkingsorgaan', 357 actief)
draagt KvK, OIN en TOOI so####. Sommige OWMS/TOOI-URI's zijn kapot ('htt//...'); de TOOI-code
wordt daarom met een regex uit de tekst gehaald, niet uit het schema.
Typen (organisatie-records, totaal): Organisatieonderdeel 1681, Organisatie met overheids-
bemoeienis 1307, Regionaal samenwerkingsorgaan 443, Gemeente 419, Overheidsstichting of
-vereniging 197, Zelfstandig bestuursorgaan 182, Externe commissie 86, Adviescollege 58,
Agentschap 31, Rechtspraak 26, Waterschap 25, Inspectie 15, Ministerie 15, Landelijk dekkende
samenwerkingen 14, Provincie 12, Hoog College van Staat 6, Politie 2, overig kleiner.
Landelijke set (alleen actieve records, dus zonder eindDatum in het verleden):
  nl_ministerie        type Ministerie (12 actief)
  nl_rijksorganisatie  type Agentschap (30), Zelfstandig bestuursorgaan (178) of Inspectie (15),
                       overlap telt eenmaal; uitgesloten als ook van type Adviescollege,
                       Rechtspraak, Hoog College van Staat, Openbaar lichaam voor beroep en
                       bedrijf, Gemeente, Waterschap, Provincie of Regionaal samenwerkingsorgaan.
  Bewust niet: adviescolleges, externe commissies, rechtspraak, Hoge Colleges van Staat,
  Politie (publieke veiligheid, geen bestuursorgaan met eigen inkoop), Organisatieonderdelen.
"""
from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import pandas as pd

from step2_enrich import (CBS_ODATA_URL, NL_STADSDEEL_INWONERS, NL_WATERSCHAP_INWONERS,
                          discover_cbs_gebieden_table, normalize)
from tam import hand_tables
from tam.config import USER_AGENT
from tam.entities import ALIAS_COLUMNS, SourceBundle, SourceStatus, make_entity_id, new_entity
from tam.sources.common import SourceCache

log = logging.getLogger(__name__)

GM_GROUP = 'Codes en namen van gemeenten'
PV_GROUP = 'Provincies'


def _clean(value) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _strip_suffix(name: str) -> str:
    """'Groningen (gemeente)' -> 'Groningen'."""
    return re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()


def resolve_cbs_keys(props: list[dict]) -> dict:
    """Zoek de veldnamen op titel op (gemeente- en provinciecode/-naam, inwonertal)."""
    groups = {p['ID']: p['Title'] for p in props if p.get('Type') == 'TopicGroup'}
    keys = {}
    for p in props:
        if p.get('Type') != 'Topic':
            continue
        group = groups.get(p.get('ParentID'), '').strip()
        title = p['Title']
        if group == GM_GROUP and title == 'Code':
            keys['gm_code'] = p['Key']
        elif group == GM_GROUP and title == 'Naam':
            keys['gm_name'] = p['Key']
        elif group == PV_GROUP and title == 'Code':
            keys['pv_code'] = p['Key']
        elif group == PV_GROUP and title == 'Naam':
            keys['pv_name'] = p['Key']
        elif title == 'Inwonertal':
            keys['pop'] = p['Key']
    missing = {'gm_code', 'gm_name', 'pv_code', 'pv_name', 'pop'} - keys.keys()
    if missing:
        raise RuntimeError(f'CBS-velden niet gevonden: {sorted(missing)}')
    return keys


def parse_cbs_gebieden(records: list[dict], keys: dict) -> pd.DataFrame:
    """Platte tabel: gm_code, gm_name, pv_code, pv_name, population (int)."""
    rows = []
    for rec in records:
        code = _clean(rec.get(keys['gm_code']))
        name = _strip_suffix(_clean(rec.get(keys['gm_name'])))
        pop = rec.get(keys['pop'])
        if not code.startswith('GM') or not name:
            continue
        rows.append({
            'gm_code': code,
            'gm_name': name,
            'pv_code': _clean(rec.get(keys['pv_code'])),
            'pv_name': _strip_suffix(_clean(rec.get(keys['pv_name']))),
            'population': int(pop) if pop is not None and not pd.isna(pop) else None,
        })
    cols = ['gm_code', 'gm_name', 'pv_code', 'pv_name', 'population']
    df = pd.DataFrame(rows, columns=cols)
    df['population'] = df['population'].astype('Int64')
    return df


def _cached_edition(cache: SourceCache):
    """Nieuwste gecachte editie (jaar, tabelid) uit bestandsnamen, of None."""
    best = None
    for p in cache.base_dir.glob('nl_cbs_*_typed.json'):
        m = re.fullmatch(r'nl_cbs_(\d{4})_(\w+)_typed\.json', p.name)
        if m and (best is None or (int(m[1]), m[2]) > best):
            best = (int(m[1]), m[2])
    return (best[1], best[0]) if best else None


def _resolve_table(cache: SourceCache):
    """(tabelid, jaar): live via de catalogus; offline of bij falen de nieuwste cache."""
    if not cache.offline:
        try:
            return discover_cbs_gebieden_table(USER_AGENT)
        except Exception as e:  # noqa: BLE001
            log.warning('CBS-catalogus onbereikbaar (%s); probeer cache', e)
    edition = _cached_edition(cache)
    if edition is None:
        raise FileNotFoundError('Geen CBS-tabel in cache en catalogus niet beschikbaar')
    return edition


def load_nl_cbs(cache: SourceCache) -> SourceBundle:
    bundle = SourceBundle.empty()
    try:
        table_id, year = _resolve_table(cache)
        base = f'nl_cbs_{year}_{table_id}'
        props_path = cache.fetch(f'{base}_props', f'{CBS_ODATA_URL}/{table_id}/DataProperties',
                                 params={'$format': 'json'}, suffix='.json')
        typed_path = cache.fetch(f'{base}_typed', f'{CBS_ODATA_URL}/{table_id}/TypedDataSet',
                                 params={'$format': 'json'}, suffix='.json')
        keys = resolve_cbs_keys(json.loads(props_path.read_text(encoding='utf-8'))['value'])
        records = json.loads(typed_path.read_text(encoding='utf-8'))['value']
        df = parse_cbs_gebieden(records, keys)
    except Exception as e:  # noqa: BLE001
        log.error('CBS gemeenten/provincies mislukt: %s', e)
        bundle.status.append(SourceStatus('nl_cbs', False, 0, '', f'mislukt: {e}'))
        return bundle

    source_date = f'{year}-01-01'
    source = f'CBS {table_id}'
    missing_pop = df[df['population'].isna()]
    if len(missing_pop):
        log.warning('CBS: %d gemeenten zonder inwonertal: %s', len(missing_pop),
                    ', '.join(missing_pop['gm_name']))

    rows, members, muni_pop = [], [], {}
    for r in df.itertuples():
        eid = make_entity_id('NL', 'GM', r.gm_code)
        pop = None if pd.isna(r.population) else int(r.population)
        if pop is not None:
            muni_pop[eid] = pop
        rows.append(new_entity(
            entity_id=eid, name=r.gm_name, country='NL', kind='nl_gemeente', region=r.pv_name,
            population=pop, population_method='own' if pop is not None else 'unknown',
            population_source=source, population_date=source_date,
            official_ids=f'cbs:{r.gm_code}', source=source, source_date=source_date))
    for (pv_code, pv_name), grp in df.groupby(['pv_code', 'pv_name']):
        if not pv_code.startswith('PV'):
            continue  # placeholder ('.' of leeg) is geen provincie
        pid = make_entity_id('NL', 'PV', pv_code)
        rows.append(new_entity(
            entity_id=pid, name=pv_name, country='NL', kind='nl_provincie',
            population_method='sum of members', population_source=source,
            population_date=source_date, official_ids=f'cbs:{pv_code}',
            source=source, source_date=source_date))
        for gm in grp['gm_code']:
            members.append({'entity_id': pid, 'member_entity_id': make_entity_id('NL', 'GM', gm),
                            'member_kind': 'nl_gemeente', 'membership_type': 'territorial',
                            'join_date': ''})

    bundle.entities = pd.DataFrame(rows, columns=bundle.entities.columns)
    bundle.memberships = pd.DataFrame(members, columns=bundle.memberships.columns)
    bundle.extras['municipal_population'] = muni_pop
    bundle.status.append(SourceStatus('nl_cbs', True, len(rows), source_date,
                                      f'{len(df)} gemeenten, {df["pv_code"].nunique()} provincies'))
    return bundle


# ---------------------------------------------------------------------------
# Register van overheidsorganisaties (OO-export)
# ---------------------------------------------------------------------------
OO_URL = 'https://organisaties.overheid.nl/archive/exportOO.xml'
OO_NS = '{https://organisaties.overheid.nl/static/schema/oo/export/2.6.13}'
OO_SOURCE = 'organisaties.overheid.nl OO-export'
_TOOI_RE = re.compile(r'/(gemeente|provincie|waterschap|so)/([a-z]{2}\d+)', re.I)
_SECTIONS = ('organisaties', 'gemeenschappelijkeRegelingen',
             'gemeenschappelijkeRegelingenGrensoverschrijdend')
# Typen die een organisatie uit de landelijke set weren
_NATIONAL_INCLUDE = ('Agentschap', 'Zelfstandig bestuursorgaan', 'Inspectie')
_NATIONAL_EXCLUDE = ('Adviescollege', 'Rechtspraak', 'Hoog College van Staat',
                     'Openbaar lichaam voor beroep en bedrijf', 'Gemeente', 'Waterschap',
                     'Provincie', 'Regionaal samenwerkingsorgaan')
_VGGM = {'vggm', 'veiligheids en gezondheidsregio gelderland midden'}
_OO_COLUMNS = ['entity_id', 'official_ids']
# Maximale lengte van de doeltekst per orgaan (unie over GR'en) in coop_descriptions
DESCRIPTION_MAX_CHARS = 400


def _tooi(text):
    """(soort, code) uit een TOOI-URI, ook bij kapotte schema's; anders (None, None)."""
    m = _TOOI_RE.search(text or '')
    return (m.group(1).lower(), m.group(2).lower()) if m else (None, None)


def _is_active(end_text, run_date: date) -> bool:
    """Actief = geen einddatum of einddatum na run_date; onleesbare datum telt als actief."""
    if not end_text or not end_text.strip():
        return True
    try:
        return date.fromisoformat(end_text.strip()[:10]) > run_date
    except ValueError:
        log.warning('OO: onleesbare einddatum %r; behandeld als actief', end_text)
        return True


def _read_org(el) -> dict:
    ids = {}
    for r in el.iter(OO_NS + 'resourceIdentifier'):
        ids.setdefault(r.get(OO_NS + 'naam'), (r.text or '').strip())
    types = [t.text for t in el.findall(f'{OO_NS}types/{OO_NS}type')]
    tooi_attr = el.get(OO_NS + 'resourceIdentifierTOOI') or ids.get('resourceIdentifierTOOI')
    return {
        'id': el.get(OO_NS + 'systeemId'), 'name': (el.findtext(OO_NS + 'naam') or '').strip(),
        'types': types, 'end': el.findtext(OO_NS + 'eindDatum'),
        'tooi': _tooi(tooi_attr), 'ids': ids,
    }


def _official_ids(org: dict) -> str:
    parts = []
    if org['ids'].get('KVK-nummer'):
        parts.append(f"kvk:{org['ids']['KVK-nummer']}")
    if org['ids'].get('OIN'):
        parts.append(f"oin:{org['ids']['OIN']}")
    if org['tooi'][1]:
        parts.append(f"tooi:{org['tooi'][1]}")
    return ';'.join(parts)


def _read_gr(el) -> dict:
    body = el.find(OO_NS + 'regionaalSamenwerkingsorgaan')
    members = []
    for d in el.iter(OO_NS + 'deelnemendeOrganisatie'):
        soort, code = _tooi(d.get(OO_NS + 'resourceIdentifierTOOI'))
        if soort in ('gemeente', 'provincie', 'waterschap'):
            members.append((soort, code, (d.findtext(OO_NS + 'toetredingsDatum') or '').strip()))
    owms = (body.get(OO_NS + 'resourceIdentifierOWMS') or '') if body is not None else ''
    return {
        'end': el.findtext(OO_NS + 'datumUitwerkingtreding'),
        'body_id': body.get(OO_NS + 'systeemId') if body is not None else None,
        'body_name': ((body.text or '').strip() if body is not None else ''),
        'members': members,
        'doel': _clean(el.findtext(OO_NS + 'doel')),
        'owms': owms.rstrip('/').rsplit('/', 1)[-1] if owms else '',
    }


def _description(name: str, doelen: list[str], owms: list[str]) -> str:
    """Doelteksten (uniek, ' | '), ingekort tot DESCRIPTION_MAX_CHARS, plus de OWMS-naam als
    hint als die iets anders zegt dan de eigen naam. Leeg als er niets is."""
    text = ' | '.join(dict.fromkeys(d for d in doelen if d))
    if len(text) > DESCRIPTION_MAX_CHARS:
        text = text[:DESCRIPTION_MAX_CHARS].rsplit(' ', 1)[0].rstrip(' |,;.') + '...'
    hints = [h for h in dict.fromkeys(_clean(o.replace('_', ' ')) for o in owms if o)
             if h and normalize(h) != normalize(name)]
    if hints:
        text = (text + ' ' if text else '') + f"(OWMS-naam: {', '.join(hints)})"
    return text


def _waterschap_population(name: str):
    """(inwoners, bron_url, peildatum) uit NL_WATERSCHAP_INWONERS op genormaliseerde naam."""
    table = {normalize(k): v for k, v in NL_WATERSCHAP_INWONERS.items()}
    n = normalize(name)
    for cand in (n, re.sub(r'^(waterschap|hoogheemraadschap)\s+(van\s+)?', '', n)):
        if cand in table:
            v = table[cand]
            return v['population'], v['bron_url'], str(v.get('peildatum', ''))
    return None


def _is_veiligheidsregio(name: str) -> bool:
    return name.startswith('Veiligheidsregio') or normalize(name) in _VGGM


def parse_oo_export(xml_path: Path, run_date: date) -> SourceBundle:
    """Lees de OO-export (iterparse, elementen worden vrijgegeven) naar een SourceBundle."""
    orgs, grs = {}, []
    section, stamp = None, ''
    for event, el in ET.iterparse(xml_path, events=('start', 'end')):
        tag = el.tag.replace(OO_NS, '')
        if event == 'start':
            if tag == 'overheidsorganisaties':
                stamp = (el.get(OO_NS + 'timestamp') or '')[:10]
            elif tag in _SECTIONS:
                section = tag
            continue
        if tag == 'organisatie' and section == 'organisaties':
            orgs[el.get(OO_NS + 'systeemId')] = _read_org(el)
            el.clear()
        elif tag == 'regeling' and section == 'gemeenschappelijkeRegelingen':
            grs.append(_read_gr(el))
            el.clear()
        elif tag == 'regeling':
            el.clear()  # grensoverschrijdend: genegeerd
    source_date = stamp or run_date.isoformat()

    rows, members, patches = [], {}, []
    # Waterschappen en landelijke organisaties
    ws_ids = set()
    n_nat = {'nl_ministerie': 0, 'nl_rijksorganisatie': 0}
    for org in orgs.values():
        if not _is_active(org['end'], run_date):
            continue
        types = org['types']
        soort, code = org['tooi']
        if 'Gemeente' in types and soort == 'gemeente':
            patches.append({'entity_id': make_entity_id('NL', 'GM', code),
                            'official_ids': _official_ids(org)})
        elif 'Waterschap' in types and soort == 'waterschap':
            eid = make_entity_id('NL', 'WS', code)
            ws_ids.add(eid)
            pop = _waterschap_population(org['name'])
            if pop is None:
                log.warning('Waterschap %s niet in NL_WATERSCHAP_INWONERS; bevolking onbekend', org['name'])
            rows.append(new_entity(
                entity_id=eid, name=org['name'], country='NL', kind='nl_waterschap',
                population=pop[0] if pop else None,
                population_method='own' if pop else 'unknown',
                population_source=pop[1] if pop else '', population_date=pop[2] if pop else '',
                official_ids=_official_ids(org), source=OO_SOURCE, source_date=source_date))
        elif 'Ministerie' in types:
            kind = 'nl_ministerie'
        elif any(t in types for t in _NATIONAL_INCLUDE) and not any(t in types for t in _NATIONAL_EXCLUDE):
            kind = 'nl_rijksorganisatie'
        else:
            continue
        if 'Gemeente' in types or 'Waterschap' in types:
            continue
        n_nat[kind] += 1
        rows.append(new_entity(
            entity_id=make_entity_id('NL', 'OO', org['id']), name=org['name'], country='NL',
            kind=kind, population_method='country total', official_ids=_official_ids(org),
            source=OO_SOURCE, source_date=source_date))

    # Samenwerkingsverbanden: een entiteit per gekoppeld orgaan, leden samengevoegd
    bodies = {}
    n_active = n_nobody = 0
    for gr in grs:
        if not _is_active(gr['end'], run_date):
            continue
        n_active += 1
        if not gr['body_id']:
            n_nobody += 1
            continue
        org = orgs.get(gr['body_id'])
        if org is None:
            org = {'id': gr['body_id'], 'name': gr['body_name'], 'types': [], 'end': None,
                   'tooi': (None, None), 'ids': {}}
            log.warning('OO: orgaan %s (%s) ontbreekt in de export', gr['body_id'], gr['body_name'])
        eid = (make_entity_id('NL', 'SO', org['tooi'][1]) if org['tooi'][0] == 'so'
               else make_entity_id('NL', 'OO', org['id']))
        body = bodies.setdefault(eid, {'org': org, 'members': {}, 'doelen': [], 'owms': []})
        body['doelen'].append(gr['doel'])
        body['owms'].append(gr['owms'])
        for soort, mcode, joined in gr['members']:
            prefix, kind = {'gemeente': ('GM', 'nl_gemeente'), 'provincie': ('PV', 'nl_provincie'),
                            'waterschap': ('WS', 'nl_waterschap')}[soort]
            mid = make_entity_id('NL', prefix, mcode)
            if soort == 'waterschap' and mid not in ws_ids:
                continue  # opgeheven waterschap
            old = body['members'].get(mid)
            if old is None or (joined and (not old[1] or joined < old[1])):
                body['members'][mid] = (kind, joined)
    descriptions = {}
    for eid, body in bodies.items():
        org = body['org']
        kind = 'nl_veiligheidsregio' if _is_veiligheidsregio(org['name']) else 'nl_samenwerking'
        text = _description(org['name'], body['doelen'], body['owms'])
        if text:
            descriptions[eid] = text
        rows.append(new_entity(
            entity_id=eid, name=org['name'], country='NL', kind=kind,
            population_method='sum of members', official_ids=_official_ids(org),
            source=OO_SOURCE, source_date=source_date))
        for mid, (mkind, joined) in body['members'].items():
            members[(eid, mid)] = {'entity_id': eid, 'member_entity_id': mid, 'member_kind': mkind,
                                   'membership_type': 'cooperation', 'join_date': joined}

    bundle = SourceBundle.empty()
    bundle.entities = pd.DataFrame(rows, columns=bundle.entities.columns)
    bundle.memberships = pd.DataFrame(list(members.values()), columns=bundle.memberships.columns)
    # Eén patch per gemeente-id; bij dubbele organisaties de official_ids samenvoegen
    merged = {}
    for pt in patches:
        parts = merged.setdefault(pt['entity_id'], [])
        parts.extend(x for x in pt['official_ids'].split(';') if x and x not in parts)
    patches = [{'entity_id': k, 'official_ids': ';'.join(v)} for k, v in merged.items()]
    bundle.extras['id_patches'] = pd.DataFrame(patches, columns=_OO_COLUMNS)
    # entity_id -> doel/OWMS-naam van het orgaan, voor de classificatie (F5)
    bundle.extras['coop_descriptions'] = descriptions
    counts = bundle.entities['kind'].value_counts().to_dict()
    msg = (f'{n_active} actieve GR\'en ({n_nobody} zonder orgaan), {len(bodies)} organen, '
           f'{counts.get("nl_veiligheidsregio", 0)} veiligheidsregio\'s, '
           f'{counts.get("nl_waterschap", 0)} waterschappen, {n_nat["nl_ministerie"]} ministeries, '
           f'{n_nat["nl_rijksorganisatie"]} rijksorganisaties, {len(patches)} gemeente-id-patches, '
           f'{len(descriptions)} organen met doel/OWMS-naam')
    log.info('OO: %s', msg)
    bundle.status.append(SourceStatus('nl_oo', True, len(bundle.entities), source_date, msg))
    return bundle


def load_nl_oo(cache: SourceCache) -> SourceBundle:
    try:
        path = cache.fetch('nl_oo_export', OO_URL, suffix='.xml')
        return parse_oo_export(path, date.today())
    except Exception as e:  # noqa: BLE001
        log.error('OO-register mislukt: %s', e)
        bundle = SourceBundle.empty()
        bundle.status.append(SourceStatus('nl_oo', False, 0, '', f'mislukt: {e}'))
        return bundle


# ---------------------------------------------------------------------------
# NL-handrijen: Amsterdamse stadsdelen (Caribisch deel: tam/sources/carib.py)
# ---------------------------------------------------------------------------
def _hand_entity(eid, name, kind, row, region=''):
    pop = row.get('population')
    return new_entity(
        entity_id=eid, name=name, country='NL', kind=kind, region=region,
        population=pop, population_method='own' if pop is not None else 'unknown',
        population_source=row['bron_url'] if pop is not None else '',
        population_date=str(row.get('peildatum', '')) if pop is not None else '',
        official_ids=row.get('official_ids', ''), source=row['bron_url'],
        source_date=str(row.get('peildatum', '')))


def load_nl_hand() -> SourceBundle:
    """Stadsdelen (step2_enrich.NL_STADSDEEL_INWONERS, ontdubbeld per bron_url). De openbare
    lichamen en de Caribische landen staan sinds spec sectie 15 in tam/sources/carib.py."""
    rows, aliases = [], []

    # Stadsdelen: de step2-tabel heeft per stadsdeel twee sleutels met dezelfde bron_url
    per_url: dict[str, list[str]] = {}
    for key, value in NL_STADSDEEL_INWONERS.items():
        per_url.setdefault(value['bron_url'], []).append(key)
    for url, keys in per_url.items():
        fixed = hand_tables.NL_STADSDEEL_IDS.get(url)
        if fixed is None:
            log.warning('Stadsdeel met bron %s heeft geen vaste id in NL_STADSDEEL_IDS; overgeslagen', url)
            continue
        value = NL_STADSDEEL_INWONERS[keys[0]]
        rows.append(_hand_entity(fixed['id'], fixed['name'], 'nl_stadsdeel', value, region='Amsterdam'))
        # Geen kale step2-sleutels ('Centrum', 'Noord') als alias: te algemeen
        for alias in fixed.get('aliases', []):
            aliases.append({'alias_name': alias, 'country': 'NL', 'entity_id': fixed['id'],
                            'reason': 'andere naam (handtabel)'})

    bundle = SourceBundle.empty()
    bundle.entities = pd.DataFrame(rows, columns=bundle.entities.columns)
    bundle.aliases = pd.DataFrame(aliases, columns=ALIAS_COLUMNS)
    counts = bundle.entities['kind'].value_counts().to_dict()
    msg = ', '.join(f'{v} {k}' for k, v in sorted(counts.items()))
    bundle.status.append(SourceStatus('nl_hand', True, len(rows), '', msg))
    return bundle
