"""
step2_enrich.py
================
Verrijkt de output van step1_classify.py met inwoneraantallen, bronvermelding,
peildatum en proces-uitleg. Haalt referentiedata op via Wikidata SPARQL.

WAT DEZE VERSIE DOET (v1):
- Download (en cache) NL/BE/DE referentielijsten van gemeenten, provincies,
  waterschappen, landkreise, verbandsgemeinden, politiezones, etc. uit Wikidata
- Download Aruba/Curaçao/Sint Maarten totaal-inwonertallen
- 1-op-1 fuzzy match per type op canonical_name (gebruikt fuzz.ratio, strenge threshold)
- Aggregatie (sommen) voor NL veiligheidsregio's en omgevingsdiensten via
  ingebouwde mapping-tabellen
- Behoudt oude cx_population waarden als geen nieuwe gevonden is
- Past optionele override-tabel toe
- Skipt records met "niet gebruiken" in de naam (CRM-markering voor obsolete)
- Schrijft Excel-output met draaitabel-tab en metadata-kolommen
- Logbestand met run-statistieken

WAT DEZE VERSIE NOG NIET DOET (v2):
- Aggregatie voor samenwerking_nl, belastingsamenwerking, hulpverleningszone,
  ggd, stadsregio, amt, verwaltungsgemeinschaft (vereisen mapping-tabellen)
- CBS Statline als primaire bron voor NL (nu alles via Wikidata)
  Trade-off: Wikidata kan 1-2 jaar oud zijn, CBS is verser

GEBRUIK:
    # Eerste keer (downloadt referentiedata, duurt 5-10 min)
    python step2_enrich.py --input step1_classified.xlsx --output step2_enriched.xlsx \\
        --user-agent "jouw-org/1.0 (jouwemail@bedrijf.nl)"

    # Test op eerste 100 records eerst
    python step2_enrich.py --input step1_classified.xlsx --output test.xlsx --test-mode \\
        --user-agent "jouw-org/1.0 (jouwemail@bedrijf.nl)"

    # Forceer verse download van referentiedata
    python step2_enrich.py --input step1_classified.xlsx --output step2_enriched.xlsx \\
        --refresh-cache --user-agent "..."

    # Met override-tabel
    python step2_enrich.py --input step1_classified.xlsx --output step2_enriched.xlsx \\
        --overrides overrides.xlsx --user-agent "..."

    # Offline-modus: alleen lokale cache, ga niet online
    python step2_enrich.py --input step1_classified.xlsx --output step2_enriched.xlsx --offline

DEPENDENCIES:
    pip install pandas openpyxl requests rapidfuzz

UITVOER-KOLOMMEN (toegevoegd):
    - cx_population:           nieuwe waarde of behouden oude
    - previous_population:     waarde vóór deze run, voor diff-analyse
    - peildatum_inwoners:      jaar van de bron-statistiek
    - bron:                    bv 'Wikidata Q1234 (nl_gemeenten)' of 'override-tabel'
    - proces:                  bv 'directe match', 'som van 4 gemeenten', 'behouden'
    - invuldatum:              datum van deze run
    - match_score:             fuzzy match score 0-100 (alleen bij directe match)
"""

import argparse
import logging
import re
import threading
import time
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from rapidfuzz import fuzz, process

# ============================================================================
# CONFIG
# ============================================================================

REFERENCE_DIR = Path('reference')
WIKIDATA_ENDPOINT = 'https://query.wikidata.org/sparql'
DEFAULT_USER_AGENT = 'CRM-Population-Enrichment/1.0 (please-set-contact-email)'
CACHE_MAX_AGE_DAYS = 365            # Referentiedata jaarlijks vers ophalen
SPARQL_TIMEOUT_SECONDS = 120
# Threshold-tuning: ratio() is strenger dan WRatio() en voorkomt fout-positieven
# zoals "Alken" -> "Halen" (die met WRatio score 80 zouden krijgen).
FUZZY_HIGH_THRESHOLD = 92           # >= deze = high confidence match
FUZZY_LOW_THRESHOLD = 85            # < deze = geen match. Onder 85 te onbetrouwbaar.
RUN_DATE = date.today().isoformat()

# Records met deze markers in hun naam zijn door CRM-gebruikers gemarkeerd als
# 'obsolete' en we proberen er geen lookup voor te doen.
SKIP_NAME_MARKERS = ['niet gebruiken', 'do not use', 'obsolete', 'deprecated']

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('enrich')


# ============================================================================
# WIKIDATA SPARQL QUERIES
# ============================================================================

def _sparql_population_template(qid_filter):
    """
    SPARQL-query die items van de gegeven klasse ophaalt met alle hun populatie-
    statements (inclusief peildatum als pq:P585 qualifier). qid_filter is bv
    'wd:Q2039348' voor NL gemeente.

    NOTE: deze query haalt ALLE population-statements op (vroeger had hij een
    FILTER NOT EXISTS om alleen de meest recente te krijgen, maar dat O(n²) join-
    pattern overschreed Wikidata's harde 60-sec timeout voor grote sets als
    NL gemeenten of DE Gemeinden). We doen de 'pak de meest recente per item'
    deduplicatie nu in Python via deduplicate_keep_latest().
    """
    # FILTER NOT EXISTS { ?item wdt:P576 ?dissolved } sluit entiteiten met een
    # ontbindingsdatum uit. Effect gemeten 2026-05-11:
    #   be_gemeenten:  581 -> 565  (matcht realiteit: BE heeft ~565 gemeenten)
    #   nl_gemeenten: 1575 -> 1316 (verbetering, maar nog te veel; veel
    #                                historische NL gemeenten missen P576)
    # Goedkope existence check, geen merkbaar timeout-effect.
    return f"""
    SELECT ?item ?itemLabel ?population ?date WHERE {{
      ?item wdt:P31 {qid_filter} .
      FILTER NOT EXISTS {{ ?item wdt:P576 ?dissolved }}
      ?item p:P1082 ?stmt .
      ?stmt ps:P1082 ?population .
      OPTIONAL {{ ?stmt pq:P585 ?date . }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "nl,en,de,fr". }}
    }}
    """


# Lijst van alle referentielijsten die we ophalen.
# 'qid' = Wikidata-klasse-Q-ID, 'description' = mens-leesbaar.
#
# NB: nl_waterschappen niet in deze lijst. Wikidata heeft P1082 voor 0 van de
# 23 actieve waterschappen (gemeten 2026-05-11, qid Q702081). Aanpak: behandel
# 'waterschap' als aggregatie-type via NL_WATERSCHAP_GEMEENTEN (zie hieronder).
#
# NB: nl_stadsdelen ook niet in deze lijst. De juiste Wikidata-klasse is
# Q15079751 ("borough of Amsterdam"), maar 0 van de 8 huidige stadsdelen heeft
# P1082 (gemeten 2026-05-11). Aanpak: directe-waarde-lookup via
# NL_STADSDEEL_INWONERS, gevoed met cijfers uit NL Wikipedia-infoboxen.
#
# NB: be_politiezones ook niet in deze lijst. De juiste klasse is Q2621126
# ("police zone"), maar 0 van de 176 politiezones heeft P1082 (gemeten
# 2026-05-11). Aanpak: aggregatie van BE gemeenten via BE_POLITIEZONE_GEMEENTEN.
REFERENCE_SOURCES = [
    {'name': 'nl_gemeenten',          'qid': 'wd:Q2039348',  'description': 'NL gemeenten'},
    {'name': 'nl_provincies',         'qid': 'wd:Q134390',   'description': 'NL provincies'},
    {'name': 'be_gemeenten',          'qid': 'wd:Q493522',   'description': 'BE gemeenten'},
    {'name': 'be_provincies',         'qid': 'wd:Q83116',    'description': 'BE provincies'},
    {'name': 'de_gemeinden',          'qid': 'wd:Q262166',   'description': 'DE gemeinden'},
    {'name': 'de_landkreise',         'qid': 'wd:Q106658',   'description': 'DE landkreise'},
    {'name': 'de_verbandsgemeinden',  'qid': 'wd:Q253019',   'description': 'DE verbandsgemeinden'},
]


# Caribische landen: één query voor de drie landen plus Caribisch Nederland.
SPARQL_CARIBBEAN = """
SELECT ?item ?itemLabel ?population ?date WHERE {
  VALUES ?item { wd:Q21203 wd:Q25279 wd:Q26273 wd:Q1462 }
  ?item p:P1082 ?stmt .
  ?stmt ps:P1082 ?population .
  OPTIONAL { ?stmt pq:P585 ?date . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "nl,en". }
}
"""
# Geen FILTER NOT EXISTS (oorzaak van 60-sec timeout). Deduplicatie naar
# meest recente populatie per land gebeurt in Python.
# Q21203 = Aruba, Q25279 = Curaçao, Q26273 = Sint Maarten, Q1462 = Caribisch Nederland


# ============================================================================
# AGGREGATIE MAPPINGS (NL VEILIGHEIDSREGIO'S EN OMGEVINGSDIENSTEN)
# ============================================================================
# Voor types waar inwonertal = som van gemeenten. Periodiek bijwerken bij
# gemeentelijke herindelingen. Bron: rijksoverheid.nl / regio-websites.
# Kanonieke namen MOETEN matchen met namen in nl_gemeenten (post-normalisatie).

NL_VEILIGHEIDSREGIO_GEMEENTEN = {
    'Brabant-Noord': [
        "'s-Hertogenbosch", "Bernheze", "Boekel", "Boxtel", "Heusden", "Land van Cuijk",
        "Maashorst", "Meierijstad", "Oss", "Sint-Michielsgestel", "Vught"
    ],
    'Brabant-Zuidoost': [
        "Asten", "Bergeijk", "Best", "Bladel", "Cranendonck", "Deurne", "Eersel",
        "Eindhoven", "Geldrop-Mierlo", "Gemert-Bakel", "Heeze-Leende", "Helmond",
        "Laarbeek", "Nuenen, Gerwen en Nederwetten", "Oirschot", "Reusel-De Mierden",
        "Someren", "Son en Breugel", "Valkenswaard", "Veldhoven", "Waalre"
    ],
    'Midden- en West-Brabant': [
        "Alphen-Chaam", "Altena", "Baarle-Nassau", "Bergen op Zoom", "Breda", "Dongen",
        "Drimmelen", "Etten-Leur", "Geertruidenberg", "Gilze en Rijen", "Goirle",
        "Halderberge", "Hilvarenbeek", "Loon op Zand", "Moerdijk", "Oisterwijk",
        "Oosterhout", "Roosendaal", "Rucphen", "Steenbergen", "Tilburg", "Waalwijk",
        "Woensdrecht", "Zundert"
    ],
    'Zeeland': [
        "Borsele", "Goes", "Hulst", "Kapelle", "Middelburg", "Noord-Beveland", "Reimerswaal",
        "Schouwen-Duiveland", "Sluis", "Terneuzen", "Tholen", "Veere", "Vlissingen"
    ],
    'Rotterdam Rijnmond': [
        "Albrandswaard", "Barendrecht", "Brielle", "Capelle aan den IJssel", "Goeree-Overflakkee",
        "Hellevoetsluis", "Krimpen aan den IJssel", "Lansingerland", "Maassluis", "Nissewaard",
        "Ridderkerk", "Rotterdam", "Schiedam", "Vlaardingen", "Voorne aan Zee", "Westvoorne"
    ],
    # Aanvullen indien jouw CRM andere veiligheidsregio's bevat.
}

# NL waterschappen: 21 actieve water boards (per 2026). Wikidata heeft GEEN
# inwonertal-data (P1082) voor waterschappen, dus we sommen NL gemeenten in
# het beheergebied. Let op: waterschap-grenzen volgen NIET netjes gemeente-
# grenzen (een gemeente kan in meerdere waterschappen vallen). De som is
# daarom een benadering. Onderzoek-bron per ingang invullen (waterschap-
# website / Wikipedia / Unie van Waterschappen).
#
# Sleutels MOETEN matchen met canonical_name uit step1 (na het strippen van
# het "Waterschap "/"Hoogheemraadschap "-prefix). Waarden zijn NL gemeente-
# namen zoals ze in nl_gemeenten staan (na normalisatie matched fuzzy).
#
# Status: STUB. Lijsten leeg tot we ze met betrouwbare bron invullen.
NL_WATERSCHAP_GEMEENTEN = {
    # Hoogheemraadschappen (4 stuks)
    'Hollands Noorderkwartier': [],         # Q4469762
    'Rijnland':                  [],         # Q2619632
    'Delfland':                  [],         # Q3046110
    'Schieland en de Krimpenerwaard': [],   # Q2304570
    'De Stichtse Rijnlanden':    [],         # Q2046915
    'Amstel, Gooi en Vecht':     [],         # Q2192659

    # Waterschappen (15 stuks)
    'Aa en Maas':                [],         # Q2553577
    'Brabantse Delta':           [],         # Q3211339
    'De Dommel':                 [],         # Q2904296
    'Drents Overijsselse Delta': [],         # Q21921798
    'Hollandse Delta':           [],         # Q3079910
    'Hunze en Aa\'s':            [],         # Q14941974
    'Limburg':                   [],         # Q27895262
    'Noorderzijlvest':           [],         # Q2096098
    'Rijn en IJssel':            [],         # Q2228586
    'Rivierenland':              [],         # Q2273075
    'Scheldestromen':            [],         # Q2422832
    'Vallei en Veluwe':          [],         # Q2474783
    'Vechtstromen':              [],         # Q15883321
    'Wetterskip Fryslan':        [],         # Q1970347   (Fries: "Fryslan")
    'Zuiderzeeland':             [],         # Q3086208
}


# Amsterdam stadsdelen (per 2026): 7 stadsdelen + 1 stadsgebied Weesp.
# Wikidata heeft GEEN P1082 voor deze entiteiten (Q15079751 - borough of
# Amsterdam). Cijfers daarom uit NL Wikipedia-infoboxen.
#
# Peildatums verschillen per artikel (2020 t/m 2022) - we slaan het jaar op
# in peildatum_inwoners. Periodiek bijwerken via officiele bron
# onderzoek.amsterdam.nl voor verse data.
#
# Beide naamsvarianten als sleutel: 'Centrum' (na strippen van "Stadsdeel "-
# prefix in step1) en 'Amsterdam-Centrum' (volledige naam zoals in sommige
# CRM-records).
NL_STADSDEEL_INWONERS = {
    'Centrum':                {'population':  87310, 'peildatum': '2020',
                               'bron_url':   'https://nl.wikipedia.org/wiki/Amsterdam-Centrum'},
    'Amsterdam-Centrum':      {'population':  87310, 'peildatum': '2020',
                               'bron_url':   'https://nl.wikipedia.org/wiki/Amsterdam-Centrum'},
    'Noord':                  {'population':  99238, 'peildatum': '2020',
                               'bron_url':   'https://nl.wikipedia.org/wiki/Amsterdam-Noord'},
    'Amsterdam-Noord':        {'population':  99238, 'peildatum': '2020',
                               'bron_url':   'https://nl.wikipedia.org/wiki/Amsterdam-Noord'},
    'Oost':                   {'population': 142049, 'peildatum': '2020',
                               'bron_url':   'https://nl.wikipedia.org/wiki/Amsterdam-Oost'},
    'Amsterdam-Oost':         {'population': 142049, 'peildatum': '2020',
                               'bron_url':   'https://nl.wikipedia.org/wiki/Amsterdam-Oost'},
    'Zuid':                   {'population': 146291, 'peildatum': '2020',
                               'bron_url':   'https://nl.wikipedia.org/wiki/Amsterdam-Zuid'},
    'Amsterdam-Zuid':         {'population': 146291, 'peildatum': '2020',
                               'bron_url':   'https://nl.wikipedia.org/wiki/Amsterdam-Zuid'},
    'Zuidoost':               {'population':  89841, 'peildatum': '2020',
                               'bron_url':   'https://nl.wikipedia.org/wiki/Amsterdam-Zuidoost'},
    'Amsterdam-Zuidoost':     {'population':  89841, 'peildatum': '2020',
                               'bron_url':   'https://nl.wikipedia.org/wiki/Amsterdam-Zuidoost'},
    'West':                   {'population': 148908, 'peildatum': '2022',
                               'bron_url':   'https://nl.wikipedia.org/wiki/Amsterdam-West'},
    'Amsterdam-West':         {'population': 148908, 'peildatum': '2022',
                               'bron_url':   'https://nl.wikipedia.org/wiki/Amsterdam-West'},
    'Nieuw-West':             {'population': 159522, 'peildatum': '2021',
                               'bron_url':   'https://nl.wikipedia.org/wiki/Amsterdam-Nieuw-West'},
    'Amsterdam-Nieuw-West':   {'population': 159522, 'peildatum': '2021',
                               'bron_url':   'https://nl.wikipedia.org/wiki/Amsterdam-Nieuw-West'},
    'Weesp':                  {'population':  20766, 'peildatum': '2022',
                               'bron_url':   'https://nl.wikipedia.org/wiki/Weesp'},
}


NL_OMGEVINGSDIENST_GEMEENTEN = {
    'DCMR Rijnmond': [
        "Albrandswaard", "Barendrecht", "Brielle", "Capelle aan den IJssel", "Goeree-Overflakkee",
        "Hellevoetsluis", "Krimpen aan den IJssel", "Lansingerland", "Maassluis", "Nissewaard",
        "Ridderkerk", "Rotterdam", "Schiedam", "Vlaardingen", "Voorne aan Zee", "Westvoorne"
    ],
    'Brabant Noord': [
        "'s-Hertogenbosch", "Bernheze", "Boekel", "Boxtel", "Heusden", "Land van Cuijk",
        "Maashorst", "Meierijstad", "Oss", "Sint-Michielsgestel", "Vught"
    ],
    'Drenthe': [
        "Aa en Hunze", "Assen", "Borger-Odoorn", "Coevorden", "De Wolden", "Emmen",
        "Hoogeveen", "Meppel", "Midden-Drenthe", "Noordenveld", "Tynaarlo", "Westerveld"
    ],
    'Limburg Noord': [
        "Beesel", "Bergen", "Echt-Susteren", "Gennep", "Horst aan de Maas", "Leudal",
        "Maasgouw", "Mook en Middelaar", "Nederweert", "Peel en Maas", "Roerdalen",
        "Roermond", "Venlo", "Venray", "Weert"
    ],
    'RUD Utrecht': [
        "Amersfoort", "Baarn", "Bunnik", "Bunschoten", "De Bilt", "De Ronde Venen",
        "Eemnes", "Houten", "IJsselstein", "Leusden", "Lopik", "Montfoort", "Nieuwegein",
        "Oudewater", "Renswoude", "Rhenen", "Soest", "Stichtse Vecht", "Utrechtse Heuvelrug",
        "Veenendaal", "Vijfheerenlanden", "Wijk bij Duurstede", "Woerden", "Woudenberg", "Zeist"
    ],
    # Aanvullen indien nodig.
}


# BE politiezones: 176 zones (per 2026). Wikidata heeft GEEN P1082 voor deze
# entiteiten (Q2621126 - police zone, gemeten 2026-05-11). Cijfers worden
# berekend als som van be_gemeenten in elk politiezonebeheergebied.
#
# Sleutels = naam van de politiezone na strippen van "PZ "/"ZP "-prefix.
# Waarden = lijst NL-gemeentenamen zoals ze in be_gemeenten staan (Wikidata
# itemLabel met taal-prioriteit nl,en,de,fr, dus Frans-talige gemeenten als
# 'Luik', 'Bergen', 'Aarlen', 'Komen-Waasten' etc.).
#
# Geextraheerd op 2026-05-11 uit NL Wikipedia:
# https://nl.wikipedia.org/wiki/Lijst_van_politiezones_in_Belgi%C3%AB
# 173 zones geparseerd; 3 minder dan 176 wegens (zeldzame) edge cases in
# de wikitext-opmaak. Periodiek vernieuwen.
BE_POLITIEZONE_GEMEENTEN = {
    'Antwerpen': ['Antwerpen'],
    'Rupel': ['Boom', 'Hemiksem', 'Niel', 'Rumst', 'Schelle'],
    'Noord': ['Kapellen', 'Stabroek'],
    'HEKLA': ['Hove', 'Edegem', 'Kontich', 'Lint', 'Aartselaar'],
    'Grens': ['Essen', 'Kalmthout', 'Wuustwezel'],
    'MINOS': ['Boechout', 'Mortsel', 'Wijnegem', 'Wommelgem'],
    'Brasschaat': ['Brasschaat'],
    'Schoten': ['Schoten'],
    'ZARA': ['Zandhoven', 'Ranst'],
    'Voorkempen': ['Brecht', 'Malle', 'Schilde', 'Zoersel'],
    'BODUKAP': ['Bonheiden', 'Duffel', 'Sint-Katelijne-Waver', 'Putte'],
    'Lier': ['Lier'],
    'Berlaar/Nijlen': ['Berlaar', 'Nijlen'],
    'Heist': ['Heist-op-den-Berg'],
    'Noorderkempen': ['Hoogstraten', 'Merksplas', 'Rijkevorsel'],
    'Regio Turnhout': ['Baarle-Hertog', 'Beerse', 'Kasterlee', 'Lille', 'Oud-Turnhout', 'Turnhout', 'Vosselaar'],
    'Zuiderkempen': ['Herselt', 'Hulshout', 'Westerlo'],
    'Geel-Laakdal-Meerhout': ['Geel', 'Laakdal', 'Meerhout'],
    'Kempen Noord-Oost': ['Arendonk', 'Ravels', 'Retie'],
    'Balen-Dessel-Mol': ['Balen', 'Dessel', 'Mol'],
    'Neteland': ['Grobbendonk', 'Herentals', 'Herenthout', 'Olen', 'Vorselaar'],
    'Rivierenland': ['Bornem', 'Puurs-Sint-Amands', 'Mechelen', 'Willebroek'],
    'Beringen/Ham/Tessenderlo': ['Beringen', 'Tessenderlo-Ham'],
    'Heusden-Zolder': ['Heusden-Zolder'],
    'Sint-Truiden/Gingelom/Nieuwerkerken': ['Sint-Truiden', 'Gingelom', 'Nieuwerkerken'],
    'Bilzen/Hoeselt/Riemst': ['Bilzen-Hoeselt', 'Riemst'],
    'Voeren': ['Voeren'],
    'Maasland': ['Dilsen-Stokkem', 'Maaseik'],
    'Lanaken/Maasmechelen': ['Lanaken', 'Maasmechelen'],
    'Limburg Regio Hoofdstad': ['Alken', 'Hasselt', 'Zonhoven', 'Diepenbeek', 'Halen', 'Herk-de-Stad', 'Lummen'],
    'CARMA': ['Genk', 'As', 'Oudsbergen', 'Zutendaal', 'Houthalen-Helchteren', 'Bocholt', 'Bree', 'Kinrooi'],
    'Noord-Limburg': ['Hamont-Achel', 'Hechtel-Eksel', 'Leopoldsburg', 'Lommel', 'Peer', 'Pelt'],
    'Leuven': ['Leuven'],
    'Hageland': ['Bekkevoort', 'Geetbets', 'Glabbeek', 'Kortenaken', 'Tielt-Winge'],
    'Bierbeek/Boutersem/Holsbeek/Lubbeek': ['Bierbeek', 'Boutersem', 'Holsbeek', 'Lubbeek'],
    'HerKo': ['Herent', 'Kortenberg'],
    'Aarschot': ['Aarschot'],
    'Boortmeerbeek/Haacht/Keerbergen': ['Boortmeerbeek', 'Haacht', 'Keerbergen'],
    'Demerdal DSZ': ['Diest', 'Scherpenheuvel-Zichem'],
    'BRT': ['Begijnendijk', 'Rotselaar', 'Tremelo'],
    'Zaventem': ['Zaventem'],
    'WOKRA': ['Wezembeek-Oppem', 'Kraainem'],
    'Druivenstreek': ['Overijse', 'Hoeilaart'],
    'Rode': ['Drogenbos', 'Linkebeek', 'Sint-Genesius-Rode'],
    'Pajottenland': ['Bever', 'Lennik', 'Pajottegem', 'Pepingen'],
    'Dilbeek': ['Dilbeek'],
    'TARL': ['Ternat', 'Affligem', 'Roosdaal', 'Liedekerke'],
    'AMOW': ['Asse', 'Merchtem', 'Opwijk', 'Wemmel'],
    'K-L-M': ['Kapelle-op-den-Bos', 'Londerzeel', 'Meise'],
    'Grimbergen': ['Grimbergen'],
    'Vilvoorde/Machelen': ['Vilvoorde', 'Machelen'],
    'KASTZE': ['Kampenhout', 'Steenokkerzeel', 'Zemst'],
    'Zennevallei': ['Beersel', 'Halle', 'Sint-Pieters-Leeuw'],
    'Voer & Dijle': ['Bertem', 'Huldenberg', 'Oud-Heverlee', 'Tervuren'],
    'Getevallei': ['Tienen', 'Hoegaarden', 'Landen', 'Linter', 'Zoutleeuw'],
    'Gent': ['Gent'],
    'Regio Puyenbroeck': ['Lochristi', 'Zelzate'],
    'Meetjesland-Centrum': ['Eeklo', 'Kaprijke', 'Sint-Laureins'],
    'Regio Rhode & Schelde': ['Destelbergen', 'Merelbeke-Melle', 'Oosterzele'],
    'Schelde-Leie': ['Gavere', 'Nazareth-De Pinte', 'Sint-Martens-Latem'],
    'Assenede/Evergem': ['Assenede', 'Evergem'],
    'Ronse': ['Ronse'],
    'Geraardsbergen/Lierde': ['Geraardsbergen', 'Lierde'],
    'Zottegem/Herzele/Sint-Lievens-Houtem': ['Zottegem', 'Herzele', 'Sint-Lievens-Houtem'],
    'Sint-Niklaas': ['Sint-Niklaas'],
    'Lokeren': ['Lokeren'],
    'Hamme/Waasmunster': ['Hamme', 'Waasmunster'],
    'Berlare/Zele': ['Berlare', 'Zele'],
    'Buggenhout/Lebbeke': ['Buggenhout', 'Lebbeke'],
    'Wetteren/Laarne/Wichelen': ['Wetteren', 'Laarne', 'Wichelen'],
    'Denderleeuw/Haaltert': ['Denderleeuw', 'Haaltert'],
    'Aalst': ['Aalst'],
    'Erpe-Mere/Lede': ['Erpe-Mere', 'Lede'],
    'Ninove': ['Ninove'],
    'Dendermonde': ['Dendermonde'],
    'Deinze-Zulte-Lievegem': ['Deinze', 'Zulte', 'Lievegem'],
    'Aalter/Maldegem': ['Aalter', 'Maldegem'],
    'Scheldewaas': ['Beveren-Kruibeke-Zwijndrecht', 'Sint-Gillis-Waas', 'Stekene', 'Temse'],
    'Vlaamse Ardennen': ['Brakel', 'Horebeke', 'Kluisbergen', 'Kruisem', 'Maarkedal', 'Oudenaarde', 'Wortegem-Petegem', 'Zwalm'],
    'Brugge': ['Brugge'],
    'Blankenberge/Zuienkerke': ['Blankenberge', 'Zuienkerke'],
    'Damme/Knokke-Heist': ['Damme', 'Knokke-Heist'],
    'Het Houtsche': ['Beernem', 'Oostkamp', 'Zedelgem'],
    'Regio Tielt': ['Ardooie', 'Lichtervelde', 'Pittem', 'Tielt', 'Wingene'],
    'Oostende': ['Oostende'],
    'Bredene/De Haan': ['Bredene', 'De Haan'],
    'Middelkerke': ['Middelkerke'],
    'Kouter': ['Gistel', 'Ichtegem', 'Jabbeke', 'Oudenburg', 'Torhout'],
    'RIHO': ['Roeselare', 'Izegem', 'Hooglede'],
    'MIDOW': ['Ingelmunster', 'Dentergem', 'Oostrozebeke', 'Wielsbeke'],
    'Grensleie': ['Ledegem', 'Menen', 'Wevelgem'],
    'VLAS': ['Kortrijk', 'Kuurne', 'Lendelede'],
    'MIRA': ['Anzegem', 'Avelgem', 'Spiere-Helkijn', 'Waregem', 'Zwevegem'],
    'Gavers': ['Deerlijk', 'Harelbeke'],
    'Spoorkin': ['Alveringem', 'Lo-Reninge', 'Veurne'],
    'Polder': ['Diksmuide', 'Houthulst', 'Koekelare', 'Kortemark'],
    'Westkust': ['De Panne', 'Koksijde', 'Nieuwpoort'],
    'ARRO Ieper': ['Heuvelland', 'Langemark-Poelkapelle', 'Mesen', 'Moorslede', 'Poperinge', 'Staden', 'Vleteren', 'Wervik', 'Ieper', 'Zonnebeke'],
    'Brussel HOOFDSTAD Elsene': ['Brussel', 'Elsene'],
    'Brussel-West': ['Sint-Jans-Molenbeek', 'Koekelberg', 'Jette', 'Ganshoren', 'Sint-Agatha-Berchem'],
    'Zuid': ['Anderlecht', 'Vorst', 'Sint-Gillis'],
    'Ukkel/Watermaal-Bosvoorde/Oudergem': ['Oudergem', 'Ukkel', 'Watermaal-Bosvoorde'],
    'Montgomery': ['Etterbeek', 'Sint-Lambrechts-Woluwe', 'Sint-Pieters-Woluwe'],
    'Evere/Schaarbeek/Sint-Joost-ten-Node': ['Evere', 'Sint-Joost-ten-Node', 'Schaarbeek'],
    'Nivelles/Genappe': ['Nijvel', 'Genepiën'],
    'Ouest Brabant Wallon': ['Kasteelbrakel', 'Itter', 'Rebecq', 'Tubeke'],
    'La Mazerine': ['Terhulpen', 'Lasne', 'Rixensart'],
    'Orne-Thyle': ['Chastre', 'Court-Saint-Étienne', 'Mont-Saint-Guibert', 'Villers-la-Ville', 'Walhain'],
    'Wavre': ['Waver'],
    'Ardennes Brabançonnes': ['Bevekom', 'Chaumont-Gistoux', 'Graven', 'Incourt'],
    "Braine-l'Alleud": ['Eigenbrakel'],
    'Waterloo': ['Waterloo'],
    'Ottignies-Louvain-la-Neuve': ['Ottignies-Louvain-la-Neuve'],
    'Brabant Wallon Est': ['Hélécine', 'Geldenaken', 'Orp-Jauche', 'Perwijs', 'Ramillies'],
    'Liège': ['Luik'],
    'Seraing/Neupré': ['Seraing', 'Neupré'],
    'Herstal': ['Herstal'],
    'Beyne-Heusay/Fléron/Soumagne': ['Beyne-Heusay', 'Fléron', 'Soumagne'],
    'Basse Meuse': ['Bitsingen', 'Blegny', 'Dalhem', 'Juprelle', 'Oupeye', 'Wezet'],
    'Flémalle': ['Flémalle'],
    'Secova': ['Aywaille', 'Chaudfontaine', 'Esneux', 'Sprimont', 'Trooz'],
    'Ans/Saint-Nicolas': ['Ans', 'Saint-Nicolas'],
    'Grâce-Hollogne/Awans': ['Grâce-Hollogne', 'Awans'],
    'Hesbaye': ['Berloz', 'Crisnée', 'Donceel', 'Faimes', 'Fexhe-le-Haut-Clocher', 'Geer', 'Oerle', 'Remicourt', 'Borgworm'],
    'Des Fagnes': ['Jalhay', 'Spa', 'Theux'],
    'Pays de Herve': ['Aubel', 'Baelen', 'Herve', 'Limburg', 'Olne', 'Plombières', 'Thimister-Clermont', 'Welkenraedt'],
    'Vesdre': ['Dison', 'Pepinster', 'Verviers'],
    'Stavelot/Malmedy': ['Lierneux', 'Malmedy', 'Stavelot', 'Stoumont', 'Trois-Ponts', 'Weismes'],
    'Hesbaye-Ouest': ['Braives', 'Burdinne', 'Hannuit', 'Héron', 'Lijsem', 'Wasseiges'],
    'Meuse-Hesbaye': ['Amay', 'Engis', 'Saint-Georges-sur-Meuse', 'Verlaine', 'Villers-le-Bouillet', 'Wanze'],
    'Huy': ['Hoei'],
    'Du Condroz': ['Anthisnes', 'Clavier', 'Comblain-au-Pont', 'Ferrières', 'Hamoir', 'Marchin', 'Modave', 'Nandrin', 'Ouffet', 'Tinlot'],
    'Arlon/Attert/Habay/Martelange': ['Aarlen', 'Attert', 'Habay', 'Martelange'],
    'Sud-Luxembourg': ['Aubange', 'Messancy', 'Musson', 'Saint-Léger'],
    'De Gaume': ['Chiny', 'Étalle', 'Florenville', 'Meix-devant-Virton', 'Rouvroy', 'Tintigny', 'Virton'],
    'Famenne Ardenne': ['Durbuy', 'Érezée', 'Gouvy', 'Hotton', 'Houffalize', 'La Roche-en-Ardenne', 'Manhay', 'Marche-en-Famenne', 'Nassogne', 'Rendeux', 'Tenneville', 'Vielsalm'],
    'Centre Ardenne': ['Bastenaken', 'Fauvillers', 'Léglise', 'Libramont-Chevigny', 'Neufchâteau', 'Sainte-Ode', 'Vaux-sur-Sûre'],
    'Semois et Lesse': ['Bertrix', 'Bouillon', 'Daverdisse', 'Herbeumont', 'Libin', 'Paliseul', 'Saint-Hubert', 'Tellin', 'Wellin'],
    'Namur': ['Namen'],
    'Orneau-Mehaigne': ['Éghezée', 'Gembloers', 'La Bruyère'],
    'Des Arches': ['Andenne', 'Assesse', 'Fernelmont', 'Gesves', 'Ohey'],
    'Entre Sambre et Meuse': ['Floreffe', 'Fosses-la-Ville', 'Mettet', 'Profondeville'],
    'Samsom': ['Sambreville', 'Sombreffe'],
    'Jemeppe-sur-Sambre': ['Jemeppe-sur-Sambre'],
    'Flowal': ['Florennes', 'Walcourt'],
    'Houille-Semois': ['Beauraing', 'Bièvre', 'Gedinne', 'Vresse-sur-Semois'],
    'Des 3 Vallées': ['Couvin', 'Viroinval'],
    'Haute-Meuse': ['Anhée', 'Dinant', 'Hastière', 'Onhaye', 'Yvoir'],
    'Lesse et Lhomme': ['Houyet', 'Rochefort'],
    'Condroz Famenne': ['Ciney', 'Hamois', 'Havelange', 'Somme-Leuze'],
    'Hermeton et Heure': ['Cerfontaine', 'Doische', 'Philippeville'],
    'Du Tournaisis': ['Doornik', 'Brunehaut', 'Rumes', 'Antoing'],
    'Mouscron': ['Moeskroen'],
    'Comines-Warneton': ['Komen-Waasten'],
    'Beloeil/Leuze-en-Hainaut': ['Belœil', 'Leuze-en-Hainaut'],
    'Ath': ['Aat'],
    "Du Val de l'Escaut": ['Celles', 'Estaimpuis', "Mont-de-l'Enclus", 'Pecq'],
    'Bernissart/Péruwelz': ['Bernissart', 'Péruwelz'],
    'Des Collines': ['Elzele', 'Vloesberg', 'Frasnes-lez-Anvaing', 'Lessen'],
    'Mons/Quévy': ['Bergen', 'Quévy'],
    'La Louvière': ['La Louvière'],
    'Sylle et Dendre': ['Brugelette', 'Chièvres', 'Edingen', 'Jurbeke', 'Lens', 'Opzullik'],
    'Boraine': ['Boussu', 'Colfontaine', 'Frameries', 'Quaregnon', 'Saint-Ghislain'],
    'Haute Senne': ["'s-Gravenbrakel", 'Écaussinnes', 'Le Rœulx', 'Zinnik'],
    'Des Hauts-Pays': ['Dour', 'Hensies', 'Honnelles', 'Quiévrain'],
    'Charleroi': ['Charleroi'],
    'Aiseau-Presles/Châtelet/Farciennes': ['Aiseau-Presles', 'Châtelet', 'Farciennes'],
    'Botte du Hainaut': ['Beaumont', 'Chimay', 'Froidchapelle', 'Momignies', 'Sivry-Rance'],
    'Mariemont': ['Chapelle-lez-Herlaimont', 'Manage', 'Morlanwelz', 'Seneffe'],
    'Des Trieux': ['Courcelles', "Fontaine-l'Evêque"],
    'Brunau': ['Fleurus', 'Les Bons Villers', 'Pont-à-Celles'],
    'Germinalt': ['Gerpinnes', 'Ham-sur-Heure-Nalinnes', 'Montigny-le-Tilleul', 'Thuin'],
    'Binche-Anderlues-Lermes': ['Anderlues', 'Binche', 'Lobbes', 'Erquelinnes', 'Merbes-le-Château', 'Estinnes'],
}


# ============================================================================
# HTTP / SPARQL UTILS
# ============================================================================

@contextmanager
def heartbeat(message, interval=10):
    """
    Context manager die elke 'interval' seconden een 'nog bezig'-bericht logt.
    Handig voor SPARQL-queries die soms 30-90 seconden duren zonder feedback.
    Stopt automatisch wanneer het with-block verlaten wordt.
    """
    stop_event = threading.Event()
    start = time.time()

    def beat():
        # Wacht eerst 'interval' seconden voordat we de eerste heartbeat sturen,
        # zodat snelle queries geen onnodige output geven
        while not stop_event.wait(interval):
            elapsed = int(time.time() - start)
            log.info(f"  ... nog bezig met {message} ({elapsed}s verstreken)")

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=1)


def sparql_query(query, user_agent, max_retries=3, retry_delay=5):
    """Voert SPARQL-query uit tegen Wikidata. Returnt geparseerde results.bindings."""
    headers = {
        'User-Agent': user_agent,
        'Accept': 'application/sparql-results+json',
    }
    data = {'query': query}
    last_error = None
    for attempt in range(max_retries):
        try:
            r = requests.post(
                WIKIDATA_ENDPOINT, data=data, headers=headers,
                timeout=SPARQL_TIMEOUT_SECONDS,
            )
            r.raise_for_status()
            return r.json()['results']['bindings']
        except requests.exceptions.RequestException as e:
            last_error = e
            log.warning(f"  SPARQL attempt {attempt + 1}/{max_retries} faalde: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))
    raise RuntimeError(f"SPARQL faalde na {max_retries} pogingen: {last_error}")


def deduplicate_keep_latest(df):
    """
    Per qid behoudt alleen de rij met de meest recente peildatum.
    Rijen zonder peildatum komen achteraan in de sortering (kunnen alleen
    bewaard worden als er voor dat qid geen rij met datum is).
    Vervangt de SPARQL-side FILTER NOT EXISTS die te traag was.
    """
    if df.empty or 'qid' not in df.columns:
        return df
    df = df.copy()
    # Lege datums sorteren we als '' wat lexicografisch voor alle echte datums
    # komt, dus met ascending=False komt een echte datum altijd eerst.
    df['_sort_date'] = df['date'].fillna('').astype(str)
    df = df.sort_values(['qid', '_sort_date'], ascending=[True, False])
    df = df.drop_duplicates(subset='qid', keep='first')
    df = df.drop(columns='_sort_date').reset_index(drop=True)
    return df


def data_leeftijd_jaren(peildatum_str):
    """
    Aantal jaren tussen RUN_DATE en het jaar in peildatum_inwoners.
    Returnt None als peildatum leeg of onparseerbaar is. Hoog getal = oude
    statistiek - bijvoorbeeld een gemeente die sindsdien is gefuseerd, of
    een bron die niet meer geactualiseerd wordt.
    """
    if not peildatum_str:
        return None
    try:
        year = int(str(peildatum_str)[:4])
    except (ValueError, TypeError):
        return None
    current_year = int(RUN_DATE[:4])
    return current_year - year


def parse_population(value):
    """
    Parsed een populatie-waarde naar int. Wikidata kan waardes teruggeven als
    pure integer ('7225'), float ('7225.0'), scientific notation ('7.225e3'),
    of soms zelfs een rare decimal ('7.225' - waarschijnlijk een data-fout).
    We doen onze best en geven None terug als het echt niet lukt.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        # Probeer eerst direct als integer
        return int(s)
    except ValueError:
        pass
    try:
        # Anders via float (vangt '7225.0', '7.225e3' en '7.225' af)
        return int(round(float(s)))
    except (ValueError, OverflowError):
        return None


def parse_sparql_to_dataframe(bindings):
    """Wikidata SPARQL JSON-bindings -> DataFrame."""
    rows = []
    for b in bindings:
        rows.append({
            'name':       b.get('itemLabel', {}).get('value', ''),
            'population': parse_population(b['population']['value']) if 'population' in b else None,
            'date':       b.get('date', {}).get('value', '')[:10] if 'date' in b else '',
            'qid':        b.get('item', {}).get('value', '').rsplit('/', 1)[-1],
        })
    return pd.DataFrame(rows)


# ============================================================================
# FETCH + CACHE
# ============================================================================

def cache_path(name):
    return REFERENCE_DIR / f'{name}.csv'


def is_cache_fresh(path, max_age_days=CACHE_MAX_AGE_DAYS):
    if not path.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age < timedelta(days=max_age_days)


def fetch_reference_data(source, user_agent, refresh=False, offline=False,
                          step_info=''):
    """
    Haalt één referentielijst op (uit cache of via Wikidata).
    step_info: optionele string zoals '(3/11)' voor voortgangsindicatie.
    """
    path = cache_path(source['name'])
    prefix = f'{step_info} ' if step_info else ''

    if offline:
        if not path.exists():
            raise FileNotFoundError(f"Offline-modus maar cache ontbreekt: {path}")
        log.info(f"  {prefix}[offline] {source['name']} <- cache {path}")
        return pd.read_csv(path)

    if not refresh and is_cache_fresh(path):
        log.info(f"  {prefix}{source['name']} <- cache {path} (vers)")
        return pd.read_csv(path)

    log.info(f"  {prefix}{source['name']} <- Wikidata SPARQL (kan 30-90 sec duren)...")
    query = _sparql_population_template(source['qid'])
    start = time.time()
    # Heartbeat zorgt voor 'nog bezig'-updates tijdens lange queries
    with heartbeat(f"{source['name']} downloaden"):
        bindings = sparql_query(query, user_agent)
    df = parse_sparql_to_dataframe(bindings)
    # SPARQL geeft alle population-statements terug (snelle query); we dedupliceren
    # naar de meest recente peildatum per item in Python.
    n_before = len(df)
    df = deduplicate_keep_latest(df)
    duration = int(time.time() - start)
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    log.info(f"  {prefix}{source['name']} klaar in {duration}s: {len(df)} unieke records (uit {n_before} statements), gecachet")
    return df


def fetch_caribbean(user_agent, refresh=False, offline=False, step_info=''):
    path = cache_path('caribbean_countries')
    prefix = f'{step_info} ' if step_info else ''
    if offline:
        if not path.exists():
            raise FileNotFoundError(f"Offline-modus maar cache ontbreekt: {path}")
        log.info(f"  {prefix}[offline] caribbean_countries <- cache {path}")
        return pd.read_csv(path)
    if not refresh and is_cache_fresh(path):
        log.info(f"  {prefix}caribbean_countries <- cache (vers)")
        return pd.read_csv(path)
    log.info(f"  {prefix}caribbean_countries <- Wikidata SPARQL (kan 30-90 sec duren)...")
    start = time.time()
    with heartbeat("caribbean_countries downloaden"):
        bindings = sparql_query(SPARQL_CARIBBEAN, user_agent)
    df = parse_sparql_to_dataframe(bindings)
    n_before = len(df)
    df = deduplicate_keep_latest(df)
    duration = int(time.time() - start)
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    log.info(f"  {prefix}caribbean_countries klaar in {duration}s: {len(df)} unieke records (uit {n_before} statements), gecachet")
    return df


def fetch_all_reference_data(user_agent, refresh=False, offline=False):
    total = len(REFERENCE_SOURCES) + 1   # +1 voor caribbean
    log.info(f"=== Referentiedata laden ({total} bronnen) ===")
    log.info(f"  (Bij eerste run worden alle bronnen gedownload, dit kan 5-10 min duren)")
    overall_start = time.time()
    out = {}
    for i, source in enumerate(REFERENCE_SOURCES, start=1):
        step = f'[{i}/{total}]'
        out[source['name']] = fetch_reference_data(
            source, user_agent, refresh, offline, step_info=step
        )
    step = f'[{total}/{total}]'
    out['caribbean_countries'] = fetch_caribbean(
        user_agent, refresh, offline, step_info=step
    )
    total_duration = int(time.time() - overall_start)
    log.info(f"=== Referentiedata klaar (totaal {total_duration}s) ===\n")
    return out


# ============================================================================
# NAAM-NORMALISATIE EN MATCHING
# ============================================================================

def normalize(s):
    """Lowercase, diakrieten weg, punctuatie weg, leading 'de'/'het' weg."""
    if not isinstance(s, str):
        return ''
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^\w\s]", ' ', s)
    s = re.sub(r"^(de|het|der|die|das|le|la)\s+", '', s)
    s = re.sub(r"\s+", ' ', s).strip()
    return s


def fuzzy_match(query_name, candidates_df):
    """
    Fuzzy match query tegen candidates_df['name']. Gebruikt fuzz.ratio (Levenshtein-based),
    wat strenger is dan WRatio en false positives als 'Alken'->'Halen' voorkomt.
    Returnt (best_row_dict, score) of (None, score < LOW_THRESHOLD).
    """
    if not isinstance(query_name, str) or not query_name.strip():
        return None, 0
    if candidates_df is None or len(candidates_df) == 0:
        return None, 0

    norm_query = normalize(query_name)
    norm_names = candidates_df['name'].fillna('').map(normalize).tolist()
    if not norm_query or not norm_names:
        return None, 0

    # Exact match (op normalized) eerst
    for i, n in enumerate(norm_names):
        if n == norm_query:
            return candidates_df.iloc[i].to_dict(), 100

    # Anders: fuzz.ratio. Geen partial/WRatio -> minder false positives.
    result = process.extractOne(norm_query, norm_names, scorer=fuzz.ratio)
    if result is None:
        return None, 0
    matched_norm, score, idx = result
    if score < FUZZY_LOW_THRESHOLD:
        return None, score
    return candidates_df.iloc[idx].to_dict(), score


# ============================================================================
# ENRICHMENT-LOGICA
# ============================================================================

# Types die expliciet geen inwonertal krijgen
NO_POPULATION_TYPES = {
    'commercieel_of_overig', 'ministerie', 'rijksoverheid', 'stadtwerke',
    'intercommunale', 'caw', 'zweckverband', 'fod_be',
}

# Aggregatie-types die we nog NIET ondersteunen in v1
UNSUPPORTED_AGGREGATION = {
    'samenwerking_nl', 'belastingsamenwerking', 'hulpverleningszone',
    'ggd', 'stadsregio', 'amt', 'verwaltungsgemeinschaft',
}

# Mapping detected_type -> naam van de referentielijst voor 1-op-1 match.
# Niet in deze tabel:
#   'waterschap'   -> aparte aggregatie via NL_WATERSCHAP_GEMEENTEN
#   'stadsdeel'    -> directe lookup in NL_STADSDEEL_INWONERS
#   'deelgemeente' -> directe lookup in NL_STADSDEEL_INWONERS (Amsterdam
#                     stadsdelen heetten formeel "deelgemeente" tot 2010;
#                     Rotterdamse deelgemeenten zijn in 2014 afgeschaft)
#   'politiezone'  -> aparte aggregatie via BE_POLITIEZONE_GEMEENTEN
TYPE_TO_REFERENCE = {
    'gemeente_nl':       'nl_gemeenten',
    'gemeente_be':       'be_gemeenten',
    'ocmw':              'be_gemeenten',    # OCMW X -> match op gemeente X
    'agb':               'be_gemeenten',    # AGB X  -> match op gemeente X
    'gemeinde_de':       'de_gemeinden',
    'provincie_nl':      'nl_provincies',
    'provincie_be':      'be_provincies',
    'landkreis':         'de_landkreise',
    'landratsamt':       'de_landkreise',   # Landratsamt X -> match op Landkreis X
    'verbandsgemeinde':  'de_verbandsgemeinden',
    'land':              'caribbean_countries',
}


def name_is_marked_obsolete(name):
    """Records met markers als 'niet gebruiken' worden geskipt."""
    if not isinstance(name, str):
        return False
    low = name.lower()
    return any(m in low for m in SKIP_NAME_MARKERS)


def aggregate_sum(member_gemeenten, ref_gemeenten_nl):
    """
    Telt inwonertallen op voor een lijst NL gemeentenamen.
    Returnt (totaal, peildatum_jaar, n_matched, missing_lijst, opmerking).
    """
    if not member_gemeenten:
        return None, None, 0, [], 'lege ledenlijst'

    pops, dates, missing = [], [], []
    for gname in member_gemeenten:
        row, score = fuzzy_match(gname, ref_gemeenten_nl)
        if row is None or score < FUZZY_HIGH_THRESHOLD:
            missing.append(gname)
            continue
        if pd.notna(row.get('population')):
            pops.append(int(row['population']))
            if row.get('date'):
                dates.append(row['date'])

    if not pops:
        return None, None, 0, missing, f'geen van {len(member_gemeenten)} gemeenten gevonden in referentielijst'

    total = sum(pops)
    years = [d[:4] for d in dates if d]
    peildatum = max(set(years), key=years.count) if years else None
    note = f'som van {len(pops)} van {len(member_gemeenten)} gemeenten'
    if missing:
        note += f' (niet gevonden: {", ".join(missing[:5])}{"..." if len(missing) > 5 else ""})'
    return total, peildatum, len(pops), missing, note


def enrich_record(row, ref_data, gemeenten_nl):
    """Bepaalt voor één record cx_population + metadata. Returnt dict."""
    etype = row['detected_type']
    canon = row.get('canonical_name') or ''
    raw_name = row.get('name') or ''

    result = {
        'cx_population_new': None,
        'peildatum_inwoners': None,
        'bron': None,
        'proces': 'geen lookup voor dit type',
        'match_score': None,
    }

    # Marker-records skippen
    if name_is_marked_obsolete(raw_name):
        result['proces'] = 'naam bevat "niet gebruiken"-marker, geen lookup uitgevoerd'
        return result

    if etype in NO_POPULATION_TYPES:
        result['proces'] = f'type {etype} heeft geen inwonertal'
        return result

    if etype == 'onbekend':
        result['proces'] = 'type onbekend, geen lookup mogelijk'
        return result

    # Aggregatie: veiligheidsregio
    if etype == 'veiligheidsregio':
        members, used_key = _resolve_mapping(canon, NL_VEILIGHEIDSREGIO_GEMEENTEN)
        if not members:
            result['proces'] = f'veiligheidsregio "{canon}" niet in mapping-tabel'
            return result
        total, peildatum, n, _missing, note = aggregate_sum(members, gemeenten_nl)
        if total:
            result.update({
                'cx_population_new':  total,
                'peildatum_inwoners': peildatum,
                'bron':               f'aggregatie NL gemeenten (Wikidata) voor veiligheidsregio {used_key}',
                'proces':             note,
            })
        else:
            result['proces'] = note
        return result

    # Aggregatie: omgevingsdienst
    if etype == 'omgevingsdienst':
        members, used_key = _resolve_mapping(canon, NL_OMGEVINGSDIENST_GEMEENTEN)
        if not members:
            result['proces'] = f'omgevingsdienst "{canon}" niet in mapping-tabel'
            return result
        total, peildatum, n, _missing, note = aggregate_sum(members, gemeenten_nl)
        if total:
            result.update({
                'cx_population_new':  total,
                'peildatum_inwoners': peildatum,
                'bron':               f'aggregatie NL gemeenten (Wikidata) voor omgevingsdienst {used_key}',
                'proces':             note,
            })
        else:
            result['proces'] = note
        return result

    # Directe waarde-lookup: Amsterdam stadsdelen + deelgemeenten
    # (Wikidata heeft geen P1082 voor deze entiteiten)
    if etype in ('stadsdeel', 'deelgemeente'):
        matched, used_key = _resolve_mapping(canon, NL_STADSDEEL_INWONERS)
        if matched is None:
            result['proces'] = (
                f'{etype} "{canon}" niet in NL_STADSDEEL_INWONERS-tabel '
                f'(alleen Amsterdam stadsdelen worden ondersteund)'
            )
            return result
        result.update({
            'cx_population_new':  matched['population'],
            'peildatum_inwoners': matched['peildatum'],
            'bron':               f"NL_STADSDEEL_INWONERS ({matched['bron_url']})",
            'proces':             f'directe waarde uit stadsdeel-tabel voor "{used_key}"',
        })
        return result

    # Aggregatie: waterschap (Wikidata heeft geen P1082 voor waterschappen)
    if etype == 'waterschap':
        members, used_key = _resolve_mapping(canon, NL_WATERSCHAP_GEMEENTEN)
        if used_key is None:
            result['proces'] = f'waterschap "{canon}" niet in NL_WATERSCHAP_GEMEENTEN-tabel'
            return result
        if not members:
            result['proces'] = f'waterschap "{used_key}": ledenlijst nog niet ingevuld in NL_WATERSCHAP_GEMEENTEN'
            return result
        total, peildatum, n, _missing, note = aggregate_sum(members, gemeenten_nl)
        if total:
            result.update({
                'cx_population_new':  total,
                'peildatum_inwoners': peildatum,
                'bron':               f'aggregatie NL gemeenten (Wikidata) voor waterschap {used_key}',
                'proces':             note,
            })
        else:
            result['proces'] = note
        return result

    # Aggregatie: BE politiezone (Wikidata heeft geen P1082 voor politiezones)
    if etype == 'politiezone':
        gemeenten_be = ref_data.get('be_gemeenten')
        members, used_key = _resolve_mapping(canon, BE_POLITIEZONE_GEMEENTEN)
        if used_key is None:
            result['proces'] = f'politiezone "{canon}" niet in BE_POLITIEZONE_GEMEENTEN-tabel'
            return result
        if not members:
            result['proces'] = f'politiezone "{used_key}": ledenlijst leeg'
            return result
        total, peildatum, n, _missing, note = aggregate_sum(members, gemeenten_be)
        if total:
            result.update({
                'cx_population_new':  total,
                'peildatum_inwoners': peildatum,
                'bron':               f'aggregatie BE gemeenten (Wikidata) voor politiezone {used_key}',
                'proces':             note,
            })
        else:
            result['proces'] = note
        return result

    if etype in UNSUPPORTED_AGGREGATION:
        result['proces'] = f'aggregatie voor {etype} vereist mapping-tabel (volgt in v2)'
        return result

    # 1-op-1 directe match
    ref_name = TYPE_TO_REFERENCE.get(etype)
    if ref_name is None:
        result['proces'] = f'geen referentielijst voor type {etype}'
        return result

    ref_df = ref_data.get(ref_name)
    if ref_df is None or len(ref_df) == 0:
        result['proces'] = f'referentielijst {ref_name} is leeg'
        return result

    matched, score = fuzzy_match(canon, ref_df)
    if matched is None:
        result['proces'] = f'geen match voor "{canon}" in {ref_name} (beste score onder {FUZZY_LOW_THRESHOLD})'
        return result

    pop = matched.get('population')
    if pd.isna(pop) or pop is None:
        result['proces'] = f'match "{matched["name"]}" gevonden maar referentielijst heeft geen populatie'
        return result

    qid = matched.get('qid', '')
    peildatum = matched.get('date', '')
    if isinstance(peildatum, str) and peildatum:
        peildatum = peildatum[:4]

    # Type-specifieke proces-tekst
    proces = f'directe match op "{matched["name"]}" (score {int(score)})'
    if etype == 'ocmw':
        proces = f'OCMW gekoppeld aan gemeente "{matched["name"]}" (score {int(score)})'
    elif etype == 'agb':
        proces = f'AGB gekoppeld aan gemeente "{matched["name"]}" (score {int(score)})'
    elif etype == 'landratsamt':
        proces = f'Landratsamt gekoppeld aan Landkreis "{matched["name"]}" (score {int(score)})'
    elif etype == 'land':
        proces = f'Caribische overheid gekoppeld aan totaal-inwonertal van {matched["name"]} (score {int(score)})'

    result.update({
        'cx_population_new':  int(pop),
        'peildatum_inwoners': peildatum if peildatum else None,
        'bron':               f'Wikidata {qid} ({ref_name})',
        'proces':             proces,
        'match_score':        int(score),
    })
    return result


def _resolve_mapping(canon, mapping):
    """
    Probeert canonical_name eerst direct in mapping te vinden, dan fuzzy.
    Returnt (members_list_or_None, used_key_or_None).
    """
    if canon in mapping:
        return mapping[canon], canon
    keys = list(mapping.keys())
    norm_canon = normalize(canon)
    best = process.extractOne(norm_canon, [normalize(k) for k in keys], scorer=fuzz.ratio)
    if best and best[1] >= FUZZY_HIGH_THRESHOLD:
        used_key = keys[best[2]]
        return mapping[used_key], used_key
    return None, None


# ============================================================================
# OVERRIDES
# ============================================================================

def load_overrides(path):
    """Override-Excel/CSV met kolommen: account_id, population_override, reden."""
    if not path or not Path(path).exists():
        return {}
    df = pd.read_excel(path) if str(path).endswith('.xlsx') else pd.read_csv(path)
    df.columns = [c.lower().strip() for c in df.columns]
    if 'account_id' not in df.columns or 'population_override' not in df.columns:
        log.warning(f"Override-bestand {path}: verwachte kolommen ontbreken. Overslaan.")
        return {}
    out = {}
    for _, r in df.iterrows():
        out[r['account_id']] = (
            r['population_override'] if pd.notna(r['population_override']) else None,
            r.get('reden', '') if pd.notna(r.get('reden', '')) else '',
        )
    log.info(f"Overrides geladen: {len(out)} records")
    return out


# ============================================================================
# MAIN ENRICHMENT-LOOP
# ============================================================================

def enrich_dataframe(df, ref_data, overrides):
    """Loop door df, voeg metadata-kolommen toe per record."""
    gemeenten_nl = ref_data.get('nl_gemeenten')
    out_records = []
    n_total = len(df)
    log_every = max(1, n_total // 20)

    for i, row in df.iterrows():
        rec = row.to_dict()
        old_pop = rec.get('cx_population')
        rec['previous_population'] = old_pop
        account_id = rec.get('accountid')

        # 1. Override heeft hoogste prioriteit
        if account_id in overrides:
            override_val, reden = overrides[account_id]
            rec['cx_population'] = override_val
            rec['peildatum_inwoners'] = None
            rec['bron'] = 'override-tabel'
            rec['proces'] = f'override: {reden}' if reden else 'override'
            rec['match_score'] = None
            rec['invuldatum'] = RUN_DATE
            rec['data_leeftijd_jaren'] = None
            out_records.append(rec)
            continue

        # 2. Normale enrichment
        result = enrich_record(rec, ref_data, gemeenten_nl)
        new_pop = result['cx_population_new']

        if new_pop is None:
            # Geen match -> behoud oude waarde (regel "oude data behouden")
            if pd.notna(old_pop):
                rec['cx_population'] = old_pop
                rec['proces'] = f'behouden uit vorige run ({result["proces"]})'
                rec['bron'] = 'eerdere CRM-waarde'
                rec['peildatum_inwoners'] = None
            else:
                rec['cx_population'] = None
                rec['proces'] = result['proces']
                rec['bron'] = None
                rec['peildatum_inwoners'] = None
        else:
            rec['cx_population'] = new_pop
            rec['proces'] = result['proces']
            rec['bron'] = result['bron']
            rec['peildatum_inwoners'] = result['peildatum_inwoners']

        rec['match_score'] = result['match_score']
        rec['invuldatum'] = RUN_DATE
        rec['data_leeftijd_jaren'] = data_leeftijd_jaren(rec['peildatum_inwoners'])
        out_records.append(rec)

        if (i + 1) % log_every == 0:
            log.info(f"  {i+1}/{n_total} verwerkt")

    return pd.DataFrame(out_records)


# ============================================================================
# OUTPUT
# ============================================================================

def write_output(df, output_path):
    """Schrijft accounts-tab + draaitabel-tab + run-log-tab."""
    log.info(f"\n=== Output schrijven naar {output_path} ===")

    # Order: metadata-kolommen achteraan.
    # data_leeftijd_jaren = aantal jaren tussen run-datum en peildatum_inwoners.
    # Hoog getal (~5+) signaleert mogelijk historische gemeente of verouderde bron.
    meta_cols = ['previous_population', 'peildatum_inwoners', 'data_leeftijd_jaren',
                 'bron', 'proces', 'match_score', 'invuldatum']
    primary_cols = [c for c in df.columns if c not in meta_cols]
    df = df[primary_cols + [c for c in meta_cols if c in df.columns]]

    # Draaitabel: aantal records en totaal inwoners per type x land.
    # Twee aparte pivots zijn cleaner in Excel dan multi-level columns.
    pivot_count = pd.pivot_table(
        df, index='detected_type', columns='detected_country',
        values='cx_population', aggfunc='count', fill_value=0,
    )
    pivot_count['TOTAAL'] = pivot_count.sum(axis=1)
    pivot_count.loc['TOTAAL'] = pivot_count.sum()

    pivot_sum = pd.pivot_table(
        df, index='detected_type', columns='detected_country',
        values='cx_population', aggfunc='sum', fill_value=0,
    )
    pivot_sum['TOTAAL'] = pivot_sum.sum(axis=1)
    pivot_sum.loc['TOTAAL'] = pivot_sum.sum()

    # Run-log
    log_df = pd.DataFrame([
        {'metriek': 'run_datum',                'waarde': RUN_DATE},
        {'metriek': 'totaal_records',           'waarde': len(df)},
        {'metriek': 'met_nieuwe_population',    'waarde': int(df['bron'].notna().sum() - (df['bron'] == 'eerdere CRM-waarde').sum())},
        {'metriek': 'behouden_uit_eerdere_run', 'waarde': int((df['bron'] == 'eerdere CRM-waarde').sum())},
        {'metriek': 'overrides_toegepast',      'waarde': int((df['bron'] == 'override-tabel').sum())},
        {'metriek': 'leeg_gebleven',            'waarde': int(df['cx_population'].isna().sum())},
        {'metriek': 'unsupported_aggregatie',   'waarde': int(df['proces'].str.contains('vereist mapping-tabel', na=False).sum())},
    ])

    with pd.ExcelWriter(output_path, engine='openpyxl') as w:
        df.to_excel(w, sheet_name='accounts', index=False)
        pivot_count.to_excel(w, sheet_name='draaitabel_aantallen')
        pivot_sum.to_excel(w, sheet_name='draaitabel_inwoners')
        log_df.to_excel(w, sheet_name='run_log', index=False)

    log.info(f"  Geschreven: {len(df)} records, 4 tabs (accounts, draaitabel_aantallen, draaitabel_inwoners, run_log)")


# ============================================================================
# CLI
# ============================================================================

def parse_args():
    p = argparse.ArgumentParser(description='Verrijkt step1-output met inwoneraantallen via Wikidata.')
    p.add_argument('--input',         required=True, help='step1_classified.xlsx')
    p.add_argument('--output',        required=True, help='uitvoer-Excel pad')
    p.add_argument('--overrides',     default=None, help='Optioneel: override-Excel/CSV')
    p.add_argument('--test-mode',     action='store_true', help='Alleen eerste 100 records')
    p.add_argument('--refresh-cache', action='store_true', help='Forceer verse Wikidata-download')
    p.add_argument('--offline',       action='store_true', help='Gebruik alleen lokale cache')
    p.add_argument('--user-agent',    default=DEFAULT_USER_AGENT,
                   help='Custom User-Agent (Wikidata vraagt contactgegevens)')
    return p.parse_args()


def main():
    args = parse_args()

    if args.user_agent == DEFAULT_USER_AGENT and not args.offline:
        log.warning(
            "LET OP: default User-Agent. Wikidata vraagt contactgegevens. "
            "Gebruik --user-agent 'jouw-org/1.0 (jouwemail@bedrijf.nl)'."
        )

    log.info(f"Input: {args.input}")
    df = pd.read_excel(args.input)
    log.info(f"Ingelezen: {len(df)} records")

    if args.test_mode:
        df = df.head(100)
        log.info(f"Test-modus: ingekort tot {len(df)} records")

    ref_data = fetch_all_reference_data(
        user_agent=args.user_agent,
        refresh=args.refresh_cache,
        offline=args.offline,
    )
    overrides = load_overrides(args.overrides) if args.overrides else {}

    log.info("\n=== Enrichment starten ===")
    enriched = enrich_dataframe(df, ref_data, overrides)
    write_output(enriched, args.output)

    log.info("\n=== Samenvatting ===")
    new_count = int(enriched['bron'].notna().sum() - (enriched['bron'] == 'eerdere CRM-waarde').sum())
    log.info(f"  Totaal:                  {len(enriched)}")
    log.info(f"  Nieuwe waarde gevonden:  {new_count}")
    log.info(f"  Behouden uit eerdere run:{(enriched['bron'] == 'eerdere CRM-waarde').sum()}")
    log.info(f"  Overrides toegepast:     {(enriched['bron'] == 'override-tabel').sum()}")
    log.info(f"  Leeg gebleven:           {enriched['cx_population'].isna().sum()}")


if __name__ == '__main__':
    main()
