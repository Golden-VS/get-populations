"""Belgische gewesten (Vlaanderen / Brussel / Wallonie) per entiteit, voor de kolom regions
in het template: per kernproduct kan de business Wallonie en/of Brussel uitsluiten.

Volgorde van bepalen:
  1. NIS-code in de id (gemeenten, provincies): uit de code zelf.
  2. Vaste waarde per bron of soort: gewesten/gemeenschappen (handtabel), districten
     (alleen Antwerpen), Waalse intercommunales (SPW), Brusselse intercommunales (handtabel).
  3. Leden (elk lidmaatschapstype, ook same_as): de unie van de gewesten van de leden;
     herhaald zodat samenwerkingen van samenwerkingen ook een gewest krijgen.
  4. Rest uit de OP-dump (Vlaamse lokale besturen): Vlaanderen.
FOD's/POD's zijn federaal en krijgen geen gewest: die vallen nooit weg op regions.
"""
from __future__ import annotations

import logging
import unicodedata

import pandas as pd

log = logging.getLogger(__name__)

BE_REGIONS = ['Vlaanderen', 'Brussel', 'Wallonie']
SEP = '; '

# Handtabel-ids van gewesten en gemeenschappen (tam/hand_tables.py)
_FIXED_IDS = {
    'BE-HAND-GEWEST-VLAANDEREN': ['Vlaanderen'],
    'BE-HAND-GEWEST-WALLONIE': ['Wallonie'],
    'BE-HAND-GEWEST-BRUSSEL': ['Brussel'],
    'BE-HAND-GEMEENSCHAP-DG': ['Wallonie'],
    'BE-HAND-GEMEENSCHAP-FWB': ['Brussel', 'Wallonie'],
}
_FIXED_PREFIXES = {
    'BE-SPW-': ['Wallonie'],         # Waals kadaster intercommunales
    'BE-HAND-BXL-': ['Brussel'],     # Brusselse intercommunales
}
_FIXED_KINDS = {'be_district': ['Vlaanderen']}   # alleen de districten van Antwerpen
_NATIONAL_KINDS = {'be_fod'}
_OP_SOURCE = 'OP-dump Agentschap Binnenland'


def _key(text) -> str:
    s = unicodedata.normalize('NFKD', str(text or ''))
    return ''.join(c for c in s if not unicodedata.combining(c)).strip().casefold()


_BY_KEY = {_key(r): r for r in BE_REGIONS}


def canonical_region(text) -> str | None:
    """'wallonië' -> 'Wallonie'; onbekend -> None."""
    return _BY_KEY.get(_key(text))


def region_of_nis(code) -> str | None:
    """Gewest van een gemeente- of provincie-NIS-code (2025-codes), None als leeg."""
    c = str(code or '').replace('BE-NIS-', '').strip()
    if not c:
        return None
    if c.startswith('21') or c == '04000':
        return 'Brussel'
    if c.startswith('25') or c == '20002' or c[0] in '5689':
        return 'Wallonie'
    return 'Vlaanderen'


def join_regions(regions) -> str:
    """Vaste volgorde (Vlaanderen, Brussel, Wallonie), gescheiden door '; '."""
    return SEP.join(r for r in BE_REGIONS if r in set(regions))


def split_regions(value) -> set[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return set()
    return {p.strip() for p in str(value).split(';') if p.strip()}


def apply_be_regions(entities: pd.DataFrame, memberships: pd.DataFrame,
                     warnings: list[str] | None = None) -> pd.DataFrame:
    """Vul kolom be_region voor alle BE-entiteiten (andere landen blijven leeg)."""
    out = entities.copy()
    out['be_region'] = ''
    be = out['country'] == 'BE'
    found: dict[str, set[str]] = {}
    for eid, kind in out.loc[be, ['entity_id', 'kind']].values:
        if kind in _NATIONAL_KINDS:
            continue
        if eid.startswith('BE-NIS-'):
            found[eid] = {region_of_nis(eid)}
        elif eid in _FIXED_IDS:
            found[eid] = set(_FIXED_IDS[eid])
        elif kind in _FIXED_KINDS:
            found[eid] = set(_FIXED_KINDS[kind])
        else:
            for prefix, regions in _FIXED_PREFIXES.items():
                if eid.startswith(prefix):
                    found[eid] = set(regions)

    if len(memberships):
        members: dict[str, set[str]] = {}
        for eid, mid in memberships[['entity_id', 'member_entity_id']].values:
            members.setdefault(eid, set()).add(mid)
        changed = True
        while changed:
            changed = False
            for eid, mids in members.items():
                if eid in found or not eid.startswith('BE-'):
                    continue
                regions = set().union(*(found.get(m, set()) for m in mids))
                if regions:
                    found[eid] = regions
                    changed = True

    for idx in out.index[be]:
        eid = out.at[idx, 'entity_id']
        if eid not in found and out.at[idx, 'source'] == _OP_SOURCE:
            found[eid] = {'Vlaanderen'}

    missing = []
    for idx in out.index[be]:
        eid = out.at[idx, 'entity_id']
        if eid in found:
            out.at[idx, 'be_region'] = join_regions(found[eid])
        elif out.at[idx, 'kind'] not in _NATIONAL_KINDS:
            missing.append(f'{eid} ({out.at[idx, "name"]})')
    if missing:
        msg = (f'{len(missing)} BE-entiteiten zonder gewest (vallen nooit weg op regions): '
               f'{", ".join(missing[:10])}{" ..." if len(missing) > 10 else ""}')
        log.warning(msg)
        if warnings is not None:
            warnings.append(msg)
    return out
