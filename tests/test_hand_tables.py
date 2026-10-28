from tam import hand_tables as ht
from tam.config import KIND_TO_SEGMENT
from tam.sources.nl import load_nl_hand

TABLES = ['NL_STADSDEEL_IDS', 'BE_GEWESTEN', 'BE_FOD',
          'BE_HULPVERLENINGSZONES_WB', 'BE_INTERCOMMUNALES_BXL']


def _rows():
    for t in TABLES:
        for key, row in getattr(ht, t).items():
            yield t, key, row


def test_hand_tables_every_row_has_source():
    for t, key, row in _rows():
        assert str(row.get('bron_url', '')).startswith('https://'), (t, key)
        assert 'population' in row and 'peildatum' in row, (t, key)


def test_hand_table_ids_fixed_and_unique():
    ids = [row['id'] for _, _, row in _rows()]
    assert len(ids) == len(set(ids))
    for t, key, row in _rows():
        assert row['id'].startswith(('NL-HAND-', 'BE-HAND-')), (t, key)
        assert row['id'] == row['id'].upper()


def test_fire_zones_wb_count_and_members():
    zones = ht.BE_HULPVERLENINGSZONES_WB
    assert len(zones) == 15
    walloon = sum(len(z['members']) for z in zones.values() if not z['id'].endswith('BRUSSEL'))
    assert walloon == 261
    assert len(zones['Brandweer Brussel (DBDMH/SIAMU)']['members']) == 19


def test_load_nl_hand():
    b = load_nl_hand()
    counts = b.entities['kind'].value_counts().to_dict()
    assert counts == {'nl_stadsdeel': 8}
    assert b.entities['entity_id'].is_unique
    assert set(b.entities['kind']) <= set(KIND_TO_SEGMENT)
    alias_names = set(b.aliases.alias_name)
    assert 'Stadsdeel Centrum' in alias_names
    assert not alias_names & {'Centrum', 'Noord', 'Oost', 'Zuid', 'West', 'Zuidoost', 'Nieuw-West', 'Weesp'}
    assert b.status[0].name == 'nl_hand' and b.status[0].ok
