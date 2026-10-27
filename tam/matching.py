"""CRM-scope, kandidaten, regelgebaseerde matching (pass 1) en overrides.

Pass 2 (AI) gebruikt `candidates()` en `entities_by_country()` uit deze module.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

from step2_enrich import normalize
from tam.config import CRM_COUNTRY_TO_TAM

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
    return s if re.fullmatch(r'\d{8}', s) else None


def _strip_prefix(normalized: str) -> str:
    """Prefix weg van een al genormaliseerde naam, daarna opnieuw normaliseren (lidwoord)."""
    return normalize(_PREFIX_RE.sub('', normalized))


def crm_name_key(row) -> str:
    """canonical_name (of anders name) zonder bestuursprefix, genormaliseerd."""
    name = _text(row.get('canonical_name')) or _text(row.get('name'))
    return _strip_prefix(normalize(name))


def _crm_postcode(row) -> str:
    """DE-postcode: cx_address3_postalcode, anders een 5-cijferig getal uit address1_composite."""
    raw = _text(row.get('cx_address3_postalcode'))
    if re.fullmatch(r'\d{4}', raw):
        raw = '0' + raw  # voorloopnul verloren in Excel
    m = re.search(r'\d{5}', raw)
    if m:
        return m.group(0)
    m = re.search(r'\b\d{5}\b', _text(row.get('address1_composite')))
    return m.group(0) if m else ''


def _plz_tokens(value) -> list[str]:
    return re.findall(r'\d{5}', _text(value))


def _plz_closeness(crm_plz: str, entity_postcode) -> int:
    """Lengte van het langste gemeenschappelijke prefix (5 = gelijke postcode)."""
    best = 0
    for token in _plz_tokens(entity_postcode):
        n = 0
        for a, b in zip(crm_plz, token):
            if a != b:
                break
            n += 1
        best = max(best, n)
    return best


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

def _rule_match(row, index, company_index, kinds_by_id, postcode_by_id):
    """(entity_id, reden) of None voor een CRM-rij volgens de regels van pass 1."""
    country = row['tam_country']
    allowed = TYPE_TO_KINDS.get(_text(row.get('detected_type')), set())

    # 1. KvK/KBO-nummer
    number = normalize_company_number(row.get('cx_kvknummer'), country)
    if number:
        ids = company_index.get((country, number), [])
        if len(ids) > 1 and allowed:
            ids = [i for i in ids if kinds_by_id.get(i) in allowed]
        if len(ids) == 1:
            return ids[0], RULE_REASON_ID

    # 2. naam binnen verenigbare kinds; zonder kinds de ruwe naam tegen alle kinds
    raw = normalize(_text(row.get('name')))
    if allowed:
        hits = [h for h in _lookup(index, country, [crm_name_key(row), raw]) if h[1] in allowed]
    else:
        hits = _lookup(index, country, [raw])
    if len(hits) == 1:
        return hits[0][0], hits[0][2]

    # 3. DE: meerdere gelijknamige treffers, beslissen op postcode
    if len(hits) > 1 and country == 'DE':
        plz = _crm_postcode(row)
        if plz:
            exact = [h for h in hits if plz in _plz_tokens(postcode_by_id.get(h[0]))]
            if not exact:
                exact = [h for h in hits
                         if any(t[:3] == plz[:3] for t in _plz_tokens(postcode_by_id.get(h[0])))]
            if len(exact) == 1:
                return exact[0][0], RULE_REASON_POSTCODE
    return None


def pass1(crm_scope, entities, index) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(matched, rest): regelgebaseerde matches en de overige in-scope rijen (alle kolommen)."""
    company_index = _company_index(entities)
    kinds_by_id = dict(zip(entities['entity_id'], entities['kind']))
    postcode_by_id = dict(zip(entities['entity_id'], entities['postcode']))
    matched = []
    rest_idx = []
    for idx, row in crm_scope.iterrows():
        found = _rule_match(row, index, company_index, kinds_by_id, postcode_by_id)
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

class _Prepared:
    """Voorberekende keuzelijsten per land; deepcopy geeft hetzelfde object terug, zodat
    pandas (dat `attrs` bij elke bewerking diep kopieert) er niet traag van wordt."""

    def __init__(self, frame: pd.DataFrame, info: dict):
        self.choices = frame['key'].tolist()
        self.entity_ids = frame['entity_id'].tolist()
        self.vias = frame['via'].tolist()
        self.norms = frame['norm'].tolist()
        self.info = info
        self.alias_pos: dict[str, list[int]] = {}
        for pos, (eid, via) in enumerate(zip(self.entity_ids, self.vias)):
            if via != 'naam':
                self.alias_pos.setdefault(eid, []).append(pos)

    def __deepcopy__(self, memo):
        return self

    def __copy__(self):
        return self


def entities_by_country(entities, aliases=None) -> dict[str, pd.DataFrame]:
    """Per land een keuzetabel voor `candidates()`.

    Een rij per entiteitsnaam (via 'naam') en per alias (via 'alias: <alias>, <reden>'),
    kolommen entity_id, name, kind, region, postcode, via, key (prefixvrij genormaliseerd),
    norm (genormaliseerd). `attrs['prepared']` bevat de voorberekende keuzelijst voor
    rapidfuzz en entity_id -> entiteitsgegevens, zodat fuzzy zoeken per account goedkoop is.
    """
    out: dict[str, pd.DataFrame] = {}
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
        frame = pd.DataFrame(rows, columns=['entity_id', 'name', 'kind', 'region', 'postcode',
                                            'via', 'key', 'norm'])
        frame.attrs['prepared'] = _Prepared(frame, info)
        out[country] = frame
    return out


def candidates(row, entities_by_country, index, k=10) -> list[dict]:
    """Kandidaat-entiteiten voor een CRM-rij (zelfde land), maximaal 15.

    Eerst elke exacte naam-/aliastreffer (elk kind, score 100), dan de top-k op
    fuzz.token_set_ratio van de prefixvrije naam (drempel 75 voor priority 'gov',
    90 voor 'other'). DE: binnen gelijke score gesorteerd op postcodenabijheid.
    Zijn er meer dan 15 exacte treffers, dan blijven de 15 met de dichtste postcode.
    """
    country = _text(row.get('tam_country'))
    frame = entities_by_country.get(country)
    if frame is None or not len(frame):
        return []
    prep = frame.attrs.get('prepared')
    if prep is None:
        info = {r.entity_id: {'entity_id': r.entity_id, 'name': r.name, 'kind': r.kind,
                              'region': r.region, 'postcode': r.postcode}
                for r in frame[frame['via'] == 'naam'].itertuples(index=False)}
        prep = _Prepared(frame, info)
    info = prep.info
    key = crm_name_key(row)
    raw = normalize(_text(row.get('name')))
    lookup_keys = [k_ for k_ in dict.fromkeys([key, raw]) if k_]
    plz = _crm_postcode(row) if country == 'DE' else ''

    def closeness(entity_id):
        return _plz_closeness(plz, info[entity_id]['postcode']) if plz else 0

    # exacte treffers (elk kind)
    exact = []
    for entity_id, _kind, reason in _lookup(index, country, lookup_keys):
        if entity_id not in info:
            continue
        via = 'naam'
        if reason != 'same name':
            via = next((prep.vias[p] for p in prep.alias_pos.get(entity_id, [])
                        if prep.norms[p] in lookup_keys or prep.choices[p] in lookup_keys),
                       f'alias: {reason}')
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
            warnings.append(f'FOUT: override voor account {accountid} verwijst naar onbekende '
                            f'entity_id {entity_id}; genegeerd')
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
