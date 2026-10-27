"""Duitse handtabellen voor de TAM/whitespace-lijstbouwer (vast id, bron_url, peildatum per rij).

Regels: nooit een bevolking of ledenlijst invullen zonder officiele bron; zonder bron blijft
de bevolking None / de ledenlijst leeg (bevolking onbekend). Ledenlijsten zijn sleutels uit
het Destatis-Gemeindeverzeichnis: 'DE-AGS-<2|3|5|8>' (Land, RB, Kreis, Gemeinde) of
'DE-ARS-<9>' (Gemeindeverband, bijv. een Amt). De bevolking wordt in tam.sources.de
berekend als som over alle Gemeinden onder die sleutels (load_de_hand).
"""

_BERLIN_URL = ('https://download.statistik-berlin-brandenburg.de/c3bba10619eb67fe/d50db46c4152/'
               'SB_A01-07_00_2025m12_BE.pdf')  # Statistischer Bericht A I 7 - m 12/25, tabel 1.5
_HAMBURG_URL = 'https://www.statistik-nord.de/fileadmin/Dokumente/A_I_2_vj_25-4_Zensus22_HH.xlsx'  # A I 2 - vj 4/25 HH


_BRON = {_BERLIN_URL: 'Amt für Statistik Berlin-Brandenburg, SB A I 7 - m 12/25',
         _HAMBURG_URL: 'Statistikamt Nord, A I 2 - vj 4/25 HH'}


def _bezirk(slug, stadt, match_name, population, url):
    return {'id': f'DE-HAND-bezirk-{slug}', 'stadt': stadt, 'match_name': match_name,
            'population': population, 'peildatum': '2025-12-31', 'bron': _BRON[url], 'bron_url': url}


# Berlin (12) en Hamburg (7): bevolking 31.12.2025, fortschrijving op basis van Zensus 2022.
# Controle: Berlijn som 3.700.577, Hamburg som 1.869.473 (= Destatis GV).
DE_BEZIRKE = {
    'Bezirksamt Mitte von Berlin': _bezirk('berlin-mitte', 'Berlin', 'Mitte', 365741, _BERLIN_URL),
    'Bezirksamt Friedrichshain-Kreuzberg von Berlin': _bezirk(
        'berlin-friedrichshain-kreuzberg', 'Berlin', 'Friedrichshain-Kreuzberg', 267258, _BERLIN_URL),
    'Bezirksamt Pankow von Berlin': _bezirk('berlin-pankow', 'Berlin', 'Pankow', 411133, _BERLIN_URL),
    'Bezirksamt Charlottenburg-Wilmersdorf von Berlin': _bezirk(
        'berlin-charlottenburg-wilmersdorf', 'Berlin', 'Charlottenburg-Wilmersdorf', 323712, _BERLIN_URL),
    'Bezirksamt Spandau von Berlin': _bezirk('berlin-spandau', 'Berlin', 'Spandau', 248122, _BERLIN_URL),
    'Bezirksamt Steglitz-Zehlendorf von Berlin': _bezirk(
        'berlin-steglitz-zehlendorf', 'Berlin', 'Steglitz-Zehlendorf', 295082, _BERLIN_URL),
    'Bezirksamt Tempelhof-Schöneberg von Berlin': _bezirk(
        'berlin-tempelhof-schoeneberg', 'Berlin', 'Tempelhof-Schöneberg', 339042, _BERLIN_URL),
    'Bezirksamt Neukölln von Berlin': _bezirk('berlin-neukoelln', 'Berlin', 'Neukölln', 309241, _BERLIN_URL),
    'Bezirksamt Treptow-Köpenick von Berlin': _bezirk(
        'berlin-treptow-koepenick', 'Berlin', 'Treptow-Köpenick', 293681, _BERLIN_URL),
    'Bezirksamt Marzahn-Hellersdorf von Berlin': _bezirk(
        'berlin-marzahn-hellersdorf', 'Berlin', 'Marzahn-Hellersdorf', 285222, _BERLIN_URL),
    'Bezirksamt Lichtenberg von Berlin': _bezirk('berlin-lichtenberg', 'Berlin', 'Lichtenberg', 305118, _BERLIN_URL),
    'Bezirksamt Reinickendorf von Berlin': _bezirk(
        'berlin-reinickendorf', 'Berlin', 'Reinickendorf', 257225, _BERLIN_URL),
    'Bezirksamt Hamburg-Mitte': _bezirk('hamburg-mitte', 'Hamburg', 'Hamburg-Mitte', 292041, _HAMBURG_URL),
    'Bezirksamt Altona': _bezirk('hamburg-altona', 'Hamburg', 'Altona', 267166, _HAMBURG_URL),
    'Bezirksamt Eimsbüttel': _bezirk('hamburg-eimsbuettel', 'Hamburg', 'Eimsbüttel', 263572, _HAMBURG_URL),
    'Bezirksamt Hamburg-Nord': _bezirk('hamburg-nord', 'Hamburg', 'Hamburg-Nord', 314913, _HAMBURG_URL),
    'Bezirksamt Wandsbek': _bezirk('hamburg-wandsbek', 'Hamburg', 'Wandsbek', 435021, _HAMBURG_URL),
    'Bezirksamt Bergedorf': _bezirk('hamburg-bergedorf', 'Hamburg', 'Bergedorf', 127711, _HAMBURG_URL),
    # Statistiek: 'Hamburg-Harburg'; het Bezirksamt heet 'Bezirksamt Harburg'
    'Bezirksamt Harburg': _bezirk('hamburg-harburg', 'Hamburg', 'Harburg', 169049, _HAMBURG_URL),
}

_BEZO_BY = 'https://www.gesetze-bayern.de/Content/Document/BayBezO-7'
# LVerbO NRW op het officiele portaal recht.nrw.de (§ 1 Mitgliedskoerperschaften, geverifieerd 2026-10-27)
_LVERBO = ('https://recht.nrw.de/lrgv/gesetz/'
           '17072024-landschaftsverbandsordnung-fuer-das-land-nordrhein-westfalen-lverbo/')


def _hkv(slug, members, url, region, match_name=None):
    row = {'id': f'DE-HAND-{slug}', 'members': members, 'bron_url': url, 'peildatum': '2026-10-27',
           'region': region}
    if match_name:
        row['match_name'] = match_name
    return row


# Hoehere Kommunalverbaende: leden = Kreise en kreisfreie Staedte, als GV-sleutel.
DE_HOEHERE_KOMMUNALVERBAENDE = {
    # BezO Art. 7: het Bezirksgebiet = de toegewezen Landkreise en kreisfreie Gemeinden, d.w.z.
    # het gebied van de gelijknamige Regierungsbezirk (GV-sleutels 091..097).
    'Bezirk Oberbayern': _hkv('bezirk-oberbayern', ['091'], _BEZO_BY, 'Bayern', 'Oberbayern'),
    'Bezirk Niederbayern': _hkv('bezirk-niederbayern', ['092'], _BEZO_BY, 'Bayern', 'Niederbayern'),
    'Bezirk Oberpfalz': _hkv('bezirk-oberpfalz', ['093'], _BEZO_BY, 'Bayern', 'Oberpfalz'),
    'Bezirk Oberfranken': _hkv('bezirk-oberfranken', ['094'], _BEZO_BY, 'Bayern', 'Oberfranken'),
    'Bezirk Mittelfranken': _hkv('bezirk-mittelfranken', ['095'], _BEZO_BY, 'Bayern', 'Mittelfranken'),
    'Bezirk Unterfranken': _hkv('bezirk-unterfranken', ['096'], _BEZO_BY, 'Bayern', 'Unterfranken'),
    'Bezirk Schwaben': _hkv('bezirk-schwaben', ['097'], _BEZO_BY, 'Bayern', 'Schwaben'),
    # LVerbO NRW § 1: Kreise en kreisfreie Staedte van de vroegere Rheinprovinz (= RB Duesseldorf
    # en Koeln) resp. van de vroegere Provinz Westfalen en Land Lippe (= RB Muenster, Detmold, Arnsberg).
    'Landschaftsverband Rheinland': _hkv('landschaftsverband-rheinland', ['051', '053'], _LVERBO,
                                         'Nordrhein-Westfalen', 'LVR'),
    'Landschaftsverband Westfalen-Lippe': _hkv('landschaftsverband-westfalen-lippe', ['055', '057', '059'],
                                               _LVERBO, 'Nordrhein-Westfalen', 'LWL'),
    # 'Die kreisfreien Staedte und die Landkreise des Landes werden zu einem LWV Hessen zusammengeschlossen'
    'Landeswohlfahrtsverband Hessen': _hkv(
        'landeswohlfahrtsverband-hessen', ['06'],
        'https://hmdis.hessen.de/sites/innen.hessen.de/files/2023-12/der_lwv_auf_einen_blick_2023.pdf',
        'Hessen', 'LWV Hessen'),
    # 'vereinigt er die zehn Landkreise und die drei kreisfreien Staedte im Freistaat Sachsen'
    'Kommunaler Sozialverband Sachsen': _hkv('kommunaler-sozialverband-sachsen', ['14'],
                                             'https://www.ksv-sachsen.de/ueber-uns', 'Sachsen', 'KSV Sachsen'),
    # JSVG (Gesetz ueber den KVJS, 1.7.2004) § 2: 'Mitglieder ... sind alle Stadt- und Landkreise'.
    # Secundaire bron (lexaris.de); landesrecht-bw.de niet op tekst te verifieren (JS-portaal).
    'Kommunalverband für Jugend und Soziales Baden-Württemberg': _hkv(
        'kommunalverband-jugend-soziales-bw', ['08'],
        'https://lexaris.de/book/version/documentflat/head/1124002', 'Baden-Württemberg', 'KVJS'),
    # Gebied van de vroegere Regierungsbezirk Pfalz: de 16 Landkreise en kreisfreie Staedte der Pfalz
    # (RB 073 zonder Rheinhessen: Mainz 07315, Worms 07319, Alzey-Worms 07331, Mainz-Bingen 07339).
    # Secundaire bron (Landeszentrale fuer politische Bildung RLP); de Bezirksordnung op
    # landesrecht.rlp.de was niet op tekst te verifieren (JS-portaal).
    'Bezirksverband Pfalz': _hkv(
        'bezirksverband-pfalz',
        ['07311', '07312', '07313', '07314', '07316', '07317', '07318', '07320',
         '07332', '07333', '07334', '07335', '07336', '07337', '07338', '07340'],
        'https://www.lpb.rlp.de/fileadmin/download/Ziehn/Zur_Sache_Kommunalsystem.pdf',
        'Rheinland-Pfalz'),
}


def _it(slug, region, feu_names, url, members=None, peildatum='2026-10-27', match_name=None):
    row = {'id': f'DE-HAND-{slug}', 'region': region, 'feu_names': feu_names, 'bron_url': url,
           'members': members or [], 'peildatum': peildatum}
    if match_name:
        row['match_name'] = match_name
    return row


_FEU_EXTRA = ('https://www.destatis.de/DE/Themen/Staat/Oeffentliche-Finanzen/Fonds-Einrichtungen-Unternehmen/'
              'Methoden/Downloads/liste-extrahaushalte-2026-xlsx.xlsx')
_FEU_SONST = ('https://www.destatis.de/DE/Themen/Staat/Oeffentliche-Finanzen/Fonds-Einrichtungen-Unternehmen/'
              'Methoden/Downloads/liste-sonstige-FEU-2026-xlsx.xlsx')

# Kommunale IT-dienstverleners in publiekrechtelijke vorm (Zweckverband, AoeR, Anstalt,
# Koerperschaft) die in de Destatis FEU-lijsten 2026 voorkomen (feu_names = exacte FEU-naam;
# die rijen worden uit de FEU-import gehaald). GmbH's en eG's zijn bewust weggelaten, net als
# Eigenbetriebe (onderdeel van een stad/Kreis) en Landes-IT. Leden alleen uit een officiele
# Verbandssatzung; anders leeg (bevolking onbekend).
DE_IT_ZWECKVERBAENDE = {
    'AKDB Anstalt für kommunale Datenverarbeitung in Bayern': _it(
        'akdb', 'Bayern', ['AKDB Anstalt für kommunale Datenverarbeitung in Bayern'], _FEU_EXTRA,
        match_name='AKDB'),
    'Zweckverband Informationstechnik Franken (ZV IT)': _it(
        'zv-it-franken', 'Bayern', ['Zweckverband Informationstechnik Franken ZV IT'], _FEU_EXTRA),
    'Zweckverband gemeindliche Datenverarbeitung im Landkreis Neu-Ulm': _it(
        'zv-datenverarbeitung-neu-ulm', 'Bayern',
        ['Zweckverband gemeindliche Datenverarbeitung im Landkreis Neu-Ulm'], _FEU_EXTRA),
    'KommunalBIT': _it('kommunalbit', 'Bayern', ['KommunalBIT'], _FEU_EXTRA),
    'IT-Verbund Landsberg am Lech KU': _it('it-verbund-landsberg', 'Bayern',
                                           ['IT-Verbund Landsberg am Lech KU'], _FEU_EXTRA),
    'Komm.ONE AöR': _it('komm-one', 'Baden-Württemberg', ['Komm.ONE AöR'], _FEU_EXTRA, match_name='Komm.ONE'),
    'Zweckverband 4IT': _it('zv-4it', 'Baden-Württemberg', ['Zweckverband 4IT'], _FEU_EXTRA),
    'Zweckverband Digitale Kommunen Brandenburg (DIKOM)': _it(
        'dikom', 'Brandenburg', ['Zweckverband Digitale Kommunen Brandenburg (DIKOM)'], _FEU_EXTRA),
    'ekom21 - KGRZ Hessen': _it('ekom21', 'Hessen', ['ekom21 - KGRZ Hessen'], _FEU_EXTRA, match_name='ekom21'),
    'Hannoversche Informationstechnologien AöR (HannIT)': _it(
        'hannit', 'Niedersachsen', ['Hannoversche Informationstechnologien AöR (HannIT)'], _FEU_EXTRA),
    'IT-Kooperation Harburg AöR': _it('it-kooperation-harburg', 'Niedersachsen',
                                      ['IT-Kooperation Harburg AöR'], _FEU_EXTRA),
    'IT-Verbund Uelzen Gemeinsame kommunale Anstalt': _it(
        'it-verbund-uelzen', 'Niedersachsen', ['IT-Verbund Uelzen Gemeinsame kommunale Anstalt'], _FEU_EXTRA),
    'Zweckverband IT-Verbund Gifhorn': _it('zv-it-verbund-gifhorn', 'Niedersachsen',
                                           ['Zweckverband IT-Verbund Gifhorn'], _FEU_EXTRA),
    'Kommunale Datenverarbeitung Oldenburg (KDO)': _it(
        'kdo', 'Niedersachsen', ['Kommunale Datenverarbeitung Oldenburg (KDO)'], _FEU_SONST),
    'Gelsenkirchener Kommunale Datenzentrale Emscher-Lippe (gkd-el)': _it(
        'gkd-el', 'Nordrhein-Westfalen', ['Gelsenkirchener Kommunale Datenzentrale Emscher-Lippe (gkd-el)'],
        _FEU_EXTRA),
    # Verbandssatzung 18.06.2026, § 1: Kreis Recklinghausen + acht kreisangehoerige Staedte
    'Gemeinsame Kommunale Datenzentrale Recklinghausen (GKD Recklinghausen)': _it(
        'gkd-recklinghausen', 'Nordrhein-Westfalen', [],
        'https://www.gkd-re.de/system/files/2026-07/Satzung%20GKD%20_18.06.26%20_final.pdf',
        members=['05562', '05562004', '05562008', '05562012', '05562014', '05562016', '05562028',
                 '05562032', '05562036'],
        peildatum='2026-06-18'),
    'ITK Rheinland': _it('itk-rheinland', 'Nordrhein-Westfalen', ['ITK Rheinland'], _FEU_EXTRA),
    'Kommunales Rechenzentrum Niederrhein (KRZN)': _it(
        'krzn', 'Nordrhein-Westfalen', ['Kommunales Rechenzentrum Niederrhein (KRZN)'], _FEU_EXTRA),
    'Zweckverband KAAW - Kommunale ADV-Anwendergemeinschaft West': _it(
        'kaaw', 'Nordrhein-Westfalen', ['Zweckverband KAAW - Kommunale ADV- Anwendergemeinschaft West'],
        _FEU_EXTRA),
    'Zweckverband Kommunale Datenverarbeitungszentrale Rhein-Erft-Rur (KDVZ)': _it(
        'kdvz-rhein-erft-rur', 'Nordrhein-Westfalen',
        ['Zweckverband Kommunale Datenverarbeitungszentrale Rhein-Erft-Rur'], _FEU_EXTRA),
    # Officiele site noemt 5 Kreise, Schwerte en 7 niet bij naam genoemde Kommunen: onvolledig -> leeg
    'Zweckverband Südwestfalen-IT': _it('suedwestfalen-it', 'Nordrhein-Westfalen',
                                        ['Zweckverband Südwestfalen-IT'], _FEU_EXTRA),
    'civitec - Zweckverband Kommunale Informationsverarbeitung': _it(
        'civitec', 'Nordrhein-Westfalen', ['civitec - Zweckverband Kommunale Informationsverarbeitung'],
        _FEU_SONST, match_name='civitec'),
    'INFOKOM Gütersloh Zweckverband für kommunale Informations- und Kommunikationstechnik': _it(
        'infokom-guetersloh', 'Nordrhein-Westfalen',
        ['INFOKOM Gütersloh Zweckverband für kommunale Informations- und Kommunikationstechnik'],
        _FEU_SONST, match_name='INFOKOM Gütersloh'),
    'Zweckverband für Informationstechnologie und Datenverarbeitung der Kommunen in Rheinland-Pfalz (ZIDKOR)': _it(
        'zidkor', 'Rheinland-Pfalz',
        ['Zweckverband für Informationstechnologie und Datenverarbeitung der Kommunen in Rheinland-Pfalz (ZIDKOR)'],
        _FEU_EXTRA, match_name='ZIDKOR'),
    'Kommunale Informationsverarbeitung Sachsen - KISA': _it(
        'kisa', 'Sachsen', ['Kommunale Informationsverarbeitung Sachsen - KISA'], _FEU_EXTRA, match_name='KISA'),
    'Sächsische Anstalt für kommunale Datenverarbeitung': _it(
        'sakd', 'Sachsen', ['Sächsische Anstalt für kommunale Datenverarbeitung'], _FEU_EXTRA),
    # Verbandssatzung (4. Aenderungssatzung, Gesamtlesefassung, Beschluss 16.06.2026) § 2 Abs. 1
    'kommunit - IT-Zweckverband Schleswig-Holstein': _it(
        'kommunit', 'Schleswig-Holstein', ['kommunit - IT-Zweckverband Schleswig-Holstein'],
        'https://www.kommunit.de/wp-content/uploads/2026/07/4.-Aenderungssatzung-Gesamtlesefassung-Ausfertigung.pdf',
        members=[
            '01056041',   # Stadt Quickborn
            '01056',      # Kreis Pinneberg
            'DE-ARS-010565660',  # Amt Rantzau
            '01058092',   # Gemeinde Kronshagen
            '01056002',   # Stadt Barmstedt
            '01054',      # Kreis Nordfriesland
            '01059',      # Kreis Schleswig-Flensburg
            'DE-ARS-010585803',  # Amt Achterwehr
            'DE-ARS-010615134',  # Amt Horst-Herzhorn
            'DE-ARS-010595919',  # Amt Huerup
            '01056050',   # Stadt Wedel
            'DE-ARS-010595937',  # Amt Langballig
            'DE-ARS-010545489',  # Amt Suedtondern
            'DE-ARS-010595949',  # Amt Mittelangeln
            '01059120',   # Gemeinde Harrislee
            'DE-ARS-010605043',  # Amt Auenland Suedholstein
            'DE-ARS-010585896',  # Amt Eidertal
            'DE-ARS-010565690',  # Amt Geest und Marsch Suedholstein
            '01060039',   # Gemeinde Henstedt-Ulzburg
            'DE-ARS-010545453',  # Amt Vioel
            'DE-ARS-010585824',  # Amt Daenischer Wohld
            '01058',      # Kreis Rendsburg-Eckernfoerde
            'DE-ARS-010595987',  # Amt Suedangeln
        ],
        peildatum='2026-06-16', match_name='kommunit'),
    'IT-Verbund Schleswig-Holstein AöR': _it('it-verbund-sh', 'Schleswig-Holstein',
                                             ['IT-Verbund Schleswig-Holstein AöR'], _FEU_EXTRA),
    'IT-Verbund Stormarn - Anstalt des öffentlichen Rechts': _it(
        'it-verbund-stormarn', 'Schleswig-Holstein',
        ['IT-Verbund Stormarn - Anstalt des öffentlichen Rechts -'], _FEU_EXTRA),
    'Kommunale Informationstechnik und Telekommunikation KITT': _it(
        'kitt', 'Thüringen', ['Kommunale Informationstechnik und Telekommunikation KITT'], _FEU_EXTRA),
}

_BREG = 'https://www.bundesregierung.de/breg-de/bundesregierung/bundesministerien'


def _min(slug):
    return {'id': f'DE-HAND-{slug}', 'bron_url': _BREG, 'peildatum': '2026-10-27'}


DE_BUNDESMINISTERIEN = {
    'Auswärtiges Amt': _min('auswaertiges-amt'),
    'Bundesministerium der Finanzen': _min('bmf'),
    'Bundesministerium des Innern': _min('bmi'),
    'Bundesministerium der Verteidigung': _min('bmvg'),
    'Bundesministerium für Wirtschaft und Energie': _min('bmwe'),
    'Bundesministerium für Forschung, Technologie und Raumfahrt': _min('bmftr'),
    'Bundesministerium der Justiz und für Verbraucherschutz': _min('bmjv'),
    'Bundesministerium für Bildung, Familie, Senioren, Frauen und Jugend': _min('bmbfsfj'),
    'Bundesministerium für Arbeit und Soziales': _min('bmas'),
    'Bundesministerium für Digitales und Staatsmodernisierung': _min('bmds'),
    'Bundesministerium für Verkehr': _min('bmv'),
    'Bundesministerium für Umwelt, Klimaschutz, Naturschutz und nukleare Sicherheit': _min('bmukn'),
    'Bundesministerium für Gesundheit': _min('bmg'),
    'Bundesministerium für Landwirtschaft, Ernährung und Heimat': _min('bmleh'),
    'Bundesministerium für wirtschaftliche Zusammenarbeit und Entwicklung': _min('bmz'),
    'Bundesministerium für Wohnen, Stadtentwicklung und Bauwesen': _min('bmwsb'),
}


def it_feu_names() -> list[str]:
    """Alle namen waaronder IT-handtabelrijen in de FEU-lijsten staan (plus de tabelnaam)."""
    names = []
    for name, row in DE_IT_ZWECKVERBAENDE.items():
        names.append(name)
        names.extend(row.get('feu_names', []))
    return names
