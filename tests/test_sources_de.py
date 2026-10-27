import pandas as pd
import pytest

from tam.sources.de import parse_gv, parse_feu, load_de_hand

COLS = ['satzart', 'textkennzeichen', 'land', 'rb', 'kreis', 'vb', 'gem', 'name', 'population', 'plz']


def _land(land, name):
    return ['10', None, land, None, None, None, None, name, None, None]


def _rb(land, rb, name):
    return ['20', None, land, rb, None, None, None, name, None, None]


def _kreis(land, rb, kreis, tk, name):
    return ['40', tk, land, rb, kreis, None, None, name, None, None]


def _vb(land, rb, kreis, vb, tk, name):
    return ['50', tk, land, rb, kreis, vb, None, name, None, None]


def _gem(land, rb, kreis, vb, gem, tk, name, pop, plz='12345'):
    return ['60', tk, land, rb, kreis, vb, gem, name, pop, plz]


def _frame(rows):
    return pd.DataFrame(rows, columns=COLS)


# Mini-Duitsland: SH met een Kreis (verbandsfreie Gemeinde + Amt met twee leden) en een
# kreisfreie Stadt; NRW met een RB en een kreisfreie Stadt; NI met een 'Statistische Region';
# de drie stadstaten; TH met een erfuellende Gemeinde; BW met GVV en vereinbarte VG.
ROWS = [
    _land('01', 'Schleswig-Holstein'),
    _kreis('01', '0', '01', '41', 'Flensburg, Stadt'),
    _vb('01', '0', '01', '0000', '50', 'Flensburg, Stadt'),
    _gem('01', '0', '01', '0000', '000', '61', 'Flensburg, Stadt', 90000, '24937'),
    _kreis('01', '0', '51', '44', 'Dithmarschen'),
    _vb('01', '0', '51', '0011', '50', 'Heide, Stadt'),
    _gem('01', '0', '51', '0011', '044', '63', 'Heide, Stadt', 1000, '25746'),
    _vb('01', '0', '51', '5163', '51', 'Burg-St. Michaelisdonn'),
    _gem('01', '0', '51', '5163', '011', '64', 'Averlak', 300, '25715'),
    _gem('01', '0', '51', '5163', '012', '64', 'Brickeln', 200, '25712'),
    _gem('01', '0', '51', '0000', '900', '66', 'Forst, gemfr. Gebiet', 0, ''),
    _land('02', 'Hamburg'),
    _kreis('02', '0', '00', '41', 'Hamburg, Freie und Hansestadt'),
    _vb('02', '0', '00', '0000', '50', 'Hamburg, Freie und Hansestadt'),
    _gem('02', '0', '00', '0000', '000', '61', 'Hamburg, Freie und Hansestadt', 1800000, '20038'),
    _land('03', 'Niedersachsen'),
    _rb('03', '1', 'Statistische Region Braunschweig'),
    _kreis('03', '1', '01', '41', 'Braunschweig, Stadt'),
    _vb('03', '1', '01', '0000', '50', 'Braunschweig, Stadt'),
    _gem('03', '1', '01', '0000', '000', '61', 'Braunschweig, Stadt', 250000, '38100'),
    _land('04', 'Bremen'),
    _kreis('04', '0', '11', '41', 'Bremen, Stadt'),
    _vb('04', '0', '11', '0000', '50', 'Bremen, Stadt'),
    _gem('04', '0', '11', '0000', '000', '61', 'Bremen, Stadt', 580000, '28195'),
    _kreis('04', '0', '12', '41', 'Bremerhaven, Stadt'),
    _vb('04', '0', '12', '0000', '50', 'Bremerhaven, Stadt'),
    _gem('04', '0', '12', '0000', '000', '61', 'Bremerhaven, Stadt', 118000, '27576'),
    _land('06', 'Hessen'),
    _rb('06', '6', 'Reg.-Bez. Kassel'),
    _kreis('06', '6', '11', '41', 'Kassel, Stadt'),
    _vb('06', '6', '11', '0000', '50', 'Kassel, Stadt'),
    _gem('06', '6', '11', '0000', '000', '61', 'Kassel, Stadt', 200000, '34117'),
    _land('08', 'Baden-Württemberg'),
    _rb('08', '1', 'Reg.-Bez. Stuttgart'),
    _kreis('08', '1', '15', '44', 'Böblingen'),
    _vb('08', '1', '15', '5001', '56', 'GVV Aidlingen/Grafenau'),
    _gem('08', '1', '15', '5001', '001', '64', 'Aidlingen', 9000, '71134'),
    _gem('08', '1', '15', '5001', '002', '64', 'Grafenau', 6000, '71120'),
    _vb('08', '1', '15', '5003', '54', 'VVG der Stadt Herrenberg'),
    _gem('08', '1', '15', '5003', '021', '67', 'Herrenberg, Stadt', 32000, '71083'),
    _gem('08', '1', '15', '5003', '022', '64', 'Nufringen', 5000, '71154'),
    _land('11', 'Berlin'),
    _kreis('11', '0', '00', '41', 'Berlin, Stadt'),
    _vb('11', '0', '00', '0000', '50', 'Berlin, Stadt'),
    _gem('11', '0', '00', '0000', '000', '61', 'Berlin, Stadt', 3700000, '10178'),
    _land('16', 'Thüringen'),
    _kreis('16', '0', '62', '44', 'Nordhausen'),
    _vb('16', '0', '62', '5054', '58', 'Bleicherode, Stadt'),
    _gem('16', '0', '62', '5054', '003', '64', 'Großlohra', 1500, '99759'),
    _gem('16', '0', '62', '5054', '004', '63', 'Bleicherode, Stadt', 10000, '99752'),
    _gem('16', '0', '62', '5054', '005', '64', 'Kehmstedt', 500, '99752'),
]


@pytest.fixture(scope='module')
def gv():
    return parse_gv(_frame(ROWS), '2026-09-30', population_date='2025-12-31')


def _ent(b, eid):
    rows = b.entities[b.entities.entity_id == eid]
    assert len(rows) == 1, f'{eid}: {len(rows)} rijen'
    return rows.iloc[0]


def test_kreisfreie_stadt_single_entity(gv):
    fl = _ent(gv, 'DE-AGS-01001000')
    assert fl['kind'] == 'de_kreisfreie_stadt'
    assert fl['population'] == 90000 and fl['population_method'] == 'own'
    assert fl['postcode'] == '24937' and fl['region'] == 'Schleswig-Holstein'
    # geen aparte Kreis-entiteit voor de kreisfreie Stadt
    assert 'DE-AGS-01001' not in set(gv.entities.entity_id)


def test_city_states_and_bremerhaven(gv):
    kinds = gv.entities.set_index('entity_id')['kind']
    for land, pop in [('02', 1800000), ('11', 3700000), ('04', 580000)]:
        st = _ent(gv, f'DE-AGS-{land}')
        assert st['kind'] == 'de_stadtstaat'
        assert st['population'] == pop  # Bremen zonder Bremerhaven
    assert kinds['DE-AGS-04012000'] == 'de_kreisfreie_stadt'
    for gid in ('DE-AGS-02000000', 'DE-AGS-11000000', 'DE-AGS-04011000'):
        assert gid not in kinds.index
    mp = gv.extras['municipal_population']
    assert mp['DE-AGS-04'] == 580000 and mp['DE-AGS-04012000'] == 118000
    assert 'DE-AGS-11000000' not in mp and mp['DE-AGS-11'] == 3700000


def test_regierungsbezirke_only_four_laender(gv):
    rb = gv.entities[gv.entities.kind == 'de_regierungsbezirk']
    assert set(rb.entity_id) == {'DE-AGS-066', 'DE-AGS-081'}
    assert _ent(gv, 'DE-AGS-066')['population'] == 200000
    assert _ent(gv, 'DE-AGS-081')['population'] == 9000 + 6000 + 32000 + 5000


def test_amt_members_become_aliases_and_amt_population_is_sum(gv):
    amt = _ent(gv, 'DE-ARS-010515163')
    assert amt['kind'] == 'de_gemeindeverband'
    assert amt['detailed_segment'] == 'Municipal federation'
    assert amt['name'] == 'Amt Burg-St. Michaelisdonn'
    assert amt['population'] == 500 and amt['population_method'] == 'sum of members'
    al = gv.aliases[gv.aliases.entity_id == 'DE-ARS-010515163']
    assert set(al.alias_name) == {'Averlak', 'Brickeln'}
    assert set(al.reason) == {'member of Amt Burg-St. Michaelisdonn'}
    assert set(al.country) == {'DE'}
    ids = set(gv.entities.entity_id)
    assert 'DE-AGS-01051011' not in ids and 'DE-AGS-01051012' not in ids
    mp = gv.extras['municipal_population']
    assert mp['DE-AGS-01051011'] == 300 and mp['DE-AGS-01051012'] == 200


def test_landkreis_population_includes_amt_members(gv):
    kr = _ent(gv, 'DE-AGS-01051')
    assert kr['kind'] == 'de_landkreis'
    assert kr['population'] == 1500 and kr['population_method'] == 'sum of members'
    assert kr['region'] == 'Schleswig-Holstein'
    sh = _ent(gv, 'DE-AGS-01')
    assert sh['kind'] == 'de_bundesland' and sh['population'] == 91500
    terr = gv.memberships[(gv.memberships.entity_id == 'DE-AGS-01051')
                          & (gv.memberships.membership_type == 'territorial')]
    assert set(terr.member_entity_id) == {'DE-AGS-01051044', 'DE-AGS-01051011', 'DE-AGS-01051012'}


def test_erfuellende_gemeinde_population_is_whole_verband(gv):
    eg = _ent(gv, 'DE-AGS-16062004')
    assert eg['kind'] == 'de_gemeinde'
    assert eg['population'] == 12000 and eg['population_method'] == 'sum of members'
    assert 'DE-ARS-160625054' not in set(gv.entities.entity_id)
    al = gv.aliases[gv.aliases.entity_id == 'DE-AGS-16062004']
    assert set(al.alias_name) == {'Großlohra', 'Kehmstedt'}
    assert set(al.reason) == {'administered by Bleicherode, Stadt'}
    # eigen bevolking blijft in municipal_population (geen dubbeltelling)
    assert gv.extras['municipal_population']['DE-AGS-16062004'] == 10000


def test_bw_gvv_members_stay_entities(gv):
    for gid, pop in [('DE-AGS-08115001', 9000), ('DE-AGS-08115002', 6000),
                     ('DE-AGS-08115021', 32000), ('DE-AGS-08115022', 5000)]:
        g = _ent(gv, gid)
        assert g['kind'] == 'de_gemeinde' and g['population'] == pop and g['population_method'] == 'own'
    gvv = _ent(gv, 'DE-ARS-081155001')
    assert gvv['kind'] == 'de_gemeindeverband' and gvv['population'] == 15000
    coop = gv.memberships[(gv.memberships.entity_id == 'DE-ARS-081155001')
                          & (gv.memberships.membership_type == 'cooperation')]
    assert set(coop.member_entity_id) == {'DE-AGS-08115001', 'DE-AGS-08115002'}
    # vereinbarte VG is geen entiteit
    assert 'DE-ARS-081155003' not in set(gv.entities.entity_id)
    assert not len(gv.aliases[gv.aliases.entity_id.str.startswith('DE-AGS-08')])


def test_verbandsfreie_placeholder_skipped(gv):
    ids = set(gv.entities.entity_id)
    assert 'DE-ARS-010510011' not in ids
    heide = _ent(gv, 'DE-AGS-01051044')
    assert heide['kind'] == 'de_gemeinde' and heide['region'] == 'Dithmarschen'
    # gemeindefreies Gebiet is geen entiteit en telt niet mee
    assert 'DE-AGS-01051900' not in ids
    assert 'DE-AGS-01051900' not in gv.extras['municipal_population']


def test_gemeinde_id_uses_8_digit_ags(gv):
    g = _ent(gv, 'DE-AGS-01051044')
    assert g['official_ids'] == 'ars:010510011044'
    assert g['postcode'] == '25746' and g['population'] == 1000
    assert g['source_date'] == '2026-09-30' and g['population_date'] == '2025-12-31'
    gem = gv.entities[gv.entities.kind.isin(['de_gemeinde', 'de_kreisfreie_stadt'])]
    assert gem.entity_id.str.fullmatch(r'DE-AGS-\d{8}').all()


def test_match_name_cut_at_comma(gv):
    assert _ent(gv, 'DE-AGS-06611000')['match_name'] == 'Kassel'
    assert _ent(gv, 'DE-AGS-06611000')['name'] == 'Kassel, Stadt'
    assert _ent(gv, 'DE-AGS-16062004')['match_name'] == 'Bleicherode'


def test_status_and_unknown_verband_type_warns(caplog):
    rows = [
        _land('07', 'Rheinland-Pfalz'),
        _kreis('07', '1', '31', '44', 'Ahrweiler'),
        _vb('07', '1', '31', '5001', '57', 'Onbekend'),
        _gem('07', '1', '31', '5001', '001', '64', 'A-dorf', 100),
        _gem('07', '1', '31', '5001', '002', '64', 'B-dorf', 50),
    ]
    with caplog.at_level('WARNING'):
        b = parse_gv(_frame(rows), '2026-09-30')
    assert 'Onbekend' in caplog.text and '57' in caplog.text
    assert _ent(b, 'DE-ARS-071315001')['population'] == 150
    assert _ent(b, 'DE-AGS-07131001')['kind'] == 'de_gemeinde'
    assert b.status[0].name == 'de_gv' and b.status[0].ok


FEU_COLS = ['id', 'name', 'ebene', 'land']


def test_feu_dedup_and_it_excluded():
    extra = pd.DataFrame([
        ['091095676824016', 'Zweckverband Wasser Nord', 'Gemeinde/Gemeindeverbände', 'Bayern'],
        ['153861990111712', 'Zweckverband Informationstechnik Franken ZV IT',
         'Gemeinde/Gemeindeverbände', 'Bayern'],
        ['121114143190614', 'Akademie der Künste', 'Bund', 'Bund'],
    ], columns=FEU_COLS)
    sonst = pd.DataFrame([
        ['091095676824016', 'Zweckverband Wasser Nord', 'Gemeinde/Gemeindeverbände', 'Bayern'],
        ['051144296293516', 'civitec - ZWECKVERBAND Kommunale Informationsverarbeitung',
         'Gemeinde/Gemeindeverbände', 'Nordrhein-Westfalen'],
        ['121252628427661', 'Abwasserzweckverband Süd', 'Gemeinde/Gemeindeverbände', 'Hessen'],
    ], columns=FEU_COLS)
    it_names = ['Zweckverband Informationstechnik Franken (ZV IT)', 'Zweckverband Informationstechnik Franken ZV IT']
    b = parse_feu([extra, sonst], it_names, '2026-01-01')
    assert sorted(b.entities.entity_id) == ['DE-FEU-051144296293516', 'DE-FEU-091095676824016',
                                            'DE-FEU-121252628427661']
    assert set(b.entities.kind) == {'de_zweckverband'}
    assert set(b.entities.population_method) == {'unknown'}
    assert b.entities.set_index('entity_id').loc['DE-FEU-121252628427661', 'region'] == 'Hessen'
    assert b.status[0].name == 'de_feu'


def test_de_hand_population_from_member_keys():
    mp = {'DE-AGS-09162000': 1500000, 'DE-AGS-09175111': 1000, 'DE-AGS-09261000': 70000,
          'DE-AGS-11': 3700000, 'DE-AGS-05314000': 300000}
    b = load_de_hand(mp)
    ent = b.entities.set_index('entity_id')
    assert ent.loc['DE-HAND-bezirk-oberbayern', 'population'] == 1501000
    assert ent.loc['DE-HAND-bezirk-oberbayern', 'kind'] == 'de_hoeherer_kommunalverband'
    assert ent.loc['DE-HAND-bezirk-oberbayern', 'population_method'] == 'sum of members'
    assert set(ent[ent.kind == 'de_bundesministerium'].population_method) == {'country total'}
    assert (ent[ent.kind == 'de_bezirk'].shape[0]) == 19
    # elke rij heeft een bron
    assert (ent['source'].fillna('') != '').all()
    assert b.status[0].name == 'de_hand'


def test_verband_name_already_has_label_and_members_extra():
    rows = [
        _land('01', 'Schleswig-Holstein'),
        _kreis('01', '0', '59', '44', 'Schleswig-Flensburg'),
        _vb('01', '0', '59', '5949', '51', 'Amt Mittelangeln'),
        _gem('01', '0', '59', '5949', '001', '64', 'Mohrkirch', 700),
        _gem('01', '0', '59', '5949', '002', '64', 'Satrup', 3000),
        _vb('01', '0', '59', '0120', '50', 'Harrislee'),
        _gem('01', '0', '59', '0120', '120', '64', 'Harrislee', 12000),
    ]
    b = parse_gv(_frame(rows), '2026-09-30')
    amt = _ent(b, 'DE-ARS-010595949')
    assert amt['name'] == 'Amt Mittelangeln' and amt['match_name'] == 'Mittelangeln'
    assert b.extras['de_verband_members'] == {
        'DE-ARS-010595949': ['DE-AGS-01059001', 'DE-AGS-01059002']}


def test_de_hand_resolves_amt_members_via_verband_members():
    from tam import hand_tables_de as ht
    # 01059999 ligt in Kreis Schleswig-Flensburg maar is zelf geen lid
    mp = {'DE-AGS-01059001': 700, 'DE-AGS-01059002': 3000, 'DE-AGS-01056041': 22000,
          'DE-AGS-01059999': 5000}
    vm = {'DE-ARS-010595949': ['DE-AGS-01059001', 'DE-AGS-01059002']}
    b = load_de_hand(mp, verband_members=vm, population_date='2025-12-31')
    eid = ht.DE_IT_ZWECKVERBAENDE['kommunit - IT-Zweckverband Schleswig-Holstein']['id']
    row = b.entities.set_index('entity_id').loc[eid]
    # alleen gemeentelijke leden (Amt Mittelangeln + Quickborn); een Kreis als lid telt niet mee
    assert row['population'] == 25700
    assert row['population_date'] == '2025-12-31'
    m = b.memberships[b.memberships.entity_id == eid].set_index('member_entity_id')['member_kind']
    assert m['DE-ARS-010595949'] == 'de_gemeindeverband'
    assert m['DE-AGS-01059'] == 'de_landkreis'
    assert m['DE-AGS-01056041'] == 'de_gemeinde'
    assert set(b.memberships.membership_type) == {'cooperation'}
    # zonder bron leden -> bevolking onbekend
    civ = ht.DE_IT_ZWECKVERBAENDE['civitec - Zweckverband Kommunale Informationsverarbeitung']['id']
    assert b.entities.set_index('entity_id').loc[civ, 'population_method'] == 'unknown'


def test_hand_tables_de_rows_have_fixed_id_and_source():
    from tam import hand_tables_de as ht
    ids = []
    for table in (ht.DE_BEZIRKE, ht.DE_HOEHERE_KOMMUNALVERBAENDE, ht.DE_IT_ZWECKVERBAENDE,
                  ht.DE_BUNDESMINISTERIEN):
        for row in table.values():
            assert row['id'].startswith('DE-HAND-') and row['bron_url'].startswith('https://')
            ids.append(row['id'])
    assert len(ids) == len(set(ids))
    berlin = sum(r['population'] for r in ht.DE_BEZIRKE.values() if r['stadt'] == 'Berlin')
    hamburg = sum(r['population'] for r in ht.DE_BEZIRKE.values() if r['stadt'] == 'Hamburg')
    assert (berlin, hamburg) == (3700577, 1869473)


def test_alias_ids_extra(gv):
    ai = gv.extras['alias_ids']
    assert ai['DE-AGS-01051011'] == 'DE-ARS-010515163'
    assert ai['DE-AGS-01051012'] == 'DE-ARS-010515163'
    assert ai['DE-AGS-16062003'] == 'DE-AGS-16062004'
    assert ai['DE-AGS-16062005'] == 'DE-AGS-16062004'
    assert len(ai) == len(gv.aliases)
    assert 'DE-AGS-16062004' not in ai and 'DE-AGS-08115001' not in ai


SN_ROWS = [
    _land('14', 'Sachsen'),
    _kreis('14', '5', '21', '44', 'Erzgebirgskreis'),
    # kernnaam 'Zschopau' == 'Zschopau, Stadt, Motorradstadt' -> erfuellende Gemeinde
    _vb('14', '5', '21', '5150', '54', 'Zschopau'),
    _gem('14', '5', '21', '5150', '090', '63', 'Zschopau, Stadt, Motorradstadt', 9000, '09405'),
    _gem('14', '5', '21', '5150', '091', '64', 'Gornau/Erzgeb.', 3000, '09405'),
    # geen eenduidige kernnaam -> Verband-entiteit + WARNING
    _vb('14', '5', '21', '5101', '54', 'Bärenstein-Königswalde'),
    _gem('14', '5', '21', '5101', '010', '64', 'Bärenstein', 2000, '09471'),
    _gem('14', '5', '21', '5101', '011', '64', 'Königswalde', 2100, '09471'),
]


def test_sn_vg_erfuellende_gemeinde_by_core_name(caplog):
    with caplog.at_level('WARNING'):
        b = parse_gv(_frame(SN_ROWS), '2026-09-30')
    eg = _ent(b, 'DE-AGS-14521090')
    assert eg['kind'] == 'de_gemeinde' and eg['population'] == 12000
    assert eg['population_method'] == 'sum of members'
    assert 'DE-ARS-145215150' not in set(b.entities.entity_id)
    al = b.aliases[b.aliases.entity_id == 'DE-AGS-14521090']
    assert list(al.alias_name) == ['Gornau/Erzgeb.']
    assert b.extras['alias_ids']['DE-AGS-14521091'] == 'DE-AGS-14521090'
    assert 'SN-VG erfuellend op kernnaam 1, als Verband 1' in b.status[0].message


def test_sn_vg_without_core_hit_falls_back_to_verband_with_warning(caplog):
    with caplog.at_level('WARNING'):
        b = parse_gv(_frame(SN_ROWS), '2026-09-30')
    vg = _ent(b, 'DE-ARS-145215101')
    assert vg['kind'] == 'de_gemeindeverband' and vg['population'] == 4100
    assert vg['name'] == 'Verwaltungsgemeinschaft Bärenstein-Königswalde'
    assert 'Bärenstein-Königswalde (145215101)' in caplog.text
    assert b.extras['alias_ids']['DE-AGS-14521010'] == 'DE-ARS-145215101'


def test_missing_gemeinde_population_stays_empty(caplog):
    rows = [
        _land('01', 'Schleswig-Holstein'),
        _kreis('01', '0', '51', '44', 'Dithmarschen'),
        _vb('01', '0', '51', '0011', '50', 'Heide, Stadt'),
        _gem('01', '0', '51', '0011', '044', '63', 'Heide, Stadt', 1000),
        _vb('01', '0', '51', '0012', '50', 'Leer'),
        _gem('01', '0', '51', '0012', '045', '64', 'Leer', None),
    ]
    with caplog.at_level('WARNING'):
        b = parse_gv(_frame(rows), '2026-09-30')
    g = _ent(b, 'DE-AGS-01051045')
    assert pd.isna(g['population']) and g['population'] != 0
    assert g['population_method'] == 'unknown'
    assert 'DE-AGS-01051045' not in b.extras['municipal_population']
    assert _ent(b, 'DE-AGS-01051')['population'] == 1000
    assert 'zonder bevolking' in caplog.text


def test_hand_population_date_and_source_name():
    b = load_de_hand({'DE-AGS-09162000': 1500000}, population_date='2025-12-31')
    ent = b.entities.set_index('entity_id')
    assert ent.loc['DE-HAND-bezirk-oberbayern', 'population_date'] == '2025-12-31'
    mitte = ent.loc['DE-HAND-bezirk-berlin-mitte']
    assert not mitte['population_source'].startswith('http')
    assert mitte['source'].startswith('https://')


class _FakeCache:
    def __init__(self, missing=()):
        self.missing = set(missing)

    def fetch(self, name, url, **kw):
        if name in self.missing:
            raise FileNotFoundError(name)
        return name


STICHTAG = {'de_gv_q1': '2026-03-31', 'de_gv_q2': '2026-06-30', 'de_gv_q3': '2026-09-30',
            'de_gv_q4': '2025-12-31'}


def test_quarter_selection_newest_first(monkeypatch):
    from tam.sources import de
    monkeypatch.setattr(de, 'gv_stichtag', lambda p: STICHTAG[p])
    cands = de.gv_candidates(_FakeCache(missing={'de_gv_q2'}))
    assert [(s, q) for s, q, _ in cands] == [('2026-09-30', 3), ('2026-03-31', 1), ('2025-12-31', 4)]


def test_load_de_gv_falls_back_to_next_quarter(monkeypatch):
    from tam.sources import de
    monkeypatch.setattr(de, 'gv_stichtag', lambda p: STICHTAG[p])
    used = []

    def fake_read(path):
        used.append(path)
        if path == 'de_gv_q3':
            raise ValueError('kapot bestand')
        return _frame(ROWS), '2025-12-31'

    monkeypatch.setattr(de, 'read_gv_xlsx', fake_read)
    b = de.load_de_gv(_FakeCache())
    assert used == ['de_gv_q3', 'de_gv_q2']
    assert b.status[0].ok and b.status[0].source_date == '2026-06-30'


def test_load_de_gv_all_quarters_fail(monkeypatch):
    from tam.sources import de
    monkeypatch.setattr(de, 'gv_stichtag', lambda p: STICHTAG[p])
    monkeypatch.setattr(de, 'read_gv_xlsx', lambda p: (_ for _ in ()).throw(ValueError('kapot')))
    b = de.load_de_gv(_FakeCache())
    assert not b.status[0].ok and 'kapot' in b.status[0].message
