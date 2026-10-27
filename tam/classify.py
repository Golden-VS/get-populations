"""Classificatie van samenwerkingsverbanden naar detailed segment (regels, cache, Claude)."""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel

from tam.ai import (AIBatchError, AIRefusal, CostCapReached, atomic_write_csv, call_parsed,
                    estimate_cost)
from tam.config import DETAILED_SEGMENTS, KIND_TO_SEGMENT, MODEL, REFERENCE_DIR
from tam.entities import slugify

log = logging.getLogger(__name__)

OTHER = 'Other joint arrangement'
CACHE_COLUMNS = ['entity_id', 'name', 'detailed_segment', 'bron', 'datum']
# Grove schatting per batch van 25 items (invoer incl. systeemprompt, uitvoer)
EST_IN_TOKENS_PER_BATCH = 2500
EST_OUT_TOKENS_PER_BATCH = 1500

SYSTEM_PROMPT = """Je bent een analist overheidsdata. Je classificeert samenwerkingsverbanden
tussen gemeenten (Nederland, Belgie, Duitsland) in een vast schema op basis van naam, land,
soort en aantal leden. Namen kunnen Nederlands, Frans, Duits of Engels zijn.

Kies voor elk genummerd item exact een "detailed_segment" uit deze lijst:
   - Municipal federation: Gemeindeverband, federatie van gemeenten
   - Shared service organization: gedeelde backoffice of uitvoeringsdienst (bv. P&O, ICT-diensten, sociale dienst)
   - IT cooperation: gezamenlijke ICT, rekencentrum, digitalisering
   - Tax cooperation: gezamenlijke belastingheffing en -invordering
   - Environmental agency: omgevingsdienst, milieu- en vergunningendienst
   - Public health service (GGD): gezondheidsdienst (GGD, GGD en GHOR)
   - Social employment & work: sociale werkvoorziening, re-integratie, werkbedrijf
   - Waste management: afval- en grondstoffenbeheer, reiniging
   - Recreation authority: recreatieschap, recreatiegebied, natuur- en landschapspark
   - Procurement cooperation: gezamenlijke inkoop
   - Transport authority: vervoersregio, openbaar vervoer
   - Regional cooperation: brede regionale samenwerking of regio (bv. regio X, regionaal samenwerkingsverband)
   - Welfare association: welzijnsvereniging (Belgie)
   - Special-purpose association: Zweckverband voor een enkel doel
   - Other joint arrangement: past in geen van de andere categorieen

REGELS:
- Gebruik alleen de naam, het land, de soort en het aantal leden; verzin geen feiten.
- Twijfel je tussen een specifieke categorie en "Other joint arrangement", kies dan "Other joint arrangement".
- Geef voor elk nummer in de invoer precies een antwoord terug, met hetzelfde volgnummer.
"""

_DetailedLiteral = Literal[tuple(DETAILED_SEGMENTS['Inter-municipal cooperation'])]


class ClassItem(BaseModel):
    volgnummer: int
    detailed_segment: _DetailedLiteral


class ClassBatch(BaseModel):
    items: list[ClassItem]


def estimate_classification_cost(n_pending: int, batch_size: int = 25) -> float:
    """Geschatte AI-kosten (USD) voor n_pending nog te classificeren rijen."""
    return estimate_cost(n_pending, batch_size, EST_IN_TOKENS_PER_BATCH,
                         EST_OUT_TOKENS_PER_BATCH)


def build_user_message(rows: list[dict], member_counts: dict) -> str:
    lines = []
    for i, r in enumerate(rows, start=1):
        parts = [f"volgnummer {i}", f"naam: {r['name']}"]
        if r.get('country'):
            parts.append(f"land: {r['country']}")
        parts.append(f"soort: {r['kind']}")
        n = member_counts.get(r['entity_id'])
        if n:
            parts.append(f'leden: {n}')
        lines.append(' | '.join(parts))
    return 'Classificeer deze samenwerkingen:\n\n' + '\n'.join(lines)


def _rule(name: str) -> str | None:
    """Naamregels op genormaliseerde naam (slug, woorden gescheiden door '-')."""
    slug = slugify(name)
    if 'omgevingsdienst' in slug:
        return 'Environmental agency'
    if re.search(r'(^|-)ggd(-|$)', slug):
        return 'Public health service (GGD)'
    if 'belasting' in slug:
        return 'Tax cooperation'
    return None


def _save_cache(path: Path, rows: dict) -> None:
    atomic_write_csv(pd.DataFrame(
        [{'entity_id': k, 'name': v[0], 'detailed_segment': v[1], 'bron': v[2], 'datum': v[3]}
         for k, v in rows.items()], columns=CACHE_COLUMNS,
    ), path)


def classify_cooperations(entities: pd.DataFrame, client, tracker, *, use_ai: bool,
                          cache_path: Path = REFERENCE_DIR / 'classify_cache.csv',
                          batch_size: int = 25, rules_only: bool = False,
                          member_counts: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Vult detailed_segment voor rijen waarvan KIND_TO_SEGMENT geen vaste waarde heeft."""
    member_counts = member_counts or {}
    out = entities.copy()
    # unclassified = cap + no_ai + failed (reden van 'Other joint arrangement')
    stats = {'rule': 0, 'cached': 0, 'ai': 0, 'unclassified': 0, 'cap': 0, 'no_ai': 0,
             'failed': 0, 'pending': 0, 'unclassified_ids': []}
    todo_kinds = {k for k, (_, d) in KIND_TO_SEGMENT.items() if d is None}
    todo = out.index[out['kind'].isin(todo_kinds)
                     & (out['detailed_segment'].fillna('') == '')]

    cache_rows = {}
    if Path(cache_path).exists():
        try:
            df = pd.read_csv(cache_path, dtype=str, keep_default_na=False)
            if list(df.columns) != CACHE_COLUMNS:
                raise ValueError(f'onverwachte kolommen {list(df.columns)}')
            cache_rows = {r.entity_id: (r.name, r.detailed_segment, r.bron, r.datum)
                          for r in df.itertuples()}
        except Exception as e:
            log.warning('Classificatiecache onleesbaar of oud schema, negeer cache: %s', e)
            cache_rows = {}
    valid = {d for d in DETAILED_SEGMENTS['Inter-municipal cooperation']}

    remaining = []
    for idx in todo:
        row = out.loc[idx]
        rule = _rule(row['name'])
        if rule:
            out.at[idx, 'detailed_segment'] = rule
            stats['rule'] += 1
            continue
        hit = cache_rows.get(row['entity_id'])
        if hit and hit[0] == row['name'] and hit[1] in valid:
            out.at[idx, 'detailed_segment'] = hit[1]
            stats['cached'] += 1
            continue
        remaining.append(idx)

    if rules_only:
        stats['pending'] = len(remaining)
        return out, stats

    def mark_other(indices, reason, counter):
        for idx in indices:
            out.at[idx, 'detailed_segment'] = OTHER
            stats['unclassified'] += 1
            stats[counter] += 1
            stats['unclassified_ids'].append(out.at[idx, 'entity_id'])
            log.warning('Niet geclassificeerd (%s): %s [%s]', reason,
                        out.at[idx, 'name'], out.at[idx, 'entity_id'])

    if not use_ai:
        mark_other(remaining, 'AI uit', 'no_ai')
        return out, stats

    est = estimate_classification_cost(batch_size, batch_size)
    for start in range(0, len(remaining), batch_size):
        batch = remaining[start:start + batch_size]
        rows = [out.loc[i].to_dict() for i in batch]
        try:
            parsed = call_parsed(client, tracker, system=SYSTEM_PROMPT,
                                 user=build_user_message(rows, member_counts),
                                 output_model=ClassBatch, estimated_cost=est)
        except CostCapReached as e:
            log.warning('Kostenplafond bereikt tijdens classificatie: %s', e)
            mark_other(remaining[start:], 'kostenplafond', 'cap')
            break
        except (AIRefusal, AIBatchError) as e:
            log.warning('Batch mislukt: %s', e)
            mark_other(batch, 'batch mislukt', 'failed')
            continue
        answers = {it.volgnummer: it.detailed_segment for it in parsed.items}
        missing = []
        for n, idx in enumerate(batch, start=1):
            seg = answers.get(n)
            if seg is None:
                missing.append(idx)
                continue
            out.at[idx, 'detailed_segment'] = seg
            stats['ai'] += 1
            cache_rows[out.at[idx, 'entity_id']] = (
                out.at[idx, 'name'], seg, f'Claude {MODEL}', date.today().isoformat())
        mark_other(missing, 'ontbreekt in antwoord', 'failed')
        _save_cache(cache_path, cache_rows)
    return out, stats
