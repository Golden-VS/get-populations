import json
import zipfile
from pathlib import Path

import pandas as pd

from tam.sources.be import (
    is_flemish_nis, load_be_wb, load_be_wikidata, parse_op_dump, parse_statbel_population,
    parse_wikidata_gemeenten,
)
from tam.sources.common import SourceCache

OP_FIXTURE = Path(__file__).parent / 'fixtures' / 'op_mini.nt'

GEMEENTEN = pd.DataFrame([
    {'entity_id': 'BE-NIS-11001', 'name': 'Alfadorp'},
    {'entity_id': 'BE-NIS-11002', 'name': 'Sint-Betadorp'},
])


def _op():
    return parse_op_dump(OP_FIXTURE, GEMEENTEN)


def _members(b, eid):
    m = b.memberships
    return m[m.entity_id == eid]


# ---- OP-dump ----

def test_op_inactive_skipped():
    b = _op()
    assert 'BE-KBO-0800000001' not in set(b.entities.entity_id)
    assert set(b.entities.entity_id) == {'BE-KBO-0862000001', 'BE-KBO-0505000001', 'BE-KBO-0682000001'}


def test_op_members_mapped_to_nis():
    b = _op()
    pz = b.entities[b.entities.entity_id == 'BE-KBO-0862000001'].iloc[0]
    assert pz['kind'] == 'be_politiezone' and pz['population_method'] == 'sum of members'
    assert pz['name'] == 'PZ Alfa/Bèta' and pz['official_ids'] == 'kbo:0862000001'
    m = _members(b, 'BE-KBO-0862000001')
    # g1 via refnis-code, g2 zonder code via genormaliseerde naam
    assert set(m.member_entity_id) == {'BE-NIS-11001', 'BE-NIS-11002'}
    assert set(m.membership_type) == {'cooperation'} and set(m.member_kind) == {'be_gemeente'}
    # welzijnsvereniging: OCMW -> zijn gemeente; opgeheven gemeente -> fusieopvolger;
    # rol 'gerelateerd' telt niet als lid; geen dubbele leden
    w = _members(b, 'BE-KBO-0682000001')
    assert sorted(w.member_entity_id) == ['BE-NIS-11001', 'BE-NIS-11002']
    wv = b.entities[b.entities.entity_id == 'BE-KBO-0682000001'].iloc[0]
    assert wv['kind'] == 'be_welzijnsvereniging' and wv['name'] == 'Welzijnsvereniging Welzijn Samen'


def test_op_agb_same_as_municipality():
    b = _op()
    agb = b.entities[b.entities.entity_id == 'BE-KBO-0505000001'].iloc[0]
    assert agb['kind'] == 'be_agb' and agb['population_method'] == 'same as municipality'
    m = _members(b, 'BE-KBO-0505000001')
    assert len(m) == 1
    assert m.iloc[0]['member_entity_id'] == 'BE-NIS-11001' and m.iloc[0]['membership_type'] == 'same_as'


def test_op_gemeente_kbo_patches():
    b = _op()
    patches = b.extras['id_patches']
    assert patches.to_dict('records') == [{'entity_id': 'BE-NIS-11001', 'official_ids': 'kbo:0207000001'}]
    assert b.status[0].name == 'be_op' and b.status[0].ok


def test_op_aliases_from_other_labels():
    b = _op()
    a = b.aliases[b.aliases.entity_id == 'BE-KBO-0682000001']
    assert 'Welzijn Samen' in set(a.alias_name)


# ---- W/B ----

def test_flemish_nis_rule():
    assert all(is_flemish_nis(c) for c in ['11001', '23105', '24045', '31005', '46030', '73109'])
    assert not any(is_flemish_nis(c) for c in ['21004', '25005', '52011', '62063', '63023', '85009', '92094'])


def test_wb_police_excludes_zones_with_any_flemish_member(tmp_path, monkeypatch):
    from tam.sources import be
    monkeypatch.setattr(be, 'BE_POLITIEZONE_GEMEENTEN', {
        'Waals': ['Luik', 'Seraing', 'Saint-Nicolas'],
        'Gemengd': ['Seraing', 'Voeren'],
        'Vlaams': ['Voeren'],
    })
    gemeenten = pd.DataFrame([
        {'entity_id': 'BE-NIS-62063', 'name': 'Liège'},
        {'entity_id': 'BE-NIS-62063', 'name': 'Luik'},
        {'entity_id': 'BE-NIS-62096', 'name': 'Seraing'},
        {'entity_id': 'BE-NIS-73109', 'name': 'Voeren'},
        {'entity_id': 'BE-NIS-62093', 'name': 'Saint-Nicolas'},
        {'entity_id': 'BE-NIS-46021', 'name': 'Sint-Niklaas'},
        {'entity_id': 'BE-NIS-46021', 'name': 'Saint-Nicolas'},
    ])
    b = load_be_wb(SourceCache(offline=True, base_dir=tmp_path), gemeenten, {'73109', '46021'})
    pz = b.entities[b.entities.kind == 'be_politiezone']
    assert len(pz) == 1 and pz.iloc[0]['population_method'] == 'sum of members'
    m = b.memberships[b.memberships.entity_id == pz.iloc[0]['entity_id']]
    # dubbelzinnige Franse naam: de niet-Vlaamse gemeente wint
    assert set(m.member_entity_id) == {'BE-NIS-62063', 'BE-NIS-62096', 'BE-NIS-62093'}
    # SPW-xlsx ontbreekt offline: rest gaat door, status meldt het
    assert any(s.name == 'be_wb' for s in b.status)
    assert (b.entities.kind == 'be_hulpverleningszone').sum() == 15
    assert (b.entities.kind == 'be_fod').sum() >= 12


def test_wb_spw_intercommunales_only(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Intercommunales'
    ws.append(['Intercommunale ', 'Nom du prestataire'])
    ws.append(['IDEA', 'x'])
    ws.append(['ORES ASSETS ', 'y'])
    ws.append([None, None])
    s2 = wb.create_sheet('SLSP')
    s2.append(['SLSP', 'Nom'])
    s2.append(['Logement Alfa', 'z'])
    wb.save(tmp_path / 'be_spw_cadastre.xlsx')
    b = load_be_wb(SourceCache(offline=True, base_dir=tmp_path), pd.DataFrame(columns=['entity_id', 'name']), set())
    spw = b.entities[b.entities.entity_id.str.startswith('BE-SPW-')]
    assert set(spw.name) == {'IDEA', 'ORES ASSETS'}
    assert set(spw.kind) == {'be_intercommunale'} and set(spw.population_method) == {'unknown'}
    assert 'BE-SPW-ORES-ASSETS' in set(spw.entity_id)


# ---- Wikidata + Statbel ----

def _bind(**kw):
    return {k: {'value': v} for k, v in kw.items()}


WD_GEM = [
    _bind(item='http://www.wikidata.org/entity/Q1', itemLabel='Luik', nis='62063', population='190000',
          date='2018-01-01T00:00:00Z', labelNl='Luik', labelFr='Liège', labelDe='Lüttich'),
    _bind(item='http://www.wikidata.org/entity/Q1', itemLabel='Luik', nis='62063', population='195000',
          date='2024-01-01T00:00:00Z', labelNl='Luik', labelFr='Liège', labelDe='Lüttich'),
    _bind(item='http://www.wikidata.org/entity/Q2', itemLabel='Q2', nis='11001',
          population='14000', date='2020-01-01T00:00:00Z', articleName='Aartselaar'),
    _bind(item='http://www.wikidata.org/entity/Q3', itemLabel='Brussel', nis='21004',
          labelNl='Brussel', labelFr='Bruxelles'),
]


def test_wikidata_gemeenten_official_language_name_and_latest_population():
    df = parse_wikidata_gemeenten(pd.DataFrame([{k: v['value'] for k, v in b.items()} for b in WD_GEM]))
    df = df.set_index('nis')
    assert df.loc['62063', 'name'] == 'Liège'               # Wallonie: Franse naam
    assert set(df.loc['62063', 'labels']) == {'Liège', 'Luik', 'Lüttich'}
    assert df.loc['62063', 'wd_population'] == 195000
    assert df.loc['11001', 'name'] == 'Aartselaar'          # label = Q-id -> wikipedia-titel
    assert df.loc['21004', 'name'] == 'Brussel'


def test_statbel_population_sum_per_refnis(tmp_path):
    txt = ('CD_REFNIS|TX_DESCR_NL|TX_DESCR_FR|MS_POPULATION\n'
           '62063|Luik|Liège|100\n62063|Luik|Liège|5\n11001|Aartselaar|Aartselaar|7\n')
    z = tmp_path / 'pop.zip'
    with zipfile.ZipFile(z, 'w') as f:
        f.writestr('TF_SOC_POP_STRUCT_2026.txt', '﻿' + txt)
    assert parse_statbel_population(z) == {'62063': 105, '11001': 7}


def test_load_be_wikidata_offline(tmp_path):
    (tmp_path / 'be_wd_gemeenten.json').write_text(json.dumps(WD_GEM))
    (tmp_path / 'be_wd_provincies.json').write_text(json.dumps([
        _bind(item='http://www.wikidata.org/entity/Q1127', itemLabel='Luik', nis='60000',
              labelNl='Luik', labelFr='Liège', labelDe='Lüttich'),
        _bind(item='http://www.wikidata.org/entity/Q1116', itemLabel='Antwerpen', nis='10000',
              labelNl='Antwerpen', labelFr='Anvers'),
    ]))
    txt = 'CD_REFNIS|MS_POPULATION\n62063|200\n'
    with zipfile.ZipFile(tmp_path / 'be_statbel_pop_2026.zip', 'w') as f:
        f.writestr('TF_SOC_POP_STRUCT_2026.txt', txt)
    b = load_be_wikidata(SourceCache(offline=True, base_dir=tmp_path))
    e = b.entities.set_index('entity_id')
    assert e.loc['BE-NIS-62063', 'population'] == 200          # Statbel wint
    assert e.loc['BE-NIS-62063', 'population_date'] == '2026-01-01'
    assert e.loc['BE-NIS-11001', 'population'] == 14000        # Wikidata-terugval
    assert e.loc['BE-NIS-62063', 'region'] == 'Liège' and e.loc['BE-NIS-62063', 'official_ids'] == 'nis:62063'
    assert e.loc['BE-NIS-21004', 'region'] == 'Brussels Hoofdstedelijk Gewest'
    assert e.loc['BE-NIS-60000', 'population_method'] == 'sum of members'
    m = b.memberships
    assert set(m[m.entity_id == 'BE-NIS-60000'].member_entity_id) == {'BE-NIS-62063'}
    assert set(m.membership_type) == {'territorial'}
    assert b.extras['municipal_population']['BE-NIS-62063'] == 200
    names = b.extras['be_gemeente_names']
    assert {'Luik', 'Liège', 'Lüttich'} <= set(names[names.entity_id == 'BE-NIS-62063'].name)
    assert 'Luik' in set(b.aliases[b.aliases.entity_id == 'BE-NIS-62063'].alias_name)
