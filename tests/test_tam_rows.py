import pandas as pd

from tam.entities import ENTITY_COLUMNS, new_entity
from tam.template import TamDefinition
from tam.tam_rows import TAM_ROW_COLUMNS, build_tam_rows


def ents(*rows):
    return pd.DataFrame([new_entity(**r) for r in rows], columns=ENTITY_COLUMNS)


def definition(**kw):
    base = dict(company='C', sales_unit='S', core_product='P', country='NL',
                segments=['Local government'], excluded_kinds=[], min_population=10000, notes='')
    base.update(kw)
    return TamDefinition(**base)


def test_status_order():
    e = ents(dict(entity_id='NL-CBS-1', name='Wijk', country='NL', kind='nl_stadsdeel', population=500))
    df = build_tam_rows(e, [definition(excluded_kinds=['City district'])], {})
    assert list(df.columns) == TAM_ROW_COLUMNS
    assert df.iloc[0]['in_tam'] == 'no - excluded kind'
    assert df.iloc[0]['in_tam_reason'] == 'uitgesloten soort: City district'


def test_unknown_population_with_cutoff():
    e = ents(dict(entity_id='NL-CBS-1', name='A', country='NL', kind='nl_gemeente', population=None))
    df = build_tam_rows(e, [definition()], {})
    assert df.iloc[0]['in_tam'] == 'unknown - population missing'
    assert df.iloc[0]['in_tam_reason'] == 'inwonertal onbekend'


def test_no_cutoff_unknown_population_is_yes():
    e = ents(dict(entity_id='NL-CBS-1', name='A', country='NL', kind='nl_gemeente', population=None))
    df = build_tam_rows(e, [definition(min_population=None)], {})
    assert df.iloc[0]['in_tam'] == 'yes'
    assert df.iloc[0]['in_tam_reason'] == ''


def test_below_and_above_cutoff_reasons():
    e = ents(dict(entity_id='NL-CBS-1', name='A', country='NL', kind='nl_gemeente', population=7512),
             dict(entity_id='NL-CBS-2', name='B', country='NL', kind='nl_gemeente', population=59000))
    df = build_tam_rows(e, [definition()], {'NL-CBS-2': 3}).set_index('entity_id')
    assert df.loc['NL-CBS-1', 'in_tam'] == 'no - below cutoff'
    assert df.loc['NL-CBS-1', 'in_tam_reason'] == 'inwoners 7.512 < 10.000'
    assert df.loc['NL-CBS-2', 'in_tam_reason'] == 'inwoners 59.000 >= 10.000'
    assert df.loc['NL-CBS-2', 'matched_accounts'] == 3
    assert df.loc['NL-CBS-1', 'matched_accounts'] == 0


def test_only_selected_segments_and_country():
    e = ents(dict(entity_id='NL-CBS-1', name='A', country='NL', kind='nl_gemeente', population=20000),
             dict(entity_id='NL-CBS-2', name='P', country='NL', kind='nl_provincie', population=20000),
             dict(entity_id='BE-NIS-1', name='B', country='BE', kind='be_gemeente', population=20000))
    df = build_tam_rows(e, [definition()], {})
    assert list(df['entity_id']) == ['NL-CBS-1']


def test_notes_copied_to_last_column():
    # M5: notes uit het sjabloon staan als laatste kolom in de TAM-rijen
    e = ents(dict(entity_id='NL-CBS-1', name='A', country='NL', kind='nl_gemeente', population=20000))
    df = build_tam_rows(e, [definition(notes='alleen grote gemeenten')], {})
    assert TAM_ROW_COLUMNS[-1] == 'notes'
    assert df.iloc[0]['notes'] == 'alleen grote gemeenten'
