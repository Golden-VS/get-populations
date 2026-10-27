import json

from tam.sources.common import SourceCache
from tam.sources import nl
from tam.sources.nl import parse_cbs_gebieden, resolve_cbs_keys, load_nl_cbs

KEYS = {'gm_code': 'Code_1', 'gm_name': 'Naam_2', 'pv_code': 'Code_28', 'pv_name': 'Naam_29',
        'pop': 'Inwonertal_56'}

RECORDS = [
    {'Code_1': 'GM0014    ', 'Naam_2': 'Groningen (gemeente)        ', 'Code_28': 'PV20      ',
     'Naam_29': 'Groningen (PV)   ', 'Inwonertal_56': 235287},
    {'Code_1': 'GM1680    ', 'Naam_2': 'Aa en Hunze   ', 'Code_28': 'PV22      ',
     'Naam_29': 'Drenthe   ', 'Inwonertal_56': 25400},
    {'Code_1': 'NL01      ', 'Naam_2': 'Nederland', 'Code_28': '.', 'Naam_29': '.',
     'Inwonertal_56': 1},
]

PROPS = [
    {'Type': 'TopicGroup', 'ID': 1, 'ParentID': None, 'Title': 'Codes en namen van gemeenten'},
    {'Type': 'Topic', 'ID': 2, 'ParentID': 1, 'Key': 'Code_1', 'Title': 'Code'},
    {'Type': 'Topic', 'ID': 3, 'ParentID': 1, 'Key': 'Naam_2', 'Title': 'Naam'},
    {'Type': 'TopicGroup', 'ID': 42, 'ParentID': 5, 'Title': 'Provincies'},
    {'Type': 'Topic', 'ID': 43, 'ParentID': 42, 'Key': 'Code_28', 'Title': 'Code'},
    {'Type': 'Topic', 'ID': 44, 'ParentID': 42, 'Key': 'Naam_29', 'Title': 'Naam'},
    {'Type': 'TopicGroup', 'ID': 85, 'ParentID': None, 'Title': 'Statistische gegevens'},
    {'Type': 'Topic', 'ID': 86, 'ParentID': 85, 'Key': 'Inwonertal_56', 'Title': 'Inwonertal'},
]


def test_parse_cleans_names_codes_population():
    df = parse_cbs_gebieden(RECORDS, KEYS)
    assert list(df['gm_code']) == ['GM0014', 'GM1680']
    assert list(df['gm_name']) == ['Groningen', 'Aa en Hunze']
    assert list(df['pv_name']) == ['Groningen', 'Drenthe']
    assert list(df['pv_code']) == ['PV20', 'PV22']
    assert int(df['population'].iloc[0]) == 235287


def test_resolve_keys_by_title():
    assert resolve_cbs_keys(PROPS) == KEYS


def test_load_nl_cbs_from_cache_offline(tmp_path):
    (tmp_path / 'nl_cbs_2026_86247NED_props.json').write_text(json.dumps({'value': PROPS}))
    (tmp_path / 'nl_cbs_2026_86247NED_typed.json').write_text(json.dumps({'value': RECORDS}))
    b = load_nl_cbs(SourceCache(offline=True, base_dir=tmp_path))
    assert b.entities['kind'].value_counts().to_dict() == {'nl_gemeente': 2, 'nl_provincie': 2}
    gm = b.entities[b.entities.entity_id == 'NL-GM-GM0014'].iloc[0]
    assert gm['region'] == 'Groningen' and gm['official_ids'] == 'cbs:GM0014'
    assert gm['population_method'] == 'own'
    pv = b.entities[b.entities.entity_id == 'NL-PV-PV22'].iloc[0]
    assert pv['population_method'] == 'sum of members'
    assert set(b.memberships['membership_type']) == {'territorial'}
    assert len(b.memberships) == 2
    assert b.extras['municipal_population'] == {'NL-GM-GM0014': 235287, 'NL-GM-GM1680': 25400}
    assert b.status[0].ok and b.status[0].name == 'nl_cbs'


def test_load_nl_cbs_offline_without_cache_reports_failure(tmp_path):
    b = load_nl_cbs(SourceCache(offline=True, base_dir=tmp_path))
    assert not b.status[0].ok and len(b.entities) == 0
