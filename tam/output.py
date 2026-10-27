"""Uitvoerwerkboek en runlog."""
import json
from pathlib import Path

import pandas as pd

from tam.config import REFERENCE_DIR

SHEETS = ['TAM', 'CRM matches', 'Entities', 'Memberships', 'CRM unmatched', 'Run log']


def check_known_detailed(values: set, path: Path = REFERENCE_DIR / 'known_detailed.json') -> set:
    """Geef waarden die in eerdere runs niet voorkwamen en bewaar de unie."""
    path = Path(path)
    known = set()
    if path.exists():
        known = set(json.loads(path.read_text(encoding='utf-8')))
    new = set(values) - known
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(known | set(values)), ensure_ascii=False, indent=1),
                    encoding='utf-8')
    return new


def _memberships_sheet(memberships: pd.DataFrame, entities: pd.DataFrame) -> pd.DataFrame:
    coop = memberships[memberships['membership_type'] == 'cooperation'].copy()
    seg = dict(zip(entities['entity_id'], entities['detailed_segment']))
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


def _rows_from(obj) -> list:
    if isinstance(obj, pd.DataFrame):
        df = obj.reset_index()
        return [(' / '.join(str(r[c]) for c in df.columns[:-1]), str(r[df.columns[-1]]))
                for _, r in df.iterrows()] if len(df.columns) > 1 else []
    if isinstance(obj, dict):
        return [(str(k), str(v)) for k, v in obj.items()]
    return [(str(x), '') for x in obj]


def build_run_log(**facts) -> list:
    log = []

    def section(title, rows):
        log.append((f'== {title} ==', ''))
        log.extend(rows)

    if facts.get('inputs'):
        section('Invoer', _rows_from(facts['inputs']))
    if facts.get('source_status'):
        section('Bronnen', [(s.name, f"{'ok' if s.ok else 'FOUT'}; {s.rows} rijen; "
                                     f"{s.source_date}; {s.message}") for s in facts['source_status']])
    if facts.get('entity_counts') is not None:
        ec = facts['entity_counts']
        if isinstance(ec, pd.DataFrame):
            rows = [(str(idx), ', '.join(f'{c}={r[c]}' for c in ec.columns if r[c]))
                    for idx, r in ec.iterrows()]
        else:
            rows = _rows_from(ec)
        section('Aantallen per land x soort', rows)
    if facts.get('tam_status_counts') is not None:
        section('TAM per status', _rows_from(facts['tam_status_counts']))
    if facts.get('population_unknown'):
        section('Inwonertal onbekend', _rows_from(facts['population_unknown']))
    if facts.get('ai_stats') or facts.get('spend') is not None:
        rows = _rows_from(facts.get('ai_stats') or {})
        if facts.get('spend') is not None:
            rows.append(('uitgaven (USD)', f"{facts['spend']:.2f}"))
        section('AI', rows)
    if facts.get('strays'):
        section('Producten buiten lijst', [(str(s.get('name', s.get('product', ''))), json.dumps(s, ensure_ascii=False, default=str))
                                           for s in facts['strays']])
    if facts.get('new_detailed'):
        section('Nieuwe detailed-waarden', [('nieuw', ', '.join(sorted(facts['new_detailed'])))])
    if facts.get('warnings'):
        section('Waarschuwingen', [('waarschuwing', w) for w in facts['warnings']])
    return log
