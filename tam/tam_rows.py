"""TAM-rijen per definitie: welke entiteiten horen bij welk product en land."""
import pandas as pd

# notes (uit het sjabloon) als laatste kolom, zodat de vaste kolommen hun plaats houden
TAM_ROW_COLUMNS = ['company', 'sales_unit', 'core_product', 'country', 'entity_id', 'name',
                   'detailed_segment', 'population', 'in_tam', 'in_tam_reason', 'matched_accounts',
                   'notes']


def _nl(n) -> str:
    """Getal met punt als duizendtalscheiding."""
    return f'{int(n):,}'.replace(',', '.')


def _status(row, definition) -> tuple[str, str]:
    if row['detailed_segment'] in definition.excluded_kinds:
        return 'no - excluded kind', f"uitgesloten soort: {row['detailed_segment']}"
    cutoff = definition.min_population
    pop = row['population']
    missing = pop is None or pd.isna(pop) or pop == ''
    if cutoff is not None and missing:
        return 'unknown - population missing', 'inwonertal onbekend'
    if cutoff is None:
        return 'yes', ''
    if pop < cutoff:
        return 'no - below cutoff', f'inwoners {_nl(pop)} < {_nl(cutoff)}'
    return 'yes', f'inwoners {_nl(pop)} >= {_nl(cutoff)}'


def build_tam_rows(entities: pd.DataFrame, definitions: list,
                   match_counts: dict) -> pd.DataFrame:
    rows = []
    for d in definitions:
        sel = entities[(entities['country'] == d.country)
                       & (entities['segment'].isin(d.segments))]
        for _, e in sel.iterrows():
            status, reason = _status(e, d)
            pop = e['population']
            rows.append({
                'company': d.company, 'sales_unit': d.sales_unit,
                'core_product': d.core_product, 'country': d.country,
                'entity_id': e['entity_id'], 'name': e['name'],
                'detailed_segment': e['detailed_segment'],
                'population': None if pop is None or pd.isna(pop) or pop == '' else pop,
                'in_tam': status, 'in_tam_reason': reason,
                'matched_accounts': match_counts.get(e['entity_id'], 0),
                'notes': d.notes,
            })
    df = pd.DataFrame(rows, columns=TAM_ROW_COLUMNS)
    return (df.sort_values(['company', 'sales_unit', 'core_product', 'country', 'name'],
                           kind='stable').reset_index(drop=True))
