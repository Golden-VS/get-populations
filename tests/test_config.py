from tam.config import DETAILED_SEGMENTS, KIND_TO_SEGMENT, SEGMENTS, all_detailed

BRIEF_KINDS = (
    'nl_gemeente nl_stadsdeel nl_provincie nl_waterschap '
    'nl_veiligheidsregio nl_samenwerking nl_ministerie '
    'nl_rijksorganisatie be_gemeente be_provincie be_gewest be_agb be_district '
    'be_politiezone be_hulpverleningszone be_samenwerking be_welzijnsvereniging '
    'be_intercommunale be_fod de_gemeinde de_kreisfreie_stadt de_stadtstaat '
    'de_bezirk de_gemeindeverband de_landkreis de_regierungsbezirk '
    'de_hoeherer_kommunalverband de_bundesland de_it_zweckverband '
    'de_zweckverband de_bundesministerium carib_land carib_ministerie '
    'bq_openbaar_lichaam bq_rijksdienst sr_regering sr_ministerie sr_district'
).split()


def test_detailed_values_unique_across_segments():
    flat = [d for values in DETAILED_SEGMENTS.values() for d in values]
    assert len(flat) == len(set(flat))
    assert set(flat) == all_detailed()


def test_kind_mapping_uses_known_values():
    for kind, (segment, detailed) in KIND_TO_SEGMENT.items():
        assert segment in SEGMENTS, kind
        if detailed is not None:
            assert detailed in DETAILED_SEGMENTS[segment], kind


def test_county_level_city_present():
    assert 'County-level city' in DETAILED_SEGMENTS['Local government']


def test_all_brief_kinds_mapped():
    assert set(BRIEF_KINDS) == set(KIND_TO_SEGMENT)
    assert len(BRIEF_KINDS) == 38
