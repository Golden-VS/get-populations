import logging
import math

import pandas as pd

from tam.entities import (
    ALIAS_COLUMNS, ENTITY_COLUMNS, MEMBERSHIP_COLUMNS, SourceBundle, SourceStatus, new_entity,
)
from tam.master import DEFAULT_ORDER, build_master, default_loaders


def _bundle(name, entities=(), memberships=(), aliases=(), extras=None, ok=True):
    b = SourceBundle.empty()
    if entities:
        b.entities = pd.DataFrame([new_entity(**e) for e in entities], columns=ENTITY_COLUMNS)
    if memberships:
        b.memberships = pd.DataFrame(
            [{'entity_id': a, 'member_entity_id': m, 'member_kind': '', 'membership_type': t,
              'join_date': ''} for a, m, t in memberships], columns=MEMBERSHIP_COLUMNS)
    if aliases:
        b.aliases = pd.DataFrame(
            [{'alias_name': n, 'country': c, 'entity_id': e, 'reason': 'test'} for n, c, e in aliases],
            columns=ALIAS_COLUMNS)
    b.extras = dict(extras or {})
    b.status.append(SourceStatus(name, ok, len(b.entities), '', 'test'))
    return b


def _gem(eid, name, pop, country='NL', kind='nl_gemeente'):
    return dict(entity_id=eid, name=name, country=country, kind=kind, population=pop,
                population_method='own', population_source='bron', population_date='2026-01-01')


def _fixed(bundle):
    return lambda ctx: bundle


def _raise(ctx):
    raise RuntimeError('bron onbereikbaar')


def _status(result, name):
    return next(s for s in result.status if s.name == name)


def test_failed_source_does_not_abort(caplog):
    a = _bundle('a', [_gem('NL-GM-GM0001', 'Aa', 100)])
    c = _bundle('c', [_gem('NL-GM-GM0002', 'Cee', 200)])
    with caplog.at_level(logging.ERROR):
        result = build_master(None, loaders=[('a', _fixed(a)), ('b', _raise), ('c', _fixed(c))])
    assert set(result.entities['entity_id']) == {'NL-GM-GM0001', 'NL-GM-GM0002'}
    st = _status(result, 'b')
    assert st.ok is False and 'bron onbereikbaar' in st.message
    assert any('bron onbereikbaar' in r.message for r in caplog.records if r.levelno == logging.ERROR)
    assert _status(result, 'a').ok and _status(result, 'c').ok


def test_dependent_loader_skipped_when_dependency_failed():
    calls = []

    def dependent(ctx):
        calls.append(ctx)
        return _bundle('dep', [_gem('NL-GM-GM0009', 'Dep', 1)])

    # Afhankelijkheid gooit een fout
    result = build_master(None, loaders=[('basis', _raise), ('dep', dependent, ('basis',))])
    st = _status(result, 'dep')
    assert st.ok is False and st.message == 'overgeslagen: basis ontbreekt'
    assert not calls and len(result.entities) == 0

    # Afhankelijkheid meldt zelf ok=False zonder entiteiten
    failed = _bundle('basis', ok=False)
    result = build_master(None, loaders=[('basis', _fixed(failed)), ('dep', dependent, ('basis',))])
    assert _status(result, 'dep').message == 'overgeslagen: basis ontbreekt'
    assert not calls


def test_dependent_loader_receives_dependency_bundle():
    seen = {}
    basis = _bundle('basis', [_gem('BE-NIS-11001', 'Aartselaar', 10, 'BE', 'be_gemeente')],
                    extras={'be_gemeente_names': pd.DataFrame({'entity_id': ['BE-NIS-11001'],
                                                               'name': ['Aartselaar']})})

    def dependent(ctx):
        seen['names'] = ctx.bundles['basis'].extras['be_gemeente_names']
        seen['merged'] = list(ctx.merged.entities['entity_id'])
        return _bundle('dep')

    result = build_master(None, loaders=[('basis', _fixed(basis)), ('dep', dependent, ('basis',))])
    assert list(seen['names']['name']) == ['Aartselaar']
    assert seen['merged'] == ['BE-NIS-11001']
    assert _status(result, 'dep').ok


def test_duplicate_entity_id_logged_and_dropped(caplog):
    a = _bundle('a', [_gem('NL-GM-GM0001', 'Eerste', 100)])
    b = _bundle('b', [_gem('NL-GM-GM0001', 'Tweede', 999)])
    with caplog.at_level(logging.ERROR):
        result = build_master(None, loaders=[('a', _fixed(a)), ('b', _fixed(b))])
    assert len(result.entities) == 1
    assert result.entities.iloc[0]['name'] == 'Eerste'
    assert any('NL-GM-GM0001' in r.message for r in caplog.records if r.levelno == logging.ERROR)
    assert any('NL-GM-GM0001' in w for w in result.extras['warnings'])


def test_id_patches_attach_kvk_to_gemeente():
    gem = dict(_gem('NL-GM-GM0363', 'Amsterdam', 900000), official_ids='cbs:GM0363')
    cbs = _bundle('nl_cbs', [gem])
    oo = _bundle('nl_oo', extras={'id_patches': pd.DataFrame(
        [{'entity_id': 'NL-GM-GM0363', 'official_ids': 'kvk:34366966;cbs:GM0363;oin:0001'},
         {'entity_id': 'NL-GM-GM9999', 'official_ids': 'kvk:12345678'},
         {'entity_id': 'NL-GM-GM0363', 'official_ids': float('nan')}])})
    result = build_master(None, loaders=[('nl_cbs', _fixed(cbs)), ('nl_oo', _fixed(oo))])
    row = result.entities.set_index('entity_id').loc['NL-GM-GM0363']
    assert row['official_ids'] == 'cbs:GM0363;kvk:34366966;oin:0001'
    assert any('NL-GM-GM9999' in w for w in result.extras['warnings'])


def test_populations_sums_country_totals_and_same_as():
    nl = _bundle('nl', [
        _gem('NL-GM-GM0001', 'Aa', 100), _gem('NL-GM-GM0002', 'Bee', 200),
        dict(entity_id='NL-PV-PV20', name='Provincie', country='NL', kind='nl_provincie',
             population_method='sum of members'),
        dict(entity_id='NL-OO-1', name='Ministerie', country='NL', kind='nl_ministerie',
             population_method='country total'),
    ], memberships=[('NL-PV-PV20', 'NL-GM-GM0001', 'territorial'),
                    ('NL-PV-PV20', 'NL-GM-GM0002', 'territorial'),
                    ('NL-PV-PV20', 'NL-GM-GM0002', 'territorial')])
    # municipal_population uit extras telt ook niet-entiteiten mee (DE Gemeinde in een Amt)
    de = _bundle('de', [
        dict(entity_id='DE-AGS-01', name='Land', country='DE', kind='de_bundesland',
             population=None, population_method='sum of members'),
    ], memberships=[('DE-AGS-01', 'DE-AGS-01001001', 'territorial'),
                    ('DE-AGS-01', 'DE-AGS-01001002', 'territorial')],
        extras={'municipal_population': {'DE-AGS-01001001': 5, 'DE-AGS-01001002': 7}})
    be = _bundle('be', [
        _gem('BE-NIS-11001', 'Aartselaar', 14000, 'BE', 'be_gemeente'),
        dict(entity_id='BE-OP-agb', name='AGB Aartselaar', country='BE', kind='be_agb',
             population_method='same as municipality'),
        dict(entity_id='BE-OP-agb2', name='AGB zonder', country='BE', kind='be_agb',
             population_method='same as municipality'),
    ], memberships=[('BE-OP-agb', 'BE-NIS-11001', 'same_as')])
    result = build_master(None, loaders=[('nl', _fixed(nl)), ('de', _fixed(de)), ('be', _fixed(be))])
    ents = result.entities.set_index('entity_id')
    assert ents.loc['NL-PV-PV20', 'population'] == 300
    assert ents.loc['NL-OO-1', 'population'] == 300
    assert ents.loc['DE-AGS-01', 'population'] == 12
    assert ents.loc['BE-OP-agb', 'population'] == 14000
    assert ents.loc['BE-OP-agb', 'population_method'] == 'same as municipality'
    assert ents.loc['BE-OP-agb', 'population_source'] == 'bron'
    assert math.isnan(ents.loc['BE-OP-agb2', 'population'])
    assert ents.loc['BE-OP-agb2', 'population_method'] == 'unknown'
    assert any('BE-OP-agb2' in w for w in result.extras['warnings'])
    # NL/BE municipal_population wordt uit de gemeente-entiteiten opgebouwd
    mp = result.extras['municipal_population']
    assert mp['NL-GM-GM0001'] == 100 and mp['BE-NIS-11001'] == 14000 and mp['DE-AGS-01001002'] == 7


def test_memberships_and_aliases_validated(caplog):
    b = _bundle('x', [
        _gem('NL-GM-GM0001', 'Aa', 100),
        dict(entity_id='NL-GR-1', name='GR', country='NL', kind='nl_samenwerking',
             population_method='sum of members'),
        dict(entity_id='NL-XX-1', name='Raar', country='NL', kind='nl_onbekend'),
    ], memberships=[('NL-GR-1', 'NL-GM-GM0001', 'cooperation'),
                    ('NL-GR-1', 'NL-GM-GM0777', 'cooperation'),     # oude gemeentecode
                    ('NL-GR-404', 'NL-GM-GM0001', 'cooperation')],  # onbekende samenwerking
        aliases=[('Oud Aa', 'NL', 'NL-GM-GM0001'), ('Spook', 'NL', 'NL-GM-GM0404')])
    with caplog.at_level(logging.ERROR):
        result = build_master(None, loaders=[('x', _fixed(b))])
    errors = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    # Onbekende samenwerking: lidmaatschap eruit met ERROR
    assert 'NL-GR-404' not in set(result.memberships['entity_id'])
    assert any('NL-GR-404' in m for m in errors)
    # Onbekend lid: blijft staan, telt niet mee, wel geteld in een waarschuwing
    assert 'NL-GM-GM0777' in set(result.memberships['member_entity_id'])
    assert result.entities.set_index('entity_id').loc['NL-GR-1', 'population'] == 100
    assert any('NL-GM-GM0777' in w and '1 ' in w for w in result.extras['warnings'])
    # Alias naar onbekende entiteit eruit met ERROR
    assert list(result.aliases['alias_name']) == ['Oud Aa']
    assert any('NL-GM-GM0404' in m for m in errors)
    # Onbekend kind: rij eruit met ERROR
    assert 'NL-XX-1' not in set(result.entities['entity_id'])
    assert any('nl_onbekend' in m and 'bron bron' not in m and 'bron ?' in m for m in errors)


def test_loader_without_status_gets_one():
    b = SourceBundle.empty()
    b.entities = pd.DataFrame([new_entity(**_gem('NL-GM-GM0001', 'Aa', 1))], columns=ENTITY_COLUMNS)
    result = build_master(None, loaders=[('kaal', _fixed(b))])
    st = _status(result, 'kaal')
    assert st.ok and st.rows == 1


def test_default_loader_order():
    specs = default_loaders()
    assert [s[0] for s in specs] == DEFAULT_ORDER == [
        'nl_cbs', 'nl_oo', 'nl_hand', 'be_wikidata', 'be_op', 'be_wb', 'de_gv', 'de_feu',
        'de_hand', 'aliases']
    deps = {s[0]: (s[2] if len(s) > 2 else ()) for s in specs}
    assert deps['be_op'] == ('be_wikidata',) and deps['be_wb'] == ('be_wikidata',)
    assert deps['de_hand'] == ('de_gv',)


def test_loader_returning_non_bundle_does_not_abort():
    good = _bundle('goed', [_gem('NL-GM-GM0001', 'Aa', 1)])

    broken_merge = SourceBundle.empty()
    broken_merge.extras = {'municipal_population': 'geen dict'}
    broken_merge.entities = None   # merge faalt op len(None)
    broken_merge.status.append(SourceStatus('stuk', True, 0, '', ''))
    result = build_master(None, loaders=[('niets', lambda ctx: None), ('stuk', lambda ctx: broken_merge),
                                         ('goed', _fixed(good))])
    st = _status(result, 'niets')
    assert st.ok is False and 'SourceBundle' in st.message
    assert _status(result, 'stuk').ok is False
    assert _status(result, 'goed').ok
    assert list(result.entities['entity_id']) == ['NL-GM-GM0001']
    assert result.entities['population'].dtype.kind in 'if'


def test_cooperation_members_from_other_bundle():
    gem = _bundle('nl_cbs', [_gem('NL-GM-GM0001', 'Aa', 100), _gem('NL-GM-GM0002', 'Bee', 250)])
    coop = _bundle('nl_oo', [
        dict(entity_id='NL-SO-SO0001', name='GR', country='NL', kind='nl_samenwerking',
             population_method='sum of members')],
        memberships=[('NL-SO-SO0001', 'NL-GM-GM0001', 'cooperation'),
                     ('NL-SO-SO0001', 'NL-GM-GM0002', 'cooperation')])
    result = build_master(None, loaders=[('nl_cbs', _fixed(gem)), ('nl_oo', _fixed(coop))])
    row = result.entities.set_index('entity_id').loc['NL-SO-SO0001']
    assert row['population'] == 350 and row['population_method'] == 'sum of members'
    assert not result.extras['warnings']


def test_default_wiring_passes_exact_arguments(monkeypatch):
    import tam.sources.aliases as al
    import tam.sources.be as be
    import tam.sources.de as de
    import tam.sources.nl as nl

    cache = object()
    calls = {}
    names = pd.DataFrame({'entity_id': ['BE-NIS-11001', 'BE-NIS-11001', 'BE-NIS-55004'],
                          'name': ['Aartselaar', 'Aartselaar FR', 'Braine-le-Comte']})
    be_wd = _bundle('be_wikidata', [
        _gem('BE-NIS-11001', 'Aartselaar', 10, 'BE', 'be_gemeente'),
        _gem('BE-NIS-55004', 'Braine-le-Comte', 20, 'BE', 'be_gemeente'),
        _gem('BE-NIS-24062', 'Leuven', 30, 'BE', 'be_gemeente'),
        dict(entity_id='BE-NIS-10000', name='Antwerpen', country='BE', kind='be_provincie',
             population_method='sum of members')],
        extras={'be_gemeente_names': names})
    de_pop = {'DE-AGS-01001000': 90000, 'DE-AGS-01051001': 500}
    verband = {'DE-VB-010515163': ['DE-AGS-01051001']}
    alias_ids = {'DE-AGS-01051001': 'DE-VB-010515163'}
    de_gv = _bundle('de_gv', [dict(entity_id='DE-AGS-01001000', name='Flensburg', country='DE',
                                   kind='de_kreisfreie_stadt', population=90000, population_method='own')],
                    extras={'municipal_population': de_pop, 'de_verband_members': verband,
                            'alias_ids': alias_ids, 'de_population_date': '2025-12-31'})

    def record(name, result=None):
        def fn(*args, **kwargs):
            calls[name] = (args, kwargs)
            return result if result is not None else _bundle(name)
        return fn

    monkeypatch.setattr(nl, 'load_nl_cbs', record('nl_cbs', _bundle('nl_cbs', [_gem('NL-GM-GM0001', 'Aa', 1)])))
    monkeypatch.setattr(nl, 'load_nl_oo', record('nl_oo'))
    monkeypatch.setattr(nl, 'load_nl_hand', record('nl_hand'))
    monkeypatch.setattr(be, 'load_be_wikidata', record('be_wikidata', be_wd))
    monkeypatch.setattr(be, 'load_be_op', record('be_op'))
    monkeypatch.setattr(be, 'load_be_wb', record('be_wb'))
    monkeypatch.setattr(de, 'load_de_gv', record('de_gv', de_gv))
    monkeypatch.setattr(de, 'load_de_feu', record('de_feu'))
    monkeypatch.setattr(de, 'load_de_hand', record('de_hand'))
    monkeypatch.setattr(al, 'load_predecessors', record('aliases'))

    result = build_master(cache)
    assert [s.name for s in result.status] == DEFAULT_ORDER
    assert all(s.ok for s in result.status)
    for name in ('nl_cbs', 'nl_oo', 'be_wikidata', 'de_gv', 'de_feu'):
        assert calls[name] == ((cache,), {})
    assert calls['nl_hand'] == ((), {})
    args, kwargs = calls['be_op']
    assert args[0] is cache and args[1] is names and not kwargs
    args, kwargs = calls['be_wb']
    assert args[0] is cache and args[1] is names and not kwargs
    assert args[2] == {'BE-NIS-11001', 'BE-NIS-24062'}
    assert calls['de_hand'] == ((de_pop,), {'verband_members': verband, 'population_date': '2025-12-31'})
    args, kwargs = calls['aliases']
    assert args[0] is cache and kwargs == {'alias_ids': alias_ids}
    assert set(args[1]['entity_id']) >= {'NL-GM-GM0001', 'BE-NIS-11001', 'DE-AGS-01001000'}
    assert list(args[2].columns) == ALIAS_COLUMNS
    assert not any('DE GV ontbreekt' in w for w in result.extras['warnings'])

    # DE GV faalt: de_hand overgeslagen, voorgangers zonder alias_ids met waarschuwing
    calls.clear()
    monkeypatch.setattr(de, 'load_de_gv', record('de_gv', _bundle('de_gv', ok=False)))
    result = build_master(cache)
    assert _status(result, 'de_hand').message == 'overgeslagen: de_gv ontbreekt'
    assert 'de_hand' not in calls
    assert calls['aliases'][1] == {'alias_ids': {}}
    assert any('DE GV ontbreekt' in w for w in result.extras['warnings'])


def test_stale_cache_fallback_visible_in_source_status():
    # F4: een lader die op een verouderde cache terugviel, krijgt dat in zijn statusbericht
    class Cache:
        stale = []

    def loader(ctx):
        ctx.cache.stale.append(('nl_oo_export', '2025-01-02'))
        return _bundle('a', [_gem('NL-GM-GM0001', 'Aa', 100)])

    result = build_master(Cache(), loaders=[('a', loader),
                                            ('b', _fixed(_bundle('b', [_gem('NL-GM-GM0002', 'Bee', 1)])))])
    assert 'verouderde cache, datum 2025-01-02' in _status(result, 'a').message
    assert 'verouderde cache' not in _status(result, 'b').message
    assert any('verouderde cache, datum 2025-01-02' in w for w in result.extras['warnings'])
