import pandas as pd
import pytest

from tam.config import COUNTRIES
from tam.template import (TamDefinition, TemplateError, load_products,
                          make_template, read_template)

CONFIG = {'companies': ['Company A', 'Company B'],
          'ignore_core_products': ['Non-product family']}


def _products_xlsx(tmp_path, rows):
    path = tmp_path / 'products.xlsx'
    pd.DataFrame(rows, columns=['Company', 'Sales Unit', 'Core Product Family']).to_excel(
        path, index=False)
    return path


def _products(tmp_path):
    rows = [('Company A', 'Unit 1', 'Product X')] * 3 + [
        ('Company A', 'Unit 2', 'Product X'),
        ('Company B', 'Unit 3', 'Product Y'),
    ]
    return load_products(_products_xlsx(tmp_path, rows), CONFIG)


def test_company_filter_and_ignore_list(tmp_path):
    rows = [
        ('Company A', 'Unit 1', 'Product X'),
        ('Company Z', 'Unit 9', 'Product Q'),
        ('Company A', 'Unit 1', '_Other'),
        ('Company A', 'Unit 1', 'Undefined'),
        ('Company B', 'Unit 3', 'Non-product family'),
        ('Company B', 'Unit 3', 'Product Y'),
    ]
    df, strays = load_products(_products_xlsx(tmp_path, rows), CONFIG)
    assert sorted(df['core_product']) == ['Product X', 'Product Y']
    assert strays == []


def test_stray_assigned_to_main_sales_unit(tmp_path):
    df, strays = _products(tmp_path)
    x = df[df['core_product'] == 'Product X']
    assert list(x['sales_unit']) == ['Unit 1']
    assert strays == [{'company': 'Company A', 'core_product': 'Product X',
                       'sales_unit': 'Unit 2', 'rows': 1}]


def test_make_refuses_overwrite(tmp_path):
    df, _ = _products(tmp_path)
    path = tmp_path / 'tpl.xlsx'
    assert make_template(df, path) == 2 * len(COUNTRIES)
    with pytest.raises(FileExistsError):
        make_template(df, path)


def _row_of(ws, headers, core_product, country):
    cp, c = headers.index('core_product') + 1, headers.index('country') + 1
    return next(r for r in range(2, ws.max_row + 1)
                if ws.cell(r, cp).value == core_product and ws.cell(r, c).value == country)


def _fill(path, updates):
    from openpyxl import load_workbook
    wb = load_workbook(path)
    ws = wb['tam_definitions']
    headers = [c.value for c in ws[1]]
    for row, values in updates.items():
        if isinstance(row, tuple):   # (core_product, country) -> Excel-rij
            row = _row_of(ws, headers, *row)
        for col, v in values.items():
            ws.cell(row=row, column=headers.index(col) + 1, value=v)
    wb.save(path)


def test_update_keeps_filled_rows_overrides_and_adds_new(tmp_path):
    df, _ = _products(tmp_path)
    path = tmp_path / 'tpl.xlsx'
    make_template(df, path)
    _fill(path, {('Product X', 'NL'): {'segments': 'Local government; Regional government',
                                       'min_population': 10000.0, 'notes': 'hi'}})
    from openpyxl import load_workbook
    wb = load_workbook(path)
    wb['match_overrides'].append(['123', 'NL-GM-0363', 'manual'])
    wb.save(path)

    new_rows = [('Company A', 'Unit 1', 'Product X'), ('Company B', 'Unit 3', 'Product Y'),
                ('Company B', 'Unit 4', 'Product W')]
    df2, _ = load_products(_products_xlsx(tmp_path, new_rows), CONFIG)
    assert make_template(df2, path, update=True) == len(COUNTRIES)

    defs, overrides = read_template(path)
    assert len(defs) == 1
    d = defs[0]
    assert d == TamDefinition('Company A', 'Unit 1', 'Product X', 'NL',
                              ['Local government', 'Regional government'], [], 10000, 'hi')
    assert list(overrides['accountid']) == ['123']
    assert len(pd.read_excel(path, sheet_name='tam_definitions')) == 3 * len(COUNTRIES)


def test_unknown_segment_value_stops_with_row_number(tmp_path):
    df, _ = _products(tmp_path)
    path = tmp_path / 'tpl.xlsx'
    make_template(df, path)
    _fill(path, {3: {'segments': 'Local goverment'},
                 4: {'segments': 'Local government', 'excluded_kinds': 'Nope',
                     'min_population': -5}})
    with pytest.raises(TemplateError) as e:
        read_template(path)
    msg = str(e.value)
    assert 'rij 3' in msg and "'Local goverment'" in msg
    assert "rij 4: onbekende waarde 'Nope' in excluded_kinds" in msg
    assert 'min_population' in msg


def test_empty_segments_row_skipped(tmp_path):
    df, _ = _products(tmp_path)
    path = tmp_path / 'tpl.xlsx'
    make_template(df, path)
    _fill(path, {2: {'segments': 'Local government', 'excluded_kinds': 'Island authority'}})
    defs, overrides = read_template(path)
    assert len(defs) == 1 and defs[0].excluded_kinds == ['Island authority']
    assert overrides.empty


def test_bad_override_entity_id(tmp_path):
    df, _ = _products(tmp_path)
    path = tmp_path / 'tpl.xlsx'
    make_template(df, path)
    from openpyxl import load_workbook
    wb = load_workbook(path)
    wb['match_overrides'].append(['1', 'bogus', 'x'])
    wb['match_overrides'].append(['2', None, 'no match'])
    wb.save(path)
    with pytest.raises(TemplateError) as e:
        read_template(path)
    assert 'match_overrides rij 2' in str(e.value)
    assert 'rij 3' not in str(e.value)


def test_duplicate_definition_rows_rejected(tmp_path):
    # M4: twee ingevulde rijen voor dezelfde (company, core_product, country) = fout
    df, _ = _products(tmp_path)
    path = tmp_path / 'tpl.xlsx'
    make_template(df, path)
    from openpyxl import load_workbook
    wb = load_workbook(path)
    wb['tam_definitions'].append(['Company A', 'Unit 1', 'Product X', 'NL', 'Nederland', None,
                                  'Regional government', None, None, None])
    wb['tam_definitions'].append(['Company A', 'Unit 1', 'Product X', 'BE', 'België', None, None,
                                  None, None, None])
    wb.save(path)
    from openpyxl import load_workbook as _lw
    ws = _lw(path)['tam_definitions']
    headers = [c.value for c in ws[1]]
    first_nl = _row_of(ws, headers, 'Product X', 'NL')
    _fill(path, {first_nl: {'segments': 'Local government'},
                 ('Product X', 'BE'): {'segments': 'Local government'}})
    with pytest.raises(TemplateError) as e:
        read_template(path)
    msg = str(e.value)
    dup_row = 2 + 2 * len(COUNTRIES)   # eerste toegevoegde rij na de kop en alle productrijen
    assert f'rij {dup_row}:' in msg and f'rij {first_nl})' in msg and 'Product X' in msg
    # de lege dubbele rij (BE, zonder segments) telt niet
    assert f'rij {dup_row + 1}' not in msg


def test_lists_sheet_shows_detailed_per_segment(tmp_path):
    from openpyxl import load_workbook
    from tam.config import DETAILED_SEGMENTS, SEGMENTS
    p = tmp_path / 't.xlsx'
    products = pd.DataFrame([('Company A', 'Unit 1', 'Product X')],
                            columns=['company', 'sales_unit', 'core_product'])
    make_template(products, p)
    ws = load_workbook(p)['lists']
    assert [c.value for c in ws[1]][:4] == ['segment', 'detailed_segment', 'landen', 'wat valt eronder']
    rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[0] in SEGMENTS and r[1]]
    expected = [(s, d) for s in SEGMENTS for d in DETAILED_SEGMENTS[s]]
    assert [(r[0], r[1]) for r in rows] == expected
    assert all(r[2] and r[3] for r in rows)
    assert ws.freeze_panes == 'A2' and ws.auto_filter.ref


def test_every_detailed_value_has_help():
    from tam.config import all_detailed
    from tam.template import DETAILED_HELP
    assert set(DETAILED_HELP) == all_detailed()


def test_instructions_sheet_first_and_kept_on_update(tmp_path):
    from openpyxl import load_workbook
    p = tmp_path / 't.xlsx'
    products = pd.DataFrame([('Company A', 'Unit 1', 'Product X')],
                            columns=['company', 'sales_unit', 'core_product'])
    make_template(products, p)
    wb = load_workbook(p)
    assert wb.sheetnames[0] == 'instructies'
    text = ' '.join(str(c) for r in wb['instructies'].iter_rows(values_only=True) for c in r if c)
    for word in ('tam_definitions', 'segments', 'excluded_kinds', 'min_population', 'lists',
                 'match_overrides', 'entity_id', 'accountid'):
        assert word in text
    # bestaand template zonder instructieblad krijgt het bij --update, maar slechts een keer
    del wb['instructies']
    wb.save(p)
    make_template(products, p, update=True)
    make_template(products, p, update=True)
    wb = load_workbook(p)
    assert wb.sheetnames.count('instructies') == 1 and wb.sheetnames[0] == 'instructies'
    defs, _ = read_template(p)
    assert defs == []


def test_template_columns_fitted(tmp_path):
    from openpyxl import load_workbook
    p = tmp_path / 't.xlsx'
    products = pd.DataFrame([('Company A', 'A rather long sales unit name', 'Product X')],
                            columns=['company', 'sales_unit', 'core_product'])
    make_template(products, p)
    ws = load_workbook(p)['tam_definitions']
    assert ws.column_dimensions['B'].width >= len('A rather long sales unit name')
    assert ws.column_dimensions['H'].width >= len('min_population')



def test_template_has_country_name_next_to_code(tmp_path):
    from openpyxl import load_workbook
    p = tmp_path / 't.xlsx'
    products = pd.DataFrame([('Company A', 'Unit 1', 'Product X')],
                            columns=['company', 'sales_unit', 'core_product'])
    make_template(products, p)
    df = pd.read_excel(p, sheet_name='tam_definitions')
    assert list(df.columns)[3:5] == ['country', 'country_name']
    names = dict(zip(df['country'], df['country_name']))
    assert names['NL'] == 'Nederland' and names['BQ'].startswith('Caribisch Nederland')
    lists = [r for r in load_workbook(p)['lists'].iter_rows(values_only=True)]
    assert ('BQ', 'Caribisch Nederland (Bonaire, Sint Eustatius, Saba)') in [tuple(r[:2]) for r in lists]


def test_update_adds_country_name_to_old_template(tmp_path):
    from openpyxl import Workbook
    p = tmp_path / 't.xlsx'
    wb = Workbook()
    ws = wb.active
    ws.title = 'tam_definitions'
    ws.append(['company', 'sales_unit', 'core_product', 'country', 'segments', 'excluded_kinds',
               'min_population', 'notes'])
    ws.append(['Company A', 'Unit 1', 'Product X', 'NL', 'Local government', None, 10000, 'hi'])
    wb.create_sheet('match_overrides').append(['accountid', 'entity_id', 'reason'])
    wb.save(p)
    products = pd.DataFrame([('Company A', 'Unit 1', 'Product X')],
                            columns=['company', 'sales_unit', 'core_product'])
    make_template(products, p, update=True)
    df = pd.read_excel(p, sheet_name='tam_definitions')
    assert list(df.columns)[3:5] == ['country', 'country_name']
    first = df[df['country'] == 'NL'].iloc[0]
    assert first['country'] == 'NL' and first['country_name'] == 'Nederland'
    assert first['segments'] == 'Local government' and first['min_population'] == 10000
    assert set(df['country']) == {'NL', 'BE', 'DE', 'AW', 'CW', 'SX', 'BQ', 'SR'}
    assert df['country_name'].notna().all()
    defs, _ = read_template(p)
    assert len(defs) == 1 and defs[0].country == 'NL' and defs[0].min_population == 10000


def test_update_keeps_excel_table_in_sync_and_widths_valid(tmp_path):
    # Zo ging het mis (2026-11-04): tam_definitions opgemaakt als Excel-tabel over A:H; na het
    # invoegen van country_name klopte de tabeldefinitie niet meer en weigerde Excel het bestand.
    from openpyxl import Workbook, load_workbook
    from openpyxl.worksheet.table import Table, TableStyleInfo
    p = tmp_path / 't.xlsx'
    wb = Workbook()
    ws = wb.active
    ws.title = 'tam_definitions'
    ws.append(['company', 'sales_unit', 'core_product', 'country', 'segments', 'excluded_kinds',
               'min_population', 'notes'])
    ws.append(['Company A', 'Unit 1', 'Product X', 'NL', 'Local government', None, 10000, 'hi'])
    t = Table(displayName='Table1', ref='A1:H2')
    t.tableStyleInfo = TableStyleInfo(name='TableStyleLight9', showRowStripes=True)
    ws.add_table(t)
    ws.column_dimensions.group('A', 'B', hidden=False)   # Excel bewaart A:B als een blok
    wb.create_sheet('match_overrides').append(['accountid', 'entity_id', 'reason'])
    wb.save(p)
    products = pd.DataFrame([('Company A', 'Unit 1', 'Product X')],
                            columns=['company', 'sales_unit', 'core_product'])
    make_template(products, p, update=True)
    wb = load_workbook(p)
    ws = wb['tam_definitions']
    header = [c.value for c in ws[1]]
    table = ws.tables['Table1']
    assert table.ref == f'A1:J{ws.max_row}'
    assert [c.name for c in table.tableColumns] == header
    assert table.autoFilter.ref == table.ref
    for sheet in wb.worksheets:
        spans = sorted((d.min, d.max) for d in sheet.column_dimensions.values() if d.min)
        for (a1, b1), (a2, b2) in zip(spans, spans[1:]):
            assert b1 < a2, (sheet.title, spans)
    defs, _ = read_template(p)
    assert len(defs) == 1 and defs[0].min_population == 10000


def test_definitions_sorted_by_columns_country_last(tmp_path):
    p = tmp_path / 't.xlsx'
    products = pd.DataFrame([('Company B', 'Unit 1', 'Product Y'), ('Company A', 'Unit 2', 'Product Z'),
                             ('Company A', 'Unit 1', 'Product X')],
                            columns=['company', 'sales_unit', 'core_product'])
    make_template(products, p)
    _fill(p, {2: {'segments': 'Local government', 'notes': 'eerste rij'}})
    filled = pd.read_excel(p, sheet_name='tam_definitions').iloc[0]
    # nieuw product erbij: sortering blijft kloppen en ingevulde waarden blijven bij hun rij
    more = pd.concat([products, pd.DataFrame([('Company A', 'Unit 1', 'Product W')],
                                             columns=products.columns)])
    make_template(more, p, update=True)
    df = pd.read_excel(p, sheet_name='tam_definitions')
    keys = list(zip(df['company'], df['sales_unit'], df['core_product'], df['country']))
    assert keys == sorted(keys)
    row = df[(df['core_product'] == filled['core_product']) & (df['country'] == filled['country'])].iloc[0]
    assert row['segments'] == 'Local government' and row['notes'] == 'eerste rij'


def test_new_template_has_regions_prefilled_for_be_only(tmp_path):
    df, _ = _products(tmp_path)
    path = tmp_path / 'tpl.xlsx'
    make_template(df, path)
    t = pd.read_excel(path, sheet_name='tam_definitions', dtype=object)
    cols = list(t.columns)
    assert cols[cols.index('country_name') + 1] == 'regions'
    assert set(t.loc[t['country'] == 'BE', 'regions']) == {'Vlaanderen; Brussel; Wallonie'}
    assert t.loc[t['country'] != 'BE', 'regions'].isna().all()
    _fill(path, {('Product X', 'BE'): {'segments': 'Local government'}})
    d = next(x for x in read_template(path)[0] if x.country == 'BE')
    assert d.regions == ['Vlaanderen', 'Brussel', 'Wallonie']


def test_update_adds_regions_and_keeps_business_values(tmp_path):
    # Oud template zonder regions, met ingevulde rijen: kolom erbij, niets kwijt
    from openpyxl import Workbook
    p = tmp_path / 't.xlsx'
    wb = Workbook()
    ws = wb.active
    ws.title = 'tam_definitions'
    ws.append(['company', 'sales_unit', 'core_product', 'country', 'country_name', 'segments',
               'excluded_kinds', 'min_population', 'notes'])
    ws.append(['Company A', 'Unit 1', 'Product X', 'BE', 'België', 'Local government',
               'City district', 5000, 'be'])
    ws.append(['Company A', 'Unit 1', 'Product X', 'NL', 'Nederland', 'Local government', None,
               10000, 'nl'])
    wb.create_sheet('match_overrides').append(['accountid', 'entity_id', 'reason'])
    wb.save(p)
    products = pd.DataFrame([('Company A', 'Unit 1', 'Product X')],
                            columns=['company', 'sales_unit', 'core_product'])
    make_template(products, p, update=True)
    t = pd.read_excel(p, sheet_name='tam_definitions', dtype=object).set_index('country')
    assert t.at['BE', 'regions'] == 'Vlaanderen; Brussel; Wallonie'
    assert pd.isna(t.at['NL', 'regions'])
    assert (t.at['BE', 'segments'], t.at['BE', 'excluded_kinds'], t.at['BE', 'min_population'],
            t.at['BE', 'notes']) == ('Local government', 'City district', 5000, 'be')
    assert (t.at['NL', 'min_population'], t.at['NL', 'notes']) == (10000, 'nl')
    assert len(t) == len(COUNTRIES)


def test_update_appends_by_column_name(tmp_path):
    # Business zette regions zelf achteraan: nieuwe rijen moeten op naam gevuld worden
    from openpyxl import Workbook
    p = tmp_path / 't.xlsx'
    wb = Workbook()
    ws = wb.active
    ws.title = 'tam_definitions'
    ws.append(['company', 'sales_unit', 'core_product', 'country', 'country_name', 'segments',
               'excluded_kinds', 'min_population', 'notes', 'regions'])
    ws.append(['Company A', 'Unit 1', 'Product X', 'BE', 'België', 'Local government', None,
               None, None, 'Vlaanderen'])
    wb.create_sheet('match_overrides').append(['accountid', 'entity_id', 'reason'])
    wb.save(p)
    products = pd.DataFrame([('Company A', 'Unit 1', 'Product X')],
                            columns=['company', 'sales_unit', 'core_product'])
    make_template(products, p, update=True)
    t = pd.read_excel(p, sheet_name='tam_definitions', dtype=object).set_index('country')
    assert t.at['BE', 'regions'] == 'Vlaanderen'
    assert t.at['NL', 'country_name'] == 'Nederland' and pd.isna(t.at['NL', 'segments'])
    assert pd.isna(t.at['NL', 'regions'])


def test_regions_values_validated(tmp_path):
    df, _ = _products(tmp_path)
    path = tmp_path / 'tpl.xlsx'
    make_template(df, path)
    _fill(path, {('Product X', 'BE'): {'segments': 'Local government',
                                       'regions': 'wallonië; Vlaams'},
                 ('Product X', 'NL'): {'segments': 'Local government', 'regions': 'Vlaanderen'}})
    with pytest.raises(TemplateError) as e:
        read_template(path)
    msg = str(e.value)
    assert "onbekende waarde 'Vlaams' in regions" in msg
    assert 'regions alleen voor BE, niet voor NL' in msg
    assert 'wallonië' not in msg
