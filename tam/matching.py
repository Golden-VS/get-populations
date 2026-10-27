"""CRM-scope, kandidaten, regelgebaseerde matching (pass 1), AI-matching (pass 2) en overrides.

Pass 2 gebruikt `candidates()` en `entities_by_country()`; `pass2_pending()` en
`estimate_matching_cost()` geven de CLI het aantal AI-accounts en de kostenschatting vooraf.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel
from rapidfuzz import fuzz, process

from step2_enrich import _plz_prefix_score, normalize
from tam.ai import AIBatchError, AIRefusal, CostCapReached, call_parsed, estimate_cost
from tam.config import CRM_COUNTRY_TO_TAM, REFERENCE_DIR

log = logging.getLogger(__name__)

MATCH_COLUMNS = ['entity_id', 'accountid', 'crm_name', 'match_pass', 'match_reason', 'confidence']
UNMATCHED_COLUMNS = ['accountid', 'crm_name', 'tam_country', 'best_candidate', 'best_score', 'reason']

# detected_type (stap 1) -> verenigbare entity-kinds; ontbrekend type = lege set
TYPE_TO_KINDS: dict[str, set[str]] = {
    'gemeente_nl': {'nl_gemeente'},
    'stadsdeel': {'nl_stadsdeel', 'be_district'},
    'deelgemeente': {'nl_stadsdeel', 'be_district'},
    'provincie_nl': {'nl_provincie'},
    'waterschap': {'nl_waterschap'},
    'veiligheidsregio': {'nl_veiligheidsregio'},
    'omgevingsdienst': {'nl_samenwerking'},
    'samenwerking': {'nl_samenwerking'},
    'samenwerking_nl': {'nl_samenwerking'},
    'belastingsamenwerking': {'nl_samenwerking'},
    'ggd': {'nl_samenwerking'},
    'stadsregio': {'nl_samenwerking'},
    'ministerie': {'nl_ministerie', 'nl_rijksorganisatie'},
    'rijksoverheid': {'nl_ministerie', 'nl_rijksorganisatie'},
    'land': {'nl_land_caribisch', 'nl_openbaar_lichaam'},
    'gemeente_be': {'be_gemeente'},
    'ocmw': {'be_gemeente'},
    'agb': {'be_agb'},
    'politiezone': {'be_politiezone'},
    'hulpverleningszone': {'be_hulpverleningszone'},
    'intercommunale': {'be_samenwerking', 'be_intercommunale', 'be_welzijnsvereniging'},
    'provincie_be': {'be_provincie'},
    'fod_be': {'be_fod'},
    'gemeinde_de': {'de_gemeinde', 'de_kreisfreie_stadt', 'de_stadtstaat', 'de_bezirk',
                    'de_gemeindeverband'},
    'landkreis': {'de_landkreis'},
    'landratsamt': {'de_landkreis'},
    'verbandsgemeinde': {'de_gemeindeverband', 'de_gemeinde'},
    'amt': {'de_gemeindeverband', 'de_gemeinde'},
    'verwaltungsgemeinschaft': {'de_gemeindeverband', 'de_gemeinde'},
    'zweckverband': {'de_zweckverband', 'de_it_zweckverband'},
}
# Primaire kind per type: bij meerdere naamtreffers gaan deze voor (R15), zodat een
# Verbandsgemeinde niet op haar gelijknamige zetelgemeente valt en omgekeerd
PRIMARY_KINDS: dict[str, set[str]] = {
    'verbandsgemeinde': {'de_gemeindeverband'},
    'amt': {'de_gemeindeverband'},
    'verwaltungsgemeinschaft': {'de_gemeindeverband'},
    'gemeinde_de': {'de_gemeinde', 'de_kreisfreie_stadt'},
    'landkreis': {'de_landkreis'},
    'landratsamt': {'de_landkreis'},
}
# Overheidstypes = alle types met verenigbare kinds (bepalen mede de prioriteit)
GOV_TYPES = frozenset(TYPE_TO_KINDS)
GOV_SEGMENT_CATEGORIES = {'Governmental', 'Unknown', 'Non-profit'}

# Prefixen die uit de CRM-naam gaan voor de naamsleutel (na normalize, dus kleine letters)
_NAME_PREFIXES = [
    'commune de', 'ville de', 'samtgemeinde', 'verbandsgemeinde', 'landkreis', 'gemeente',
    'provincie', 'province', 'stadt', 'stad', 'kreis', 'ocmw', 'cpas', 'amt', 'markt',
]
_PREFIX_RE = re.compile(r'^(?:' + '|'.join(re.escape(p) for p in _NAME_PREFIXES) + r')\s+')

MAX_CANDIDATES = 15
FUZZY_FLOOR = {'gov': 75, 'other': 90}
RULE_REASON_ID = 'KvK/KBO-nummer'
RULE_REASON_POSTCODE = 'naam + postcode'


def _blank(value) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip() == ''


def _text(value) -> str:
    return '' if _blank(value) else str(value).strip()


# ---------- CRM inlezen en scope ----------

def load_crm(path: Path) -> pd.DataFrame:
    """CRM-bestand (stap 1b-output) als tekst, zodat KvK-nummers hun voorloopnullen houden."""
    path = Path(path)
    if path.suffix.lower() == '.csv':
        return pd.read_csv(path, dtype=str)
    return pd.read_excel(path, dtype=str)


def _priority(row) -> str:
    category = _text(row.get('Segment (category)')) or 'Unknown'
    if category in GOV_SEGMENT_CATEGORIES or _text(row.get('detected_type')) in GOV_TYPES:
        return 'gov'
    return 'other'


def crm_in_scope(crm: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(in_scope, out_of_scope_gov).

    in_scope: NL/BE/DE/Caribisch, zonder zeker-commerciele accounts; extra kolommen
    `tam_country` en `priority` (gov/other).
    out_of_scope_gov: buitenlandse (OTHER) Governmental-accounts in het unmatched-schema.
    """
    country = crm['detected_country'].map(lambda v: _text(v).upper())
    category = crm['Segment (category)'].map(_text)
    commercial = (
        (crm['detected_type'].map(_text) == 'commercieel_of_overig')
        & (category == 'Commercial')
        & (crm['segment_confidence'].map(lambda v: _text(v).lower()) == 'high')
    )
    in_country = country.isin(CRM_COUNTRY_TO_TAM.keys())
    scope = crm[in_country & ~commercial].copy()
    log.info('CRM-scope: %d accounts met onbekend land of land buiten scope (OTHER of leeg) '
             'weggelaten, %d zeker-commerciele accounts weggelaten',
             int((~in_country).sum()), int((in_country & commercial).sum()))
    scope['tam_country'] = country[scope.index].map(CRM_COUNTRY_TO_TAM)
    scope['priority'] = [_priority(r) for _, r in scope.iterrows()] if len(scope) else []

    foreign = crm[(country == 'OTHER') & (category == 'Governmental')]
    out_gov = pd.DataFrame({
        'accountid': foreign['accountid'].values,
        'crm_name': foreign['name'].values,
        'tam_country': '',
        'best_candidate': '',
        'best_score': None,
        'reason': 'land buiten scope',
    }, columns=UNMATCHED_COLUMNS)
    log.info('CRM-scope: %d accounts in scope, %d buitenlandse overheidsaccounts buiten scope',
             len(scope), len(out_gov))
    return scope, out_gov


# ---------- normalisatie ----------

def normalize_company_number(value, country: str) -> str | None:
    """NL: 8 cijfers (KvK); BE: 10 cijfers (KBO, 9 cijfers krijgt een voorloop-0); DE: None."""
    if _blank(value) or country not in ('NL', 'BE'):
        return None
    s = str(value).strip()
    s = re.sub(r'\.0$', '', s) if re.fullmatch(r'\d+\.0', s) else s
    if country == 'BE':
        s = re.sub(r'^be', '', s.strip(), flags=re.IGNORECASE)
        s = re.sub(r'[.\s]', '', s)
        if len(s) == 9:
            s = '0' + s
        return s if re.fullmatch(r'\d{10}', s) else None
    s = re.sub(r'\s', '', s)
    if re.fullmatch(r'\d{7}', s):
        s = '0' + s  # voorloopnul verloren in Excel; KvK heeft altijd 8 cijfers (R14)
    return s if re.fullmatch(r'\d{8}', s) else None


def _strip_prefix(normalized: str) -> str:
    """Prefix weg van een al genormaliseerde naam, daarna opnieuw normaliseren (lidwoord)."""
    return normalize(_PREFIX_RE.sub('', normalized))


def crm_name_key(row) -> str:
    """canonical_name (of anders name) zonder bestuursprefix, genormaliseerd."""
    name = _text(row.get('canonical_name')) or _text(row.get('name'))
    return _strip_prefix(normalize(name))


_PLZ_RE = re.compile(r'(?<!\d)\d{5}(?!\d)')


def _crm_postcode(row) -> str:
    """DE-postcode: cx_address3_postalcode, anders een los 5-cijferig getal uit address1_composite."""
    raw = _text(row.get('cx_address3_postalcode'))
    if re.fullmatch(r'\d{4}', raw):
        raw = '0' + raw  # voorloopnul verloren in Excel
    m = _PLZ_RE.search(raw) or _PLZ_RE.search(_text(row.get('address1_composite')))
    return m.group(0) if m else ''


def _plz_closeness(crm_plz: str, entity_postcode) -> int:
    """Gemeenschappelijke prefixlengte (5 = gelijke postcode), via step2_enrich."""
    return _plz_prefix_score(crm_plz, _text(entity_postcode))


# ---------- naamindex ----------

def build_name_index(entities, aliases) -> dict[tuple[str, str], list[tuple[str, str, str]]]:
    """(land, normalize(naam)) -> [(entity_id, kind, reden)].

    Entiteiten: sleutel normalize(match_name), plus de variant zonder bestuursprefix
    (zodat 'Amt X' ook onder 'x' staat); reden 'same name'. Aliassen: sleutel
    normalize(alias_name) (plus prefixvrije variant), kind van de doelentiteit, reden
    uit de aliasrij. Aliassen naar een onbekende entiteit worden overgeslagen.
    """
    index: dict[tuple[str, str], list[tuple[str, str, str]]] = {}

    def add(country, name, hit):
        norm = normalize(_text(name))
        for key in dict.fromkeys([norm, _strip_prefix(norm)]):
            if not key:
                continue
            bucket = index.setdefault((country, key), [])
            if all(h[0] != hit[0] for h in bucket):
                bucket.append(hit)

    kinds: dict[str, str] = {}
    for row in entities.itertuples(index=False):
        kinds[row.entity_id] = row.kind
        add(row.country, _text(row.match_name) or _text(row.name), (row.entity_id, row.kind, 'same name'))
    if aliases is not None:
        for row in aliases.itertuples(index=False):
            kind = kinds.get(row.entity_id)
            if kind is None:
                log.warning('Alias %r verwijst naar onbekende entiteit %s; overgeslagen',
                            row.alias_name, row.entity_id)
                continue
            add(row.country, row.alias_name, (row.entity_id, kind, _text(row.reason) or 'alias'))
    return index


def _lookup(index, country: str, keys) -> list[tuple[str, str, str]]:
    hits: list[tuple[str, str, str]] = []
    seen = set()
    for key in keys:
        for hit in index.get((country, key), []):
            if hit[0] not in seen:
                seen.add(hit[0])
                hits.append(hit)
    return hits


def _company_index(entities) -> dict[tuple[str, str], list[str]]:
    """(land, genormaliseerd KvK/KBO-nummer) -> entity_ids uit official_ids."""
    out: dict[tuple[str, str], list[str]] = {}
    for row in entities.itertuples(index=False):
        for part in _text(row.official_ids).split(';'):
            scheme, _, value = part.partition(':')
            scheme = scheme.strip().lower()
            country = {'kvk': 'NL', 'kbo': 'BE'}.get(scheme)
            number = normalize_company_number(value, country) if country else None
            if number:
                ids = out.setdefault((country, number), [])
                if row.entity_id not in ids:
                    ids.append(row.entity_id)
    return out


# ---------- pass 1 ----------

def _rule_match(row, index, company_index, postcode_by_id):
    """(entity_id, reden) of None voor een CRM-rij volgens de regels van pass 1."""
    country = row['tam_country']
    allowed = TYPE_TO_KINDS.get(_text(row.get('detected_type')), set())

    # 1. KvK/KBO-nummer; een nummer dat bij meer dan een entiteit hoort matcht nooit (R13)
    number = normalize_company_number(row.get('cx_kvknummer'), country)
    if number:
        ids = company_index.get((country, number), [])
        if len(ids) == 1:
            return ids[0], RULE_REASON_ID

    # 2. naam binnen verenigbare kinds; zonder kinds de ruwe naam tegen alle kinds
    detected_type = _text(row.get('detected_type'))
    raw = normalize(_text(row.get('name')))
    if allowed:
        hits = [h for h in _lookup(index, country, [crm_name_key(row), raw]) if h[1] in allowed]
    else:
        hits = _lookup(index, country, [raw])
    # bij meerdere treffers gaat de primaire kind van het CRM-type voor (R15)
    primary = PRIMARY_KINDS.get(detected_type)
    if len(hits) > 1 and primary:
        preferred = [h for h in hits if h[1] in primary]
        if preferred:
            hits = preferred
    if len(hits) == 1:
        return hits[0][0], hits[0][2]

    # 3. DE: meerdere gelijknamige treffers van dezelfde kind, beslissen op postcode;
    #    gemengde kinds gaan naar pass 2
    if len(hits) > 1 and country == 'DE' and len({h[1] for h in hits}) == 1:
        plz = _crm_postcode(row)
        if plz:
            exact = [h for h in hits if _plz_closeness(plz, postcode_by_id.get(h[0])) == 5]
            if not exact:
                exact = [h for h in hits if _plz_closeness(plz, postcode_by_id.get(h[0])) >= 3]
            if len(exact) == 1:
                return exact[0][0], RULE_REASON_POSTCODE
    return None


def pass1(crm_scope, entities, index) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(matched, rest): regelgebaseerde matches en de overige in-scope rijen (alle kolommen)."""
    company_index = _company_index(entities)
    postcode_by_id = dict(zip(entities['entity_id'], entities['postcode']))
    matched = []
    rest_idx = []
    for idx, row in crm_scope.iterrows():
        found = _rule_match(row, index, company_index, postcode_by_id)
        if found is None:
            rest_idx.append(idx)
            continue
        entity_id, reason = found
        matched.append({'entity_id': entity_id, 'accountid': row['accountid'],
                        'crm_name': _text(row.get('name')), 'match_pass': 'rule',
                        'match_reason': reason, 'confidence': 'high'})
    log.info('Pass 1: %d accounts gematcht op regels, %d over voor pass 2', len(matched), len(rest_idx))
    return pd.DataFrame(matched, columns=MATCH_COLUMNS), crm_scope.loc[rest_idx].copy()


# ---------- kandidaten (voor pass 2) ----------

_CHOICE_COLUMNS = ['entity_id', 'name', 'kind', 'region', 'postcode', 'via', 'key', 'norm']


@dataclass
class CountryChoices:
    """Keuzetabel van een land voor `candidates()`, met voorberekende lijsten voor rapidfuzz.

    `frame`: een rij per entiteitsnaam (via 'naam') en per alias (via 'alias: <alias>, <reden>'),
    kolommen entity_id, name, kind, region, postcode, via, key (prefixvrij genormaliseerd),
    norm (genormaliseerd). `info`: entity_id -> entity_id/name/kind/region/postcode.
    """
    frame: pd.DataFrame
    info: dict
    choices: list = field(init=False)
    entity_ids: list = field(init=False)
    vias: list = field(init=False)
    norms: list = field(init=False)
    alias_pos: dict = field(init=False)

    def __post_init__(self):
        self.choices = self.frame['key'].tolist()
        self.entity_ids = self.frame['entity_id'].tolist()
        self.vias = self.frame['via'].tolist()
        self.norms = self.frame['norm'].tolist()
        self.alias_pos = {}
        for pos, (eid, via) in enumerate(zip(self.entity_ids, self.vias)):
            if via != 'naam':
                self.alias_pos.setdefault(eid, []).append(pos)

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> 'CountryChoices':
        info = {r.entity_id: {'entity_id': r.entity_id, 'name': r.name, 'kind': r.kind,
                              'region': r.region, 'postcode': r.postcode}
                for r in frame[frame['via'] == 'naam'].itertuples(index=False)}
        return cls(frame, info)


def entities_by_country(entities, aliases=None) -> dict[str, CountryChoices]:
    """Per land een `CountryChoices` (keuzetabel + voorberekende lijsten) voor `candidates()`.

    Zonder `aliases` bevat de tabel alleen entiteitsnamen; geef de aliassen mee zodat
    aliasnamen ook fuzzy gevonden worden.
    """
    out: dict[str, CountryChoices] = {}
    alias_rows = aliases if aliases is not None else pd.DataFrame(
        columns=['alias_name', 'country', 'entity_id', 'reason'])
    for country, group in entities.groupby('country'):
        info = {}
        rows = []
        for e in group.itertuples(index=False):
            base = {'entity_id': e.entity_id, 'name': _text(e.name), 'kind': _text(e.kind),
                    'region': _text(e.region), 'postcode': _text(e.postcode)}
            info[e.entity_id] = base
            norm = normalize(_text(e.match_name) or _text(e.name))
            rows.append({**base, 'via': 'naam', 'key': _strip_prefix(norm), 'norm': norm})
        for a in alias_rows[alias_rows['country'] == country].itertuples(index=False):
            base = info.get(a.entity_id)
            if base is None:
                continue
            reason = _text(a.reason)
            via = f'alias: {_text(a.alias_name)}' + (f', {reason}' if reason else '')
            norm = normalize(_text(a.alias_name))
            rows.append({**base, 'via': via, 'key': _strip_prefix(norm), 'norm': norm})
        out[country] = CountryChoices(pd.DataFrame(rows, columns=_CHOICE_COLUMNS), info)
    return out


def candidates(row, entities_by_country, index, k=10) -> list[dict]:
    """Kandidaat-entiteiten voor een CRM-rij (zelfde land), maximaal 15.

    Eerst elke exacte naam-/aliastreffer (elk kind, score 100), dan de top-k op
    fuzz.token_set_ratio van de prefixvrije naam (drempel 75 voor priority 'gov',
    90 voor 'other'). DE: binnen gelijke score gesorteerd op postcodenabijheid.
    Zijn er meer dan 15 exacte treffers, dan blijven de 15 met de dichtste postcode.
    """
    country = _text(row.get('tam_country'))
    prep = entities_by_country.get(country)
    if prep is None:
        return []
    if isinstance(prep, pd.DataFrame):
        log.warning('candidates(): keuzetabel voor %s is niet voorberekend (gebruik '
                    'entities_by_country); wordt per aanroep opgebouwd', country)
        prep = CountryChoices.from_frame(prep)
    if not prep.entity_ids:
        return []
    info = prep.info
    key = crm_name_key(row)
    raw = normalize(_text(row.get('name')))
    lookup_keys = [k_ for k_ in dict.fromkeys([key, raw]) if k_]
    plz = _crm_postcode(row) if country == 'DE' else ''

    def closeness(entity_id):
        return _plz_closeness(plz, info[entity_id]['postcode']) if plz else 0

    # exacte treffers (elk kind)
    exact = []
    seen_ids = set()
    for lookup_key in lookup_keys:
        for entity_id, _kind, reason in index.get((country, lookup_key), []):
            if entity_id not in info or entity_id in seen_ids:
                continue
            seen_ids.add(entity_id)
            via = 'naam'
            if reason != 'same name':
                # aliastekst uit de keuzetabel; zonder aliassen daar de gevonden (genormaliseerde) naam
                via = next((prep.vias[p] for p in prep.alias_pos.get(entity_id, [])
                            if prep.norms[p] == lookup_key or prep.choices[p] == lookup_key),
                           f'alias: {lookup_key}, {reason}')
            exact.append({**info[entity_id], 'score': 100, 'via': via})
    exact.sort(key=lambda c: -closeness(c['entity_id']))

    # fuzzy top-k (unieke entiteiten, beste naam/alias per entiteit)
    fuzzy: dict[str, dict] = {}
    if key:
        floor = FUZZY_FLOOR.get(_text(row.get('priority')), FUZZY_FLOOR['other'])
        seen_exact = {c['entity_id'] for c in exact}
        for _choice, score, pos in process.extract(key, prep.choices, scorer=fuzz.token_set_ratio,
                                                   score_cutoff=floor, limit=None):
            entity_id = prep.entity_ids[pos]
            if entity_id in seen_exact:
                continue
            score = int(round(score))
            prev = fuzzy.get(entity_id)
            if prev is None or score > prev['score']:
                fuzzy[entity_id] = {**info[entity_id], 'score': score, 'via': prep.vias[pos]}
    ranked = sorted(fuzzy.values(), key=lambda c: (-c['score'], -closeness(c['entity_id'])))[:k]
    return (exact + ranked)[:MAX_CANDIDATES]


# ---------- pass 2 (AI) ----------

MATCH_CACHE_COLUMNS = ['accountid', 'name', 'candidate_hash', 'entity_id', 'reason',
                       'confidence', 'datum']
NONE_ID = 'none'
REASON_NO_CANDIDATE = 'geen kandidaat boven drempel'
REASON_AI_NONE = 'AI: geen passende organisatie'
REASON_NO_AI = 'AI overgeslagen (--no-ai)'
REASON_CAP = 'kostenplafond bereikt'
REASON_REFUSED = 'AI weigerde'
REASON_FAILED = 'AI-fout'
# Grove schatting per batch van 20 accounts met ~10 kandidaten (invoer incl. systeemprompt, uitvoer)
EST_IN_TOKENS_PER_BATCH = 6000
EST_OUT_TOKENS_PER_BATCH = 2500

MATCH_SYSTEM_PROMPT = """Je bent een analist overheidsdata. Je koppelt CRM-accounts (klantrecords
uit een CRM-systeem) aan officiele overheidsorganisaties in Nederland, Belgie en Duitsland.
Namen kunnen Nederlands, Frans, Duits of Engels zijn.

Elk account heeft een volgnummer, de CRM-naam, het door een eerdere stap herkende type,
adres/postcode/plaats en land, plus een lijst kandidaten in de vorm
"id | naam | soort | regio | postcode | via". "via" zegt hoe de kandidaat gevonden is:
"naam" (op de eigen naam) of "alias: <naam>, <reden>" (bv. een voorganger of een lid).

Kies per account precies een kandidaat-id uit de lijst van DAT account, of "none".

REGELS:
- Gebruik alleen ids uit de kandidatenlijst van dat account; verzin nooit een id.
- Een OCMW/CPAS, of een afdeling, dienst of bedrijf-in-eigen-beheer van een gemeente
  (bv. Burgerzaken, Bürgeramt, Stadtverwaltung, Fachbereich), hoort bij die gemeente.
- Een Duitse Ortsgemeinde die in een Amt, Verbandsgemeinde, Samtgemeinde of
  Verwaltungsgemeinschaft zit, hoort bij dat Amt/Verband; die staat dan als
  alias-kandidaat in de lijst.
- Een voorgangergemeente (opgegaan in een fusie) hoort bij haar opvolger; die staat als
  alias-kandidaat met de fusiereden in de lijst.
- Let op de soort: "Veiligheidsregio Zeeland" is niet de provincie Zeeland, een
  Landkreis is niet de gelijknamige Stadt. Kies de kandidaat waarvan de soort past bij
  de organisatie in de CRM-naam; gebruik postcode en regio om gelijke namen te scheiden.
- Commerciele bedrijven (Stadtwerke, GmbH, AG, B.V., NV, BV, SA) zijn "none", tenzij het
  account echt de overheidsorganisatie zelf is.
- Scholen, ziekenhuizen, verenigingen, stichtingen en andere organisaties die geen van
  de kandidaten zijn: "none".
- Twijfel je tussen twee kandidaten, kies dan de beste en geef confidence "low".
- "reason": korte reden (hooguit ~10 woorden), bv. "predecessor municipality, merged 2016",
  "department of", "OCMW van de gemeente", "Ortsgemeinde im Amt", "duplicate account",
  "commercial company".
- "confidence": "high" = zeker, "medium" = waarschijnlijk, "low" = twijfel.
- Geef voor elk volgnummer in de invoer precies een antwoord terug, met hetzelfde volgnummer.
"""


class MatchItem(BaseModel):
    volgnummer: int
    entity_id: str
    reason: str
    confidence: Literal['high', 'medium', 'low']


class MatchBatch(BaseModel):
    items: list[MatchItem]


def estimate_matching_cost(n_accounts: int, batch_size: int = 20) -> float:
    """Geschatte AI-kosten (USD) voor n_accounts die naar pass 2 gaan."""
    return estimate_cost(n_accounts, batch_size, EST_IN_TOKENS_PER_BATCH, EST_OUT_TOKENS_PER_BATCH)


def candidate_hash(cands: list[dict]) -> str:
    """sha1 van de gesorteerde kandidaat-ids (cache-sleutel naast de naam)."""
    return hashlib.sha1(';'.join(sorted(c['entity_id'] for c in cands)).encode('utf-8')).hexdigest()


def _load_match_cache(path) -> dict[str, dict]:
    """accountid -> cacherij; onleesbaar of oud schema = lege cache (met waarschuwing)."""
    if path is None or not Path(path).exists():
        return {}
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        if list(df.columns) != MATCH_CACHE_COLUMNS:
            raise ValueError(f'onverwachte kolommen {list(df.columns)}')
    except Exception as e:
        log.warning('Matchcache onleesbaar of oud schema, negeer cache: %s', e)
        return {}
    return {r['accountid']: r for r in df.to_dict('records')}


def _save_match_cache(path, rows: dict[str, dict]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(list(rows.values()), columns=MATCH_CACHE_COLUMNS).to_csv(path, index=False)


def _cache_hit(cache: dict, accountid: str, name: str, chash: str) -> dict | None:
    hit = cache.get(accountid)
    if hit and hit['name'] == name and hit['candidate_hash'] == chash:
        return hit
    return None


def pass2_pending(rest: pd.DataFrame, entities_by_country, index, *, cache_path=None) -> int:
    """Aantal accounts dat pass 2 naar de AI zou sturen (voor de kostenschatting en --dry-run).

    Telt accounts met minstens een kandidaat; met `cache_path` vallen geldige cachetreffers af.
    """
    cache = _load_match_cache(cache_path)
    n = 0
    for _, row in rest.iterrows():
        cands = candidates(row, entities_by_country, index)
        if not cands:
            continue
        if _cache_hit(cache, _text(row.get('accountid')), _text(row.get('name')),
                      candidate_hash(cands)):
            continue
        n += 1
    return n


def _account_block(n: int, row, cands: list[dict]) -> str:
    country = _text(row.get('tam_country'))
    crm_country = _text(row.get('detected_country')).upper()
    land = country if not crm_country or crm_country == country else f'{country} (CRM: {crm_country})'
    lines = [
        f'volgnummer {n}',
        f"  crm-naam: {_text(row.get('name'))}",
        f"  type: {_text(row.get('detected_type')) or 'onbekend'}",
        f"  adres: {_text(row.get('address1_composite'))} | postcode: "
        f"{_text(row.get('cx_address3_postalcode'))} | plaats: {_text(row.get('cx_address3_city'))}",
        f'  land: {land}',
        '  kandidaten (id | naam | soort | regio | postcode | via):',
    ]
    for c in cands:
        lines.append('    ' + ' | '.join(_text(c.get(k)) for k in
                                         ('entity_id', 'name', 'kind', 'region', 'postcode', 'via')))
    return '\n'.join(lines)


def build_match_message(items: list[tuple]) -> str:
    """items: [(row, kandidaten)] in batchvolgorde; volgnummers 1..n."""
    blocks = [_account_block(n, row, cands) for n, (row, cands) in enumerate(items, start=1)]
    return ('Koppel elk account aan een kandidaat-id uit zijn eigen lijst, of "none".\n\n'
            + '\n\n'.join(blocks))


def pass2(rest: pd.DataFrame, entities, aliases, client, tracker, *, use_ai: bool,
          cache_path: Path = REFERENCE_DIR / 'match_cache.csv', batch_size: int = 20,
          index=None, by_country=None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """AI-matching van de accounts die pass 1 overliet -> (matched, unmatched, stats).

    - Accounts zonder kandidaat gaan nooit naar de AI ('geen kandidaat boven drempel').
    - Cache per accountid, alleen hergebruikt bij gelijke naam en kandidatenset; ook met
      use_ai=False. Alleen echte AI-antwoorden (match of none) worden gecachet, nooit
      fallbacks (weigering, fout, plafond, --no-ai, id buiten de lijst, ontbrekend antwoord).
    - Batches: priority 'gov' eerst (stabiel), zodat een kostenplafond 'other' het laatst raakt.
    - De cache wordt na elke batch weggeschreven.
    `index`/`by_country` mogen voorberekend meegegeven worden (anders hier opgebouwd met aliassen).
    stats['to_ai'] = aantal accounts dat (na cache) naar de AI moest, ook bij use_ai=False.
    """
    if index is None:
        index = build_name_index(entities, aliases)
    if by_country is None:
        by_country = entities_by_country(entities, aliases)
    cache = _load_match_cache(cache_path)
    stats = {'no_candidate': 0, 'cached': 0, 'to_ai': 0, 'ai_matched': 0, 'ai_none': 0,
             'invalid_id': 0, 'no_ai': 0, 'cap': 0, 'refused': 0, 'failed': 0, 'batches': 0}
    results: dict[int, tuple[str, dict]] = {}  # positie in rest -> ('match'|'unmatched', rij)
    pending = []  # (positie, row, kandidaten, hash)

    def unmatched(pos, row, cands, reason):
        best = cands[0] if cands else None
        results[pos] = ('unmatched', {
            'accountid': _text(row.get('accountid')), 'crm_name': _text(row.get('name')),
            'tam_country': _text(row.get('tam_country')),
            'best_candidate': best['name'] if best else '',
            'best_score': best['score'] if best else None, 'reason': reason})

    def matched(pos, row, entity_id, reason, confidence):
        results[pos] = ('match', {
            'entity_id': entity_id, 'accountid': _text(row.get('accountid')),
            'crm_name': _text(row.get('name')), 'match_pass': 'ai', 'match_reason': reason,
            'confidence': confidence})

    for pos, (_, row) in enumerate(rest.iterrows()):
        cands = candidates(row, by_country, index)
        if not cands:
            stats['no_candidate'] += 1
            unmatched(pos, row, cands, REASON_NO_CANDIDATE)
            continue
        chash = candidate_hash(cands)
        hit = _cache_hit(cache, _text(row.get('accountid')), _text(row.get('name')), chash)
        if hit:
            stats['cached'] += 1
            if hit['entity_id'] == NONE_ID:
                unmatched(pos, row, cands, REASON_AI_NONE)
            else:
                matched(pos, row, hit['entity_id'], hit['reason'], hit['confidence'])
            continue
        pending.append((pos, row, cands, chash))

    # gov eerst; sorted() is stabiel
    pending.sort(key=lambda p: _text(p[1].get('priority')) != 'gov')
    stats['to_ai'] = len(pending)
    log.info('Pass 2: %d accounts zonder kandidaat, %d uit cache, %d naar AI',
             stats['no_candidate'], stats['cached'], len(pending))

    if not use_ai:
        for pos, row, cands, _ in pending:
            unmatched(pos, row, cands, REASON_NO_AI)
        stats['no_ai'] = len(pending)
    else:
        est = estimate_matching_cost(batch_size, batch_size)
        for start in range(0, len(pending), batch_size):
            batch = pending[start:start + batch_size]
            user = build_match_message([(row, cands) for _, row, cands, _ in batch])
            try:
                parsed = call_parsed(client, tracker, system=MATCH_SYSTEM_PROMPT, user=user,
                                     output_model=MatchBatch, estimated_cost=est)
            except CostCapReached as e:
                log.warning('Kostenplafond bereikt tijdens matching: %s; %d accounts niet gematcht',
                            e, len(pending) - start)
                for pos, row, cands, _ in pending[start:]:
                    unmatched(pos, row, cands, REASON_CAP)
                stats['cap'] = len(pending) - start
                break
            except AIRefusal as e:
                log.warning('Matchbatch geweigerd (%d accounts): %s', len(batch), e)
                for pos, row, cands, _ in batch:
                    unmatched(pos, row, cands, REASON_REFUSED)
                stats['refused'] += len(batch)
                continue
            except AIBatchError as e:
                log.warning('Matchbatch mislukt (%d accounts): %s', len(batch), e)
                for pos, row, cands, _ in batch:
                    unmatched(pos, row, cands, REASON_FAILED)
                stats['failed'] += len(batch)
                continue
            stats['batches'] += 1
            answers: dict[int, MatchItem] = {}
            for item in parsed.items:
                answers.setdefault(item.volgnummer, item)
            today = date.today().isoformat()
            for n, (pos, row, cands, chash) in enumerate(batch, start=1):
                accountid = _text(row.get('accountid'))
                item = answers.get(n)
                if item is None:
                    log.warning('Matching: geen antwoord voor account %s (volgnummer %d)',
                                accountid, n)
                    unmatched(pos, row, cands, REASON_FAILED)
                    stats['failed'] += 1
                    continue
                entity_id = item.entity_id.strip()
                if entity_id.lower() == NONE_ID:
                    unmatched(pos, row, cands, REASON_AI_NONE)
                    stats['ai_none'] += 1
                    entity_id = NONE_ID
                elif entity_id not in {c['entity_id'] for c in cands}:
                    log.warning('Matching: AI koos %s voor account %s, niet in de kandidatenlijst; '
                                'behandeld als none', entity_id, accountid)
                    unmatched(pos, row, cands, REASON_AI_NONE)
                    stats['invalid_id'] += 1
                    continue
                else:
                    matched(pos, row, entity_id, item.reason, item.confidence)
                    stats['ai_matched'] += 1
                cache[accountid] = {'accountid': accountid, 'name': _text(row.get('name')),
                                    'candidate_hash': chash, 'entity_id': entity_id,
                                    'reason': item.reason, 'confidence': item.confidence,
                                    'datum': today}
            _save_match_cache(cache_path, cache)

    match_rows = [r for _, (kind, r) in sorted(results.items()) if kind == 'match']
    unmatched_rows = [r for _, (kind, r) in sorted(results.items()) if kind == 'unmatched']
    log.info('Pass 2: %d gematcht (AI of cache), %d niet gematcht (geweigerd %d, fout %d, '
             'plafond %d, id buiten lijst %d)', len(match_rows), len(unmatched_rows),
             stats['refused'], stats['failed'], stats['cap'], stats['invalid_id'])
    return (pd.DataFrame(match_rows, columns=MATCH_COLUMNS),
            pd.DataFrame(unmatched_rows, columns=UNMATCHED_COLUMNS), stats)


# ---------- overrides ----------

def apply_overrides(matches: pd.DataFrame, overrides: pd.DataFrame, entity_ids: set[str],
                    crm_names: dict | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Overrides (accountid, entity_id, reason) winnen van pass 1 en 2.

    Lege entity_id = geforceerd geen match; onbekende entity_id = FOUT-melding, genegeerd.
    `crm_names` (optioneel, accountid -> naam) vult crm_name voor accounts zonder match.
    """
    out = matches[MATCH_COLUMNS].copy() if len(matches) else pd.DataFrame(columns=MATCH_COLUMNS)
    warnings: list[str] = []
    if overrides is None or not len(overrides):
        return out, warnings
    names = dict(crm_names or {})
    names.update({a: n for a, n in zip(out['accountid'], out['crm_name']) if not _blank(n)})
    for o in overrides.itertuples(index=False):
        accountid = _text(getattr(o, 'accountid', ''))
        if not accountid:
            continue
        entity_id = _text(getattr(o, 'entity_id', ''))
        reason = _text(getattr(o, 'reason', ''))
        if entity_id and entity_id not in entity_ids:
            message = (f'FOUT: override voor account {accountid} verwijst naar onbekende '
                       f'entity_id {entity_id}; genegeerd')
            log.error(message)
            warnings.append(message)
            continue
        out = out[out['accountid'] != accountid]
        if not entity_id:
            log.info('Override: account %s geforceerd zonder match (%s)', accountid, reason or '-')
            continue
        log.info('Override: account %s -> %s (%s)', accountid, entity_id, reason or '-')
        new = pd.DataFrame([{'entity_id': entity_id, 'accountid': accountid,
                             'crm_name': names.get(accountid, ''), 'match_pass': 'override',
                             'match_reason': reason or 'override', 'confidence': 'high'}],
                           columns=MATCH_COLUMNS)
        out = pd.concat([out, new], ignore_index=True) if len(out) else new
    return out.reset_index(drop=True), warnings
