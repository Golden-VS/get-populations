"""Handtabellen Caribisch deel van het Koninkrijk en Suriname (spec sectie 15).

Een rij per entiteit: sleutel = officiele naam, waarde = dict met vaste 'id'
(<land>-HAND-...), 'country', 'kind', 'population' (None = geen officieel cijfer, of
landtotaal via de master), 'peildatum' en 'bron_url'. Optioneel 'aliases' en 'official_ids'.
Bevolking alleen uit het officiele statistiekbureau; zonder bron blijft ze leeg.
Ministeries, regering en Rijksdienst krijgen het landtotaal (population_method 'country total'):
AW/CW/SX = de landrij, BQ = som van de drie eilanden, SR = som van de tien districten
(tam/master.py, _COUNTRY_TOTAL_KINDS).
Alle bronnen geraadpleegd op 2026-10-28; de peildatum van een rij zonder bevolkingscijfer is die
raadpleegdatum.
"""

CONSULTED = '2026-10-28'

AW_MINISTRIES_URL = 'https://www.gobierno.aw/nl/ministeries'
CBS_AW_URL = 'https://cbs.aw/wp/index.php/population/'
CW_MINISTRIES_URL = 'https://gobiernu.cw/nl/ministeries/'
CW_MINISTERIONAN_URL = 'https://gobiernu.cw/ministerionan/'
CBS_CW_URL = 'https://www.cbs.cw/population'
SX_GOVERNING_PROGRAM_URL = ('https://www.sintmaartengov.org/Government/Documents/'
                            '2024-2028%20Governing%20Program%20-%20Cabinet%20Mercelina%20II.pdf')
SX_POPULATION_URL = ('https://www.sintmaartengov.org/news/Pages/Rebased-Population-Estimates-and-'
                     'Vital-Statistics-for-January-1-2025.aspx')
CBS_BES_URL = 'https://opendata.cbs.nl/statline/#/CBS/nl/dataset/83698NED/table'
RCN_URL = 'https://www.rijksdienstcn.com/'
SR_GOV_URL = 'https://gov.sr/ministeries/'
ABS_CENSUS8_URL = 'https://statistics-suriname.org/wp-content/uploads/2019/09/presentatie.pdf'


def _min(country, kind, url, rows):
    """Ministerierijen: geen eigen bevolking (landtotaal), peildatum = raadpleegdatum."""
    out = {}
    for name, row in rows.items():
        out[name] = {'country': country, 'kind': kind, 'population': None, 'peildatum': CONSULTED,
                     'bron_url': url, **row}
    return out


# ---------------------------------------------------------------------------
# Aruba
# ---------------------------------------------------------------------------
# Bevolking: CBS Aruba (cbs.aw) is niet automatisch te lezen (botcontrole). Het CBS
# (Nederland) noemt in 'De Nederlandse Caraiben vijftien jaar na de staatskundige hervorming'
# (2025) alleen een afgerond cijfer (108,4 duizend, eind 2024); dat is geen exact officieel
# cijfer en wordt niet gebruikt. Bevolking dus leeg: handmatig aanvullen vanaf de bron_url.
AW_LAND = {
    'Aruba': {'id': 'AW-HAND-ARUBA', 'country': 'AW', 'kind': 'carib_land', 'population': None,
              'peildatum': CONSULTED, 'bron_url': CBS_AW_URL,
              'aliases': ['Land Aruba']},
}
# Ministeries zoals op gobierno.aw/nl/ministeries (8)
AW_MINISTERIES = _min('AW', 'carib_ministerie', AW_MINISTRIES_URL, {
    'Ministerie van Algemene Zaken, Innovatie, Overheidsorganisatie, Infrastructuur en Ruimtelijke '
    'Ordening': {'id': 'AW-HAND-MIN-ALGEMENE-ZAKEN'},
    'Ministerie van Arbeid, Energie en Integratie': {'id': 'AW-HAND-MIN-ARBEID'},
    'Ministerie van Economische Zaken, Communicatie, Duurzame Ontwikkeling':
        {'id': 'AW-HAND-MIN-ECONOMISCHE-ZAKEN'},
    'Ministerie van Financiën en Cultuur': {'id': 'AW-HAND-MIN-FINANCIEN'},
    'Ministerie van Justitie en Sociale Zaken': {'id': 'AW-HAND-MIN-JUSTITIE'},
    'Ministerie van Onderwijs en Sport': {'id': 'AW-HAND-MIN-ONDERWIJS'},
    'Ministerie van Toerisme en Volksgezondheid': {'id': 'AW-HAND-MIN-TOERISME'},
    'Ministerie van Transport, Integriteit, Natuur en Ouderenzaken': {'id': 'AW-HAND-MIN-TRANSPORT'},
})

# ---------------------------------------------------------------------------
# Curacao
# ---------------------------------------------------------------------------
# CBS Curacao, 'Key figures', totale bevolking op 1 januari 2026
CW_LAND = {
    'Curaçao': {'id': 'CW-HAND-CURACAO', 'country': 'CW', 'kind': 'carib_land', 'population': 158006,
                'peildatum': '2026-01-01', 'bron_url': CBS_CW_URL,
                'aliases': ['Land Curaçao', 'Gobièrnu di Kòrsou']},
}
# Ministeries zoals op gobiernu.cw/nl/ministeries (9); aliassen = Papiamentse naam van
# gobiernu.cw/ministerionan
CW_MINISTERIES = _min('CW', 'carib_ministerie', CW_MINISTRIES_URL, {
    'Ministerie van Algemene Zaken en Minister President': {
        'id': 'CW-HAND-MIN-ALGEMENE-ZAKEN',
        'aliases': ['Ministerio di Asuntunan General i Promé Minister',
                    'Ministerio di Asuntunan General']},
    'Ministerie van Bestuur, Planning & Dienstverlening': {
        'id': 'CW-HAND-MIN-BESTUUR',
        'aliases': ['Ministerio di Maneho di Gobernashon, Planifikashon i Servisio Públiko']},
    'Ministerie van Economische Ontwikkeling': {
        'id': 'CW-HAND-MIN-ECONOMISCHE-ONTWIKKELING', 'aliases': ['Ministerio di Desaroyo Ekonómiko']},
    'Ministerie van Financiën': {'id': 'CW-HAND-MIN-FINANCIEN', 'aliases': ['Ministerio di Finansa']},
    'Ministerie van Gezondheid, Milieu & Natuur': {
        'id': 'CW-HAND-MIN-GEZONDHEID',
        'aliases': ['Ministerio di Salubridat Públiko, Medio Ambiente i Naturalesa']},
    'Ministerie van Justitie': {'id': 'CW-HAND-MIN-JUSTITIE', 'aliases': ['Ministerio di Hustisia']},
    'Ministerie van Onderwijs, Wetenschap, Cultuur & Sport': {
        'id': 'CW-HAND-MIN-ONDERWIJS', 'aliases': ['Ministerio di Enseñansa, Siensia, Kultura & Deporte']},
    'Ministerie van Sociale Ontwikkeling, Arbeid & Welzijn': {
        'id': 'CW-HAND-MIN-SOCIALE-ONTWIKKELING',
        'aliases': ['Ministerio di Desaroyo Sosial, Labor i Bienestar']},
    'Ministerie van Verkeer, Vervoer & Ruimtelijke Planning': {
        'id': 'CW-HAND-MIN-VERKEER',
        'aliases': ['Ministerio di Tráfiko, Transporte i Planifikashon Urbano']},
})

# ---------------------------------------------------------------------------
# Sint Maarten
# ---------------------------------------------------------------------------
# STAT (Department of Statistics) via sintmaartengov.org: 42.449 op 1 januari 2025 (nieuwer
# cijfer niet gepubliceerd op 2026-10-28)
SX_LAND = {
    'Sint Maarten': {'id': 'SX-HAND-SINT-MAARTEN', 'country': 'SX', 'kind': 'carib_land',
                     'population': 42449, 'peildatum': '2025-01-01', 'bron_url': SX_POPULATION_URL,
                     'aliases': ['Land Sint Maarten']},
}
# Ministeries zoals in het regeerprogramma 2024-2028 (kabinet Mercelina II) op sintmaartengov.org
# (7); afkortingen zoals in datzelfde document
SX_MINISTERIES = _min('SX', 'carib_ministerie', SX_GOVERNING_PROGRAM_URL, {
    'Ministry of General Affairs': {'id': 'SX-HAND-MIN-GENERAL-AFFAIRS'},
    'Ministry of Finance': {'id': 'SX-HAND-MIN-FINANCE'},
    'Ministry of Justice': {'id': 'SX-HAND-MIN-JUSTICE'},
    'Ministry of Education, Culture, Youth & Sport': {'id': 'SX-HAND-MIN-ECYS',
                                                      'aliases': ['Ministry of ECYS']},
    'Ministry of Public Health, Social Development & Labor': {'id': 'SX-HAND-MIN-VSA',
                                                              'aliases': ['Ministry of VSA']},
    'Ministry of Public Housing, Spatial Planning, Environment & Infrastructure': {
        'id': 'SX-HAND-MIN-VROMI', 'aliases': ['Ministry of VROMI']},
    'Ministry of Tourism, Economic Affairs, Telecommunications & Traffic': {
        'id': 'SX-HAND-MIN-TEATT', 'aliases': ['Ministry of TEATT']},
})

# ---------------------------------------------------------------------------
# Caribisch Nederland (BQ)
# ---------------------------------------------------------------------------
# CBS StatLine 83698NED 'Caribisch Nederland; bevolking; geslacht, leeftijd, burgerlijke
# staat', onderwerp 'Bevolking op 1 januari', totaal geslacht/leeftijd/burgerlijke staat,
# periode 2026 (CBS-codes GM9001-GM9003; som 33.229 = CN01 Caribisch Nederland).
BQ_OPENBARE_LICHAMEN = {
    'Openbaar lichaam Bonaire': {'id': 'BQ-HAND-BONAIRE', 'country': 'BQ', 'kind': 'bq_openbaar_lichaam',
                                 'population': 27611, 'peildatum': '2026-01-01', 'bron_url': CBS_BES_URL,
                                 'official_ids': 'cbs:GM9001', 'aliases': ['Bonaire']},
    'Openbaar lichaam Sint Eustatius': {'id': 'BQ-HAND-SINT-EUSTATIUS', 'country': 'BQ',
                                        'kind': 'bq_openbaar_lichaam', 'population': 3348,
                                        'peildatum': '2026-01-01', 'bron_url': CBS_BES_URL,
                                        'official_ids': 'cbs:GM9002',
                                        'aliases': ['Sint Eustatius', 'Statia']},
    'Openbaar lichaam Saba': {'id': 'BQ-HAND-SABA', 'country': 'BQ', 'kind': 'bq_openbaar_lichaam',
                              'population': 2270, 'peildatum': '2026-01-01', 'bron_url': CBS_BES_URL,
                              'official_ids': 'cbs:GM9003', 'aliases': ['Saba']},
}
# Rijksdienst Caribisch Nederland: landtotaal BQ (som van de eilanden)
BQ_RIJKSDIENST = {
    'Rijksdienst Caribisch Nederland': {'id': 'BQ-HAND-RCN', 'country': 'BQ', 'kind': 'bq_rijksdienst',
                                        'population': None, 'peildatum': CONSULTED, 'bron_url': RCN_URL,
                                        'aliases': ['RCN']},
}

# ---------------------------------------------------------------------------
# Suriname
# ---------------------------------------------------------------------------
# Regering en ministeries zoals in het menu 'Kabinetten en ministeries' van gov.sr (17
# ministeries; het Kabinet van de President is een alias van de regering, het Kabinet van de
# Vicepresident is geen aparte entiteit).
SR_REGERING = {
    'Regering van de Republiek Suriname': {
        'id': 'SR-HAND-REGERING', 'country': 'SR', 'kind': 'sr_regering', 'population': None,
        'peildatum': CONSULTED, 'bron_url': SR_GOV_URL,
        'aliases': ['Republiek Suriname', 'Kabinet van de President', 'Suriname']},
}
SR_MINISTERIES = _min('SR', 'sr_ministerie', SR_GOV_URL, {
    'Ministerie van Binnenlandse Zaken': {'id': 'SR-HAND-MIN-BINNENLANDSE-ZAKEN'},
    'Ministerie van Buitenlandse Zaken, Internationale Handel & Samenwerking':
        {'id': 'SR-HAND-MIN-BUITENLANDSE-ZAKEN'},
    'Ministerie van Defensie': {'id': 'SR-HAND-MIN-DEFENSIE'},
    'Ministerie van Economische Zaken, Ondernemerschap en Technologische Innovatie':
        {'id': 'SR-HAND-MIN-ECONOMISCHE-ZAKEN'},
    'Ministerie van Financiën en Planning': {'id': 'SR-HAND-MIN-FINANCIEN'},
    'Ministerie van Grond- en Bosbeheer': {'id': 'SR-HAND-MIN-GROND-EN-BOSBEHEER'},
    'Ministerie van Jeugdontwikkeling en Sport': {'id': 'SR-HAND-MIN-JEUGDONTWIKKELING'},
    'Ministerie van Justitie en Veiligheid': {'id': 'SR-HAND-MIN-JUSTITIE'},
    'Ministerie van Landbouw, Veeteelt en Visserij': {'id': 'SR-HAND-MIN-LANDBOUW'},
    'Ministerie van Natuurlijke Hulpbronnen': {'id': 'SR-HAND-MIN-NATUURLIJKE-HULPBRONNEN'},
    'Ministerie van Olie, Gas en Milieu': {'id': 'SR-HAND-MIN-OLIE-GAS-MILIEU'},
    'Ministerie van Onderwijs, Wetenschap en Cultuur': {'id': 'SR-HAND-MIN-ONDERWIJS'},
    'Ministerie van Openbare Werken & Ruimtelijke Ordening': {'id': 'SR-HAND-MIN-OPENBARE-WERKEN'},
    'Ministerie van Regionale Ontwikkeling': {'id': 'SR-HAND-MIN-REGIONALE-ONTWIKKELING'},
    'Ministerie van Sociale Zaken en Huisvesting': {'id': 'SR-HAND-MIN-SOCIALE-ZAKEN'},
    'Ministerie van Transport, Communicatie en Toerisme': {'id': 'SR-HAND-MIN-TRANSPORT'},
    'Ministerie van Volksgezondheid, Welzijn & Arbeid': {'id': 'SR-HAND-MIN-VOLKSGEZONDHEID'},
})

# Districten: ABS (Algemeen Bureau voor de Statistiek), Achtste Algemene Volks- en
# Woningtelling, definitieve resultaten Volume I (presentatie, tabel 'BEVOLKING', kolom 2012;
# totaal 541.638). Telling van 13 augustus 2012 (begin veldwerk volgens de ABS-evaluatie van
# Census 8). Nieuwer officieel districtscijfer bestaat niet: de Negende Volkstelling liep nog
# op 2026-10-28. Ressorts zijn geen entiteiten.
_SR_DISTRICT_POP = {
    'Paramaribo': 240924, 'Wanica': 118222, 'Nickerie': 34233, 'Coronie': 3391,
    'Saramacca': 17480, 'Commewijne': 31420, 'Marowijne': 18294, 'Para': 24700,
    'Brokopondo': 15909, 'Sipaliwini': 37065,
}
SR_DISTRICTEN = {
    f'District {name}': {'id': f'SR-HAND-DISTRICT-{name.upper()}', 'country': 'SR', 'kind': 'sr_district',
                         'population': pop, 'peildatum': '2012-08-13', 'bron_url': ABS_CENSUS8_URL,
                         'aliases': [name, f'Districtscommissariaat {name}']}
    for name, pop in _SR_DISTRICT_POP.items()
}

# Alle tabellen in laadvolgorde
TABLES = [AW_LAND, AW_MINISTERIES, CW_LAND, CW_MINISTERIES, SX_LAND, SX_MINISTERIES,
          BQ_OPENBARE_LICHAMEN, BQ_RIJKSDIENST, SR_REGERING, SR_MINISTERIES, SR_DISTRICTEN]
