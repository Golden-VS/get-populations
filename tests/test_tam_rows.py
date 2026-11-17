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


def test_regions_filter_belgian_entities():
    e = ents(dict(entity_id='BE-NIS-44021', name='Gent', country='BE', kind='be_gemeente',
                  population=270000, be_region='Vlaanderen'),
             dict(entity_id='BE-NIS-62063', name='Luik', country='BE', kind='be_gemeente',
                  population=195000, be_region='Wallonie'),
             dict(entity_id='BE-HAND-PZ-X', name='Zone X', country='BE', kind='be_politiezone',
                  population=50000, be_region='Brussel; Wallonie'),
             dict(entity_id='BE-HAND-FOD-BOSA', name='BOSA', country='BE', kind='be_fod',
                  population=None))
    segs = ['Local government', 'Public safety & emergency', 'National government']
    d = definition(country='BE', segments=segs, min_population=None,
                   regions=['Vlaanderen', 'Brussel'])
    df = build_tam_rows(e, [d], {}).set_index('name')
    assert df.at['Gent', 'in_tam'] == 'yes' and df.at['Gent', 'be_region'] == 'Vlaanderen'
    assert df.at['Luik', 'in_tam'] == 'no - excluded region'
    assert df.at['Luik', 'in_tam_reason'] == 'gewest niet in regions: Wallonie'
    assert df.at['Zone X', 'in_tam'] == 'yes'      # deels Brussel: telt mee
    assert df.at['BOSA', 'in_tam'] == 'yes'        # federaal: nooit weg op gewest
    all_be = build_tam_rows(e, [definition(country='BE', segments=segs, min_population=None)], {})
    assert set(all_be['in_tam']) == {'yes'}         # leeg regions = heel Belgie


def test_every_status_is_listed_for_the_summary():
    # de samenvatting van tam_build telt per status uit IN_TAM_STATUSES
    import inspect
    from tam import tam_rows
    from tam.config import IN_TAM_STATUSES
    import re
    used = set(re.findall(r"return '([^']+)'", inspect.getsource(tam_rows._status)))
    assert used <= set(IN_TAM_STATUSES) and 'no - excluded region' in used


def test_factor_per_detailed_segment_and_missing_report():
    from tam.tam_rows import missing_factors
    e = ents(dict(entity_id='NL-CBS-1', name='A', country='NL', kind='nl_gemeente', population=20000),
             dict(entity_id='NL-CBS-2', name='Wijk', country='NL', kind='nl_stadsdeel', population=20000),
             dict(entity_id='NL-CBS-3', name='Klein', country='NL', kind='nl_gemeente', population=5))
    df = build_tam_rows(e, [definition(factors={'Municipality': 1.0})], {}).set_index('name')
    assert df.at['A', 'factor'] == 1.0 and pd.isna(df.at['Wijk', 'factor'])
    msg = missing_factors(df.reset_index())
    # alleen in_tam yes telt: Klein valt onder de ondergrens
    assert msg.startswith('1 van 2 TAM-rijen (in_tam yes) zonder factor, 1 combinaties')
    assert 'S / P / NL / City district (1)' in msg
    assert missing_factors(df[df.index == 'A'].reset_index()) is None
