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


# ---- OO-register (Task 5) ----
from datetime import date
from pathlib import Path

from tam.sources.nl import parse_oo_export, load_nl_oo

OO_FIXTURE = Path(__file__).parent / 'fixtures' / 'oo_mini.xml'
RUN = date(2026, 10, 27)


def _oo():
    return parse_oo_export(OO_FIXTURE, RUN)


def _members(b, eid):
    m = b.memberships
    return set(m[m.entity_id == eid]['member_entity_id'])


def test_ended_gr_skipped():
    b = _oo()
    assert 'NL-SO-SO0004' not in set(b.entities.entity_id)


def test_gr_without_body_skipped():
    b = _oo()
    # GR 8004 heeft geen orgaan: alleen de drie gekoppelde organen bestaan
    bodies = set(b.entities[b.entities.kind.isin(
        ['nl_samenwerking', 'nl_veiligheidsregio'])]['entity_id'])
    assert bodies == {'NL-SO-SO0001', 'NL-SO-SO0003', 'NL-OO-9002'}
    assert set(b.memberships.entity_id) <= set(b.entities.entity_id)


def test_two_grs_same_body_merged_members_deduplicated():
    b = _oo()
    alfa = b.entities[b.entities.entity_id == 'NL-SO-SO0001']
    assert len(alfa) == 1 and alfa.iloc[0]['kind'] == 'nl_samenwerking'
    assert alfa.iloc[0]['population_method'] == 'sum of members'
    assert alfa.iloc[0]['official_ids'] == 'kvk:11111111;oin:00000001111111110000;tooi:so0001'
    members = _members(b, 'NL-SO-SO0001')
    assert {'NL-GM-GM0001', 'NL-GM-GM0002', 'NL-PV-PV20'} <= members
    assert 'NL-GM-GM7777' not in members          # grensoverschrijdend genegeerd
    m = b.memberships
    rows = m[(m.entity_id == 'NL-SO-SO0001') & (m.member_entity_id == 'NL-GM-GM0002')]
    assert len(rows) == 1 and rows.iloc[0]['join_date'] == '2012-05-01'
    assert set(m['membership_type']) == {'cooperation'}
    kinds = m[m.entity_id == 'NL-SO-SO0001'].set_index('member_entity_id')['member_kind']
    assert kinds['NL-GM-GM0001'] == 'nl_gemeente' and kinds['NL-PV-PV20'] == 'nl_provincie'
    assert kinds['NL-WS-WS0654'] == 'nl_waterschap'


def test_body_without_tooi_falls_back_to_systeemid():
    b = _oo()
    assert 'NL-OO-9002' in set(b.entities.entity_id)


def test_veiligheidsregio_kind():
    b = _oo()
    r = b.entities[b.entities.entity_id == 'NL-SO-SO0003'].iloc[0]
    assert r['kind'] == 'nl_veiligheidsregio'
    assert r['segment'] == 'Public safety & emergency'


def test_waterschap_population_from_table():
    b = _oo()
    ws = b.entities[b.entities.kind == 'nl_waterschap'].set_index('entity_id')
    assert set(ws.index) == {'NL-WS-WS0654', 'NL-WS-WS0999'}
    aa = ws.loc['NL-WS-WS0654']
    from step2_enrich import NL_WATERSCHAP_INWONERS as T
    assert aa['population'] == T['Aa en Maas']['population']
    assert aa['population_method'] == 'own' and aa['population_source'] == T['Aa en Maas']['bron_url']
    unk = ws.loc['NL-WS-WS0999']
    assert unk['population_method'] == 'unknown' and unk['population'] != unk['population']


def test_ministerie_country_total():
    b = _oo()
    e = b.entities[b.entities.entity_id == 'NL-OO-9030'].iloc[0]
    assert e['kind'] == 'nl_ministerie' and e['population_method'] == 'country total'
    assert e['country'] == 'NL'
    ag = b.entities[b.entities.entity_id == 'NL-OO-9031'].iloc[0]
    assert ag['kind'] == 'nl_rijksorganisatie'
    assert 'NL-OO-9032' not in set(b.entities.entity_id)   # adviescollege uitgesloten


def test_id_patches_for_active_gemeenten():
    b = _oo()
    p = b.extras['id_patches']
    assert list(p.columns) == ['entity_id', 'official_ids']
    assert list(p['entity_id']) == ['NL-GM-GM0001']
    assert p.iloc[0]['official_ids'] == 'kvk:12345678;oin:00000001234567890000;tooi:gm0001'


def test_status_single_nl_oo():
    b = _oo()
    assert [s.name for s in b.status] == ['nl_oo'] and b.status[0].ok


def test_load_nl_oo_uses_cache(tmp_path):
    (tmp_path / 'nl_oo_export.xml').write_bytes(OO_FIXTURE.read_bytes())
    b = load_nl_oo(SourceCache(offline=True, base_dir=tmp_path))
    assert b.status[0].ok and len(b.entities)


def test_load_nl_oo_failure_reported(tmp_path):
    b = load_nl_oo(SourceCache(offline=True, base_dir=tmp_path))
    assert not b.status[0].ok and b.status[0].name == 'nl_oo' and len(b.entities) == 0


def test_province_placeholder_not_created():
    recs = RECORDS + [{'Code_1': 'GM9999    ', 'Naam_2': 'Ergens', 'Code_28': '.',
                       'Naam_29': '.', 'Inwonertal_56': 10}]
    df = parse_cbs_gebieden(recs, KEYS)
    assert 'GM9999' in set(df['gm_code'])
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / 'nl_cbs_2026_86247NED_props.json').write_text(json.dumps({'value': PROPS}))
        (d / 'nl_cbs_2026_86247NED_typed.json').write_text(json.dumps({'value': recs}))
        b = load_nl_cbs(SourceCache(offline=True, base_dir=d))
    pv = b.entities[b.entities.kind == 'nl_provincie']
    assert set(pv.entity_id) == {'NL-PV-PV20', 'NL-PV-PV22'}
    assert not b.memberships['entity_id'].str.contains(r'PV-\.').any()


def _mini_xml(tmp_path, orgs='', grs=''):
    ns = 'https://organisaties.overheid.nl/static/schema/oo/export/2.6.13'
    path = tmp_path / 'mini.xml'
    path.write_text(f'<p:overheidsorganisaties xmlns:p="{ns}"><p:organisaties>{orgs}</p:organisaties>'
                    f'<p:gemeenschappelijkeRegelingen>{grs}</p:gemeenschappelijkeRegelingen>'
                    f'</p:overheidsorganisaties>', encoding='utf-8')
    return path


def _body(sid, name, so):
    return (f'<p:organisatie p:systeemId="{sid}" p:resourceIdentifierTOOI='
            f'"https://identifier.overheid.nl/tooi/id/so/{so}"><p:naam>{name}</p:naam>'
            '<p:types><p:type>Regionaal samenwerkingsorgaan</p:type></p:types></p:organisatie>')


def _gr(sid, body, end=''):
    e = f'<p:datumUitwerkingtreding>{end}</p:datumUitwerkingtreding>' if end else ''
    return (f'<p:regeling p:systeemId="r{sid}">{e}'
            f'<p:regionaalSamenwerkingsorgaan p:systeemId="{body}">x</p:regionaalSamenwerkingsorgaan>'
            '</p:regeling>')


def test_end_date_equal_run_date_is_ended(tmp_path):
    path = _mini_xml(tmp_path, _body(1, 'Een', 'so0001'),
                     _gr(1, 1, end='2026-10-27'))
    assert len(parse_oo_export(path, RUN).entities) == 0
    path = _mini_xml(tmp_path, _body(1, 'Een', 'so0001'), _gr(1, 1, end='2026-10-28'))
    assert len(parse_oo_export(path, RUN).entities) == 1


def test_malformed_end_date_counts_active_with_warning(tmp_path, caplog):
    path = _mini_xml(tmp_path, _body(1, 'Een', 'so0001'), _gr(1, 1, end='binnenkort'))
    with caplog.at_level('WARNING'):
        b = parse_oo_export(path, RUN)
    assert list(b.entities.entity_id) == ['NL-SO-SO0001']
    assert 'onleesbare einddatum' in caplog.text


def test_vggm_full_name_is_veiligheidsregio(tmp_path):
    name = 'Veiligheids- en Gezondheidsregio Gelderland-Midden'
    path = _mini_xml(tmp_path, _body(1, name, 'so0001') + _body(2, 'VGGM', 'so0002'),
                     _gr(1, 1) + _gr(2, 2))
    kinds = parse_oo_export(path, RUN).entities.set_index('entity_id')['kind']
    assert set(kinds) == {'nl_veiligheidsregio'} and len(kinds) == 2


def test_id_patches_deduplicated_by_entity_id(tmp_path):
    def gm(sid, kvk):
        return (f'<p:organisatie p:systeemId="{sid}" p:resourceIdentifierTOOI='
                '"https://identifier.overheid.nl/tooi/id/gemeente/gm0005"><p:naam>G</p:naam>'
                '<p:types><p:type>Gemeente</p:type></p:types><p:identificatiecodes>'
                f'<p:resourceIdentifier p:naam="KVK-nummer">{kvk}</p:resourceIdentifier>'
                '</p:identificatiecodes></p:organisatie>')
    p = parse_oo_export(_mini_xml(tmp_path, gm(1, '111') + gm(2, '222')), RUN).extras['id_patches']
    assert list(p['entity_id']) == ['NL-GM-GM0005']
    assert p.iloc[0]['official_ids'] == 'kvk:111;tooi:gm0005;kvk:222'


def test_coop_descriptions_from_doel_and_owms_slug():
    # F5: doel van alle actieve GR'en van een orgaan (unie) plus de OWMS-naam als hint
    desc = _oo().extras['coop_descriptions']
    assert desc['NL-SO-SO0001'] == ('Uitvoering van de Participatiewet voor de deelnemers. | '
                                    'Gezamenlijke ICT-dienstverlening. '
                                    '(OWMS-naam: Sociale Dienst Alfa)')
    # OWMS-naam gelijk aan de eigen naam en geen doel: geen beschrijving
    assert 'NL-OO-9002' not in desc
    # beeindigde GR'en en organen zonder GR tellen niet mee
    assert set(desc) <= set(_oo().entities['entity_id'])


def test_coop_description_truncated(tmp_path):
    body = OO_FIXTURE.read_text(encoding='utf-8').replace(
        'Gezamenlijke ICT-dienstverlening.', 'woord ' * 200)
    path = tmp_path / 'oo.xml'
    path.write_text(body, encoding='utf-8')
    text = parse_oo_export(path, RUN).extras['coop_descriptions']['NL-SO-SO0001']
    assert len(text) <= 450 and '...' in text and text.endswith('(OWMS-naam: Sociale Dienst Alfa)')
