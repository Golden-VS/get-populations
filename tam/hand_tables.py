"""Handtabellen voor de TAM/whitespace-lijstbouwer (NL en BE; Caribisch deel en Suriname:
tam/hand_tables_carib.py).

Vorm zoals step2_enrich.NL_WATERSCHAP_INWONERS: sleutel = naam, waarde = dict met
'population', 'peildatum' en 'bron_url', plus een vaste 'id' (nooit afgeleid van de naam
tijdens een run). Optioneel 'aliases' (andere officiele namen) en 'members' (gemeentenamen).
Een bevolking die niet uit een officiele bron te halen was staat op None.
Alle bronnen geraadpleegd op 2026-10-27.
"""

STATBEL_POP_URL = ('https://statbel.fgov.be/nl/open-data/'
                   'bevolking-naar-woonplaats-nationaliteit-burgerlijke-staat-leeftijd-en-geslacht-14')
BELGIUM_FOD_URL = ('https://www.belgium.be/nl/over_belgie/overheid/federale_overheid/'
                   'federale_en_programmatorische_overheidsdiensten')
BXL_INTERCO_URL = ('https://be.brussels/fr/propos-de-la-region/structure-et-organisation/'
                   'institutions-et-commissions-communautaires/les-intercommunales-bruxelloises')
ZONES_PDF_URL = ('https://civieleveiligheid.be/sites/default/files/explorer/partie_s_incendie/'
                 'coordonnees-zones-nl-fr_05_2026.pdf')

# ---------------------------------------------------------------------------
# Nederland
# ---------------------------------------------------------------------------
# Openbare lichamen Bonaire/Sint Eustatius/Saba en de landen Aruba/Curacao/Sint Maarten staan
# sinds spec sectie 15 in tam/hand_tables_carib.py (eigen landen AW/CW/SX/BQ).

# Vaste ids en weergavenamen voor de Amsterdamse stadsdelen uit
# step2_enrich.NL_STADSDEEL_INWONERS, gesleuteld op bron_url (die tabel is per stadsdeel
# ontdubbeld op bron_url). Bevolking en peildatum komen uit die tabel. Aliassen alleen in de
# vorm 'Stadsdeel X': kale namen als 'Centrum' of 'Noord' zijn te algemeen om te matchen.
NL_STADSDEEL_IDS = {
    'https://nl.wikipedia.org/wiki/Amsterdam-Centrum': {'id': 'NL-HAND-AMSTERDAM-CENTRUM', 'name': 'Amsterdam-Centrum', 'aliases': ['Stadsdeel Centrum'],
        'population': None, 'peildatum': '', 'bron_url': 'https://nl.wikipedia.org/wiki/Amsterdam-Centrum'},
    'https://nl.wikipedia.org/wiki/Amsterdam-Noord': {'id': 'NL-HAND-AMSTERDAM-NOORD', 'name': 'Amsterdam-Noord', 'aliases': ['Stadsdeel Noord'],
        'population': None, 'peildatum': '', 'bron_url': 'https://nl.wikipedia.org/wiki/Amsterdam-Noord'},
    'https://nl.wikipedia.org/wiki/Amsterdam-Oost': {'id': 'NL-HAND-AMSTERDAM-OOST', 'name': 'Amsterdam-Oost', 'aliases': ['Stadsdeel Oost'],
        'population': None, 'peildatum': '', 'bron_url': 'https://nl.wikipedia.org/wiki/Amsterdam-Oost'},
    'https://nl.wikipedia.org/wiki/Amsterdam-Zuid': {'id': 'NL-HAND-AMSTERDAM-ZUID', 'name': 'Amsterdam-Zuid', 'aliases': ['Stadsdeel Zuid'],
        'population': None, 'peildatum': '', 'bron_url': 'https://nl.wikipedia.org/wiki/Amsterdam-Zuid'},
    'https://nl.wikipedia.org/wiki/Amsterdam-Zuidoost': {'id': 'NL-HAND-AMSTERDAM-ZUIDOOST',
        'name': 'Amsterdam-Zuidoost', 'aliases': ['Stadsdeel Zuidoost'], 'population': None, 'peildatum': '',
        'bron_url': 'https://nl.wikipedia.org/wiki/Amsterdam-Zuidoost'},
    'https://nl.wikipedia.org/wiki/Amsterdam-West': {'id': 'NL-HAND-AMSTERDAM-WEST', 'name': 'Amsterdam-West', 'aliases': ['Stadsdeel West'],
        'population': None, 'peildatum': '', 'bron_url': 'https://nl.wikipedia.org/wiki/Amsterdam-West'},
    'https://nl.wikipedia.org/wiki/Amsterdam-Nieuw-West': {'id': 'NL-HAND-AMSTERDAM-NIEUW-WEST',
        'name': 'Amsterdam-Nieuw-West', 'aliases': ['Stadsdeel Nieuw-West'], 'population': None, 'peildatum': '',
        'bron_url': 'https://nl.wikipedia.org/wiki/Amsterdam-Nieuw-West'},
    # Weesp is sinds 2022 een stadsgebied van Amsterdam; geen alias 'Weesp' (dat is de
    # opgeheven gemeente, die als voorganger naar Amsterdam verwijst).
    'https://nl.wikipedia.org/wiki/Weesp': {'id': 'NL-HAND-AMSTERDAM-WEESP', 'name': 'Stadsgebied Weesp',
        'population': None, 'peildatum': '', 'bron_url': 'https://nl.wikipedia.org/wiki/Weesp'},
}

# ---------------------------------------------------------------------------
# Belgie
# ---------------------------------------------------------------------------
# Statbel TF_SOC_POP_STRUCT_2026 (bevolking op 1 januari 2026), gesommeerd per gewest
# (CD_RGN_REFNIS 02000 / 03000 / 04000). Vlaamse Gemeenschap = instelling van het Vlaams
# Gewest (een rij). Duitstalige Gemeenschap = som van de 9 gemeenten van het Duitse
# taalgebied (Grondwet art. 4 en 130: Amel, Büllingen, Burg-Reuland, Bütgenbach, Eupen,
# Kelmis, Lontzen, Raeren, Sankt Vith) in hetzelfde Statbel-bestand.
# Federatie Wallonie-Brussel: geen officieel bevolkingscijfer (bevoegd voor Franstaligen in
# Wallonie en Brussel; voor Brussel niet territoriaal af te bakenen), dus leeg.
BE_GEWESTEN = {
    'Vlaams Gewest': {'id': 'BE-HAND-GEWEST-VLAANDEREN', 'population': 6898350, 'peildatum': '2026-01-01',
                      'bron_url': STATBEL_POP_URL,
                      'aliases': ['Vlaamse Gemeenschap', 'Vlaamse overheid', 'Région flamande']},
    'Waals Gewest': {'id': 'BE-HAND-GEWEST-WALLONIE', 'population': 3713450, 'peildatum': '2026-01-01',
                     'bron_url': STATBEL_POP_URL, 'aliases': ['Région wallonne', 'Wallonie']},
    'Brussels Hoofdstedelijk Gewest': {'id': 'BE-HAND-GEWEST-BRUSSEL', 'population': 1255834,
                                       'peildatum': '2026-01-01', 'bron_url': STATBEL_POP_URL,
                                       'aliases': ['Région de Bruxelles-Capitale']},
    'Duitstalige Gemeenschap': {'id': 'BE-HAND-GEMEENSCHAP-DG', 'population': 79515, 'peildatum': '2026-01-01',
                                'bron_url': STATBEL_POP_URL,
                                'aliases': ['Deutschsprachige Gemeinschaft', 'Communauté germanophone',
                                            'Ostbelgien']},
    'Federatie Wallonië-Brussel': {'id': 'BE-HAND-GEMEENSCHAP-FWB', 'population': None, 'peildatum': '',
                                   'bron_url': 'https://www.federation-wallonie-bruxelles.be/',
                                   'aliases': ['Fédération Wallonie-Bruxelles', 'Franse Gemeenschap',
                                               'Communauté française']},
}

# Federale en programmatorische overheidsdiensten zoals vermeld op belgium.be
# (11 FOD's, Ministerie van Defensie, 2 POD's). Bevolking = landtotaal (master).
BE_FOD = {
    'FOD Kanselarij van de Eerste Minister': {'id': 'BE-HAND-FOD-KANSELARIJ'},
    'FOD Beleid en Ondersteuning': {'id': 'BE-HAND-FOD-BOSA', 'aliases': ['BOSA']},
    'FOD Buitenlandse Zaken, Buitenlandse Handel en Ontwikkelingssamenwerking': {'id': 'BE-HAND-FOD-BUZA'},
    'FOD Binnenlandse Zaken': {'id': 'BE-HAND-FOD-BINNENLANDSE-ZAKEN'},
    'FOD Financiën': {'id': 'BE-HAND-FOD-FINANCIEN'},
    'FOD Mobiliteit en Vervoer': {'id': 'BE-HAND-FOD-MOBILITEIT'},
    'FOD Werkgelegenheid, Arbeid en Sociaal Overleg': {'id': 'BE-HAND-FOD-WASO'},
    'FOD Sociale Zekerheid': {'id': 'BE-HAND-FOD-SOCIALE-ZEKERHEID'},
    'FOD Volksgezondheid, Veiligheid van de Voedselketen en Leefmilieu': {'id': 'BE-HAND-FOD-VOLKSGEZONDHEID'},
    'FOD Justitie': {'id': 'BE-HAND-FOD-JUSTITIE'},
    'FOD Economie, KMO, Middenstand en Energie': {'id': 'BE-HAND-FOD-ECONOMIE'},
    'Ministerie van Defensie': {'id': 'BE-HAND-DEFENSIE', 'aliases': ['Defensie']},
    'POD Maatschappelijke Integratie, Armoedebestrijding, Sociale Economie en Grootstedenbeleid':
        {'id': 'BE-HAND-POD-MI'},
    'POD Wetenschapsbeleid': {'id': 'BE-HAND-POD-BELSPO', 'aliases': ['BELSPO']},
}
for _row in BE_FOD.values():
    _row.update({'population': None, 'peildatum': '2026-10-27', 'bron_url': BELGIUM_FOD_URL})

# Hulpverleningszones in Wallonie (14) en Brussel (1), leden overgenomen uit de zonelijst
# van civieleveiligheid.be ('Update 01/10/2026'). De Vlaamse zones (20) komen uit de OP-dump.
# Gemeentenamen zoals in de PDF (Frans; Brussel in het Nederlands), met deze correcties van
# kennelijke tikfouten naar de officiele Statbel-naam: Tenneviller -> Tenneville,
# Chapelle-lez-Harlaimont -> Chapelle-lez-Herlaimont, Pépinster -> Pepinster,
# Vresse -> Vresse-sur-Semois.
_Z = {'population': None, 'peildatum': '2026-10-01', 'bron_url': ZONES_PDF_URL}
BE_HULPVERLENINGSZONES_WB = {
    'Zone de secours du Brabant wallon': {**_Z, 'id': 'BE-HAND-HVZ-BRABANT-WALLON', 'members': [
        'Beauvechain', "Braine-l'Alleud", 'Braine-le-Château', 'Chastre', 'Chaumont-Gistoux',
        'Court-Saint-Etienne', 'Genappe', 'Grez-Doiceau', 'Hélécine', 'Incourt', 'Ittre', 'Jodoigne',
        'Lasne', 'La Hulpe', 'Mont-Saint-Guibert', 'Nivelles', 'Orp-Jauche', 'Ottignies-Louvain-la-Neuve',
        'Perwez', 'Ramillies', 'Rebecq', 'Rixensart', 'Tubize', 'Villers-la-Ville', 'Walhain',
        'Waterloo', 'Wavre']},
    'Zone de secours Wallonie Picarde': {**_Z, 'id': 'BE-HAND-HVZ-WALLONIE-PICARDE', 'members': [
        'Antoing', 'Ath', 'Beloeil', 'Bernissart', 'Brunehaut', 'Celles', 'Comines-Warneton',
        'Ellezelles', 'Estaimpuis', 'Flobecq', 'Frasnes-lez-Anvaing', 'Lessines', 'Leuze-en-Hainaut',
        "Mont-de-l'Enclus", 'Mouscron', 'Pecq', 'Péruwelz', 'Rumes', 'Tournai']},
    'Zone de secours Hainaut-Est': {**_Z, 'id': 'BE-HAND-HVZ-HAINAUT-EST', 'members': [
        'Aiseau-Presles', 'Anderlues', 'Beaumont', 'Charleroi', 'Châtelet', 'Chimay', 'Courcelles',
        'Erquelinnes', 'Farciennes', 'Fleurus', "Fontaine-l'Evêque", 'Froidchapelle', 'Gerpinnes',
        'Ham-sur-Heure-Nalinnes', 'Les Bons Villers', 'Lobbes', 'Merbes-le-Château', 'Momignies',
        'Montigny-le-Tilleul', 'Pont-à-Celles', 'Sivry-Rance', 'Thuin']},
    'Zone de secours Hainaut-Centre': {**_Z, 'id': 'BE-HAND-HVZ-HAINAUT-CENTRE', 'members': [
        'Binche', 'Boussu', 'Braine-le-Comte', 'Brugelette', 'Chapelle-lez-Herlaimont', 'Chièvres',
        'Colfontaine', 'Dour', 'Ecaussinnes', 'Enghien', 'Estinnes', 'Frameries', 'Hensies', 'Honnelles',
        'Jurbise', 'La Louvière', 'Lens', 'Le Roeulx', 'Manage', 'Mons', 'Morlanwelz', 'Quaregnon',
        'Quévy', 'Quiévrain', 'Seneffe', 'Silly', 'Soignies', 'Saint-Ghislain']},
    'Zone de secours Hesbaye': {**_Z, 'id': 'BE-HAND-HVZ-HESBAYE', 'members': [
        'Berloz', 'Braives', 'Burdinne', 'Donceel', 'Faimes', 'Geer', 'Hannut', 'Lincent', 'Oreye',
        'Remicourt', 'Verlaine', 'Waremme', 'Wasseiges']},
    'Liège Zone 2 IILE-SRI': {**_Z, 'id': 'BE-HAND-HVZ-LIEGE-ZONE-2', 'members': [
        'Ans', 'Awans', 'Bassenge', 'Beyne-Heusay', 'Chaudfontaine', 'Crisnée', 'Engis', 'Esneux',
        'Fexhe-le-Haut-Clocher', 'Flémalle', 'Fléron', 'Grâce-Hollogne', 'Herstal', 'Juprelle', 'Liège',
        'Neupré', 'Oupeye', 'Saint-Georges-sur-Meuse', 'Saint-Nicolas', 'Seraing', 'Visé']},
    'Zone de secours Hemeco': {**_Z, 'id': 'BE-HAND-HVZ-HEMECO', 'members': [
        'Amay', 'Anthisnes', 'Clavier', 'Comblain-au-Pont', 'Ferrières', 'Hamoir', 'Héron', 'Huy',
        'Marchin', 'Modave', 'Nandrin', 'Ouffet', 'Tinlot', 'Villers-le-Bouillet', 'Wanze']},
    'Zone de secours Vesdre-Hoëgne & Plateau': {**_Z, 'id': 'BE-HAND-HVZ-VHP', 'members': [
        'Aubel', 'Baelen', 'Blegny', 'Dalhem', 'Dison', 'Herve', 'Jalhay', 'Limbourg', 'Olne', 'Pepinster',
        'Plombières', 'Soumagne', 'Spa', 'Sprimont', 'Theux', 'Thimister-Clermont', 'Trooz', 'Verviers',
        'Welkenraedt']},
    'Zone de secours 5 Warche Amblève Lienne': {**_Z, 'id': 'BE-HAND-HVZ-WAL', 'members': [
        'Aywaille', 'Lierneux', 'Malmedy', 'Stavelot', 'Stoumont', 'Trois-Ponts', 'Waimes']},
    'Zone de secours DG': {**_Z, 'id': 'BE-HAND-HVZ-DG', 'aliases': ['Hilfeleistungszone DG'], 'members': [
        'Amblève', 'Bullange', 'Burg-Reuland', 'Butgenbach', 'Eupen', 'La Calamine', 'Lontzen', 'Raeren',
        'Saint-Vith']},
    'Zone de secours Luxembourg': {**_Z, 'id': 'BE-HAND-HVZ-LUXEMBOURG', 'members': [
        'Arlon', 'Attert', 'Aubange', 'Bastogne', 'Bertrix', 'Bouillon', 'Chiny', 'Daverdisse', 'Durbuy',
        'Erezée', 'Etalle', 'Fauvillers', 'Florenville', 'Gouvy', 'Habay', 'Herbeumont', 'Hotton',
        'Houffalize', 'La Roche-en-Ardenne', 'Léglise', 'Libin', 'Libramont-Chevigny', 'Manhay',
        'Marche-en-Famenne', 'Martelange', 'Meix-devant-Virton', 'Messancy', 'Musson', 'Nassogne',
        'Neufchâteau', 'Paliseul', 'Rendeux', 'Rouvroy', 'Saint-Hubert', 'Saint-Léger', 'Sainte-Ode',
        'Tellin', 'Tenneville', 'Tintigny', 'Vaux-sur-Sûre', 'Vielsalm', 'Virton', 'Wellin']},
    'Zone de secours NAGE': {**_Z, 'id': 'BE-HAND-HVZ-NAGE', 'aliases': ['Nage'], 'members': [
        'Andenne', 'Assesse', 'Eghezée', 'Fernelmont', 'Gembloux', 'Gesves', 'La Bruyère', 'Namur', 'Ohey',
        'Profondeville']},
    'Zone de secours Dinaphi': {**_Z, 'id': 'BE-HAND-HVZ-DINAPHI', 'members': [
        'Anhée', 'Beauraing', 'Bièvre', 'Cerfontaine', 'Ciney', 'Couvin', 'Dinant', 'Doische', 'Florennes',
        'Gedinne', 'Hamois', 'Hastière', 'Havelange', 'Houyet', 'Onhaye', 'Philippeville', 'Rochefort',
        'Somme-Leuze', 'Viroinval', 'Vresse-sur-Semois', 'Walcourt', 'Yvoir']},
    'Zone de secours Val de Sambre': {**_Z, 'id': 'BE-HAND-HVZ-VAL-DE-SAMBRE', 'members': [
        'Floreffe', 'Fosses-la-Ville', 'Jemeppe-sur-Sambre', 'Mettet', 'Sambreville', 'Sombreffe']},
    'Brandweer Brussel (DBDMH/SIAMU)': {**_Z, 'id': 'BE-HAND-HVZ-BRUSSEL',
        'aliases': ['Brandweer Brussel', 'Pompiers de Bruxelles', 'DBDMH', 'SIAMU',
                    'Brandweer en Dringende Medische Hulp',
                    "Service d'Incendie et d'Aide Médicale Urgente"],
        'members': [
            'Anderlecht', 'Brussel', 'Elsene', 'Etterbeek', 'Evere', 'Ganshoren', 'Jette', 'Koekelberg',
            'Oudergem', 'Schaarbeek', 'Sint-Agatha-Berchem', 'Sint-Gillis', 'Sint-Jans-Molenbeek',
            'Sint-Joost-ten-Node', 'Sint-Lambrechts-Woluwe', 'Sint-Pieters-Woluwe', 'Ukkel', 'Vorst',
            'Watermaal-Bosvoorde']},
}

# Brusselse intercommunales zoals opgesomd op be.brussels (9). Leden en bevolking niet
# gepubliceerd: bevolking onbekend.
_B = {'population': None, 'peildatum': '2026-10-27', 'bron_url': BXL_INTERCO_URL}
BE_INTERCOMMUNALES_BXL = {
    'VIVAQUA': {**_B, 'id': 'BE-HAND-BXL-VIVAQUA'},
    'Sibelga': {**_B, 'id': 'BE-HAND-BXL-SIBELGA'},
    'Académie intercommunale de Musique, des Arts de la parole, et de la Danse de '
    'Saint-Josse-ten-Noode/Schaerbeek': {**_B, 'id': 'BE-HAND-BXL-ACADEMIE-SJTN-SCHAERBEEK'},
    'Ecole Régionale et Intercommunale de Police': {**_B, 'id': 'BE-HAND-BXL-ERIP', 'aliases': ['ERIP']},
    "Intercommunale d'Enseignement supérieur d'Architecture": {**_B, 'id': 'BE-HAND-BXL-IEAI',
                                                               'aliases': ['IEAI']},
    'Brulabo': {**_B, 'id': 'BE-HAND-BXL-BRULABO',
                'aliases': ['Laboratoire Intercommunal Bruxellois de Chimie et de Bactériologie']},
    "Intercommunale d'Inhumation": {**_B, 'id': 'BE-HAND-BXL-INHUMATION'},
    'Société Coopérative Intercommunale de Crémation': {**_B, 'id': 'BE-HAND-BXL-SCIC', 'aliases': ['SCIC']},
    'Brutélé': {**_B, 'id': 'BE-HAND-BXL-BRUTELE'},
}
