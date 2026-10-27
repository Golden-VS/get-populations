"""Tests voor voorgangers-aliassen (geen netwerk)."""
import pandas as pd

from tam.entities import ALIAS_COLUMNS, ENTITY_COLUMNS
from tam.sources import aliases
from tam.sources.aliases import load_predecessors, resolve_chain


def test_chain_resolved_to_current():
    result = resolve_chain({'A': 'B', 'B': 'C'}, {'C'})
    assert result == {'A': 'C', 'B': 'C'}


def test_cycle_does_not_hang():
    assert resolve_chain({'A': 'B', 'B': 'A'}, {'C'}) == {}


def test_depth_limit():
    edges = {f'N{i}': f'N{i + 1}' for i in range(10)}
    result = resolve_chain(edges, {'N10'})
    assert 'N9' in result and 'N5' in result
    assert 'N0' not in result


class FakeCache:
    def __init__(self, tables):
        self.tables = tables
        self.calls = []

    def sparql(self, name, query):
        self.calls.append(name)
        return self.tables.get(name, pd.DataFrame())


def _entities(ids):
    rows = [{c: '' for c in ENTITY_COLUMNS} | {'entity_id': i, 'name': i, 'country': i[:2]} for i in ids]
    return pd.DataFrame(rows, columns=ENTITY_COLUMNS)


def _bind(pred, label, end, succ, succ_label='', code=''):
    return {'pred': pred, 'predLabel': label, 'end': end, 'succ': succ,
            'succLabel': succ_label, 'code': code}


def test_nl_parse_with_chain_and_year():
    nl = pd.DataFrame([
        _bind('Q1', 'Bussum', '2016-01-01T00:00:00Z', 'Q2'),
        _bind('Q2', 'Tussenstop', '2018-01-01T00:00:00Z', 'Q3'),
        _bind('Q3', 'Gooise Meren', '', '', code=''),  # niet gebruikt
        _bind('Q9', 'Weesp', '2022-03-24T00:00:00Z', 'Q4', code='0363'),
        _bind('Q1', 'Bussum', '2016-01-01T00:00:00Z', 'Q2'),  # dubbel
        _bind('Q7', 'Nergens', '2000-01-01T00:00:00Z', 'Q8', code='9999'),  # onbekend
        _bind('Q5', 'Split', '2000-01-01T00:00:00Z', 'Q4', code='0363'),
        _bind('Q5', 'Split', '2000-01-01T00:00:00Z', 'Q6', code='GM1942'),  # dubbelzinnig
    ])
    nl.loc[nl.index[1], 'succ'] = 'Q3'
    nl.loc[nl.index[2], ['pred', 'succ']] = ['Q3x', 'Q3x']  # ruis
    nl = nl.drop(index=2)
    # Q2 -> Q3 (Q3 heeft code 1942 via een eigen regel)
    nl = pd.concat([nl, pd.DataFrame([_bind('Q0', 'Anders', '2001-01-01T00:00:00Z', 'Q3', code='GM1942')])],
                   ignore_index=True)
    ents = _entities(['NL-GM-GM0363', 'NL-GM-GM1942'])
    res = load_predecessors(FakeCache({'aliases_nl': nl}), ents, pd.DataFrame(columns=ALIAS_COLUMNS))
    got = {r.alias_name: (r.entity_id, r.reason) for r in res.aliases.itertuples()}
    assert got['Bussum'] == ('NL-GM-GM1942', 'predecessor, merged 2016')
    assert got['Tussenstop'] == ('NL-GM-GM1942', 'predecessor, merged 2018')
    assert got['Weesp'] == ('NL-GM-GM0363', 'predecessor, merged 2022')
    assert 'Nergens' not in got
    assert 'Split' not in got  # twee verschillende opvolgers
    assert len(res.aliases) == len(set(res.aliases.alias_name))
    assert list(res.aliases.columns) == ALIAS_COLUMNS
    assert (res.aliases.country == 'NL').all()
    assert res.status[0].name == 'aliases'


def test_label_fallback_and_unknown_year():
    nl = pd.DataFrame([
        {'pred': 'Q1', 'predLabel': 'Q1', 'article': 'Zottegem oud', 'end': '', 'succ': 'Q2',
         'succLabel': '', 'code': '0363'},
        {'pred': 'Q3', 'predLabel': 'Q3', 'end': '2001-01-01T00:00:00Z', 'succ': 'Q2',
         'succLabel': '', 'code': '0363'},
    ])
    ents = _entities(['NL-GM-GM0363'])
    res = load_predecessors(FakeCache({'aliases_nl': nl}), ents, pd.DataFrame(columns=ALIAS_COLUMNS))
    assert list(res.aliases.alias_name) == ['Zottegem oud']
    assert res.aliases.iloc[0].reason == 'predecessor'


def test_be_code_padding():
    be = pd.DataFrame([_bind('Q1', 'Zwijndrecht', '2025-01-01T00:00:00Z', 'Q2', code='23105')])
    ents = _entities(['BE-NIS-23105', 'BE-NIS-99999'])
    res = load_predecessors(FakeCache({'aliases_be': be}), ents, pd.DataFrame(columns=ALIAS_COLUMNS))
    assert res.aliases.iloc[0].entity_id == 'BE-NIS-23105'
    assert res.aliases.iloc[0].country == 'BE'


def test_de_successor_via_alias_ids_and_alias_table():
    de = pd.DataFrame([
        _bind('Q1', 'Altdorf', '2020-01-01T00:00:00Z', 'Q2', 'Neudorf', code='01001001'),
        _bind('Q3', 'Oberdorf', '2019-01-01T00:00:00Z', 'Q4', 'Mitteldorf', code=''),
    ])
    ents = _entities(['DE-AGS-01002000'])
    al = pd.DataFrame([{'alias_name': 'Mitteldorf', 'country': 'DE',
                        'entity_id': 'DE-AGS-01002000', 'reason': 'Gemeinde in Amt'}])
    res = load_predecessors(FakeCache({'aliases_de': de}), ents, al,
                            alias_ids={'DE-AGS-01001001': 'DE-AGS-01002000'})
    got = {r.alias_name: r.entity_id for r in res.aliases.itertuples()}
    assert got == {'Altdorf': 'DE-AGS-01002000', 'Oberdorf': 'DE-AGS-01002000'}


def test_de_falls_back_to_chunks(monkeypatch):
    class Boom(FakeCache):
        def sparql(self, name, query):
            self.calls.append(name)
            if name == 'aliases_de':
                raise TimeoutError('te groot')
            return pd.DataFrame()
    cache = Boom({})
    res = load_predecessors(cache, _entities([]), pd.DataFrame(columns=ALIAS_COLUMNS))
    assert 'aliases_de_01' in cache.calls and 'aliases_de_16' in cache.calls
    assert res.status[0].ok


def test_total_failure_gives_status_not_crash():
    class Dead:
        def sparql(self, name, query):
            raise RuntimeError('geen netwerk')
    res = load_predecessors(Dead(), _entities([]), pd.DataFrame(columns=ALIAS_COLUMNS))
    assert res.aliases.empty
    assert res.status[0].name == 'aliases' and not res.status[0].ok
