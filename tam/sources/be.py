"""Belgische bronnen voor de TAM/whitespace-lijstbouwer.

Wikidata + Statbel (load_be_wikidata)
  Gemeenten: wdt:P31 wd:Q493522 zonder P576, NIS-code P1567 (statements met einddatum
  pq:P582 vallen weg: Bastenaken had 82003 tot 2024-12-02 en nu 82039), P1082 + pq:P585.
  Op 2026-10-27: 565 items, 565 unieke NIS-codes. Labels nl/fr/de + nl.wikipedia-titel als
  vangnet (zoals step2_enrich._sparql_population_template). Wikidata-bevolking is grotendeels
  peildatum 2018; daarom (spec 4.2: 'Statbel if reachable') wint Statbel:
  TF_SOC_POP_STRUCT_<jaar>.zip (open data 'Bevolking naar woonplaats, nationaliteit,
  burgerlijke staat, leeftijd en geslacht'), een pipe-gescheiden txt met o.a. CD_REFNIS,
  TX_DESCR_NL, TX_DESCR_FR, CD_PROV_REFNIS, CD_RGN_REFNIS en MS_POPULATION; bevolking per
  gemeente = som van MS_POPULATION per CD_REFNIS. Editie 2026 (1 januari 2026): 565
  gemeenten, 11.867.634 inwoners, dezelfde codes als Wikidata.
  Provincies: wdt:P31 wd:Q83116 met P1567 (10 stuks); leden via het NIS-voorvoegsel
  (1 -> 10000, 23/24 -> 20001, 25 -> 20002, 3/4/5/6/7/8/9 -> x0000; 21 = Brussel, geen provincie).
  Naam = label in de officiele taal (Vlaanderen en Brussel nl, Wallonie fr, Duits taalgebied
  de); andere labels worden aliassen.

OP-dump (parse_op_dump / load_be_op)
  Agentschap Binnenland OrganisatiePortaal, PublicCacheGraphDump. Vinden via
  GET https://organisaties.abb.vlaanderen.be/datasets?filter[subject]=http://data.lblod.info/
  datasets/delta-producer/dumps/PublicCacheGraphDump&sort=-release-date&include=distributions
  -> included[distributions] -> /distributions/<id>/subject (bestand) -> /files/<id>/download.
  Formaat volgens de metadata text/turtle, in de praktijk N-Triples met volledige URI's, maar
  literals als \"\"\"...\"\"\" die over meerdere regels lopen. Gelezen 2026-10-27: 155 MB,
  822.249 regels, 822.167 triples. Licentie staat niet in de metadata (open punt, gelogd).
  Gebruikte vorm (prefixen: besluit = http://data.vlaanderen.be/ns/besluit#, org =
  http://www.w3.org/ns/org#, regorg = http://www.w3.org/ns/regorg#, skos, adms, generiek =
  https://data.vlaanderen.be/ns/generiek#):
    organisatie   rdf:type besluit:Bestuurseenheid (3725)
    naam          regorg:legalName (formeel), skos:prefLabel (kort), skos:altLabel (afkorting
                  of '5451 PZ Middelkerke')
    soort         org:classification -> concept met skos:prefLabel ('Politiezone', ...); de
                  concepten staan in .../BestuurseenheidClassificatieCode/<id>
    status        regorg:orgStatus -> concept met skos:prefLabel 'Actief' (2911), 'Niet Actief'
                  (801) of 'In oprichting' (12); alleen 'Actief' telt
    KBO/OVO       adms:identifier -> adms:Identifier met skos:notation 'KBO nummer' |
                  'OVO-nummer' | 'SharePoint identificator' en generiek:gestructureerdeIdentificator
                  -> generiek:lokaleIdentificator (de waarde, bv. '0862903288')
    gebied        besluit:werkingsgebied -> skos:exactMatch
                  <http://vocab.belgif.be/auth/refnis2025/35011> (NIS-code; alle actieve
                  gemeenten, OCMW's en provincies hebben er een)
    lidmaatschap  org:Membership met org:organization (de samenwerking), org:member (het lid)
                  en org:role -> skos:prefLabel 'participant' | 'stichtend lid' | 'gerelateerd'
                  | 'bedienend'; alleen de eerste twee zijn lidmaatschappen
    fusies        org:ChangeEvent met org:originalOrganization -> org:resultingOrganization
  Actieve aantallen per soort (2026-10-27): Gemeente 304 (285 Vlaams + 19 Brussels), OCMW 285,
  Provincie 5, Politiezone 98, Hulpverleningszone 20, Autonoom gemeentebedrijf 159, District 10
  (Antwerpen incl. Borsbeek), Projectvereniging 61, Dienstverlenende vereniging 25,
  Opdrachthoudende vereniging 53 (+1 met private deelname), Welzijnsvereniging 58.
  Leden: welzijnsverenigingen hebben vooral OCMW's als lid (-> de gemeente met dezelfde
  NIS-code); 113 lidmaatschappen wijzen naar een opgeheven gemeente (fusie 2025) en worden
  via de ChangeEvents naar de fusiegemeente (rechtsopvolger) doorgezet.

W/B (load_be_wb)
  Politiezones: step2_enrich.BE_POLITIEZONE_GEMEENTEN (173 zones), zonder elke zone met een
  Vlaams lid (die komen uit de OP-dump). Brandweerzones, Brusselse intercommunales, gewesten
  en FOD's: tam.hand_tables. Waalse intercommunales: SPW-kadaster
  cadastre-<jaar>-interco-et-slsp.xlsx, blad 'Intercommunales' (81 rijen), kolom A
  'Intercommunale ' (de naam; overige kolommen gaan over de revisoraatsopdracht); blad 'SLSP'
  (huisvestingsmaatschappijen) wordt bewust niet gelezen.
"""
from __future__ import annotations

import logging
import re
import warnings
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

import openpyxl
import pandas as pd
import requests

from step2_enrich import BE_POLITIEZONE_GEMEENTEN, normalize
from tam import hand_tables
from tam.config import USER_AGENT
from tam.entities import ALIAS_COLUMNS, SourceBundle, SourceStatus, make_entity_id, new_entity, slugify

log = logging.getLogger(__name__)

_PATCH_COLUMNS = ['entity_id', 'official_ids']


# ---------------------------------------------------------------------------
# Gedeelde hulpjes
# ---------------------------------------------------------------------------
def name_key(text) -> str:
    """Vergelijkingssleutel voor namen: step2-normalize na ligaturen en typografische quotes."""
    s = str(text or '').replace('’', "'").replace('œ', 'oe').replace('Œ', 'Oe')
    s = s.replace('æ', 'ae').replace('Æ', 'Ae')
    return normalize(s)


def _nis(code) -> str:
    return str(code).replace('BE-NIS-', '').strip()


def is_flemish_nis(code) -> bool:
    """Ruling R1: Vlaamse NIS-codes beginnen met 1, 3, 4, 7 of 23/24 (Vlaams-Brabant)."""
    c = _nis(code)
    return c[:1] in ('1', '3', '4', '7') or c[:2] in ('23', '24')


def province_of(code) -> str | None:
    """NIS-code van de provincie van een gemeente; None voor Brussel."""
    c = _nis(code)
    if c.startswith('21'):
        return None
    if c[:2] in ('23', '24'):
        return '20001'
    if c.startswith('25'):
        return '20002'
    return c[0] + '0000'


def build_name_index(gemeenten: pd.DataFrame) -> dict[str, set[str]]:
    """Genormaliseerde naam -> entity_ids. Accepteert een frame met entity_id en name (en
    eventueel match_name/kind); meerdere rijen per gemeente (andere talen) mogen."""
    index: dict[str, set[str]] = defaultdict(set)
    if gemeenten is None or not len(gemeenten):
        return index
    df = gemeenten
    if 'kind' in df.columns:
        df = df[df['kind'].isin(['be_gemeente', '']) | df['kind'].isna()]
    for col in ('name', 'match_name'):
        if col not in df.columns:
            continue
        for eid, name in zip(df['entity_id'], df[col]):
            if isinstance(name, str) and name.strip():
                index[name_key(name)].add(eid)
    return index


def _lookup(index, name, prefer=None):
    """Eenduidige entity_id voor een naam; bij meerdere kandidaten beslist prefer (filter)."""
    ids = index.get(name_key(name), set())
    if len(ids) > 1 and prefer is not None:
        ids = {i for i in ids if prefer(i)}
    return next(iter(ids)) if len(ids) == 1 else None


def _alias_rows(entity_id, name, candidates, reason):
    seen = {name_key(name)}
    rows = []
    for c in candidates:
        c = (c or '').strip()
        if c and name_key(c) not in seen:
            seen.add(name_key(c))
            rows.append({'alias_name': c, 'country': 'BE', 'entity_id': entity_id, 'reason': reason})
    return rows


# ---------------------------------------------------------------------------
# Wikidata + Statbel: gemeenten en provincies
# ---------------------------------------------------------------------------
GEM_QUERY = """
SELECT ?item ?itemLabel ?nis ?population ?date ?labelNl ?labelFr ?labelDe ?articleName WHERE {
  ?item wdt:P31 wd:Q493522 .
  FILTER NOT EXISTS { ?item wdt:P576 ?dissolved }
  ?item p:P1567 ?nisStmt . ?nisStmt ps:P1567 ?nis .
  FILTER NOT EXISTS { ?nisStmt pq:P582 ?nisEnd }
  OPTIONAL { ?item p:P1082 ?stmt . ?stmt ps:P1082 ?population . OPTIONAL { ?stmt pq:P585 ?date . } }
  OPTIONAL { ?item rdfs:label ?labelNl . FILTER(LANG(?labelNl) = "nl") }
  OPTIONAL { ?item rdfs:label ?labelFr . FILTER(LANG(?labelFr) = "fr") }
  OPTIONAL { ?item rdfs:label ?labelDe . FILTER(LANG(?labelDe) = "de") }
  OPTIONAL {
    ?article schema:about ?item ;
             schema:isPartOf <https://nl.wikipedia.org/> ;
             schema:name ?articleName .
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "nl,en,de,fr". }
}
"""

PROV_QUERY = """
SELECT ?item ?itemLabel ?nis ?labelNl ?labelFr ?labelDe WHERE {
  ?item wdt:P31 wd:Q83116 .
  FILTER NOT EXISTS { ?item wdt:P576 ?dissolved }
  ?item wdt:P1567 ?nis .
  OPTIONAL { ?item rdfs:label ?labelNl . FILTER(LANG(?labelNl) = "nl") }
  OPTIONAL { ?item rdfs:label ?labelFr . FILTER(LANG(?labelFr) = "fr") }
  OPTIONAL { ?item rdfs:label ?labelDe . FILTER(LANG(?labelDe) = "de") }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "nl,en,de,fr". }
}
"""

# Gemeenten van het Duitse taalgebied (Grondwet art. 4)
DG_NIS = {'63001', '63012', '63013', '63023', '63040', '63048', '63061', '63067', '63087'}
_FR_PROVINCES = {'20002', '50000', '60000', '80000', '90000'}
BRUSSELS_REGION = 'Brussels Hoofdstedelijk Gewest'

STATBEL_POP_ZIP_URL = ('https://statbel.fgov.be/sites/default/files/files/opendata/'
                   'bevolking%20naar%20woonplaats%2C%20nationaliteit%20burgelijke%20staat%20%2C'
                   '%20leeftijd%20en%20geslacht/TF_SOC_POP_STRUCT_{year}.zip')


def _language(nis: str) -> str:
    if nis in DG_NIS:
        return 'de'
    if nis[:1] in ('5', '6', '8', '9') or nis.startswith('25') or nis in _FR_PROVINCES:
        return 'fr'
    return 'nl'


def _col(df, name):
    return df[name] if name in df.columns else pd.Series([None] * len(df), index=df.index)


def _pick_name(nis, row) -> str:
    """Label in de officiele taal; anders itemLabel (als het geen Q-id is) of de wikipedia-titel."""
    preferred = {'nl': row.get('labelNl'), 'fr': row.get('labelFr'), 'de': row.get('labelDe')}
    lang = _language(nis)
    order = [preferred[lang]] + [row.get('itemLabel')] + [preferred[k] for k in ('nl', 'fr', 'de')]
    for cand in order:
        if isinstance(cand, str) and cand.strip() and not re.fullmatch(r'Q\d+', cand.strip()):
            return cand.strip()
    article = row.get('articleName')
    if isinstance(article, str) and article.strip():
        return re.sub(r'\s*\([^)]*\)\s*$', '', article).strip()
    return ''


def parse_wikidata_gemeenten(df: pd.DataFrame) -> pd.DataFrame:
    """Een rij per NIS-code: nis, qid, name, labels (lijst), wd_population, wd_date."""
    cols = ['nis', 'qid', 'name', 'labels', 'wd_population', 'wd_date']
    if df is None or not len(df) or 'nis' not in df.columns:
        return pd.DataFrame(columns=cols)
    df = df.copy()
    for c in ('itemLabel', 'labelNl', 'labelFr', 'labelDe', 'articleName', 'population', 'date'):
        df[c] = _col(df, c)
    df['date'] = df['date'].fillna('').astype(str)
    out = []
    for nis, grp in df.groupby('nis', sort=True):
        items = grp['item'].unique()
        if len(items) > 1:
            log.warning('Wikidata: NIS %s bij meerdere items (%s); eerste genomen', nis, ', '.join(items))
            grp = grp[grp['item'] == items[0]]
        first = grp.iloc[0].to_dict()
        name = _pick_name(nis, first)
        labels = [name] + [first.get(k) for k in ('labelNl', 'labelFr', 'labelDe')]
        labels = list(dict.fromkeys(x.strip() for x in labels if isinstance(x, str) and x.strip()))
        pops = grp.dropna(subset=['population']).sort_values('date', ascending=False)
        pop = int(float(pops.iloc[0]['population'])) if len(pops) else None
        out.append({'nis': nis, 'qid': first['item'].rsplit('/', 1)[-1], 'name': name, 'labels': labels,
                    'wd_population': pop, 'wd_date': pops.iloc[0]['date'][:10] if len(pops) else ''})
    return pd.DataFrame(out, columns=cols)


def parse_statbel(zip_path: Path) -> tuple[dict[str, int], dict[str, list[str]]]:
    """(bevolking per CD_REFNIS, officiele namen nl/fr per CD_REFNIS) uit de Statbel-zip."""
    with zipfile.ZipFile(zip_path) as z:
        member = next(n for n in z.namelist() if n.lower().endswith('.txt'))
        with z.open(member) as f:
            df = pd.read_csv(f, sep='|', dtype=str, encoding='utf-8-sig',
                             usecols=lambda c: c in ('CD_REFNIS', 'TX_DESCR_NL', 'TX_DESCR_FR',
                                                     'MS_POPULATION'))
    df['MS_POPULATION'] = pd.to_numeric(df['MS_POPULATION'], errors='coerce').fillna(0).astype(int)
    pop = {str(k): int(v) for k, v in df.groupby('CD_REFNIS')['MS_POPULATION'].sum().items()}
    names: dict[str, list[str]] = {}
    name_cols = [c for c in ('TX_DESCR_NL', 'TX_DESCR_FR') if c in df.columns]
    if name_cols:
        for row in df.drop_duplicates('CD_REFNIS').itertuples(index=False):
            d = row._asdict()
            names[d['CD_REFNIS']] = [d[c] for c in name_cols if isinstance(d[c], str)]
    return pop, names


def parse_statbel_population(zip_path: Path) -> dict[str, int]:
    return parse_statbel(zip_path)[0]


def _valid_zip(path: Path) -> bool:
    """Geldige zip; anders (bv. een HTML-foutpagina) wordt het bestand verwijderd."""
    if zipfile.is_zipfile(path):
        return True
    log.warning('Statbel: %s is geen geldige zip; verwijderd', path.name)
    path.unlink(missing_ok=True)
    return False


def _statbel_file(cache):
    """(pad, jaar) van de nieuwste geldige Statbel-editie: live proberen, anders de cache."""
    if not cache.offline:
        this_year = date.today().year
        for year in (this_year, this_year - 1, this_year - 2):
            try:
                path = cache.fetch(f'be_statbel_pop_{year}', STATBEL_POP_ZIP_URL.format(year=year),
                                   suffix='.zip')
            except Exception as e:  # noqa: BLE001
                log.info('Statbel %s niet beschikbaar (%s)', year, e)
                continue
            if _valid_zip(path):
                return path, year
    for path in sorted(cache.base_dir.glob('be_statbel_pop_*.zip'), reverse=True):
        m = re.search(r'(\d{4})', path.name)
        if m and _valid_zip(path):
            return path, int(m.group(1))
    return None, None


def load_be_wikidata(cache) -> SourceBundle:
    bundle = SourceBundle.empty()
    try:
        gem = parse_wikidata_gemeenten(cache.sparql('be_wd_gemeenten', GEM_QUERY))
        prov = parse_wikidata_gemeenten(cache.sparql('be_wd_provincies', PROV_QUERY))
    except Exception as e:  # noqa: BLE001
        log.error('BE Wikidata mislukt: %s', e)
        bundle.status.append(SourceStatus('be_wikidata', False, 0, '', f'mislukt: {e}'))
        return bundle

    statbel_pop, statbel_names, statbel_year = {}, {}, None
    try:
        path, statbel_year = _statbel_file(cache)
        if path is not None:
            statbel_pop, statbel_names = parse_statbel(path)
    except Exception as e:  # noqa: BLE001
        log.warning('Statbel-bevolking onleesbaar (%s); Wikidata-bevolking wordt gebruikt', e)
        statbel_pop, statbel_year = {}, None
    if not statbel_pop:
        log.warning('Geen Statbel-bevolking beschikbaar; Wikidata P1082 (vaak peildatum 2018) gebruikt')
    else:
        only_statbel = sorted(set(statbel_pop) - set(gem['nis']))
        only_wd = sorted(set(gem['nis']) - set(statbel_pop))
        if only_statbel or only_wd:
            log.warning('NIS-verschil Statbel/Wikidata: alleen Statbel %s, alleen Wikidata %s',
                        only_statbel, only_wd)

    run_date = date.today().isoformat()
    prov_names = {r.nis: r.name for r in prov.itertuples()}
    rows, members, aliases, names, muni_pop = [], [], [], [], {}
    for r in gem.itertuples():
        eid = make_entity_id('BE', 'NIS', r.nis)
        if r.nis in statbel_pop:
            pop, src, pdate = statbel_pop[r.nis], f'Statbel TF_SOC_POP_STRUCT_{statbel_year}', f'{statbel_year}-01-01'
        elif r.wd_population is not None:
            pop, src, pdate = r.wd_population, 'Wikidata P1082', r.wd_date
        else:
            pop, src, pdate = None, '', ''
            log.warning('Gemeente %s (%s) zonder bevolking', r.name, r.nis)
        if pop is not None:
            muni_pop[eid] = pop
        pcode = province_of(r.nis)
        region = BRUSSELS_REGION if pcode is None else prov_names.get(pcode, '')
        rows.append(new_entity(
            entity_id=eid, name=r.name, country='BE', kind='be_gemeente', region=region,
            population=pop, population_method='own' if pop is not None else 'unknown',
            population_source=src, population_date=pdate, official_ids=f'nis:{r.nis}',
            source='Wikidata', source_date=run_date))
        all_names = list(dict.fromkeys(list(r.labels) + statbel_names.get(r.nis, [])))
        names.extend({'entity_id': eid, 'name': n} for n in all_names)
        aliases.extend(_alias_rows(eid, r.name, all_names, 'naam in andere landstaal'))
        if pcode is not None:
            members.append({'entity_id': make_entity_id('BE', 'NIS', pcode), 'member_entity_id': eid,
                            'member_kind': 'be_gemeente', 'membership_type': 'territorial', 'join_date': ''})
    for r in prov.itertuples():
        pid = make_entity_id('BE', 'NIS', r.nis)
        rows.append(new_entity(
            entity_id=pid, name=r.name, country='BE', kind='be_provincie',
            population_method='sum of members', official_ids=f'nis:{r.nis}',
            source='Wikidata', source_date=run_date))
        aliases.extend(_alias_rows(pid, r.name, r.labels, 'naam in andere landstaal'))
    known_prov = {make_entity_id('BE', 'NIS', n) for n in prov['nis']}
    orphan = [m for m in members if m['entity_id'] not in known_prov]
    if orphan:
        log.warning('BE: %d gemeenten met een provincie die niet in Wikidata staat', len(orphan))
        members = [m for m in members if m['entity_id'] in known_prov]

    n_gem = len(gem)
    if not 560 <= n_gem <= 570:
        log.warning('BE: %d gemeenten, verwacht 560-570 (na de Vlaamse fusies van 2025: 565)', n_gem)
    bundle.entities = pd.DataFrame(rows, columns=bundle.entities.columns)
    bundle.memberships = pd.DataFrame(members, columns=bundle.memberships.columns)
    bundle.aliases = pd.DataFrame(aliases, columns=ALIAS_COLUMNS)
    bundle.extras['municipal_population'] = muni_pop
    bundle.extras['be_gemeente_names'] = pd.DataFrame(names, columns=['entity_id', 'name'])
    msg = (f'{n_gem} gemeenten ({sum(1 for n in gem["nis"] if n in statbel_pop)} met Statbel-'
           f'bevolking {statbel_year or "-"}), {len(prov)} provincies')
    log.info('BE Wikidata: %s', msg)
    bundle.status.append(SourceStatus('be_wikidata', True, len(rows),
                                      f'{statbel_year}-01-01' if statbel_year else run_date, msg))
    return bundle


# ---------------------------------------------------------------------------
# OP-dump (Agentschap Binnenland)
# ---------------------------------------------------------------------------
OP_DATASETS_URL = 'https://organisaties.abb.vlaanderen.be/datasets'
OP_BASE = 'https://organisaties.abb.vlaanderen.be'
OP_SUBJECT = 'http://data.lblod.info/datasets/delta-producer/dumps/PublicCacheGraphDump'
OP_SOURCE = 'OP-dump Agentschap Binnenland'

_P = {
    '<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>': 'type',
    '<http://www.w3.org/2004/02/skos/core#prefLabel>': 'prefLabel',
    '<http://www.w3.org/2004/02/skos/core#altLabel>': 'altLabel',
    '<http://www.w3.org/ns/regorg#legalName>': 'legalName',
    '<http://www.w3.org/ns/org#classification>': 'classification',
    '<http://www.w3.org/ns/regorg#orgStatus>': 'status',
    '<http://www.w3.org/ns/adms#identifier>': 'identifier',
    '<http://www.w3.org/2004/02/skos/core#notation>': 'notation',
    '<https://data.vlaanderen.be/ns/generiek#gestructureerdeIdentificator>': 'structId',
    '<https://data.vlaanderen.be/ns/generiek#lokaleIdentificator>': 'localId',
    '<http://data.vlaanderen.be/ns/besluit#werkingsgebied>': 'area',
    '<http://www.w3.org/2004/02/skos/core#exactMatch>': 'exactMatch',
    '<http://www.w3.org/ns/org#organization>': 'organization',
    '<http://www.w3.org/ns/org#member>': 'member',
    '<http://www.w3.org/ns/org#role>': 'role',
    '<http://www.w3.org/ns/org#originalOrganization>': 'original',
    '<http://www.w3.org/ns/org#resultingOrganization>': 'resulting',
}
_T_ORG = 'http://data.vlaanderen.be/ns/besluit#Bestuurseenheid'
_T_MEMBERSHIP = 'http://www.w3.org/ns/org#Membership'
_T_CHANGE = 'http://www.w3.org/ns/org#ChangeEvent'
_STMT = re.compile(r'^(<[^>]*>|_:\S+)\s+(<[^>]*>)\s+(\S.*?)\s*\.\s*$', re.S)
_LIT = re.compile(r'^(?:"""(.*)"""|"(.*)")(?:@[\w-]+|\^\^<[^>]*>)?$', re.S)
_REFNIS = re.compile(r'/refnis\d*/(\d{5})$')

KIND_BY_CLASS = {
    'politiezone': 'be_politiezone',
    'hulpverleningszone': 'be_hulpverleningszone',
    'autonoom gemeentebedrijf': 'be_agb',
    'district': 'be_district',
    'projectvereniging': 'be_samenwerking',
    'dienstverlenende vereniging': 'be_samenwerking',
    'opdrachthoudende vereniging': 'be_samenwerking',
    'opdrachthoudende vereniging met private deelname': 'be_samenwerking',
    'welzijnsvereniging': 'be_welzijnsvereniging',
}
METHOD_BY_KIND = {
    'be_politiezone': 'sum of members', 'be_hulpverleningszone': 'sum of members',
    'be_samenwerking': 'sum of members', 'be_welzijnsvereniging': 'sum of members',
    'be_agb': 'same as municipality', 'be_district': 'unknown',
}
_MEMBER_ROLES = ('stichtend lid', 'participant')   # volgorde = voorkeur voor AGB


def _object(o: str) -> str:
    if o.startswith('<'):
        return o[1:-1]
    m = _LIT.match(o)
    if not m:
        return o
    v = m.group(1) if m.group(1) is not None else m.group(2)
    return v.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')


def iter_triples(path: Path, stats: dict | None = None):
    """Regel voor regel lezen; literals met \"\"\" mogen over meerdere regels lopen.
    stats['bad'] telt de onleesbare statements."""
    buf = ''
    with open(path, encoding='utf-8') as f:
        for line in f:
            buf += line
            if buf.count('"""') % 2 == 1:
                continue
            s = buf.strip()
            if not s:
                buf = ''
                continue
            if not s.endswith('.'):
                continue
            buf = ''
            m = _STMT.match(s)
            if m:
                yield m.group(1), m.group(2), m.group(3)
            else:
                if stats is not None:
                    stats['bad'] = stats.get('bad', 0) + 1
                log.debug('OP-dump: onleesbare regel %r', s[:120])


class _OpGraph:
    """Alleen de predicaten die we nodig hebben, per predicaat subject -> [objecten]."""

    def __init__(self, path: Path):
        self.p: dict[str, dict[str, list[str]]] = {v: defaultdict(list) for v in _P.values()}
        self.stats: dict[str, int] = {'bad': 0}
        for s, p, o in iter_triples(path, self.stats):
            short = _P.get(p)
            if short is None:
                continue
            obj = _object(o)
            if short == 'type' and obj not in (_T_ORG, _T_MEMBERSHIP, _T_CHANGE):
                continue
            self.p[short][s[1:-1] if s.startswith('<') else s].append(obj)
        self.types: dict[str, set[str]] = defaultdict(set)
        for s, objs in self.p['type'].items():
            self.types[s].update(objs)

    def one(self, pred, s, default=''):
        v = self.p[pred].get(s)
        return v[0] if v else default

    def label(self, s):
        return self.one('prefLabel', s)

    def cls(self, s):
        return self.label(self.one('classification', s)).strip().lower()

    def active(self, s):
        return self.label(self.one('status', s)).strip() == 'Actief'

    def kbo(self, s):
        for ident in self.p['identifier'].get(s, []):
            if self.one('notation', ident).strip().lower().startswith('kbo'):
                for sid in self.p['structId'].get(ident, []):
                    digits = re.sub(r'\D', '', self.one('localId', sid))
                    if digits:
                        return digits.zfill(10)
        return ''

    def nis(self, s):
        for area in self.p['area'].get(s, []):
            for match in self.p['exactMatch'].get(area, []):
                m = _REFNIS.search(match)
                if m:
                    return m.group(1)
        return ''

    def name(self, s):
        return (self.one('legalName', s) or self.label(s)).strip()


def _op_entity_id(g: _OpGraph, s: str) -> str:
    kbo = g.kbo(s)
    if kbo:
        return make_entity_id('BE', 'KBO', kbo)
    log.warning('OP: %s (%s) zonder KBO-nummer; id op basis van de URI', g.name(s), s)
    return make_entity_id('BE', 'OP', s.rstrip('/').rsplit('/', 1)[-1])


def parse_op_dump(nt_path: Path, gemeenten: pd.DataFrame, source_date: str = '') -> SourceBundle:
    """OP-dump naar entiteiten (zones, AGB's, districten, verenigingen), leden en KBO-patches."""
    g = _OpGraph(Path(nt_path))
    index = build_name_index(gemeenten)
    gem_ids = set(gemeenten['entity_id']) if gemeenten is not None and len(gemeenten) else set()
    source_date = source_date or date.today().isoformat()

    successors: dict[str, list[str]] = defaultdict(list)
    for ev in [s for s, t in g.types.items() if _T_CHANGE in t]:
        for orig in g.p['original'].get(ev, []):
            for res in g.p['resulting'].get(ev, []):
                if res != orig:
                    successors[orig].append(res)

    orgs = [s for s, t in g.types.items() if _T_ORG in t]
    kept = {s: KIND_BY_CLASS[g.cls(s)] for s in orgs if g.cls(s) in KIND_BY_CLASS and g.active(s)}
    n_starting = sum(1 for s in orgs if g.cls(s) in KIND_BY_CLASS
                     and g.label(g.one('status', s)).strip().lower() == 'in oprichting')
    if g.stats['bad']:
        log.warning('OP-dump: %d onleesbare statements overgeslagen', g.stats['bad'])
    if not kept:
        msg = (f'geen actieve organisaties van de gezochte soorten herkend in {len(orgs)} '
               f'bestuurseenheden ({g.stats["bad"]} onleesbare statements); formaat gewijzigd?')
        log.error('OP-dump: %s', msg)
        bundle = SourceBundle.empty()
        bundle.status.append(SourceStatus('be_op', False, 0, source_date, msg))
        return bundle
    ids = {s: _op_entity_id(g, s) for s in kept}
    unresolved: list[str] = []
    # Botsingsregel voor kale districtsnamen: niet gelijk aan een gemeente- of provincienaam
    taken_names = set(index) | {name_key(g.label(s)) for s in orgs if g.cls(s) in ('gemeente', 'provincie')}

    def gemeente_id(s):
        code = g.nis(s)
        if code and (not gem_ids or make_entity_id('BE', 'NIS', code) in gem_ids):
            return make_entity_id('BE', 'NIS', code)
        return _lookup(index, g.label(s)) or _lookup(index, g.name(s))

    def follow(s):
        """Opgeheven organisatie -> actieve rechtsopvolger (fusie), max. 5 stappen."""
        seen = set()
        while not g.active(s) and s not in seen and len(seen) < 5:
            seen.add(s)
            nxt = [x for x in dict.fromkeys(successors.get(s, [])) if g.cls(x) == g.cls(s)]
            if len(nxt) != 1:
                return None
            s = nxt[0]
        return s if g.active(s) else None

    def resolve(member):
        """(entity_id, kind) van een lid of None."""
        cur = follow(member)
        cls = g.cls(member)
        if cur is None:
            unresolved.append(f'{g.label(member)} ({cls}, opgeheven zonder eenduidige opvolger)')
            return None
        if cls in ('gemeente', 'ocmw'):
            eid = gemeente_id(cur)
            if eid is None:
                unresolved.append(f'{g.label(cur)} ({cls})')
                return None
            return eid, 'be_gemeente'
        if cls == 'provincie':
            code = g.nis(cur)
            return (make_entity_id('BE', 'NIS', code), 'be_provincie') if code else None
        if cur in kept:
            return ids[cur], kept[cur]
        return None

    memberships: dict[str, list[tuple[str, str]]] = defaultdict(list)   # org -> [(rol, lid)]
    for m in [s for s, t in g.types.items() if _T_MEMBERSHIP in t]:
        org, member = g.one('organization', m), g.one('member', m)
        role = g.label(g.one('role', m)).strip().lower()
        if org in kept and member and role in _MEMBER_ROLES:
            memberships[org].append((role, member))

    rows, members, aliases = [], {}, []
    for s, kind in kept.items():
        eid = ids[s]
        name = g.name(s)
        bare = []
        if kind == 'be_district' and not name.lower().startswith('district'):
            bare = [name] if name_key(name) not in taken_names else []
            name = f'District {name}'
        rows.append(new_entity(
            entity_id=eid, name=name, country='BE', kind=kind,
            population_method=METHOD_BY_KIND[kind], official_ids=f'kbo:{g.kbo(s)}' if g.kbo(s) else '',
            source=OP_SOURCE, source_date=source_date))
        alts = [g.label(s)] + [re.sub(r'^\d{3,5}\s+', '', a) for a in g.p['altLabel'].get(s, [])]
        if kind == 'be_district':
            alts = bare + [a for a in alts if name_key(a) not in taken_names]
        aliases.extend(_alias_rows(eid, name, alts, 'andere naam (OP-dump)'))
        if kind == 'be_agb':
            ordered = sorted(memberships.get(s, []), key=lambda rm: _MEMBER_ROLES.index(rm[0]))
            targets = [r for r in (resolve(mem) for _, mem in ordered) if r and r[1] == 'be_gemeente']
            if not targets and g.nis(s):
                fallback = make_entity_id('BE', 'NIS', g.nis(s))
                targets = [(fallback, 'be_gemeente')] if not gem_ids or fallback in gem_ids else []
            distinct = list(dict.fromkeys(t[0] for t in targets))
            if len(distinct) > 1:
                log.warning('OP: AGB %s gekoppeld aan meerdere gemeenten %s; eerste genomen', name, distinct)
            if not distinct:
                log.warning('OP: AGB %s zonder gemeente; bevolking onbekend', name)
                continue
            members[(eid, distinct[0])] = {'entity_id': eid, 'member_entity_id': distinct[0],
                                           'member_kind': 'be_gemeente', 'membership_type': 'same_as',
                                           'join_date': ''}
            continue
        for _, mem in memberships.get(s, []):
            r = resolve(mem)
            if r is None or r[0] == eid:
                continue
            members[(eid, r[0])] = {'entity_id': eid, 'member_entity_id': r[0], 'member_kind': r[1],
                                    'membership_type': 'cooperation', 'join_date': ''}

    # KBO-nummers van gemeenten en provincies als id-patch op de Wikidata-entiteiten
    patches = {}
    for s in orgs:
        cls = g.cls(s)
        if cls not in ('gemeente', 'provincie') or not g.active(s) or not g.kbo(s):
            continue
        eid = gemeente_id(s) if cls == 'gemeente' else (
            make_entity_id('BE', 'NIS', g.nis(s)) if g.nis(s) else None)
        if eid is None:
            unresolved.append(f'{g.label(s)} (KBO-patch {cls})')
            continue
        patches[eid] = {'entity_id': eid, 'official_ids': f'kbo:{g.kbo(s)}'}

    if unresolved:
        uniq = sorted(set(unresolved))
        log.warning('OP: %d leden/gemeenten niet gekoppeld: %s', len(uniq), '; '.join(uniq[:50]))
    if n_starting:
        log.info('OP: %d organisaties "in oprichting" niet opgenomen', n_starting)
    # Bronlacune zichtbaar maken: Vlaamse gemeenten zonder politie- of hulpverleningszone
    flemish_gem = {i for i in gem_ids if is_flemish_nis(i)}
    for zone_kind in ('be_politiezone', 'be_hulpverleningszone'):
        zone_ids = {ids[s] for s, k in kept.items() if k == zone_kind}
        covered = {mid for (eid, mid) in members if eid in zone_ids}
        missing = sorted(flemish_gem - covered)
        if flemish_gem and missing:
            log.warning('OP: %d Vlaamse gemeenten zonder %s-lidmaatschap in de dump: %s',
                        len(missing), zone_kind, ', '.join(missing))
    n_district = sum(1 for v in kept.values() if v == 'be_district')
    if n_district:
        log.warning('OP: %d districten zonder bron voor bevolking (methode unknown)', n_district)

    bundle = SourceBundle.empty()
    bundle.entities = pd.DataFrame(rows, columns=bundle.entities.columns)
    bundle.memberships = pd.DataFrame(list(members.values()), columns=bundle.memberships.columns)
    bundle.aliases = pd.DataFrame(aliases, columns=ALIAS_COLUMNS)
    bundle.extras['id_patches'] = pd.DataFrame(list(patches.values()), columns=_PATCH_COLUMNS)
    counts = bundle.entities['kind'].value_counts().to_dict() if len(rows) else {}
    msg = (', '.join(f'{v} {k}' for k, v in sorted(counts.items())) +
           f'; {len(members)} lidmaatschappen, {len(patches)} KBO-patches, '
           f'{len(set(unresolved))} niet gekoppeld, {g.stats["bad"]} onleesbare statements')
    log.info('OP: %s', msg)
    bundle.status.append(SourceStatus('be_op', True, len(rows), source_date, msg))
    return bundle


def _op_dump_url() -> tuple[str, str]:
    """(download-URL, release-datum) van de nieuwste PublicCacheGraphDump."""
    headers = {'User-Agent': USER_AGENT, 'Accept': 'application/vnd.api+json'}
    params = {'filter[subject]': OP_SUBJECT, 'sort': '-release-date', 'include': 'distributions',
              'page[size]': '1'}
    r = requests.get(OP_DATASETS_URL, params=params, headers=headers, timeout=60)
    r.raise_for_status()
    data = r.json()
    release = data['data'][0]['attributes'].get('release-date', '')
    dist = next(i for i in data.get('included', []) if i['type'] == 'distributions')
    r = requests.get(f'{OP_BASE}/distributions/{dist["id"]}/subject', headers=headers, timeout=60)
    r.raise_for_status()
    file_id = r.json()['data']['id']
    return f'{OP_BASE}/files/{file_id}/download', release[:10]


def load_be_op(cache, gemeenten: pd.DataFrame) -> SourceBundle:
    log.info('OP-dump: licentie niet vermeld in de dataset-metadata (open punt)')
    cached = cache.base_dir / 'be_op_dump.nt'
    try:
        url, release = ('', '')
        if not cache.offline:
            try:
                url, release = _op_dump_url()
            except Exception as e:  # noqa: BLE001
                if not cached.exists():
                    raise
                log.warning('OP-dump: catalogus onbereikbaar (%s); gecachte dump gebruikt', e)
        path = cache.fetch('be_op_dump', url, suffix='.nt') if url else cached
        if not path.exists():
            raise FileNotFoundError(f'Offline en niet in cache: {path}')
        source_date = release or date.fromtimestamp(path.stat().st_mtime).isoformat()
        return parse_op_dump(path, gemeenten, source_date=source_date)
    except Exception as e:  # noqa: BLE001
        log.error('OP-dump mislukt: %s', e)
        bundle = SourceBundle.empty()
        bundle.status.append(SourceStatus('be_op', False, 0, '', f'mislukt: {e}'))
        return bundle


# ---------------------------------------------------------------------------
# Wallonie en Brussel
# ---------------------------------------------------------------------------
SPW_URL = 'https://interieur.wallonie.be/files/documents/institutionnel/cadastre-{year}-interco-et-slsp.xlsx'
SPW_SOURCE = 'SPW cadastre intercommunales'
_PZ_SOURCE = 'step2_enrich.BE_POLITIEZONE_GEMEENTEN (nl.wikipedia, 2026-05-11)'


def _spw_file(cache):
    if not cache.offline:
        this_year = date.today().year
        for year in (this_year, this_year - 1):
            try:
                return cache.fetch(f'be_spw_cadastre_{year}', SPW_URL.format(year=year), suffix='.xlsx')
            except Exception as e:  # noqa: BLE001
                log.info('SPW-kadaster %s niet beschikbaar (%s)', year, e)
    cached = sorted(cache.base_dir.glob('be_spw_cadastre*.xlsx'), reverse=True)
    if not cached:
        raise FileNotFoundError('SPW-kadaster niet beschikbaar (online noch in cache)')
    return cached[0]


def parse_spw_intercommunales(xlsx_path: Path) -> list[str]:
    """Namen uit kolom A van het blad 'Intercommunales' (rij 1 = kop)."""
    with warnings.catch_warnings():
        # Het SPW-bestand heeft een printbereik op een tabelnaam; openpyxl waarschuwt onschuldig
        warnings.filterwarnings('ignore', message='Print area cannot be set', category=UserWarning)
        wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    try:
        sheet = next(ws for ws in wb.worksheets if ws.title.strip().lower().startswith('intercommunale'))
        names = []
        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            if i == 0 or not row or row[0] is None:
                continue
            name = re.sub(r'\s+', ' ', str(row[0])).strip()
            if name and name not in names:
                names.append(name)
        return names
    finally:
        wb.close()


def _resolve_members(index, names, context, prefer=None):
    ids, missing = [], []
    for n in names:
        eid = _lookup(index, n, prefer)
        (ids.append(eid) if eid else missing.append(n))
    if missing:
        log.warning('%s: gemeenten niet gevonden: %s', context, ', '.join(missing))
    return list(dict.fromkeys(ids)), missing


def _coop_rows(eid, member_ids):
    return [{'entity_id': eid, 'member_entity_id': m, 'member_kind': 'be_gemeente',
             'membership_type': 'cooperation', 'join_date': ''} for m in member_ids]


def _hand_row(row, name, kind, method):
    pop = row.get('population')
    if method == 'own' and pop is None:
        method = 'unknown'
    return new_entity(
        entity_id=row['id'], name=name, country='BE', kind=kind, population=pop,
        population_method=method, population_source=row['bron_url'] if pop is not None else '',
        population_date=str(row.get('peildatum', '')) if pop is not None else '',
        source=row['bron_url'], source_date=str(row.get('peildatum', '')))


def load_be_wb(cache, gemeenten: pd.DataFrame, flemish_nis: set[str]) -> SourceBundle:
    index = build_name_index(gemeenten)
    flemish = {_nis(c) for c in flemish_nis}
    index_ids = set().union(*index.values()) if index else set()
    first_name = {}
    if gemeenten is not None and len(gemeenten):
        first_name = dict(gemeenten.drop_duplicates('entity_id')[['entity_id', 'name']].values)

    def not_flemish(eid):
        # Naam in W/B-bronnen met twee kandidaten (Saint-Nicolas = ook Sint-Niklaas in het Frans)
        return _nis(eid) not in flemish

    run_date = date.today().isoformat()
    rows, members, aliases, notes = [], [], [], []

    # Politiezones W/B uit de step2-tabel; zones met een Vlaams lid komen uit de OP-dump
    n_pz = n_fl = n_empty = 0
    for key, names in BE_POLITIEZONE_GEMEENTEN.items():
        ids, _ = _resolve_members(index, names, f'Politiezone {key}', not_flemish)
        codes = [_nis(i) for i in ids]
        if any(c in flemish for c in codes):
            n_fl += 1
            continue
        if not ids:
            n_empty += 1
            log.warning('Politiezone %s: geen enkel lid gevonden; overgeslagen', key)
            continue
        brussels = all(c.startswith('21') for c in codes)
        prefix, other = ('PZ', 'ZP') if brussels else ('ZP', 'PZ')
        eid = make_entity_id('BE', 'HAND', 'PZ-' + slugify(key))
        rows.append(new_entity(entity_id=eid, name=f'{prefix} {key}', country='BE', kind='be_politiezone',
                               population_method='sum of members', source=_PZ_SOURCE, source_date='2026-05-11'))
        aliases.extend(_alias_rows(eid, f'{prefix} {key}', [f'{other} {key}'], 'andere naam (taal)'))
        members.extend(_coop_rows(eid, ids))
        n_pz += 1
    notes.append(f'{n_pz} W/B-politiezones ({n_fl} met Vlaams lid overgeslagen, {n_empty} zonder leden; '
                 f'tabel heeft {len(BE_POLITIEZONE_GEMEENTEN)} zones)')
    # Dekking: niet-Vlaamse gemeenten zonder W/B-politiezone (tegenhanger van de OP-controle)
    wb_gem = {i for i in index_ids if not is_flemish_nis(i)}
    covered = {m['member_entity_id'] for m in members}
    missing = sorted(wb_gem - covered)
    if missing:
        log.warning('W/B: %d niet-Vlaamse gemeenten zonder politiezone: %s', len(missing),
                    ', '.join(f'{i} ({first_name.get(i, "")})' for i in missing))
        notes.append(f'{len(missing)} niet-Vlaamse gemeenten zonder politiezone')

    # Hulpverleningszones W/B (handtabel)
    for name, row in hand_tables.BE_HULPVERLENINGSZONES_WB.items():
        ids, _ = _resolve_members(index, row['members'], name, not_flemish)
        rows.append(_hand_row(row, name, 'be_hulpverleningszone', 'sum of members'))
        aliases.extend(_alias_rows(row['id'], name, row.get('aliases', []), 'andere naam (handtabel)'))
        members.extend(_coop_rows(row['id'], ids))
    notes.append(f'{len(hand_tables.BE_HULPVERLENINGSZONES_WB)} W/B-hulpverleningszones')

    # Waalse intercommunales (SPW-kadaster)
    try:
        spw = parse_spw_intercommunales(_spw_file(cache))
        for name in spw:
            # id op de volledige naam (stabiel); match_name zonder toelichting tussen haakjes
            match_name = re.sub(r'\s*\([^)]*\)', '', name).strip() or name
            rows.append(new_entity(
                entity_id=make_entity_id('BE', 'SPW', slugify(name)), name=name, match_name=match_name,
                country='BE', kind='be_intercommunale', population_method='unknown', source=SPW_SOURCE,
                source_date=run_date))
        notes.append(f'{len(spw)} Waalse intercommunales')
    except Exception as e:  # noqa: BLE001
        log.error('SPW-kadaster mislukt: %s', e)
        notes.append(f'Waalse intercommunales ontbreken ({e})')

    for name, row in hand_tables.BE_INTERCOMMUNALES_BXL.items():
        rows.append(_hand_row(row, name, 'be_intercommunale', 'unknown'))
        aliases.extend(_alias_rows(row['id'], name, row.get('aliases', []), 'andere naam (handtabel)'))
    for name, row in hand_tables.BE_GEWESTEN.items():
        rows.append(_hand_row(row, name, 'be_gewest', 'own'))
        aliases.extend(_alias_rows(row['id'], name, row.get('aliases', []), 'andere naam (handtabel)'))
        if row.get('population') is None:
            log.warning('%s: geen officieel bevolkingscijfer (bevolking onbekend)', name)
    for name, row in hand_tables.BE_FOD.items():
        rows.append(_hand_row(row, name, 'be_fod', 'country total'))
        aliases.extend(_alias_rows(row['id'], name, row.get('aliases', []), 'andere naam (handtabel)'))
    notes.append(f'{len(hand_tables.BE_INTERCOMMUNALES_BXL)} Brusselse intercommunales, '
                 f'{len(hand_tables.BE_GEWESTEN)} gewesten/gemeenschappen, {len(hand_tables.BE_FOD)} FOD/POD')

    bundle = SourceBundle.empty()
    bundle.entities = pd.DataFrame(rows, columns=bundle.entities.columns)
    bundle.memberships = pd.DataFrame(members, columns=bundle.memberships.columns)
    bundle.aliases = pd.DataFrame(aliases, columns=ALIAS_COLUMNS)
    msg = '; '.join(notes)
    log.info('BE W/B: %s', msg)
    bundle.status.append(SourceStatus('be_wb', True, len(rows), run_date, msg))
    return bundle
