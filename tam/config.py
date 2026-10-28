"""Vaste lijsten en constanten voor de TAM/whitespace-lijstbouwer."""
from pathlib import Path

MODEL = 'claude-opus-5-5'
# Prijzen in USD per miljoen tokens (voor kostenbewaking)
PRICES_PER_MTOK = {'input': 4.0, 'output': 20.0, 'cache_write': 5.0, 'cache_read': 0.20}
DEFAULT_MAX_COST = 50.0

SEGMENTS = [
    'Local government',
    'Regional government',
    'National government',
    'Inter-municipal cooperation',
    'Public safety & emergency',
]

# Vaste detailed-segmentlijst (spec sectie 5); waarden mogen niet hernoemd worden
DETAILED_SEGMENTS = {
    'Local government': [
        'Municipality', 'County-level city', 'City district', 'Island authority',
        'Municipal autonomous agency',
        # sectie 15: Surinaamse districten (achteraan, bestaande volgorde blijft gelijk)
        'District administration',
    ],
    'Regional government': [
        'State', 'Region / Community', 'Province', 'Administrative district',
        'County', 'Higher municipal association', 'Water authority',
    ],
    'National government': [
        'Ministry', 'National agency', 'Federal public service',
        'Country government (Caribbean)',
    ],
    'Public safety & emergency': [
        'Safety region', 'Police zone', 'Emergency services zone',
    ],
    'Inter-municipal cooperation': [
        'Municipal federation', 'Shared service organization', 'IT cooperation',
        'Tax cooperation', 'Environmental agency', 'Public health service (GGD)',
        'Social employment & work', 'Waste management', 'Recreation authority',
        'Procurement cooperation', 'Transport authority', 'Regional cooperation',
        'Welfare association', 'Special-purpose association',
        'Other joint arrangement',
    ],
}

# kind -> (segment, detailed); detailed None = later geclassificeerd (samenwerkingen)
KIND_TO_SEGMENT = {
    'nl_gemeente': ('Local government', 'Municipality'),
    'be_gemeente': ('Local government', 'Municipality'),
    'de_gemeinde': ('Local government', 'Municipality'),
    'de_kreisfreie_stadt': ('Local government', 'County-level city'),
    'nl_stadsdeel': ('Local government', 'City district'),
    'be_district': ('Local government', 'City district'),
    'de_bezirk': ('Local government', 'City district'),
    'be_agb': ('Local government', 'Municipal autonomous agency'),
    'de_stadtstaat': ('Regional government', 'State'),
    'de_bundesland': ('Regional government', 'State'),
    'be_gewest': ('Regional government', 'Region / Community'),
    'nl_provincie': ('Regional government', 'Province'),
    'be_provincie': ('Regional government', 'Province'),
    'de_regierungsbezirk': ('Regional government', 'Administrative district'),
    'de_landkreis': ('Regional government', 'County'),
    'de_hoeherer_kommunalverband': ('Regional government', 'Higher municipal association'),
    'nl_waterschap': ('Regional government', 'Water authority'),
    'nl_ministerie': ('National government', 'Ministry'),
    'de_bundesministerium': ('National government', 'Ministry'),
    'nl_rijksorganisatie': ('National government', 'National agency'),
    'be_fod': ('National government', 'Federal public service'),
    'nl_veiligheidsregio': ('Public safety & emergency', 'Safety region'),
    'be_politiezone': ('Public safety & emergency', 'Police zone'),
    'be_hulpverleningszone': ('Public safety & emergency', 'Emergency services zone'),
    'de_gemeindeverband': ('Inter-municipal cooperation', 'Municipal federation'),
    'de_it_zweckverband': ('Inter-municipal cooperation', 'IT cooperation'),
    'de_zweckverband': ('Inter-municipal cooperation', 'Special-purpose association'),
    'be_welzijnsvereniging': ('Inter-municipal cooperation', 'Welfare association'),
    'nl_samenwerking': ('Inter-municipal cooperation', None),
    'be_samenwerking': ('Inter-municipal cooperation', None),
    'be_intercommunale': ('Inter-municipal cooperation', None),
    # Caribisch deel van het Koninkrijk en Suriname (spec sectie 15)
    'carib_land': ('National government', 'Country government (Caribbean)'),
    'carib_ministerie': ('National government', 'Ministry'),
    'bq_openbaar_lichaam': ('Local government', 'Island authority'),
    'bq_rijksdienst': ('National government', 'National agency'),
    'sr_regering': ('National government', 'National agency'),
    'sr_ministerie': ('National government', 'Ministry'),
    'sr_district': ('Local government', 'District administration'),
}

IN_TAM_STATUSES = ['yes', 'no - below cutoff', 'no - excluded kind', 'unknown - population missing']

# AW/CW/SX = Aruba, Curacao, Sint Maarten; BQ = Caribisch Nederland (Bonaire, Sint Eustatius,
# Saba); SR = Suriname (spec sectie 15)
COUNTRIES = ['NL', 'BE', 'DE', 'AW', 'CW', 'SX', 'BQ', 'SR']
# CRM-landcodes (stap 1, detected_country) naar TAM-land. Stap 1 kent geen SR: Surinaamse
# accounts zijn OTHER en krijgen SR via het adresland (ADDRESS_COUNTRY_TO_TAM, crm_in_scope).
CRM_COUNTRY_TO_TAM = {'NL': 'NL', 'BE': 'BE', 'DE': 'DE', 'AW': 'AW', 'CW': 'CW', 'SX': 'SX',
                      'BQ': 'BQ', 'SR': 'SR'}
# Adresland (cx_address1_country / cx_address3_country, kleine letters) -> TAM-land, alleen
# voor accounts die stap 1 als OTHER of UNKNOWN markeerde
ADDRESS_COUNTRY_TO_TAM = {'suriname': 'SR'}

REFERENCE_DIR = Path('reference/tam')
CACHE_MAX_AGE_DAYS = 365
USER_AGENT = 'get-populations-tam/1.0 (+https://github.com/Golden-VS/get-populations)'


def all_detailed() -> set[str]:
    """Alle toegestane detailed-segmentwaarden."""
    return {d for values in DETAILED_SEGMENTS.values() for d in values}
