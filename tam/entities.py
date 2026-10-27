"""Entiteitsmodel en bevolkingsregels voor de TAM/whitespace-lijstbouwer."""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field

import pandas as pd

from tam.config import KIND_TO_SEGMENT

log = logging.getLogger(__name__)

ENTITY_COLUMNS = [
    'entity_id', 'name', 'match_name', 'country', 'kind', 'segment', 'detailed_segment',
    'region', 'postcode', 'population', 'population_method', 'population_source',
    'population_date', 'official_ids', 'source', 'source_date',
]
MEMBERSHIP_COLUMNS = ['entity_id', 'member_entity_id', 'member_kind', 'membership_type', 'join_date']
ALIAS_COLUMNS = ['alias_name', 'country', 'entity_id', 'reason']


@dataclass
class SourceStatus:
    name: str
    ok: bool
    rows: int
    source_date: str
    message: str


def _empty(columns):
    return pd.DataFrame(columns=columns)


@dataclass
class SourceBundle:
    entities: pd.DataFrame
    memberships: pd.DataFrame
    aliases: pd.DataFrame
    status: list = field(default_factory=list)
    extras: dict = field(default_factory=dict)

    @staticmethod
    def empty() -> 'SourceBundle':
        return SourceBundle(_empty(ENTITY_COLUMNS), _empty(MEMBERSHIP_COLUMNS), _empty(ALIAS_COLUMNS))

    def merge(self, other: 'SourceBundle') -> 'SourceBundle':
        def cat(a, b):
            frames = [f for f in (a, b) if len(f)]
            if not frames:
                return a.copy()
            if len(frames) == 1:
                return frames[0].reset_index(drop=True)
            # Kolommen die in een frame volledig leeg (NA) zijn niet meenemen in de concat
            # (pandas-3-gedrag rond dtypes); daarna de vaste kolomvolgorde herstellen
            columns = list(dict.fromkeys(list(a.columns) + list(b.columns)))
            trimmed = [f.dropna(axis=1, how='all') for f in frames]
            return pd.concat(trimmed, ignore_index=True).reindex(columns=columns)

        extras = dict(self.extras)
        for key, value in other.extras.items():
            old = extras.get(key)
            if isinstance(value, pd.DataFrame) and isinstance(old, pd.DataFrame):
                extras[key] = pd.concat([old, value], ignore_index=True)
            elif isinstance(value, dict) and isinstance(old, dict):
                merged = dict(old)
                merged.update(value)
                extras[key] = merged
            else:
                extras[key] = value
        return SourceBundle(
            cat(self.entities, other.entities),
            cat(self.memberships, other.memberships),
            cat(self.aliases, other.aliases),
            list(self.status) + list(other.status),
            extras,
        )


def make_entity_id(country: str, scheme: str, code: str) -> str:
    """Deterministische id; code wordt getrimd, witruimte samengevoegd en hoofdletters."""
    clean = re.sub(r'\s+', ' ', str(code)).strip().upper()
    return f'{country}-{scheme.upper()}-{clean}'


_TRANSLIT = {'ß': 'ss', 'ø': 'o', 'ł': 'l', 'æ': 'ae', 'œ': 'oe', 'đ': 'd'}


def slugify(text: str) -> str:
    """Kleine letters, puur ascii, gescheiden met '-'; lidwoorden blijven staan."""
    s = unicodedata.normalize('NFKD', str(text))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = ''.join(_TRANSLIT.get(c.lower(), c) for c in s)
    s = s.encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def new_entity(**fields) -> dict:
    """Nieuwe entiteit met alle kolommen; segment/detailed volgen uit kind."""
    row = {c: '' for c in ENTITY_COLUMNS}
    row['population'] = None
    row.update(fields)
    seg = KIND_TO_SEGMENT.get(row['kind'])
    if seg:
        if not fields.get('segment'):
            row['segment'] = seg[0]
        if not fields.get('detailed_segment') and seg[1]:
            row['detailed_segment'] = seg[1]
    if not fields.get('match_name'):
        row['match_name'] = row['name']
    return row


def _is_empty(value) -> bool:
    return value is None or value == '' or pd.isna(value)


def apply_member_population(entities, memberships, municipal_population):
    """Som van unieke gemeente-leden voor 'sum of members'-rijen zonder bevolking."""
    out = entities.copy()
    warnings: list[str] = []
    members_by_entity = {}
    if len(memberships):
        for eid, group in memberships.groupby('entity_id'):
            members_by_entity[eid] = list(dict.fromkeys(group['member_entity_id']))
    for idx, row in out.iterrows():
        if row['population_method'] != 'sum of members' or not _is_empty(row['population']):
            continue
        members = members_by_entity.get(row['entity_id'], [])
        found = [m for m in members if m in municipal_population]
        if found:
            out.at[idx, 'population'] = sum(municipal_population[m] for m in found)
        else:
            out.at[idx, 'population'] = float('nan')
            out.at[idx, 'population_method'] = 'unknown'
            warnings.append(
                f"Geen leden met bekende bevolking voor {row['entity_id']} ({row['name']}); "
                f"ledenlijst: {', '.join(members) if members else '(leeg)'}")
    return out, warnings


def apply_country_totals(entities, municipal_population):
    """'country total'-rijen krijgen de som van alle gemeenten van hun land."""
    out = entities.copy()
    totals: dict[str, int] = {}
    for mid, pop in municipal_population.items():
        prefix = mid.split('-', 1)[0]
        totals[prefix] = totals.get(prefix, 0) + pop
    mask = out['population_method'] == 'country total'
    for idx in out.index[mask]:
        country = out.at[idx, 'country']
        if country in totals:
            out.at[idx, 'population'] = totals[country]
        else:
            log.warning("Geen gemeentebevolking voor land %s; 'country total' blijft leeg voor %s",
                        country, out.at[idx, 'entity_id'])
    return out
