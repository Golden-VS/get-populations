import pandas as pd

from tam.entities import ALIAS_COLUMNS, ENTITY_COLUMNS, new_entity
from tam.matching import (
    MATCH_COLUMNS, TYPE_TO_KINDS, UNMATCHED_COLUMNS, apply_overrides, build_name_index,
    candidates, crm_in_scope, crm_name_key, entities_by_country, load_crm,
    normalize_company_number, pass1,
)

CRM_COLUMNS = [
    'accountid', 'name', 'canonical_name', 'detected_type', 'detected_country', 'Segment',
    'Segment (category)', 'segment_confidence', 'cx_kvknummer', 'cx_address3_postalcode',
    'cx_address3_city', 'address1_composite',
]


def ents(*rows):
    return pd.DataFrame([new_entity(**r) for r in rows], columns=ENTITY_COLUMNS)


def aliases(*rows):
    return pd.DataFrame(list(rows), columns=ALIAS_COLUMNS)


def crm(*rows):
    out = []
    for i, r in enumerate(rows):
        base = {c: float('nan') for c in CRM_COLUMNS}
        base.update({'accountid': f'acc-{i}', 'detected_type': 'onbekend', 'detected_country': 'NL',
                     'Segment (category)': 'Governmental', 'segment_confidence': 'high'})
        base.update(r)
        out.append(base)
    return pd.DataFrame(out, columns=CRM_COLUMNS)


def run_pass1(crm_frame, entities, alias_frame=None):
    alias_frame = alias_frame if alias_frame is not None else aliases()
    scope, _ = crm_in_scope(crm_frame)
    index = build_name_index(entities, alias_frame)
    return pass1(scope, entities, index)


def matched_ids(matched):
    return dict(zip(matched['accountid'], matched['entity_id']))


# ---------- scope ----------

def test_scope_excludes_other_and_confident_commercial():
    frame = crm(
        dict(name='Gemeente A', detected_country='NL'),
        dict(name='Foreign Ltd', detected_country='OTHER', **{'Segment (category)': 'Commercial'}),
        dict(name='Shop BV', detected_type='commercieel_of_overig',
             **{'Segment (category)': 'Commercial', 'segment_confidence': 'high'}),
        dict(name='Maybe BV', detected_type='commercieel_of_overig',
             **{'Segment (category)': 'Commercial', 'segment_confidence': 'medium'}),
        dict(name='Stichting X', detected_type='commercieel_of_overig',
             **{'Segment (category)': 'Non-profit', 'segment_confidence': 'high'}),
        dict(name='Stadt Bonn', detected_type='gemeinde_de', detected_country='DE',
             **{'Segment (category)': 'Commercial', 'segment_confidence': 'low'}),
    )
    scope, _ = crm_in_scope(frame)
    assert list(scope['name']) == ['Gemeente A', 'Maybe BV', 'Stichting X', 'Stadt Bonn']
    assert list(scope['tam_country']) == ['NL', 'NL', 'NL', 'DE']
    assert list(scope['priority']) == ['gov', 'other', 'gov', 'gov']


def test_other_country_governmental_listed_out_of_scope():
    frame = crm(
        dict(name='Ville de Paris', detected_country='OTHER', **{'Segment (category)': 'Governmental'}),
        dict(name='Foreign Ltd', detected_country='OTHER', **{'Segment (category)': 'Commercial'}),
    )
    scope, out_gov = crm_in_scope(frame)
    assert len(scope) == 0
    assert list(out_gov.columns) == UNMATCHED_COLUMNS
    assert len(out_gov) == 1
    row = out_gov.iloc[0]
    assert row['accountid'] == 'acc-0'
    assert row['crm_name'] == 'Ville de Paris'
    assert row['tam_country'] == ''
    assert row['best_candidate'] == ''
    assert row['best_score'] is None or pd.isna(row['best_score'])
    assert row['reason'] == 'land buiten scope'


def test_caribbean_maps_to_nl():
    entities = ents(dict(entity_id='NL-HAND-CW', name='Curaçao', country='NL', kind='nl_land_caribisch'))
    frame = crm(dict(name='Land Curaçao', canonical_name='Curaçao', detected_type='land',
                     detected_country='CW'))
    scope, _ = crm_in_scope(frame)
    assert scope.iloc[0]['tam_country'] == 'NL'
    matched, rest = run_pass1(frame, entities)
    assert matched_ids(matched) == {'acc-0': 'NL-HAND-CW'}
    assert len(rest) == 0


# ---------- helpers ----------

def test_type_to_kinds_values():
    assert TYPE_TO_KINDS['ocmw'] == {'be_gemeente'}
    assert TYPE_TO_KINDS['stadsdeel'] == {'nl_stadsdeel', 'be_district'}
    assert 'stadtwerke' not in TYPE_TO_KINDS


def test_be_company_number_normalised():
    assert normalize_company_number('BE 0123.456.789', 'BE') == '0123456789'
    assert normalize_company_number('123456789', 'BE') == '0123456789'
    assert normalize_company_number('be0123456789', 'BE') == '0123456789'
    assert normalize_company_number('12345', 'BE') is None
    assert normalize_company_number('0123 4567', 'NL') == '01234567'
    assert normalize_company_number('1234567', 'NL') is None
    assert normalize_company_number('HRB 1234', 'DE') is None
    assert normalize_company_number(float('nan'), 'NL') is None


def test_cx_kvknummer_leading_zero_kept(tmp_path):
    path = tmp_path / 'crm.xlsx'
    crm(dict(name='Gemeente A', cx_kvknummer='01234567')).to_excel(path, index=False)
    loaded = load_crm(path)
    assert loaded.iloc[0]['cx_kvknummer'] == '01234567'
    assert normalize_company_number(loaded.iloc[0]['cx_kvknummer'], 'NL') == '01234567'


def test_crm_name_key_strips_prefixes():
    assert crm_name_key({'name': 'Gemeente De Bilt', 'canonical_name': float('nan')}) == 'bilt'
    assert crm_name_key({'name': 'Ville de Liège', 'canonical_name': ''}) == 'liege'
    assert crm_name_key({'name': 'X', 'canonical_name': 'Stadt Köln'}) == 'koln'
    assert crm_name_key({'name': 'Landkreis Kassel', 'canonical_name': None}) == 'kassel'


# ---------- pass 1 ----------

def test_kvk_match_wins():
    entities = ents(
        dict(entity_id='NL-CBS-GM0001', name='Aadorp', country='NL', kind='nl_gemeente',
             official_ids='cbs:GM0001;kvk:01234567'),
        dict(entity_id='NL-CBS-GM0002', name='Bedum', country='NL', kind='nl_gemeente',
             official_ids='cbs:GM0002;kvk:87654321'),
    )
    frame = crm(dict(name='Gemeente Bedum', canonical_name='Bedum', detected_type='gemeente_nl',
                     cx_kvknummer='0123 4567'))
    matched, rest = run_pass1(frame, entities)
    assert list(matched.columns) == MATCH_COLUMNS
    row = matched.iloc[0]
    assert row['entity_id'] == 'NL-CBS-GM0001'
    assert row['match_pass'] == 'rule'
    assert row['match_reason'] == 'KvK/KBO-nummer'
    assert row['confidence'] == 'high'
    assert row['crm_name'] == 'Gemeente Bedum'
    assert len(rest) == 0


def test_kbo_match():
    entities = ents(dict(entity_id='BE-NIS-44021', name='Gent', country='BE', kind='be_gemeente',
                         official_ids='nis:44021;kbo:0207451227'))
    frame = crm(dict(name='Stad X', detected_country='BE', cx_kvknummer='BE 207.451.227'))
    matched, _ = run_pass1(frame, entities)
    assert matched_ids(matched) == {'acc-0': 'BE-NIS-44021'}


def test_kind_filter_blocks_wrong_kind():
    entities = ents(
        dict(entity_id='NL-CBS-PV29', name='Zeeland', country='NL', kind='nl_provincie'),
        dict(entity_id='BE-NIS-44021', name='Gent', country='BE', kind='be_gemeente'),
        dict(entity_id='DE-AGS-05314000', name='Bonn', country='DE', kind='de_kreisfreie_stadt'),
    )
    frame = crm(
        dict(name='Veiligheidsregio Zeeland', canonical_name='Zeeland', detected_type='veiligheidsregio'),
        dict(name='Politiezone Gent', canonical_name='Gent', detected_type='politiezone',
             detected_country='BE'),
        dict(name='Stadtwerke Bonn', canonical_name='Bonn', detected_type='stadtwerke',
             detected_country='DE'),
    )
    matched, rest = run_pass1(frame, entities)
    assert len(matched) == 0
    assert list(rest['accountid']) == ['acc-0', 'acc-1', 'acc-2']


def test_same_name_and_kind_matches():
    entities = ents(
        dict(entity_id='NL-CBS-PV29', name='Zeeland', country='NL', kind='nl_provincie'),
        dict(entity_id='NL-VR-19', name='Veiligheidsregio Zeeland', country='NL',
             kind='nl_veiligheidsregio'),
    )
    frame = crm(
        dict(name='Provincie Zeeland', canonical_name='Zeeland', detected_type='provincie_nl'),
        dict(name='Veiligheidsregio Zeeland', canonical_name='Zeeland', detected_type='veiligheidsregio'),
    )
    matched, rest = run_pass1(frame, entities)
    assert matched_ids(matched) == {'acc-0': 'NL-CBS-PV29', 'acc-1': 'NL-VR-19'}
    assert set(matched['match_reason']) == {'same name'}


def test_unknown_type_uses_raw_name_against_all_kinds():
    entities = ents(
        dict(entity_id='NL-OO-1', name='Dienst Dommelvallei', country='NL', kind='nl_samenwerking'),
        dict(entity_id='NL-CBS-GM1', name='Dommelvallei', country='NL', kind='nl_gemeente'),
    )
    frame = crm(dict(name='Dienst Dommelvallei', canonical_name='Dommelvallei', detected_type='onbekend'))
    matched, _ = run_pass1(frame, entities)
    assert matched_ids(matched) == {'acc-0': 'NL-OO-1'}


def test_de_same_name_resolved_by_postcode():
    entities = ents(
        dict(entity_id='DE-AGS-07137068', name='Neustadt', country='DE', kind='de_gemeinde',
             postcode='56579'),
        dict(entity_id='DE-AGS-09575153', name='Neustadt', country='DE', kind='de_gemeinde',
             postcode='91413'),
        dict(entity_id='DE-AGS-06534016', name='Neustadt', country='DE', kind='de_gemeinde',
             postcode='35279'),
    )
    frame = crm(
        dict(name='Stadt Neustadt', canonical_name='Neustadt', detected_type='gemeinde_de',
             detected_country='DE', cx_address3_postalcode='91413'),
        dict(name='Gemeinde Neustadt', canonical_name='Neustadt', detected_type='gemeinde_de',
             detected_country='DE', address1_composite='Hauptstr. 1, 35277 Neustadt'),
        dict(name='Markt Neustadt', canonical_name='Neustadt', detected_type='gemeinde_de',
             detected_country='DE', cx_address3_postalcode='10115'),
    )
    matched, rest = run_pass1(frame, entities)
    assert matched_ids(matched) == {'acc-0': 'DE-AGS-09575153', 'acc-1': 'DE-AGS-06534016'}
    assert set(matched['match_reason']) == {'naam + postcode'}
    assert list(rest['accountid']) == ['acc-2']


def test_ambiguous_exact_name_not_matched_in_pass1():
    entities = ents(
        dict(entity_id='NL-OO-1', name='Regio Noord', country='NL', kind='nl_samenwerking'),
        dict(entity_id='NL-OO-2', name='Regio Noord', country='NL', kind='nl_samenwerking'),
        dict(entity_id='DE-AGS-1', name='Neuhof', country='DE', kind='de_gemeinde', postcode='36119'),
        dict(entity_id='DE-AGS-2', name='Neuhof', country='DE', kind='de_gemeinde', postcode='36118'),
    )
    frame = crm(
        dict(name='Regio Noord', detected_type='samenwerking_nl'),
        dict(name='Gemeinde Neuhof', canonical_name='Neuhof', detected_type='gemeinde_de',
             detected_country='DE', cx_address3_postalcode='36110'),
    )
    matched, rest = run_pass1(frame, entities)
    assert len(matched) == 0
    assert list(rest['accountid']) == ['acc-0', 'acc-1']
    assert 'priority' in rest.columns and 'cx_address3_city' in rest.columns


def test_alias_match_reason():
    entities = ents(dict(entity_id='NL-CBS-GM1942', name='Gooise Meren', country='NL',
                         kind='nl_gemeente'))
    alias_frame = aliases({'alias_name': 'Bussum', 'country': 'NL', 'entity_id': 'NL-CBS-GM1942',
                           'reason': 'predecessor, merged 2016'})
    frame = crm(dict(name='Gemeente Bussum', canonical_name='Bussum', detected_type='gemeente_nl'))
    matched, _ = run_pass1(frame, entities, alias_frame)
    row = matched.iloc[0]
    assert row['entity_id'] == 'NL-CBS-GM1942'
    assert row['match_reason'] == 'predecessor, merged 2016'


def test_build_name_index_shape():
    entities = ents(dict(entity_id='NL-CBS-GM1942', name='Gooise Meren', country='NL',
                         kind='nl_gemeente'))
    alias_frame = aliases({'alias_name': 'Bussum', 'country': 'NL', 'entity_id': 'NL-CBS-GM1942',
                           'reason': 'predecessor, merged 2016'})
    index = build_name_index(entities, alias_frame)
    assert index[('NL', 'gooise meren')] == [('NL-CBS-GM1942', 'nl_gemeente', 'same name')]
    assert index[('NL', 'bussum')] == [('NL-CBS-GM1942', 'nl_gemeente', 'predecessor, merged 2016')]


def test_ocmw_account_matches_gemeente():
    entities = ents(dict(entity_id='BE-NIS-44021', name='Gent', country='BE', kind='be_gemeente'))
    frame = crm(dict(name='OCMW Gent', canonical_name='Gent', detected_type='ocmw', detected_country='BE'))
    matched, _ = run_pass1(frame, entities)
    assert matched_ids(matched) == {'acc-0': 'BE-NIS-44021'}


# ---------- candidates ----------

def _cand_setup():
    entities = ents(
        dict(entity_id='NL-CBS-GM1942', name='Gooise Meren', country='NL', kind='nl_gemeente',
             region='Noord-Holland'),
        dict(entity_id='NL-CBS-GM0001', name='Bussum Noord', country='NL', kind='nl_samenwerking'),
        dict(entity_id='NL-CBS-GM0002', name='Utrecht', country='NL', kind='nl_gemeente'),
    )
    alias_frame = aliases({'alias_name': 'Bussum', 'country': 'NL', 'entity_id': 'NL-CBS-GM1942',
                           'reason': 'predecessor, merged 2016'})
    return entities, alias_frame


def test_candidates_include_alias_hit_with_via():
    entities, alias_frame = _cand_setup()
    by_country = entities_by_country(entities, alias_frame)
    index = build_name_index(entities, alias_frame)
    row = {'name': 'Gemeente Bussum', 'canonical_name': 'Bussum', 'tam_country': 'NL',
           'priority': 'gov', 'detected_type': 'gemeente_nl'}
    cands = candidates(row, by_country, index)
    assert cands[0]['entity_id'] == 'NL-CBS-GM1942'
    assert cands[0]['via'] == 'alias: Bussum, predecessor, merged 2016'
    assert cands[0]['score'] == 100
    assert cands[0]['region'] == 'Noord-Holland'
    assert set(cands[0]) == {'entity_id', 'name', 'kind', 'region', 'postcode', 'score', 'via'}
    ids = [c['entity_id'] for c in cands]
    assert 'NL-CBS-GM0001' in ids  # fuzzy hit (token set)
    assert 'NL-CBS-GM0002' not in ids
    assert len(ids) == len(set(ids))


def test_candidates_exact_hit_any_kind():
    entities = ents(dict(entity_id='NL-CBS-PV29', name='Zeeland', country='NL', kind='nl_provincie'))
    index = build_name_index(entities, aliases())
    row = {'name': 'Veiligheidsregio Zeeland', 'canonical_name': 'Zeeland', 'tam_country': 'NL',
           'priority': 'other', 'detected_type': 'veiligheidsregio'}
    cands = candidates(row, entities_by_country(entities), index)
    assert [c['entity_id'] for c in cands] == ['NL-CBS-PV29']
    assert cands[0]['via'] == 'naam'


def test_candidates_floor_depends_on_priority():
    entities = ents(dict(entity_id='NL-OO-1', name='Regionale Dienst Gooi', country='NL',
                         kind='nl_samenwerking'))
    by_country = entities_by_country(entities)
    index = build_name_index(entities, aliases())
    base = {'name': 'Regio Dienst Goi', 'canonical_name': float('nan'), 'tam_country': 'NL',
            'detected_type': 'onbekend'}
    gov = candidates({**base, 'priority': 'gov'}, by_country, index)
    other = candidates({**base, 'priority': 'other'}, by_country, index)
    assert [c['entity_id'] for c in gov] == ['NL-OO-1']
    assert 75 <= gov[0]['score'] < 90
    assert other == []


def test_candidates_de_sorted_by_postcode_and_capped():
    rows = [dict(entity_id=f'DE-AGS-{i:08d}', name='Neustadt', country='DE', kind='de_gemeinde',
                 postcode=f'{10000 + i * 1000:05d}') for i in range(20)]
    rows.append(dict(entity_id='DE-AGS-99999999', name='Neustadt', country='DE', kind='de_gemeinde',
                     postcode='29123'))
    entities = ents(*rows)
    index = build_name_index(entities, aliases())
    row = {'name': 'Stadt Neustadt', 'canonical_name': 'Neustadt', 'tam_country': 'DE',
           'priority': 'gov', 'detected_type': 'gemeinde_de', 'cx_address3_postalcode': '29124'}
    cands = candidates(row, entities_by_country(entities), index)
    assert len(cands) == 15
    assert cands[0]['entity_id'] == 'DE-AGS-99999999'
    assert cands[1]['postcode'] == '29000'


def test_candidates_country_missing_returns_empty():
    row = {'name': 'Gemeente A', 'canonical_name': 'A', 'tam_country': 'BE', 'priority': 'gov',
           'detected_type': 'gemeente_be'}
    assert candidates(row, {}, {}) == []


# ---------- overrides ----------

def _matches(*rows):
    return pd.DataFrame([dict(zip(MATCH_COLUMNS, r)) for r in rows], columns=MATCH_COLUMNS)


def test_override_forces_no_match():
    matches = _matches(('E1', 'acc-1', 'Gemeente A', 'rule', 'same name', 'high'),
                       ('E2', 'acc-2', 'Gemeente B', 'ai', 'x', 'low'))
    overrides = pd.DataFrame([{'accountid': 'acc-1', 'entity_id': '', 'reason': 'geen klant'}])
    out, warnings = apply_overrides(matches, overrides, {'E1', 'E2'})
    assert list(out['accountid']) == ['acc-2']
    assert list(out.columns) == MATCH_COLUMNS
    assert warnings == []


def test_override_replaces_and_unknown_id_warns():
    matches = _matches(('E1', 'acc-1', 'Gemeente A', 'rule', 'same name', 'high'),
                       ('E2', 'acc-2', 'Gemeente B', 'ai', 'x', 'low'))
    overrides = pd.DataFrame([
        {'accountid': 'acc-2', 'entity_id': 'E3', 'reason': 'handmatig'},
        {'accountid': 'acc-1', 'entity_id': 'E-UNKNOWN', 'reason': 'typo'},
        {'accountid': 'acc-9', 'entity_id': 'E1', 'reason': float('nan')},
    ])
    out, warnings = apply_overrides(matches, overrides, {'E1', 'E2', 'E3'})
    by_acc = out.set_index('accountid')
    assert by_acc.loc['acc-1', 'entity_id'] == 'E1'
    assert by_acc.loc['acc-1', 'match_pass'] == 'rule'
    assert by_acc.loc['acc-2', 'entity_id'] == 'E3'
    assert by_acc.loc['acc-2', 'match_pass'] == 'override'
    assert by_acc.loc['acc-2', 'match_reason'] == 'handmatig'
    assert by_acc.loc['acc-2', 'crm_name'] == 'Gemeente B'
    assert by_acc.loc['acc-9', 'match_pass'] == 'override'
    assert by_acc.loc['acc-9', 'match_reason'] == 'override'
    assert len(warnings) == 1 and 'E-UNKNOWN' in warnings[0] and 'acc-1' in warnings[0]
