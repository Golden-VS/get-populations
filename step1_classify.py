"""
Stap 1: Classificatie van CRM-accounts
======================================
Doel: voor elk record bepaalt dit script het entiteitstype (gemeente, provincie,
waterschap, OCMW, landkreis, ziekenhuis, commercieel, etc.) en het land
(NL/BE/DE/OTHER), op basis van:
  1. De naam (primair, hoogste vertrouwen)
  2. Het adres / land (voor land-detectie)
  3. cx_businesstype (alleen als zwakke hint als naam geen patroon matcht)

Doet GEEN lookup van inwoneraantallen. Dat is stap 2.

Output: oorspronkelijke kolommen + 4 nieuwe:
  - detected_country:        NL / BE / DE / OTHER / UNKNOWN
  - detected_type:           gemeente / provincie / waterschap / ocmw / agb /
                             politiezone / stadt / gemeinde / landkreis /
                             verbandsgemeinde / stadsdeel / omgevingsdienst /
                             ministerie / commercieel / onbekend / etc.
  - canonical_name:          de gemeente/regio-naam zonder prefix
                             (bijv. "Gavere" uit "Gemeente Gavere")
  - classification_proces:   korte uitleg waarom deze classificatie
  - classification_confidence: high / medium / low / none
"""

import argparse
import re

import pandas as pd

# ============================================================================
# LAND-DETECTIE
# ============================================================================
# We mappen de Nederlandstalige landennamen uit cx_address1_country naar
# ISO-achtige codes. Onbekende landen worden OTHER.
COUNTRY_MAP = {
    'Nederland': 'NL',
    'België': 'BE', 'Belgie': 'BE',
    'Duitsland': 'DE', 'Deutschland': 'DE',
    'Aruba': 'AW',
    'Curaçao': 'CW', 'Curacao': 'CW',
    'Sint Maarten': 'SX',
    'Caribisch Nederland': 'BQ',
}

# Caribische records die overheidskenmerken hebben krijgen het LANDS-inwonertal
# (Aruba, Curaçao, Sint Maarten zijn aparte landen met eigen totaal-inwonertal).
# We detecteren overheidskarakter aan keywords in de naam.
CARIBBEAN_GOVT_KEYWORDS = (
    'overheid', 'ministerie', 'departement', 'bevolking', 'bestuur',
    'regering', 'parlement', 'directie',
)
CARIBBEAN_COUNTRIES = {'AW', 'CW', 'SX', 'BQ'}

def detect_country(row):
    c1 = row.get('cx_address1_country')
    if isinstance(c1, str) and c1 in COUNTRY_MAP:
        return COUNTRY_MAP[c1]
    if isinstance(c1, str):
        return 'OTHER'
    # Fallback: kijk naar suffix van address1_composite (bevat soms ", NL" etc.)
    addr = row.get('address1_composite') or ''
    if isinstance(addr, str):
        last = addr.rstrip().split('\n')[-1].strip()
        if last in ('NL', 'BE', 'DE'):
            return last
    return 'UNKNOWN'


# ============================================================================
# NAAM-PATRONEN
# ============================================================================
# Volgorde matters: meest specifieke patronen eerst.
# Format: (regex, detected_type, confidence, korte_uitleg)
#
# We capture group(1) = de canonical_name (de naam achter het prefix).

NL_PATTERNS = [
    # Dubbele prefix afhandelen: "Waterschap Hoogheemraadschap van X" -> capture X
    (r'^Waterschap\s+Hoogheemraadschap\s+(?:van\s+)?(.+)$', 'waterschap', 'high', 'NL waterschap (dubbel prefix)'),
    # Hoogheemraadschap eerst, want "Hoogheemraadschap van Rijnland" is langer dan "Waterschap"
    (r'^Hoogheemraadschap\s+(?:van\s+)?(.+)$', 'waterschap',       'high',   'NL hoogheemraadschap'),
    (r'^Waterschap\s+(.+)$',                   'waterschap',       'high',   'NL waterschap'),
    (r'^Provincie\s+(.+)$',                    'provincie_nl',     'high',   'NL provincie'),
    (r'^Gemeente\s+(.+)$',                     'gemeente_nl',      'high',   'NL gemeente'),
    (r'^Stadsdeel\s+(.+)$',                    'stadsdeel',        'high',   'NL stadsdeel'),
    (r'^Deelgemeente\s+(.+)$',                 'deelgemeente',     'high',   'NL deelgemeente'),
    (r'^Stadsregio\s+(.+)$',                   'stadsregio',       'medium', 'NL stadsregio (som van gemeenten)'),
    (r'^Veiligheidsregio\s+(.+)$',             'veiligheidsregio', 'medium', 'NL veiligheidsregio (som van gemeenten)'),
    (r'^Omgevingsdienst\s+(.+)$',              'omgevingsdienst',  'medium', 'NL omgevingsdienst (som van gemeenten)'),
    (r'^GGD\s+(.+)$',                          'ggd',              'medium', 'NL GGD-regio (som van gemeenten)'),
    (r'^Belastingsamenwerking\s+(.+)$',        'belastingsamenwerking', 'medium', 'NL belastingsamenwerking (som van gemeenten)'),
    (r'^Ministerie\s+(.+)$',                   'ministerie',       'high',   'NL ministerie (geen inwonertal)'),
    # NL samenwerkingsverband-prefixen en afkortingen.
    # Allemaal 'samenwerking_nl': in stap 2 zoeken we ze op tegen een mapping-tabel
    # van bekende GR's en hun deelnemende gemeenten, en sommeren we de inwoners.
    (r'^(?:GRSK|GR\s+SK)\s+(.+)$',                       'samenwerking_nl', 'medium', 'NL GRSK (gemeenschappelijke regeling, som van gemeenten)'),
    (r'^GR\s+(.+)$',                                     'samenwerking_nl', 'medium', 'NL GR (gemeenschappelijke regeling, som van gemeenten)'),
    (r'^Gemeenschappelijke\s+Regeling\s+(.+)$',          'samenwerking_nl', 'medium', 'NL gemeenschappelijke regeling (som van gemeenten)'),
    (r'^ISD\s+(.+)$',                                    'samenwerking_nl', 'medium', 'NL ISD intergemeentelijke sociale dienst (som van gemeenten)'),
    (r'^RSD\s+(.+)$',                                    'samenwerking_nl', 'medium', 'NL RSD regionale sociale dienst (som van gemeenten)'),
    (r'^RUD\s+(.+)$',                                    'samenwerking_nl', 'medium', 'NL RUD regionale uitvoeringsdienst (som van gemeenten)'),
    (r'^Werkplein\s+(.+)$',                              'samenwerking_nl', 'medium', 'NL werkplein regionaal (som van gemeenten)'),
    (r'^Werkbedrijf\s+(.+)$',                            'samenwerking_nl', 'medium', 'NL werkbedrijf regionaal (som van gemeenten)'),
    (r'^Werkvoorzieningschap\s+(.+)$',                   'samenwerking_nl', 'medium', 'NL werkvoorzieningschap (som van gemeenten)'),
    (r'^Uitvoeringsorganisatie\s+(.+)$',                 'samenwerking_nl', 'medium', 'NL uitvoeringsorganisatie (mogelijk som van gemeenten)'),
    (r'^Samenwerkingsverband\s+(.+)$',                   'samenwerking_nl', 'medium', 'NL samenwerkingsverband (som van gemeenten)'),
]

BE_PATTERNS = [
    (r'^Provincie\s+(.+)$',                              'provincie_be',   'high',   'BE provincie'),
    (r'^Politiezone\s+(.+)$',                            'politiezone',    'medium', 'BE politiezone'),
    (r'^Lokale\s+Politie\s+(.+)$',                       'politiezone',    'medium', 'BE lokale politie (= politiezone)'),
    (r'^Hulpverleningszone\s+(.+)$',                     'hulpverleningszone', 'medium', 'BE hulpverleningszone (brandweer, som van gemeenten)'),
    (r'^OCMW\s+(.+)$',                                   'ocmw',           'high',   'BE OCMW (gekoppeld aan gemeente)'),
    (r'^(?:AGB|Autonoom\s+Gemeentebedrijf)\s+(.+)$',     'agb',            'high',   'BE AGB (gekoppeld aan gemeente)'),
    (r'^Stadsbestuur\s+(.+)$',                           'gemeente_be',    'high',   'BE stadsbestuur (= stad/gemeente)'),
    (r'^Gemeentebestuur\s+(.+)$',                        'gemeente_be',    'high',   'BE gemeentebestuur (= gemeente)'),
    (r'^Gemeente\s+(.+)$',                               'gemeente_be',    'high',   'BE gemeente'),
    (r'^Stad\s+(.+)$',                                   'gemeente_be',    'high',   'BE stad (= gemeente)'),
    (r'^(?:FOD|Federale\s+Overheidsdienst)\s+(.+)$',     'fod_be',         'high',   'BE federale overheidsdienst (geen inwonertal)'),
    (r'^(?:Intercommunale|Dienstverlenende\s+Vereniging)\s+(.+)$', 'intercommunale', 'low', 'BE intercommunale (geen vast inwonertal)'),
    (r'^CAW\s+(.+)$',                                    'caw',            'low',    'BE CAW (welzijn, geen inwonertal)'),
]

DE_PATTERNS = [
    (r'^Verbandsgemeinde\s+(.+)$',          'verbandsgemeinde',         'high',   'DE verbandsgemeinde'),
    (r'^Verwaltungsgemeinschaft\s+(.+)$',   'verwaltungsgemeinschaft',  'high',   'DE verwaltungsgemeinschaft (som van gemeinden)'),
    (r'^Zweckverband\s+(.+)$',              'zweckverband',             'low',    'DE zweckverband (geen vast inwonertal)'),
    (r'^(?:Landkreis|Kreis)\s+(.+)$',       'landkreis',                'high',   'DE landkreis'),
    (r'^Landratsamt\s+(.+)$',               'landratsamt',              'high',   'DE landratsamt (= landkreis)'),
    (r'^Kreisverwaltung\s+(.+)$',           'landkreis',                'high',   'DE kreisverwaltung (admin van landkreis)'),
    (r'^Stadtwerke\s+(.+)$',                'stadtwerke',               'high',   'DE stadtwerke (nutsbedrijf, geen inwonertal)'),
    (r'^Amt\s+(.+)$',                       'amt',                      'medium', 'DE amt (samenwerking van gemeinden)'),
    # Stad-varianten met epitheta: alle eindigen feitelijk op een gemeente.
    # We capturen de gemeentenaam (laatste woorden na het epitheton).
    (r'^Stadtverwaltung\s+(.+)$',           'gemeinde_de',              'high',   'DE stadtverwaltung (admin van stadt)'),
    (r'^Landeshauptstadt\s+(.+)$',          'gemeinde_de',              'high',   'DE landeshauptstadt (= stadt, deelstaathoofdstad)'),
    (r'^Lutherstadt\s+(.+)$',               'gemeinde_de',              'high',   'DE lutherstadt (= stadt, Luther-titel)'),
    (r'^Hansestadt\s+(.+)$',                'gemeinde_de',              'high',   'DE hansestadt (= stadt)'),
    (r'^Hochschulstadt\s+(.+)$',            'gemeinde_de',              'high',   'DE hochschulstadt (= stadt)'),
    (r'^Burggemeinde\s+(.+)$',              'gemeinde_de',              'high',   'DE burggemeinde (= gemeinde)'),
    (r'^Marktgemeinde\s+(.+)$',             'gemeinde_de',              'high',   'DE marktgemeinde (= gemeinde)'),
    # Combinaties met 'Kreis- und ...' eerst proberen
    (r'^Kreis-\s*und\s+\S+\s+(.+)$',        'gemeinde_de',              'medium', 'DE kreis- und [type] (= stadt)'),
    (r'^Kreisstadt\s+(.+)$',                'gemeinde_de',              'high',   'DE kreisstadt (= gemeinde)'),
    (r'^Markt\s+(.+)$',                     'gemeinde_de',              'high',   'DE markt (= gemeinde)'),
    (r'^Stadt\s+(.+)$',                     'gemeinde_de',              'high',   'DE stadt (= gemeinde)'),
    (r'^Gemeinde\s+(.+)$',                  'gemeinde_de',              'high',   'DE gemeinde'),
]

# Prefixen die zo onmiskenbaar uit één land komen dat we het cx_address1_country
# overrulen. Voorbeeld: "Stadt Lübeck" met cx_address1_country='Nederland'
# is duidelijk een DE-record met fout land in CRM. Hier corrigeren we dat.
COUNTRY_OVERRIDE_PREFIXES = {
    'DE': ['Stadt ', 'Gemeinde ', 'Markt ', 'Landkreis ', 'Kreis ', 'Landratsamt ',
           'Verbandsgemeinde ', 'Verwaltungsgemeinschaft ', 'Stadtwerke ', 'Zweckverband ',
           'Kreisstadt ', 'Stadtverwaltung ', 'Kreisverwaltung ', 'Landeshauptstadt ',
           'Lutherstadt ', 'Hansestadt ', 'Hochschulstadt ', 'Burggemeinde ',
           'Marktgemeinde ', 'Amt ', 'Kreis- und '],
    'BE': ['OCMW ', 'AGB ', 'Autonoom Gemeentebedrijf ', 'Politiezone ', 'Stad ',
           'Stadsbestuur ', 'Gemeentebestuur ', 'Hulpverleningszone ',
           'FOD ', 'Federale Overheidsdienst ', 'Lokale Politie '],
    'NL': ['Hoogheemraadschap ', 'Waterschap ', 'Stadsdeel ', 'Veiligheidsregio ',
           'Omgevingsdienst ', 'Belastingsamenwerking ', 'Gemeenschappelijke Regeling ',
           'GRSK ', 'GR ', 'ISD ', 'RSD ', 'RUD ', 'Werkplein ', 'Werkbedrijf ',
           'Werkvoorzieningschap ', 'Samenwerkingsverband '],
}


# Suffixen die uit canonical_name moeten worden gestript zodat de naam matcht
# met referentielijsten. Bijv. "Stadtwerke Gütersloh GmbH" -> canonical = "Gütersloh".
CANONICAL_NAME_STRIP_SUFFIXES = [
    r'\s*\(BE\)\s*$', r'\s*\(NL\)\s*$', r'\s*\(DE\)\s*$',
    r'\s+GmbH\s*(?:&\s*Co\.?\s*KG)?\s*$', r'\s+AG\s*$', r'\s+KG\s*$',
    r'\s+B\.?V\.?\s*$', r'\s+N\.?V\.?\s*$', r'\s+bvba\s*$', r'\s+cvba\s*$',
]

def clean_canonical(name):
    """Verwijdert juridische rechtsvormen en land-suffixen uit een canonical_name."""
    if not isinstance(name, str):
        return name
    cleaned = name
    for pat in CANONICAL_NAME_STRIP_SUFFIXES:
        cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


# ============================================================================
# CX_BUSINESSTYPE FALLBACKS
# ============================================================================
# Alleen gebruikt als de naam GEEN patroon matcht.
# Naam wint altijd van businesstype (volgens de regel: naam → adres → kvk → rest).

# Types die per definitie GEEN inwonertal hebben (commercieel of zorg/etc.)
NO_POPULATION_TYPES = {
    'Commerciële organisatie', 'Aannemer buitenruimte', 'Adviesbureau',
    'Leverancier', 'Bosbouwer / Dienstverlener Bosbouw', 'Ingenieursbureau',
    'Ziekenhuis', 'Apotheek', 'Zorg Instelling', 'Onderwijs', 'Hotel',
    'Sportbedrijf', 'Afval verwerker', 'Belastingkantoor', 'Rechtbank',
    'Woningcorporatie',
}

# Types die wel een inwonertal kunnen hebben maar uit naam alleen niet duidelijk waren
GOVT_TYPE_FALLBACK = {
    # Per regel "naam wint": als naam GEEN patroon matcht, dan trekken we
    # geen conclusies meer uit cx_businesstype. Alle govt-type fallbacks worden
    # 'onbekend' met een opmerking dat businesstype iets anders suggereerde.
    # Stap 2 doet dan geen lookup en de cell blijft leeg, met opmerking.
    'Gemeente':                                ('onbekend', 'none', 'cx_businesstype = Gemeente, maar naam matcht geen patroon (genegeerd)'),
    'Provincie':                               ('onbekend', 'none', 'cx_businesstype = Provincie, maar naam matcht geen patroon (genegeerd)'),
    'Waterschap':                              ('onbekend', 'none', 'cx_businesstype = Waterschap, maar naam matcht geen patroon (genegeerd)'),
    'Politie/politiezone':                     ('onbekend', 'none', 'cx_businesstype = Politiezone, maar naam matcht geen patroon (genegeerd)'),
    'Deelgemeente':                            ('onbekend', 'none', 'cx_businesstype = Deelgemeente, maar naam matcht geen patroon (genegeerd)'),
    'Rijksoverheid':                           ('rijksoverheid',   'low', 'cx_businesstype = Rijksoverheid (geen inwonertal)'),
    'Ambtelijke samenwerking tussen gemeenten':('onbekend', 'none', 'cx_businesstype = Ambtelijke samenwerking, maar naam matcht geen patroon (genegeerd)'),
    'Intercommunale':                          ('intercommunale',  'low', 'cx_businesstype = Intercommunale (geen vast inwonertal)'),
    'Other':                                   ('onbekend',        'none','cx_businesstype = Other (te vaag)'),
}


# ============================================================================
# CLASSIFICATIE-FUNCTIE
# ============================================================================

def classify(row):
    """
    Classificeert één record. Returnt een dict met 5 velden.
    Logica:
      1. Detecteer land (uit cx_address1_country, fallback adres-suffix).
      2. Probeer naam-patroon matchen. Patroon-set hangt af van land,
         maar voor BE en NL proberen we beide patroon-sets omdat namen
         soms door elkaar gebruikt worden.
      3. Als geen naam-patroon: gebruik cx_businesstype als zwakke hint.
      4. Als ook dat niets oplevert: type = onbekend.
    """
    name = (row.get('name') or '')
    if not isinstance(name, str):
        name = ''
    name = name.strip()
    country = detect_country(row)
    btype = row.get('cx_businesstype')

    # Naam-prefix kan land overrulen (regel: naam wint van adres/CRM-velden).
    # Voorbeeld: "Stadt Lübeck" met cx_address1_country='Nederland' is een DE-record
    # met foutief land in CRM. We corrigeren dat hier.
    country_override = None
    for override_country, prefixes in COUNTRY_OVERRIDE_PREFIXES.items():
        if any(name.startswith(p) for p in prefixes):
            country_override = override_country
            break
    if country_override and country_override != country:
        country = country_override

    # Bouw de patronen-set op basis van land. We zijn iets ruimhartig:
    # NL- en BE-patronen mogen ook bij elkaar matchen, want sommige BE-records
    # gebruiken "Gemeente X" en andersom.
    if country == 'NL':
        patterns = NL_PATTERNS + BE_PATTERNS  # BE als backup voor edge cases
    elif country == 'BE':
        patterns = BE_PATTERNS + NL_PATTERNS
    elif country == 'DE':
        patterns = DE_PATTERNS
    else:
        patterns = NL_PATTERNS + BE_PATTERNS + DE_PATTERNS

    # Probeer naam-patroon
    for pat, etype, conf, proces in patterns:
        m = re.match(pat, name, flags=re.IGNORECASE)
        if m:
            return {
                'detected_country':           country,
                'detected_type':              etype,
                'canonical_name':             clean_canonical(m.group(1).strip()),
                'classification_confidence':  conf,
                'classification_proces':      f'naam-patroon: {proces}',
            }

    # Caribische landen: als de naam een overheidskarakter heeft, classificeren
    # we als 'land' en gebruikt stap 2 het totaal-inwonertal van het land.
    if country in CARIBBEAN_COUNTRIES:
        name_low = name.lower()
        if any(kw in name_low for kw in CARIBBEAN_GOVT_KEYWORDS):
            country_names = {'AW': 'Aruba', 'CW': 'Curaçao', 'SX': 'Sint Maarten', 'BQ': 'Caribisch Nederland'}
            return {
                'detected_country':           country,
                'detected_type':              'land',
                'canonical_name':             country_names[country],
                'classification_confidence':  'medium',
                'classification_proces':      f'Caribisch overheidsorgaan, krijgt totaal-inwonertal van {country_names[country]}',
            }

    # Geen naam-match. Val terug op cx_businesstype.
    if isinstance(btype, str):
        if btype in NO_POPULATION_TYPES:
            return {
                'detected_country':           country,
                'detected_type':              'commercieel_of_overig',
                'canonical_name':             None,
                'classification_confidence':  'high',
                'classification_proces':      f'cx_businesstype = {btype} (geen inwonertal)',
            }
        if btype in GOVT_TYPE_FALLBACK:
            etype, conf, proces = GOVT_TYPE_FALLBACK[btype]
            return {
                'detected_country':           country,
                'detected_type':              etype,
                'canonical_name':             name,  # ruwe naam, want geen prefix gestript
                'classification_confidence':  conf,
                'classification_proces':      proces,
            }

    # Niets bekend
    return {
        'detected_country':           country,
        'detected_type':              'onbekend',
        'canonical_name':             None,
        'classification_confidence':  'none',
        'classification_proces':      'geen naam-patroon, geen bruikbare cx_businesstype',
    }


# ============================================================================
# MAIN
# ============================================================================

def main(input_path='full_input.xlsx', output_path='step1_classified.xlsx'):
    df = pd.read_excel(input_path, sheet_name=0)
    print(f"Ingelezen: {len(df)} records")

    # Pas classificatie toe
    extra = df.apply(classify, axis=1, result_type='expand')
    out = pd.concat([df, extra], axis=1)

    # Samenvatting per detected_type
    print("\n=== Verdeling per detected_type ===")
    print(out['detected_type'].value_counts().to_string())

    # Kruistabel land x type
    print("\n=== Kruistabel detected_country x detected_type ===")
    print(out.groupby(['detected_country', 'detected_type']).size()
          .unstack(fill_value=0).to_string())

    # Records waar cx_businesstype iets zegt maar wij 'onbekend' classificeren
    suspicious = out[
        (out['detected_type'] == 'onbekend') & out['cx_businesstype'].notna()
    ]
    print(f"\n=== 'Onbekend' maar wel een cx_businesstype: {len(suspicious)} records ===")
    if len(suspicious) > 0:
        print(suspicious[['name', 'cx_businesstype', 'cx_address1_country']]
              .head(10).to_string())

    # Records waar wij een government-type detecteren maar cx_businesstype iets anders zegt
    # (handig om te zien of de bestaande kolom betrouwbaar is)
    govt_types = ('gemeente_nl', 'gemeente_be', 'gemeente_de', 'gemeinde_de',
                  'provincie_nl', 'provincie_be', 'waterschap', 'landkreis',
                  'ocmw', 'agb', 'politiezone', 'verbandsgemeinde',
                  'stadsdeel', 'omgevingsdienst', 'veiligheidsregio')
    conflict = out[
        out['detected_type'].isin(govt_types)
        & out['cx_businesstype'].notna()
        & ~out['cx_businesstype'].isin(['Gemeente', 'Provincie', 'Waterschap',
                                          'Politie/politiezone', 'Deelgemeente'])
    ]
    print(f"\n=== Conflict tussen onze detectie en cx_businesstype: {len(conflict)} ===")
    if len(conflict) > 0:
        print(conflict[['name', 'detected_type', 'cx_businesstype']]
              .head(10).to_string())

    # Schrijf output
    out.to_excel(output_path, index=False)
    print(f"\nOutput: {output_path}")
    return out


def parse_args():
    p = argparse.ArgumentParser(description='Classificeert CRM-accounts op type en land.')
    p.add_argument('--input',  default='full_input.xlsx',
                   help='ruwe CRM-export (xlsx, default full_input.xlsx)')
    p.add_argument('--output', default='step1_classified.xlsx',
                   help='uitvoer-Excel pad (default step1_classified.xlsx)')
    return p.parse_args()


if __name__ == '__main__':
    args = parse_args()
    main(args.input, args.output)
