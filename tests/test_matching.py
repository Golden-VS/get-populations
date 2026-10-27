import re as _re

import pandas as pd
import pytest

from tam import matching as mt
from tam.ai import AIBatchError, AIRefusal, CostCapReached, CostTracker
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


def test_type_without_kinds_never_name_matches_in_pass1():
    # M2: zonder verenigbare kinds (onbekend of niet-overheidstype) geen naamregel, door naar pass 2
    entities = ents(
        dict(entity_id='NL-OO-1', name='Dienst Dommelvallei', country='NL', kind='nl_samenwerking'),
        dict(entity_id='NL-CBS-GM1', name='Dommelvallei', country='NL', kind='nl_gemeente'),
        dict(entity_id='NL-CBS-PV29', name='Zeeland', country='NL', kind='nl_provincie'),
    )
    frame = crm(
        dict(name='Dienst Dommelvallei', canonical_name='Dommelvallei', detected_type='onbekend'),
        dict(name='Zeeland', detected_type=float('nan')),
        dict(name='Zeeland', detected_type='commercieel_of_overig',
             **{'Segment (category)': 'Non-profit'}),
    )
    matched, rest = run_pass1(frame, entities)
    assert len(matched) == 0
    assert list(rest['accountid']) == ['acc-0', 'acc-1', 'acc-2']


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


# ---------- review fix round 1 ----------

def _adenau():
    return ents(
        dict(entity_id='DE-ARS-071315003', name='Verbandsgemeinde Adenau', match_name='Adenau',
             country='DE', kind='de_gemeindeverband', postcode='53518;53520'),
        dict(entity_id='DE-AGS-07131003', name='Adenau', country='DE', kind='de_gemeinde',
             postcode='53518'),
    )


def test_verband_account_matches_verband_not_seat_gemeinde():
    frame = crm(dict(name='Verbandsgemeinde Adenau', canonical_name='Adenau',
                     detected_type='verbandsgemeinde', detected_country='DE',
                     cx_address3_postalcode='53518'))
    matched, rest = run_pass1(frame, _adenau())
    assert matched_ids(matched) == {'acc-0': 'DE-ARS-071315003'}
    assert matched.iloc[0]['match_reason'] == 'same name'


def test_gemeinde_account_matches_gemeinde_not_verband():
    frame = crm(dict(name='Gemeinde Adenau', canonical_name='Adenau', detected_type='gemeinde_de',
                     detected_country='DE', cx_address3_postalcode='53518'))
    matched, _ = run_pass1(frame, _adenau())
    assert matched_ids(matched) == {'acc-0': 'DE-AGS-07131003'}


def _roth():
    # Ortsgemeinde Roth zit in een Verbandsgemeinde (RP, alias); een zelfstandige Roth in Bayern
    entities = ents(
        dict(entity_id='DE-ARS-071325009', name='Verbandsgemeinde Hamm (Sieg)',
             match_name='Hamm (Sieg)', country='DE', kind='de_gemeindeverband',
             postcode='57539;57577'),
        dict(entity_id='DE-AGS-09576143', name='Roth', country='DE', kind='de_gemeinde',
             postcode='91154'),
    )
    alias_frame = aliases({'alias_name': 'Roth', 'country': 'DE', 'entity_id': 'DE-ARS-071325009',
                           'reason': 'member of Verbandsgemeinde Hamm (Sieg)'})
    return entities, alias_frame


def test_de_narrowed_hit_in_other_land_goes_to_pass2():
    # F1: de vernauwing naar de primaire kind mag niet over Landsgrenzen heen matchen
    entities, alias_frame = _roth()
    frame = crm(
        dict(name='Ortsgemeinde Roth', canonical_name='Roth', detected_type='gemeinde_de',
             detected_country='DE', cx_address3_postalcode='57539'),
        dict(name='Gemeinde Roth', canonical_name='Roth', detected_type='gemeinde_de',
             detected_country='DE'),
        dict(name='Stadt Roth', canonical_name='Roth', detected_type='gemeinde_de',
             detected_country='DE', cx_address3_postalcode='91154'),
    )
    matched, rest = run_pass1(frame, entities, alias_frame)
    assert matched_ids(matched) == {'acc-2': 'DE-AGS-09576143'}
    assert list(rest['accountid']) == ['acc-0', 'acc-1']


def test_de_narrowed_hit_needs_postcode_at_least_as_close_as_discarded():
    entities, alias_frame = _roth()
    # de gehouden Gemeinde deelt 3 cijfers, de weggevallen alias (Verband) alle 5
    entities.loc[entities['entity_id'] == 'DE-AGS-09576143', 'postcode'] = '57511'
    frame = crm(dict(name='Roth', canonical_name='Roth', detected_type='gemeinde_de',
                     detected_country='DE', cx_address3_postalcode='57539'))
    matched, rest = run_pass1(frame, entities, alias_frame)
    assert len(matched) == 0 and list(rest['accountid']) == ['acc-0']


def test_mixed_kind_tie_goes_to_rest():
    entities = ents(
        dict(entity_id='DE-AGS-1', name='Hof', country='DE', kind='de_gemeinde', postcode='95028'),
        dict(entity_id='DE-AGS-2', name='Hof', country='DE', kind='de_kreisfreie_stadt',
             postcode='95030'),
    )
    frame = crm(dict(name='Stadt Hof', canonical_name='Hof', detected_type='gemeinde_de',
                     detected_country='DE', cx_address3_postalcode='95028'))
    matched, rest = run_pass1(frame, entities)
    assert len(matched) == 0
    assert list(rest['accountid']) == ['acc-0']


def test_shared_company_number_never_rule_matches():
    entities = ents(
        dict(entity_id='NL-A', name='Amsterdam', country='NL', kind='nl_gemeente',
             official_ids='kvk:34366966'),
        dict(entity_id='NL-B', name='Stadsdeel Noord', country='NL', kind='nl_stadsdeel',
             official_ids='kvk:34366966'),
    )
    frame = crm(
        dict(name='Gemeente Amsterdam', canonical_name='Amsterdam', detected_type='gemeente_nl',
             cx_kvknummer='34366966'),
        dict(name='Iets', detected_type='onbekend', cx_kvknummer='34366966'),
    )
    matched, rest = run_pass1(frame, entities)
    assert matched_ids(matched) == {'acc-0': 'NL-A'}
    assert matched.iloc[0]['match_reason'] == 'same name'
    assert list(rest['accountid']) == ['acc-1']


def test_nl_kvk_seven_digits_left_padded():
    assert normalize_company_number('1234567', 'NL') == '01234567'
    assert normalize_company_number('1234567.0', 'NL') == '01234567'
    assert normalize_company_number('123456', 'NL') is None


def test_postcode_needs_word_boundaries():
    entities = ents(
        dict(entity_id='DE-AGS-1', name='Neustadt', country='DE', kind='de_gemeinde', postcode='12345'),
        dict(entity_id='DE-AGS-2', name='Neustadt', country='DE', kind='de_gemeinde', postcode='99999'),
    )
    frame = crm(
        dict(name='Stadt Neustadt', canonical_name='Neustadt', detected_type='gemeinde_de',
             detected_country='DE', address1_composite='Postfach 1234567, Neustadt'),
        dict(name='Stadt Neustadt', canonical_name='Neustadt', detected_type='gemeinde_de',
             detected_country='DE', cx_address3_postalcode='123456'),
        dict(name='Stadt Neustadt', canonical_name='Neustadt', detected_type='gemeinde_de',
             detected_country='DE', cx_address3_postalcode='D-12345'),
    )
    matched, rest = run_pass1(frame, entities)
    assert matched_ids(matched) == {'acc-2': 'DE-AGS-1'}
    assert list(rest['accountid']) == ['acc-0', 'acc-1']


def test_alias_via_fallback_names_alias():
    entities, alias_frame = _cand_setup()
    index = build_name_index(entities, alias_frame)
    row = {'name': 'Gemeente Bussum', 'canonical_name': 'Bussum', 'tam_country': 'NL',
           'priority': 'gov', 'detected_type': 'gemeente_nl'}
    cands = candidates(row, entities_by_country(entities), index)  # zonder aliassen voorberekend
    assert cands[0]['entity_id'] == 'NL-CBS-GM1942'
    assert cands[0]['via'] == 'alias: bussum, predecessor, merged 2016'


def test_entities_by_country_container_and_plain_frame_warning(caplog):
    entities, alias_frame = _cand_setup()
    by_country = entities_by_country(entities, alias_frame)
    assert isinstance(by_country['NL'].frame, pd.DataFrame)
    index = build_name_index(entities, alias_frame)
    row = {'name': 'Utrecht', 'canonical_name': 'Utrecht', 'tam_country': 'NL', 'priority': 'gov',
           'detected_type': 'gemeente_nl'}
    with caplog.at_level('WARNING', logger='tam.matching'):
        cands = candidates(row, {'NL': by_country['NL'].frame}, index)
    assert [c['entity_id'] for c in cands][0] == 'NL-CBS-GM0002'
    assert any('voorberekend' in r.getMessage() for r in caplog.records)


def test_scope_logs_dropped_counts(caplog):
    frame = crm(
        dict(name='Gemeente A'),
        dict(name='Foreign Ltd', detected_country='OTHER', **{'Segment (category)': 'Commercial'}),
        dict(name='Leeg', detected_country=float('nan')),
        dict(name='Shop BV', detected_type='commercieel_of_overig',
             **{'Segment (category)': 'Commercial', 'segment_confidence': 'high'}),
    )
    with caplog.at_level('INFO', logger='tam.matching'):
        crm_in_scope(frame)
    text = ' '.join(r.getMessage() for r in caplog.records)
    assert '2 accounts met onbekend land' in text
    assert '1 zeker-commerciele accounts' in text


def test_override_unknown_id_logs_error(caplog):
    matches = _matches(('E1', 'acc-1', 'Gemeente A', 'rule', 'same name', 'high'))
    overrides = pd.DataFrame([{'accountid': 'acc-1', 'entity_id': 'E-UNKNOWN', 'reason': 'typo'}])
    with caplog.at_level('ERROR', logger='tam.matching'):
        _, warnings = apply_overrides(matches, overrides, {'E1'})
    assert warnings[0].startswith('FOUT:')
    errors = [r for r in caplog.records if r.levelname == 'ERROR']
    assert len(errors) == 1 and 'E-UNKNOWN' in errors[0].getMessage()


def test_override_for_account_not_in_crm_warns_and_is_ignored(caplog):
    # M3: een override voor een accountid dat niet in de CRM staat, wordt genegeerd
    matches = _matches(('E1', 'acc-1', 'Gemeente A', 'rule', 'same name', 'high'))
    overrides = pd.DataFrame([{'accountid': 'acc-77', 'entity_id': 'E1', 'reason': 'oud'},
                              {'accountid': 'acc-78', 'entity_id': '', 'reason': 'oud'}])
    with caplog.at_level('WARNING', logger='tam.matching'):
        out, warnings = apply_overrides(matches, overrides, {'E1'},
                                        crm_names={'acc-1': 'Gemeente A'})
    assert list(out['accountid']) == ['acc-1']
    assert len(warnings) == 2 and 'acc-77' in warnings[0] and 'acc-78' in warnings[1]
    assert all('niet in de CRM' in w for w in warnings)
    logged = [r.getMessage() for r in caplog.records if r.levelname == 'WARNING']
    assert any('acc-77' in m for m in logged)


# ---------- pass 2 (AI) ----------

_BLOCK_RE = _re.compile(r'^volgnummer (\d+)\n  crm-naam: (.*)$', _re.MULTILINE)


class FakeMatch:
    """Nep voor call_parsed: kiest per CRM-naam een vaste entity_id (standaard de eerste kandidaat)."""

    def __init__(self, choose=None, exc=None, skip=()):
        self.choose = choose or {}
        self.exc = list(exc or [])
        self.skip = set(skip)
        self.calls = []

    def __call__(self, client, tracker, **kw):
        self.calls.append(kw)
        if self.exc:
            exc = self.exc.pop(0)
            if exc is not None:
                raise exc
        items = []
        for block in _re.split(r'\n(?=volgnummer \d+\n)', kw['user']):
            m = _BLOCK_RE.search(block)
            if not m:
                continue
            n, name = int(m.group(1)), m.group(2)
            if name in self.skip:
                continue
            first = _re.search(r'^    (\S+) \| ', block, _re.MULTILINE)
            entity_id = self.choose.get(name, first.group(1) if first else 'none')
            items.append(mt.MatchItem(volgnummer=n, entity_id=entity_id, reason='zelfde gemeente',
                                      confidence='high'))
        return mt.MatchBatch(items=items)

    def names(self, call):
        return [m.group(2) for m in _BLOCK_RE.finditer(self.calls[call]['user'])]


@pytest.fixture
def fake_ai(monkeypatch):
    def _p(fake):
        monkeypatch.setattr(mt, 'call_parsed', fake)
        return fake
    return _p


def _p2_entities():
    entities = ents(
        dict(entity_id='NL-CBS-GM1942', name='Gooise Meren', country='NL', kind='nl_gemeente',
             region='Noord-Holland'),
        dict(entity_id='NL-CBS-GM0002', name='Utrecht', country='NL', kind='nl_gemeente'),
        dict(entity_id='NL-CBS-GM0003', name='Aadorp', country='NL', kind='nl_gemeente'),
        dict(entity_id='NL-CBS-GM0004', name='Bedorp', country='NL', kind='nl_gemeente'),
        dict(entity_id='NL-CBS-GM0005', name='Cedorp', country='NL', kind='nl_gemeente'),
    )
    alias_frame = aliases({'alias_name': 'Bussum', 'country': 'NL', 'entity_id': 'NL-CBS-GM1942',
                           'reason': 'predecessor, merged 2016'})
    return entities, alias_frame


def run_pass2(frame, tmp_path, *, use_ai=True, batch_size=20, tracker=None, entities=None):
    default_entities, alias_frame = _p2_entities()
    entities = default_entities if entities is None else entities
    scope, _ = crm_in_scope(frame)
    return mt.pass2(scope, entities, alias_frame, object(), tracker or CostTracker(50),
                    use_ai=use_ai, cache_path=tmp_path / 'match_cache.csv', batch_size=batch_size)


def _reasons(unmatched):
    return dict(zip(unmatched['accountid'], unmatched['reason']))


def test_no_candidate_no_ai_call(tmp_path, fake_ai):
    fake = fake_ai(FakeMatch())
    matched, unmatched, stats = run_pass2(crm(dict(name='Qwxyz Holding')), tmp_path)
    assert fake.calls == []
    assert len(matched) == 0
    assert list(unmatched.columns) == UNMATCHED_COLUMNS
    row = unmatched.iloc[0]
    assert row['reason'] == 'geen kandidaat boven drempel'
    assert row['best_candidate'] == ''
    assert row['tam_country'] == 'NL'
    assert stats['no_candidate'] == 1


def test_ai_match_columns_and_prompt(tmp_path, fake_ai):
    fake = fake_ai(FakeMatch())
    frame = crm(dict(name='Gemeente Bussum', canonical_name='Bussum', detected_type='gemeente_nl',
                     cx_address3_postalcode='1401 AA', cx_address3_city='Bussum'))
    matched, unmatched, stats = run_pass2(frame, tmp_path)
    assert list(matched.columns) == MATCH_COLUMNS
    assert matched.iloc[0].to_dict() == {
        'entity_id': 'NL-CBS-GM1942', 'accountid': 'acc-0', 'crm_name': 'Gemeente Bussum',
        'match_pass': 'ai', 'match_reason': 'zelfde gemeente', 'confidence': 'high'}
    assert len(unmatched) == 0
    user = fake.calls[0]['user']
    assert 'type: gemeente_nl' in user
    assert '1401 AA' in user and 'Bussum' in user and 'land: NL' in user
    assert ('NL-CBS-GM1942 | Gooise Meren | nl_gemeente | Noord-Holland |  | '
            'alias: Bussum, predecessor, merged 2016') in user
    system = fake.calls[0]['system']
    for word in ('OCMW', 'Ortsgemeinde', 'none', 'Stadtwerke', 'GmbH'):
        assert word in system
    assert fake.calls[0]['output_model'] is mt.MatchBatch
    assert stats['ai_matched'] == 1


def test_ai_choice_outside_candidates_rejected(tmp_path, fake_ai, caplog):
    fake = fake_ai(FakeMatch(choose={'Gemeente Bussum': 'NL-CBS-GM0002'}))  # Utrecht: geen kandidaat
    frame = crm(dict(name='Gemeente Bussum', canonical_name='Bussum', detected_type='gemeente_nl'))
    with caplog.at_level('WARNING', logger='tam.matching'):
        matched, unmatched, stats = run_pass2(frame, tmp_path)
    assert len(fake.calls) == 1
    assert len(matched) == 0
    assert _reasons(unmatched) == {'acc-0': 'AI: geen passende organisatie'}
    assert unmatched.iloc[0]['best_candidate'] == 'Gooise Meren'
    assert unmatched.iloc[0]['best_score'] == 100
    assert any('NL-CBS-GM0002' in r.getMessage() for r in caplog.records)
    assert stats['invalid_id'] == 1


def test_ai_none_is_unmatched_and_cached(tmp_path, fake_ai):
    fake_ai(FakeMatch(choose={'Gemeente Bussum': 'none'}))
    frame = crm(dict(name='Gemeente Bussum', canonical_name='Bussum', detected_type='gemeente_nl'))
    matched, unmatched, _ = run_pass2(frame, tmp_path)
    assert len(matched) == 0
    assert _reasons(unmatched) == {'acc-0': 'AI: geen passende organisatie'}
    fake2 = fake_ai(FakeMatch())
    _, unmatched2, stats2 = run_pass2(frame, tmp_path)
    assert fake2.calls == []
    assert _reasons(unmatched2) == {'acc-0': 'AI: geen passende organisatie'}
    assert stats2['cached'] == 1


def test_cache_reused_when_name_and_candidates_same(tmp_path, fake_ai):
    frame = crm(dict(name='Gemeente Bussum', canonical_name='Bussum', detected_type='gemeente_nl'))
    fake_ai(FakeMatch())
    first, _, _ = run_pass2(frame, tmp_path)
    cache = pd.read_csv(tmp_path / 'match_cache.csv', dtype=str, keep_default_na=False)
    assert list(cache.columns) == ['accountid', 'name', 'candidate_hash', 'entity_id', 'reason',
                                   'confidence', 'datum']
    assert list(cache['entity_id']) == ['NL-CBS-GM1942']

    fake2 = fake_ai(FakeMatch())
    second, _, stats = run_pass2(frame, tmp_path)
    assert fake2.calls == []
    assert stats['cached'] == 1
    assert second.to_dict('records') == first.to_dict('records')

    # andere kandidatenset (extra entiteit) -> opnieuw naar AI
    entities, _ = _p2_entities()
    extra = ents(dict(entity_id='NL-X-1', name='Bussum Noord', country='NL', kind='nl_samenwerking'))
    fake3 = fake_ai(FakeMatch())
    run_pass2(frame, tmp_path, entities=pd.concat([entities, extra], ignore_index=True))
    assert len(fake3.calls) == 1
    assert 'NL-X-1 | Bussum Noord' in fake3.calls[0]['user']

    # andere naam -> opnieuw naar AI
    renamed = crm(dict(name='Gemeente Bussum (oud)', canonical_name='Bussum',
                       detected_type='gemeente_nl'))
    fake4 = fake_ai(FakeMatch())
    run_pass2(renamed, tmp_path)
    assert len(fake4.calls) == 1


def _three_accounts():
    return crm(dict(name='Gemeente Aadorp'), dict(name='Gemeente Bedorp'),
               dict(name='Gemeente Cedorp'))


def test_cap_reached_leaves_rest_unmatched(tmp_path, fake_ai):
    fake = fake_ai(FakeMatch(exc=[None, CostCapReached('plafond')]))
    matched, unmatched, stats = run_pass2(_three_accounts(), tmp_path, batch_size=1)
    assert len(fake.calls) == 2
    assert matched_ids(matched) == {'acc-0': 'NL-CBS-GM0003'}
    assert _reasons(unmatched) == {'acc-1': 'kostenplafond bereikt',
                                   'acc-2': 'kostenplafond bereikt'}
    cache = pd.read_csv(tmp_path / 'match_cache.csv', dtype=str, keep_default_na=False)
    assert list(cache['accountid']) == ['acc-0']
    assert stats['cap'] == 2


def test_failed_batch_marked_and_next_batch_runs(tmp_path, fake_ai):
    fake = fake_ai(FakeMatch(exc=[AIBatchError('kapot')]))
    matched, unmatched, stats = run_pass2(_three_accounts(), tmp_path, batch_size=2)
    assert len(fake.calls) == 2
    assert matched_ids(matched) == {'acc-2': 'NL-CBS-GM0005'}
    assert _reasons(unmatched) == {'acc-0': 'AI-fout', 'acc-1': 'AI-fout'}
    cache = pd.read_csv(tmp_path / 'match_cache.csv', dtype=str, keep_default_na=False)
    assert list(cache['accountid']) == ['acc-2']  # fouten worden niet gecachet
    assert stats['failed'] == 2


def test_refused_batch_marked_and_not_cached(tmp_path, fake_ai):
    fake_ai(FakeMatch(exc=[AIRefusal('nee')]))
    matched, unmatched, _ = run_pass2(_three_accounts(), tmp_path, batch_size=2)
    assert _reasons(unmatched) == {'acc-0': 'AI weigerde', 'acc-1': 'AI weigerde'}
    assert matched_ids(matched) == {'acc-2': 'NL-CBS-GM0005'}
    cache = pd.read_csv(tmp_path / 'match_cache.csv', dtype=str, keep_default_na=False)
    assert list(cache['accountid']) == ['acc-2']


def test_gov_priority_batches_first(tmp_path, fake_ai):
    fake = fake_ai(FakeMatch())
    commercial = {'Segment (category)': 'Commercial', 'segment_confidence': 'low'}
    frame = crm(dict(name='Gemeente Aadorp', **commercial), dict(name='Gemeente Bedorp'),
                dict(name='Gemeente Cedorp', **commercial), dict(name='Gemeente Bussum'))
    run_pass2(frame, tmp_path, batch_size=2)
    assert fake.names(0) == ['Gemeente Bedorp', 'Gemeente Bussum']
    assert fake.names(1) == ['Gemeente Aadorp', 'Gemeente Cedorp']


def test_no_ai_skips_calls_but_uses_cache(tmp_path, fake_ai):
    fake_ai(FakeMatch())
    run_pass2(crm(dict(name='Gemeente Aadorp')), tmp_path)
    fake = fake_ai(FakeMatch())
    matched, unmatched, stats = run_pass2(_three_accounts(), tmp_path, use_ai=False)
    assert fake.calls == []
    assert matched_ids(matched) == {'acc-0': 'NL-CBS-GM0003'}
    assert _reasons(unmatched) == {'acc-1': 'AI overgeslagen (--no-ai)',
                                   'acc-2': 'AI overgeslagen (--no-ai)'}
    cache = pd.read_csv(tmp_path / 'match_cache.csv', dtype=str, keep_default_na=False)
    assert list(cache['accountid']) == ['acc-0']
    assert stats['to_ai'] == 2


def test_pass2_pending_counts_accounts_needing_ai(tmp_path, fake_ai):
    entities, alias_frame = _p2_entities()
    frame = crm(dict(name='Gemeente Aadorp'), dict(name='Qwxyz Holding'), dict(name='Gemeente Bedorp'))
    scope, _ = crm_in_scope(frame)
    index = build_name_index(entities, alias_frame)
    by_country = entities_by_country(entities, alias_frame)
    assert mt.pass2_pending(scope, by_country, index) == 2
    fake_ai(FakeMatch())
    run_pass2(crm(dict(name='Gemeente Aadorp')), tmp_path)
    assert mt.pass2_pending(scope, by_country, index, cache_path=tmp_path / 'match_cache.csv') == 1


def test_estimate_matching_cost():
    # 2 batches x (9000 x $4 + 3000 x $20) / 1e6 = 2 x 0.096
    assert mt.estimate_matching_cost(21) == pytest.approx(0.192)
    assert mt.estimate_matching_cost(0) == 0


# ---------- pass 2 review polish ----------

def _cache_ids(tmp_path):
    cache = pd.read_csv(tmp_path / 'match_cache.csv', dtype=str, keep_default_na=False)
    return dict(zip(cache['accountid'], cache['entity_id']))


def test_missing_volgnummer_is_ai_error_and_not_cached(tmp_path, fake_ai, caplog):
    fake_ai(FakeMatch(skip={'Gemeente Bedorp'}))
    with caplog.at_level('WARNING', logger='tam.matching'):
        matched, unmatched, stats = run_pass2(_three_accounts(), tmp_path)
    assert matched_ids(matched) == {'acc-0': 'NL-CBS-GM0003', 'acc-2': 'NL-CBS-GM0005'}
    assert _reasons(unmatched) == {'acc-1': 'AI-fout'}
    assert _cache_ids(tmp_path) == {'acc-0': 'NL-CBS-GM0003', 'acc-2': 'NL-CBS-GM0005'}
    assert stats['failed'] == 1
    assert any('acc-1' in r.getMessage() for r in caplog.records)


def test_empty_entity_id_is_none_without_invalid_warning(tmp_path, fake_ai, caplog):
    fake_ai(FakeMatch(choose={'Gemeente Aadorp': ''}))
    with caplog.at_level('WARNING', logger='tam.matching'):
        matched, unmatched, stats = run_pass2(crm(dict(name='Gemeente Aadorp')), tmp_path)
    assert len(matched) == 0
    assert _reasons(unmatched) == {'acc-0': 'AI: geen passende organisatie'}
    assert stats['ai_none'] == 1 and stats['invalid_id'] == 0
    assert not any('kandidatenlijst' in r.getMessage() for r in caplog.records)
    assert _cache_ids(tmp_path) == {'acc-0': 'none'}


def test_batch_error_log_is_truncated(tmp_path, fake_ai, caplog):
    secret = 'modeltekst ' * 100  # 1100 tekens
    fake_ai(FakeMatch(exc=[AIBatchError(secret)]))
    with caplog.at_level('WARNING', logger='tam.matching'):
        run_pass2(crm(dict(name='Gemeente Aadorp')), tmp_path)
    messages = [r.getMessage() for r in caplog.records if 'Matchbatch mislukt' in r.getMessage()]
    assert len(messages) == 1
    assert 'AIBatchError' in messages[0]
    assert secret not in messages[0]
    assert len(messages[0]) < 300


def _failing_to_csv(monkeypatch):
    """to_csv schrijft half en faalt dan (schijf vol tijdens schrijven)."""
    def broken(self, path=None, *args, **kwargs):
        with open(path, 'w') as fh:
            fh.write('half geschreven')
        raise OSError('schijf vol')

    monkeypatch.setattr(pd.DataFrame, 'to_csv', broken)


def test_match_cache_write_failure_keeps_previous_cache(tmp_path, fake_ai, monkeypatch):
    fake_ai(FakeMatch())
    run_pass2(crm(dict(name='Gemeente Aadorp')), tmp_path)
    before = (tmp_path / 'match_cache.csv').read_text()
    _failing_to_csv(monkeypatch)
    with pytest.raises(OSError):
        run_pass2(crm(dict(name='Gemeente Aadorp'), dict(name='Gemeente Bedorp')), tmp_path)
    assert (tmp_path / 'match_cache.csv').read_text() == before
    assert not (tmp_path / 'match_cache.csv.part').exists()
