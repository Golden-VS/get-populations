"""Invoersjabloon (tam_template.xlsx): aanmaken, bijwerken, lezen en valideren."""
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from openpyxl import Workbook, load_workbook

from tam.config import COUNTRIES, DETAILED_SEGMENTS, SEGMENTS, all_detailed

DEF_COLUMNS = ['company', 'sales_unit', 'core_product', 'country', 'segments',
               'excluded_kinds', 'min_population', 'notes']
OVERRIDE_COLUMNS = ['accountid', 'entity_id', 'reason']
ALWAYS_IGNORED = ['_Other', 'Undefined']
ENTITY_ID_RE = re.compile(r'^(NL|BE|DE)-[A-Z]+-.+$')


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


def _lists_sheet(wb: Workbook) -> None:
    ws = wb.create_sheet('lists')
    ws.append(['segments', 'detailed_segments'])
    detailed = [d for values in DETAILED_SEGMENTS.values() for d in values]
    for i in range(max(len(SEGMENTS), len(detailed))):
        ws.append([SEGMENTS[i] if i < len(SEGMENTS) else None,
                   detailed[i] if i < len(detailed) else None])
    ws.append([])
    ws.append(['Meerdere waarden in een cel: scheiden met ; (puntkomma).'])


def _product_rows(products: pd.DataFrame):
    for r in products.itertuples():
        for country in COUNTRIES:
            yield [r.company, r.sales_unit, r.core_product, country, None, None, None, None]


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
        wb.create_sheet('match_overrides').append(OVERRIDE_COLUMNS)
        _lists_sheet(wb)
        wb.save(path)
        return len(rows)
    wb = load_workbook(path)
    ws = wb['tam_definitions']
    existing = {(r[0], r[2], r[3]) for r in ws.iter_rows(min_row=2, values_only=True)}
    added = 0
    for row in _product_rows(products):
        if (row[0], row[2], row[3]) not in existing:
            ws.append(row)
            added += 1
    wb.save(path)
    return added


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == ''


def _split(v) -> list[str]:
    return [] if _blank(v) else [p.strip() for p in str(v).split(';') if p.strip()]


def read_template(path: Path) -> tuple[list[TamDefinition], pd.DataFrame]:
    errors: list[str] = []
    defs: list[TamDefinition] = []
    df = pd.read_excel(path, sheet_name='tam_definitions', dtype=object)
    for idx, row in df.iterrows():
        xl = idx + 2
        segments = _split(row.get('segments'))
        if not segments:
            continue
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
        notes = '' if _blank(row.get('notes')) else str(row['notes'])
        defs.append(TamDefinition(str(row['company']), str(row['sales_unit']),
                                  str(row['core_product']), country, segments, excluded,
                                  minpop, notes))
    overrides = pd.read_excel(path, sheet_name='match_overrides', dtype=str)
    overrides = overrides.reindex(columns=OVERRIDE_COLUMNS)
    for idx, eid in overrides['entity_id'].items():
        if not _blank(eid) and not ENTITY_ID_RE.match(str(eid).strip()):
            errors.append(f"match_overrides rij {idx + 2}: onbekende waarde '{eid}' in entity_id")
    if errors:
        raise TemplateError('\n'.join(errors))
    overrides['entity_id'] = overrides['entity_id'].fillna('').str.strip()
    return defs, overrides
