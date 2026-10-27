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
"""
from __future__ import annotations

import json
import logging
import re

import pandas as pd

from step2_enrich import CBS_ODATA_URL, discover_cbs_gebieden_table
from tam.config import USER_AGENT
from tam.entities import SourceBundle, SourceStatus, make_entity_id, new_entity
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
        if not pv_code:
            continue
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
