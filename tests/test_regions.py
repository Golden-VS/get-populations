import pandas as pd

from tam.entities import ENTITY_COLUMNS, MEMBERSHIP_COLUMNS, new_entity
from tam.regions import apply_be_regions, canonical_region, region_of_nis


def ents(*rows):
    return pd.DataFrame([new_entity(**r) for r in rows], columns=ENTITY_COLUMNS)


def mems(*pairs):
    return pd.DataFrame([{'entity_id': a, 'member_entity_id': m, 'member_kind': '',
                          'membership_type': t, 'join_date': ''} for a, m, t in pairs],
                        columns=MEMBERSHIP_COLUMNS)


def test_region_of_nis():
    assert region_of_nis('BE-NIS-44021') == 'Vlaanderen'     # Gent
    assert region_of_nis('24062') == 'Vlaanderen'            # Leuven (Vlaams-Brabant)
    assert region_of_nis('20001') == 'Vlaanderen'            # provincie Vlaams-Brabant
    assert region_of_nis('21004') == 'Brussel'
    assert region_of_nis('25072') == 'Wallonie'              # Waals-Brabant
    assert region_of_nis('20002') == 'Wallonie'              # provincie Waals-Brabant
    assert region_of_nis('62063') == 'Wallonie'              # Luik
    assert region_of_nis('') is None


def test_canonical_region_ignores_accents_and_case():
    assert canonical_region(' wallonië ') == 'Wallonie'
    assert canonical_region('BRUSSEL') == 'Brussel'
    assert canonical_region('Vlaams') is None


def test_apply_be_regions_sources_members_and_fallbacks():
    op = 'OP-dump Agentschap Binnenland'
    e = ents(
        dict(entity_id='BE-NIS-44021', name='Gent', country='BE', kind='be_gemeente'),
        dict(entity_id='BE-NIS-21004', name='Brussel', country='BE', kind='be_gemeente'),
        dict(entity_id='BE-NIS-62063', name='Luik', country='BE', kind='be_gemeente'),
        dict(entity_id='BE-OCMW-21015', name='OCMW Schaarbeek', country='BE', kind='be_ocmw'),
        dict(entity_id='BE-KBO-1', name='AGB Gent', country='BE', kind='be_agb', source=op),
        dict(entity_id='BE-HAND-PZ-X', name='Zone X', country='BE', kind='be_politiezone'),
        dict(entity_id='BE-KBO-2', name='Koepel', country='BE', kind='be_samenwerking', source=op),
        dict(entity_id='BE-KBO-3', name='Zonder leden', country='BE', kind='be_samenwerking',
             source=op),
        dict(entity_id='BE-SPW-ideta', name='IDETA', country='BE', kind='be_intercommunale'),
        dict(entity_id='BE-HAND-GEMEENSCHAP-FWB', name='FWB', country='BE', kind='be_gewest'),
        dict(entity_id='BE-HAND-FOD-BOSA', name='BOSA', country='BE', kind='be_fod'),
        dict(entity_id='BE-HAND-ONBEKEND', name='Raadsel', country='BE', kind='be_samenwerking'),
        dict(entity_id='NL-CBS-GM0363', name='Amsterdam', country='NL', kind='nl_gemeente'),
    )
    m = mems(('BE-KBO-1', 'BE-NIS-44021', 'same_as'),
             ('BE-HAND-PZ-X', 'BE-NIS-21004', 'member'),
             ('BE-HAND-PZ-X', 'BE-NIS-62063', 'member'),
             ('BE-KBO-2', 'BE-HAND-PZ-X', 'member'))   # samenwerking van een samenwerking
    warnings = []
    out = apply_be_regions(e, m, warnings).set_index('entity_id')['be_region']
    assert out['BE-NIS-44021'] == 'Vlaanderen'
    assert out['BE-KBO-1'] == 'Vlaanderen'
    assert out['BE-OCMW-21015'] == 'Brussel'
    assert out['BE-HAND-PZ-X'] == 'Brussel; Wallonie'
    assert out['BE-KBO-2'] == 'Brussel; Wallonie'
    assert out['BE-KBO-3'] == 'Vlaanderen'
    assert out['BE-SPW-ideta'] == 'Wallonie'
    assert out['BE-HAND-GEMEENSCHAP-FWB'] == 'Brussel; Wallonie'
    assert out['BE-HAND-FOD-BOSA'] == ''
    assert out['NL-CBS-GM0363'] == ''
    assert out['BE-HAND-ONBEKEND'] == ''
    assert len(warnings) == 1 and 'BE-HAND-ONBEKEND' in warnings[0] and 'BOSA' not in warnings[0]
