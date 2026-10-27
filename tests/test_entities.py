import math

import pandas as pd

from tam.entities import (
    ALIAS_COLUMNS, ENTITY_COLUMNS, MEMBERSHIP_COLUMNS, SourceBundle, SourceStatus,
    apply_country_totals, apply_member_population, make_entity_id, new_entity, slugify,
)


def _ents(rows):
    return pd.DataFrame([new_entity(**r) for r in rows], columns=ENTITY_COLUMNS)


def _mem(pairs):
    return pd.DataFrame(
        [{'entity_id': a, 'member_entity_id': b, 'member_kind': '', 'membership_type': 'cooperation',
          'join_date': ''} for a, b in pairs], columns=MEMBERSHIP_COLUMNS)


def test_entity_id_is_deterministic():
    assert make_entity_id('NL', 'GM', 'gm0363') == 'NL-GM-GM0363'
    assert make_entity_id('DE', 'HAND', 'Bezirk Mitte') == make_entity_id('DE', 'HAND', 'bezirk  mitte')


def test_slugify():
    assert slugify('Gemeente Zwölfaxing & Co') == 'gemeente-zwolfaxing-co'


def test_new_entity_defaults():
    e = new_entity(entity_id='x', name='Foo', kind='nl_gemeente')
    assert e['segment'] == 'Local government' and e['detailed_segment'] == 'Municipality'
    assert e['match_name'] == 'Foo'
    assert set(e) == set(ENTITY_COLUMNS)
    assert e['population'] is None and e['region'] == ''


def test_bundle_empty_and_merge():
    b = SourceBundle.empty()
    assert list(b.entities.columns) == ENTITY_COLUMNS
    assert list(b.memberships.columns) == MEMBERSHIP_COLUMNS
    assert list(b.aliases.columns) == ALIAS_COLUMNS
    o = SourceBundle.empty()
    o.entities = _ents([{'entity_id': 'a', 'name': 'A', 'kind': 'nl_gemeente'}])
    o.status.append(SourceStatus('s', True, 1, '2026', ''))
    o.extras = {'municipal_population': {'a': 1}}
    o2 = SourceBundle.empty()
    o2.extras = {'municipal_population': {'b': 2}}
    m = b.merge(o).merge(o2)
    assert len(m.entities) == 1 and len(m.status) == 1
    assert m.extras['municipal_population'] == {'a': 1, 'b': 2}


def test_sum_counts_distinct_municipal_members_only():
    ents = _ents([{'entity_id': 'X', 'name': 'X', 'kind': 'nl_samenwerking',
                   'population_method': 'sum of members'}])
    mem = _mem([('X', 'GM1'), ('X', 'GM1'), ('X', 'PV1'), ('X', 'GM2')])
    out, warns = apply_member_population(ents, mem, {'GM1': 100, 'GM2': 50})
    assert out.loc[0, 'population'] == 150
    assert out.loc[0, 'population_method'] == 'sum of members'
    assert warns == []


def test_sum_includes_non_entity_municipalities():
    ents = _ents([{'entity_id': 'A', 'name': 'A', 'kind': 'de_gemeindeverband',
                   'population_method': 'sum of members'}])
    out, _ = apply_member_population(ents, _mem([('A', 'DE-AGS-07131001')]),
                                     {'DE-AGS-07131001': 900})
    assert out.loc[0, 'population'] == 900


def test_prefilled_population_not_recomputed():
    ents = _ents([{'entity_id': 'X', 'name': 'X', 'kind': 'nl_samenwerking',
                   'population_method': 'sum of members', 'population': 7}])
    out, _ = apply_member_population(ents, _mem([('X', 'GM1')]), {'GM1': 100})
    assert out.loc[0, 'population'] == 7


def test_no_resolvable_members_gives_unknown():
    ents = _ents([{'entity_id': 'X', 'name': 'X', 'kind': 'nl_samenwerking',
                   'population_method': 'sum of members'}])
    out, warns = apply_member_population(ents, _mem([('X', 'U1'), ('X', 'U2')]), {'GM1': 1})
    assert math.isnan(out.loc[0, 'population'])
    assert out.loc[0, 'population_method'] == 'unknown'
    assert len(warns) == 1 and 'U1' in warns[0] and 'U2' in warns[0] and 'X' in warns[0]


def test_country_total():
    ents = _ents([
        {'entity_id': 'NL-GM-1', 'name': 'a', 'country': 'NL', 'kind': 'nl_gemeente', 'population': 100},
        {'entity_id': 'NL-GM-2', 'name': 'b', 'country': 'NL', 'kind': 'nl_gemeente', 'population': 200},
        {'entity_id': 'NL-MIN-1', 'name': 'm', 'country': 'NL', 'kind': 'nl_ministerie',
         'population_method': 'country total'},
    ])
    out, = [apply_country_totals(ents, {'NL-GM-1': 100, 'NL-GM-2': 200, 'BE-NIS-1': 999})]
    assert out.loc[out.entity_id == 'NL-MIN-1', 'population'].iloc[0] == 300
