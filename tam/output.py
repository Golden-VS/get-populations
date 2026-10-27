"""Uitvoerwerkboek en runlog."""
import json
import logging
from pathlib import Path

import pandas as pd

from tam.config import REFERENCE_DIR

log = logging.getLogger(__name__)
SHEETS = ['TAM', 'CRM matches', 'Entities', 'Memberships', 'CRM unmatched', 'Run log']


def check_known_detailed(values: set, path: Path = REFERENCE_DIR / 'known_detailed.json',
                         *, save: bool = True) -> set:
    """Geef waarden die in eerdere runs niet voorkwamen; met save=True ook de unie bewaren."""
    path = Path(path)
    known = set()
    if path.exists():
        known = set(json.loads(path.read_text(encoding='utf-8')))
    new = set(values) - known
    if not save:
        return new
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(known | set(values)), ensure_ascii=False, indent=1),
                    encoding='utf-8')
    return new


def _memberships_sheet(memberships: pd.DataFrame, entities: pd.DataFrame) -> pd.DataFrame:
    coop = memberships[memberships['membership_type'] == 'cooperation'].copy()
    seg = dict(zip(entities['entity_id'], entities['detailed_segment']))
    missing = sorted(set(coop['entity_id']) - set(seg))
    if missing:
        log.warning('samenwerking niet in entities: %s', ', '.join(missing))
    coop.insert(1, 'detailed_segment', coop['entity_id'].map(seg).fillna(''))
    return coop.drop(columns=['membership_type']).reset_index(drop=True)


def write_output(path: Path, *, tam, matches, entities, memberships, unmatched, run_log) -> list:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheets = {
        'TAM': tam, 'CRM matches': matches, 'Entities': entities,
        'Memberships': _memberships_sheet(memberships, entities),
        'CRM unmatched': unmatched,
        'Run log': pd.DataFrame(run_log, columns=['onderwerp', 'waarde']),
    }
    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        for name in SHEETS:
            df = sheets[name].copy()
            if 'official_ids' in df.columns:
                df['official_ids'] = df['official_ids'].map(lambda v: '' if v is None else str(v))
            df.to_excel(writer, sheet_name=name, index=False)
            ws = writer.sheets[name]
            ws.freeze_panes = 'A2'
            ws.auto_filter.ref = ws.dimensions
            if 'official_ids' in df.columns:
                col = list(df.columns).index('official_ids') + 1
                for row in ws.iter_rows(min_row=2, min_col=col, max_col=col):
                    for cell in row:
                        cell.number_format = '@'
                        cell.data_type = 's'
    return [path]


def _require(df, columns, what):
    if not isinstance(df, pd.DataFrame) or not set(columns) <= set(df.columns):
        raise ValueError(f'{what}: DataFrame met kolommen {columns} verwacht')


def _rows_from(obj) -> list:
    """Dict {label: waarde} of lijst van labels naar (label, waarde)-rijen."""
    if isinstance(obj, dict):
        return [(str(k), str(v)) for k, v in obj.items()]
    return [(str(x), '') for x in obj]


def build_run_log(**facts) -> list:
    """Pure formatter. Vormen:
    entity_counts: DataFrame (country, kind, count); tam_status_counts: DataFrame
    (company, sales_unit, core_product, country, in_tam, count); population_unknown: dict
    {label: count}; ai_stats: dict; source_status: list[SourceStatus]; strays: list of
    {company, core_product, sales_unit, rows}; new_detailed: set; match_stats: dict
    {label: count}; warnings: list[str]."""
    log = []

    def section(title, rows):
        log.append((f'== {title} ==', ''))
        log.extend(rows)

    if facts.get('inputs'):
        section('Invoer', _rows_from(facts['inputs']))
    if facts.get('source_status'):
        section('Bronnen', [(s.name, f'ok, {s.rows} rijen, {s.source_date}' if s.ok
                             else f'FOUT: {s.message}') for s in facts['source_status']])
    if facts.get('entity_counts') is not None:
        df = facts['entity_counts']
        _require(df, ['country', 'kind', 'count'], 'entity_counts')
        section('Aantallen per land x soort',
                [(f'{r.country} / {r.kind}', r.count) for r in df.itertuples()])
    if facts.get('tam_status_counts') is not None:
        df = facts['tam_status_counts']
        _require(df, ['company', 'sales_unit', 'core_product', 'country', 'in_tam', 'count'],
                 'tam_status_counts')
        section('TAM per status',
                [(f'{r.company} / {r.core_product} / {r.country} / {r.in_tam}', r.count)
                 for r in df.itertuples()])
    if facts.get('population_unknown'):
        section('Inwonertal onbekend', _rows_from(facts['population_unknown']))
    if facts.get('match_stats'):
        section('Matching', _rows_from(facts['match_stats']))
    if facts.get('ai_stats') or facts.get('spend') is not None:
        rows = _rows_from(facts.get('ai_stats') or {})
        if facts.get('spend') is not None:
            rows.append(('uitgaven (USD)', f"{facts['spend']:.2f}"))
        section('AI', rows)
    if facts.get('strays'):
        section('Producten buiten lijst',
                [(f"{s['company']} / {s['core_product']}", f"{s['sales_unit']}: {s['rows']} regels")
                 for s in facts['strays']])
    if facts.get('new_detailed'):
        section('Nieuwe detailed-waarden', [('nieuw', ', '.join(sorted(facts['new_detailed'])))])
    if facts.get('warnings'):
        section('Waarschuwingen', [('waarschuwing', w) for w in facts['warnings']])
    return log
