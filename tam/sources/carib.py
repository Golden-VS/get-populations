"""Lader voor het Caribisch deel van het Koninkrijk en Suriname (spec sectie 15).

Alleen handtabellen (tam/hand_tables_carib.py), geen download en geen afhankelijkheden.
Landrijen, eilanden en districten hebben een eigen bevolking ('own'); regering, ministeries en
Rijksdienst krijgen het landtotaal ('country total', ingevuld door de master).
"""
from __future__ import annotations

import logging

import pandas as pd

from tam import hand_tables_carib as hc
from tam.entities import ALIAS_COLUMNS, SourceBundle, SourceStatus, new_entity

log = logging.getLogger(__name__)

# Kinds met een landtotaal in plaats van een eigen bevolking
COUNTRY_TOTAL_KINDS = frozenset({'carib_ministerie', 'bq_rijksdienst', 'sr_regering', 'sr_ministerie'})


def _entity(name: str, row: dict) -> dict:
    pop = row.get('population')
    if row['kind'] in COUNTRY_TOTAL_KINDS:
        method = 'country total'
    else:
        method = 'own' if pop is not None else 'unknown'
    has_pop = pop is not None
    return new_entity(
        entity_id=row['id'], name=name, country=row['country'], kind=row['kind'],
        population=pop, population_method=method,
        population_source=row['bron_url'] if has_pop else '',
        population_date=str(row.get('peildatum', '')) if has_pop else '',
        official_ids=row.get('official_ids', ''), source=row['bron_url'],
        source_date=str(row.get('peildatum', '')))


def load_carib_sr() -> SourceBundle:
    """AW/CW/SX (land + ministeries), BQ (openbare lichamen + Rijksdienst) en SR (regering,
    ministeries, districten) uit de handtabellen."""
    rows, aliases = [], []
    for table in hc.TABLES:
        for name, row in table.items():
            entity = _entity(name, row)
            rows.append(entity)
            if entity['population_method'] == 'unknown':
                log.warning('%s (%s): geen officieel bevolkingscijfer in de handtabel (bron: %s)',
                            name, row['id'], row['bron_url'])
            for alias in row.get('aliases', []):
                aliases.append({'alias_name': alias, 'country': row['country'], 'entity_id': row['id'],
                                'reason': 'andere naam (handtabel)'})

    bundle = SourceBundle.empty()
    bundle.entities = pd.DataFrame(rows, columns=bundle.entities.columns)
    bundle.aliases = pd.DataFrame(aliases, columns=ALIAS_COLUMNS)
    counts = bundle.entities.groupby('country').size().to_dict()
    msg = ', '.join(f'{c}: {counts.get(c, 0)}' for c in ('AW', 'CW', 'SX', 'BQ', 'SR'))
    log.info('Caribisch deel en Suriname: %d entiteiten (%s)', len(rows), msg)
    bundle.status.append(SourceStatus('carib_sr', True, len(rows), hc.CONSULTED, msg))
    return bundle
