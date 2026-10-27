"""Voorgangers van gefuseerde gemeenten als aliassen (Wikidata P576 + P1366).

Een opgeheven gemeente (P576) met opvolger (P1366) wordt een aliasrij die naar
de huidige entiteit van de opvolger wijst (bv. Bussum -> Gooise Meren).
Ketens (A -> B -> C) worden gevolgd tot de huidige entiteit.
"""
from __future__ import annotations

import logging

import pandas as pd

from step2_enrich import normalize
from tam.entities import ALIAS_COLUMNS, SourceBundle, SourceStatus

log = logging.getLogger(__name__)

MAX_DEPTH = 5
DE_PREFIXES = [f'{i:02d}' for i in range(1, 17)]

# land -> (klasse-filter of None, code-eigenschap, labeltalen, wikipedia-taal)
_CONFIG = {
    'NL': ('?pred wdt:P31 wd:Q2039348 .', 'P382', 'nl,fr,de,en', 'nl'),
    'BE': ('?pred wdt:P31 wd:Q493522 .', 'P1567', 'nl,fr,de,en', 'nl'),
    'DE': ('?pred wdt:P439 ?predAgs .', 'P439', 'de,en', 'de'),
}


def resolve_chain(edges: dict[str, str], current: set[str]) -> dict[str, str]:
    """Volg elke rand naar een huidige knoop (max MAX_DEPTH stappen).

    Knopen in een cyclus of zonder pad naar een huidige knoop vallen weg.
    """
    result = {}
    for start in edges:
        node, seen = start, {start}
        for _ in range(MAX_DEPTH):
            node = edges.get(node)
            if node is None or node in seen:
                node = None
                break
            if node in current:
                break
            seen.add(node)
        else:
            node = None
        if node is not None and node in current:
            result[start] = node
    return result


def _query(country: str, ags_prefix: str | None = None) -> str:
    cls, code_prop, langs, wiki = _CONFIG[country]
    prefix_filter = f'FILTER(STRSTARTS(?predAgs, "{ags_prefix}"))' if ags_prefix else ''
    return f"""
    SELECT ?pred ?predLabel ?article ?end ?succ ?succLabel ?code WHERE {{
      {cls}
      ?pred wdt:P576 ?end ; wdt:P1366 ?succ .
      {prefix_filter}
      OPTIONAL {{ ?succ wdt:{code_prop} ?code . }}
      OPTIONAL {{
        ?art schema:about ?pred ;
             schema:isPartOf <https://{wiki}.wikipedia.org/> ;
             schema:name ?article .
      }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{langs}". }}
    }}
    """


def _entity_id(country: str, code: str) -> str:
    code = str(code).strip()
    if not code:
        return ''
    if country == 'NL':
        digits = code[2:] if code.upper().startswith('GM') else code
        return f'NL-GM-GM{digits.zfill(4)}'
    if country == 'BE':
        return f'BE-NIS-{code.zfill(5)}'
    return f'DE-AGS-{code.zfill(8)}'


def _is_qid(text: str) -> bool:
    return len(text) > 1 and text[0] == 'Q' and text[1:].isdigit()


def _label(row) -> str:
    for key in ('predLabel', 'article'):
        value = str(row.get(key, '') or '').strip()
        if value and not _is_qid(value):
            return value
    return ''


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    if name in df.columns:
        return df[name].fillna('').astype(str)
    return pd.Series([''] * len(df), index=df.index)


def parse_aliases(df: pd.DataFrame, country: str, entity_ids: set[str],
                  alias_ids: dict[str, str], alias_lookup: dict[str, set[str]]):
    """Bindings -> (aliasrijen, aantal overgeslagen). Pure functie."""
    if df is None or df.empty:
        return [], 0
    df = df.copy()
    for name in ('pred', 'predLabel', 'article', 'end', 'succ', 'succLabel', 'code'):
        df[name] = _col(df, name)
    df['pred'] = df['pred'].str.rsplit('/', n=1).str[-1]
    df['succ'] = df['succ'].str.rsplit('/', n=1).str[-1]

    # opvolger-qid -> huidige entiteit (via code, alias_ids of aliastabel)
    qid_entity: dict[str, str] = {}
    for succ, label, code in zip(df['succ'], df['succLabel'], df['code']):
        if not succ or succ in qid_entity:
            continue
        eid = _entity_id(country, code) if code else ''
        if eid in entity_ids:
            qid_entity[succ] = eid
        elif eid in alias_ids and alias_ids[eid] in entity_ids:
            qid_entity[succ] = alias_ids[eid]
    for succ, label in zip(df['succ'], df['succLabel']):
        if succ in qid_entity or not label or _is_qid(label):
            continue
        targets = alias_lookup.get(normalize(label), set())
        if len(targets) == 1:
            qid_entity[succ] = next(iter(targets))

    # opvolgers per voorganger; meerdere verschillende opvolgers = niet eenduidig
    successors: dict[str, set[str]] = {}
    for pred, succ in zip(df['pred'], df['succ']):
        if pred and succ:
            successors.setdefault(pred, set()).add(succ)
    edges, skipped = {}, 0
    for pred, succs in successors.items():
        targets = {qid_entity.get(s) for s in succs}
        if len(succs) == 1 or (len(targets) == 1 and None not in targets):
            edges[pred] = sorted(succs)[0]
        else:
            skipped += 1
    resolved = resolve_chain(edges, set(qid_entity))

    first = df.drop_duplicates('pred').set_index('pred')
    years = {}
    for pred, end in zip(df['pred'], df['end']):
        year = end[:4]
        if year.isdigit():
            years[pred] = max(years.get(pred, year), year)
    rows, seen = [], set()
    for pred in edges:
        if pred not in resolved:
            skipped += 1
            continue
        name = _label(first.loc[pred])
        eid = qid_entity[resolved[pred]]
        if not name:
            skipped += 1
            continue
        key = (name, eid)
        if key in seen:
            continue
        seen.add(key)
        year = years.get(pred, '')
        reason = f'predecessor, merged {year}' if year else 'predecessor'
        rows.append({'alias_name': name, 'country': country, 'entity_id': eid, 'reason': reason})
    return rows, skipped


def _fetch(cache, country: str) -> pd.DataFrame:
    name = f'aliases_{country.lower()}'
    if country != 'DE':
        return cache.sparql(name, _query(country))
    try:
        return cache.sparql(name, _query(country))
    except Exception as exc:  # te grote of te trage query: per Bundesland
        log.warning(f'  aliases DE in een keer mislukt ({exc}); per Bundesland')
    parts = []
    for prefix in DE_PREFIXES:
        part = cache.sparql(f'{name}_{prefix}', _query(country, prefix))
        if len(part):
            parts.append(part)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def load_predecessors(cache, entities: pd.DataFrame, aliases: pd.DataFrame,
                      alias_ids: dict[str, str] | None = None) -> SourceBundle:
    """Aliasrijen voor opgeheven gemeenten (alleen `aliases` gevuld).

    alias_ids: optionele map van een niet-entiteit (bv. DE-AGS-<8> van een
    Gemeinde in een Amt) naar de entity_id waartoe die hoort; de master bouwt
    die uit de DE-GV-data. Opvolgers zonder code worden ook gezocht via de
    naam in `aliases`.
    """
    alias_ids = alias_ids or {}
    entity_ids = set(entities['entity_id']) if len(entities) else set()
    bundle = SourceBundle.empty()
    all_rows, problems, skipped_total = [], [], 0
    for country in ('NL', 'BE', 'DE'):
        lookup: dict[str, set[str]] = {}
        if aliases is not None and len(aliases):
            for r in aliases[aliases['country'] == country].itertuples():
                lookup.setdefault(normalize(r.alias_name), set()).add(r.entity_id)
        try:
            df = _fetch(cache, country)
            rows, skipped = parse_aliases(df, country, entity_ids, alias_ids, lookup)
        except Exception as exc:
            log.warning(f'  aliases {country} mislukt: {exc}')
            problems.append(f'{country}: {exc}')
            continue
        log.info(f'  aliases {country}: {len(rows)} voorgangers, {skipped} overgeslagen')
        all_rows.extend(rows)
        skipped_total += skipped
    if all_rows:
        bundle.aliases = pd.DataFrame(all_rows, columns=ALIAS_COLUMNS)
    counts = ', '.join(f'{c} {sum(r["country"] == c for r in all_rows)}' for c in ('NL', 'BE', 'DE'))
    message = f'{counts}; {skipped_total} overgeslagen'
    if problems:
        message += '; mislukt: ' + ' | '.join(problems)
    bundle.status.append(SourceStatus('aliases', not problems, len(all_rows), '', message))
    return bundle
