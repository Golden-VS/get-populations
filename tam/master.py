"""Masterlijst: alle bronladers in afhankelijkheidsvolgorde, samengevoegd en gevalideerd.

Laderlijst (`loaders`): elk element is `(naam, functie)` of `(naam, functie, afhankelijkheden)`.
- `naam` is ook de naam van de SourceStatus (gelijk aan wat de lader zelf meldt).
- `functie(ctx: LoadContext) -> SourceBundle`; `ctx.cache` is de SourceCache,
  `ctx.bundles` de bundels van eerder geslaagde laders (op naam) en `ctx.merged`
  alles wat tot nu toe is samengevoegd.
- `afhankelijkheden` is een tuple met namen van eerdere laders. Ontbreekt er een
  (exceptie, overgeslagen, of ok=False zonder entiteiten), dan draait deze lader niet
  en krijgt hij status ok=False 'overgeslagen: <naam> ontbreekt'.

Tests geven nep-laders mee, bv. `[('a', lambda ctx: bundle), ('b', fn, ('a',))]`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from tam.config import KIND_TO_SEGMENT
from tam.entities import (
    SourceBundle, SourceStatus, _is_empty, apply_country_totals, apply_member_population,
)

log = logging.getLogger(__name__)

# Gemeente-kinds waarvan de eigen bevolking in municipal_population hoort (DE komt uit parse_gv)
_MUNICIPAL_KINDS = ('nl_gemeente', 'be_gemeente')
# Basis voor het landtotaal van AW/CW/SX (de landrij), BQ (som van de eilanden) en SR (som van
# de districten), spec sectie 15. Ze gaan ook in municipal_population: apply_country_totals telt
# per landprefix van de entity_id, en deze ids beginnen met hun land (AW-HAND-..., SR-HAND-...).
_COUNTRY_TOTAL_KINDS = ('carib_land', 'bq_openbaar_lichaam', 'sr_district')
_SAMPLE = 20


@dataclass
class LoadContext:
    cache: object
    bundles: dict = field(default_factory=dict)
    merged: SourceBundle = field(default_factory=SourceBundle.empty)
    warnings: list = field(default_factory=list)   # komen in extras['warnings']


# ---------------------------------------------------------------------------
# Echte laders
# ---------------------------------------------------------------------------
def _nl_cbs(ctx):
    from tam.sources.nl import load_nl_cbs
    return load_nl_cbs(ctx.cache)


def _nl_oo(ctx):
    from tam.sources.nl import load_nl_oo
    return load_nl_oo(ctx.cache)


def _nl_hand(ctx):
    from tam.sources.nl import load_nl_hand
    return load_nl_hand()


def _be_wikidata(ctx):
    from tam.sources.be import load_be_wikidata
    return load_be_wikidata(ctx.cache)


def _be_names(ctx) -> pd.DataFrame:
    # Naamvarianten NL/FR/DE per gemeente, niet het entiteitenframe
    return ctx.bundles['be_wikidata'].extras['be_gemeente_names']


def _be_op(ctx):
    from tam.sources.be import load_be_op
    return load_be_op(ctx.cache, _be_names(ctx))


def _be_wb(ctx):
    from tam.sources.be import is_flemish_nis, load_be_wb
    ents = ctx.bundles['be_wikidata'].entities
    gem_ids = ents.loc[ents['kind'] == 'be_gemeente', 'entity_id']
    flemish = {i for i in gem_ids if is_flemish_nis(i)}
    return load_be_wb(ctx.cache, _be_names(ctx), flemish)


def _de_gv(ctx):
    from tam.sources.de import load_de_gv
    return load_de_gv(ctx.cache)


def _de_feu(ctx):
    from tam.sources.de import load_de_feu
    return load_de_feu(ctx.cache)


def _de_hand(ctx):
    from tam.sources.de import load_de_hand
    extras = ctx.bundles['de_gv'].extras
    return load_de_hand(extras.get('municipal_population', {}),
                        verband_members=extras.get('de_verband_members'),
                        population_date=extras.get('de_population_date', ''))


def _carib_sr(ctx):
    from tam.sources.carib import load_carib_sr
    return load_carib_sr()


def _aliases(ctx):
    from tam.sources.aliases import load_predecessors
    gv = ctx.bundles.get('de_gv')
    alias_ids = gv.extras.get('alias_ids', {}) if gv is not None else {}
    if gv is None:
        msg = 'Voorgangers: DE GV ontbreekt; geen alias_ids voor Gemeinden in een Amt'
        log.warning(msg)
        ctx.warnings.append(msg)
    return load_predecessors(ctx.cache, ctx.merged.entities, ctx.merged.aliases, alias_ids=alias_ids)


def default_loaders() -> list[tuple]:
    """De echte laders in afhankelijkheidsvolgorde; voorgangers als laatste."""
    return [
        ('nl_cbs', _nl_cbs),
        ('nl_oo', _nl_oo),
        ('nl_hand', _nl_hand),
        ('be_wikidata', _be_wikidata),
        ('be_op', _be_op, ('be_wikidata',)),
        ('be_wb', _be_wb, ('be_wikidata',)),
        ('de_gv', _de_gv),
        ('de_feu', _de_feu),
        ('de_hand', _de_hand, ('de_gv',)),
        ('carib_sr', _carib_sr),
        ('aliases', _aliases),
    ]


DEFAULT_ORDER = [spec[0] for spec in default_loaders()]


# ---------------------------------------------------------------------------
# Laders draaien
# ---------------------------------------------------------------------------
def _usable(bundle: SourceBundle) -> bool:
    """Bruikbaar als afhankelijkheid: niet (gemeld mislukt en zonder entiteiten)."""
    failed = any(not s.ok for s in bundle.status)
    return not (failed and len(bundle.entities) == 0)


def _stale_note(cache, start: int) -> str:
    """'verouderde cache, datum X' voor bestanden die sinds `start` uit de cache kwamen na een
    mislukte download (SourceCache.stale); leeg als er geen waren."""
    stale = list(getattr(cache, 'stale', None) or [])[start:]
    return '; '.join(f'verouderde cache, datum {d} ({n})' for n, d in stale)


def _with_note(message: str, note: str) -> str:
    return f'{message}; {note}' if message else note


# Lengte waarop een verzamelde laderwaarschuwing in de runlog wordt afgekapt
_WARNING_MAX_CHARS = 1000


class _WarningCollector(logging.Handler):
    """Verzamelt WARNING+ van de tam-loggers tijdens de laders (M6), behalve de eigen
    master-regels (die staan al in de bronstatus en 'Bronnen met fouten')."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record):
        if record.name == __name__:
            return
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001
            return
        if len(message) > _WARNING_MAX_CHARS:
            message = message[:_WARNING_MAX_CHARS] + ' (...)'
        self.messages.append(message)


def _run_loaders(cache, loaders) -> LoadContext:
    collector = _WarningCollector()
    tam_logger = logging.getLogger('tam')
    tam_logger.addHandler(collector)
    try:
        ctx = _run_loader_list(cache, loaders)
    finally:
        tam_logger.removeHandler(collector)
    ctx.warnings = list(dict.fromkeys(ctx.warnings + collector.messages))
    return ctx


def _run_loader_list(cache, loaders) -> LoadContext:
    ctx = LoadContext(cache)
    for spec in loaders:
        name, fn = spec[0], spec[1]
        deps = tuple(spec[2]) if len(spec) > 2 else ()
        missing = [d for d in deps if d not in ctx.bundles]
        if missing:
            msg = f'overgeslagen: {missing[0]} ontbreekt'
            log.error('Bron %s %s', name, msg)
            ctx.merged.status.append(SourceStatus(name, False, 0, '', msg))
            continue
        n_stale = len(getattr(cache, 'stale', None) or [])
        try:
            # Alles per lader binnen de try: een kapotte lader breekt de run niet af
            bundle = fn(ctx)
            if not isinstance(bundle, SourceBundle):
                raise TypeError(f'lader gaf {type(bundle).__name__} in plaats van een SourceBundle')
            if not bundle.status:
                bundle.status.append(SourceStatus(name, True, len(bundle.entities), '', ''))
            note = _stale_note(cache, n_stale)
            if note:
                # verouderde cache zichtbaar in de bronstatus en de runlog (F4)
                for st in bundle.status:
                    st.message = _with_note(st.message, note)
                ctx.warnings.append(f'Bron {name}: download mislukt, {note}')
            merged = ctx.merged.merge(bundle)
        except Exception as e:  # noqa: BLE001
            log.error('Bron %s mislukt: %s', name, e, exc_info=True)
            msg = _with_note(str(e) or type(e).__name__, _stale_note(cache, n_stale))
            ctx.merged.status.append(SourceStatus(name, False, 0, '', msg))
            continue
        for st in bundle.status:
            if not st.ok:
                log.error('Bron %s meldt een fout: %s', st.name, st.message)
        ctx.merged = merged
        if _usable(bundle):
            ctx.bundles[name] = bundle
    return ctx


# ---------------------------------------------------------------------------
# Nabewerking
# ---------------------------------------------------------------------------
def _sample(items) -> str:
    items = list(items)
    more = f' (+{len(items) - _SAMPLE} meer)' if len(items) > _SAMPLE else ''
    return ', '.join(str(i) for i in items[:_SAMPLE]) + more


def _drop_duplicate_ids(entities, warnings):
    dup = entities['entity_id'].duplicated(keep='first')
    if dup.any():
        ids = list(dict.fromkeys(entities.loc[dup, 'entity_id']))
        msg = f'{int(dup.sum())} dubbele entity_ids (eerste behouden): {_sample(ids)}'
        log.error(msg)
        warnings.append(msg)
        entities = entities[~dup].reset_index(drop=True)
    return entities


def _drop_unknown_kinds(entities, warnings):
    bad = ~entities['kind'].isin(list(KIND_TO_SEGMENT))
    if bad.any():
        pairs = [f'{e} ({k}, bron {s or "?"})'
                 for e, k, s in entities.loc[bad, ['entity_id', 'kind', 'source']].values]
        msg = f'{int(bad.sum())} entiteiten met onbekend kind verwijderd: {_sample(pairs)}'
        log.error(msg)
        warnings.append(msg)
        entities = entities[~bad].reset_index(drop=True)
    return entities


def _apply_id_patches(entities, patches, warnings):
    """Plak official_ids uit id_patches achter de bestaande; dubbele delen eruit."""
    if not isinstance(patches, pd.DataFrame) or not len(patches):
        return entities
    out = entities.copy()
    pos = {eid: i for i, eid in zip(out.index, out['entity_id'])}
    unknown, n = [], 0
    for eid, ids in patches[['entity_id', 'official_ids']].values:
        if _is_empty(eid) or _is_empty(ids):
            continue
        if eid not in pos:
            unknown.append(eid)
            continue
        idx = pos[eid]
        current = out.at[idx, 'official_ids']
        parts = [p for p in ('' if _is_empty(current) else str(current)).split(';') if p]
        parts.extend(p for p in str(ids).split(';') if p and p not in parts)
        out.at[idx, 'official_ids'] = ';'.join(dict.fromkeys(parts))
        n += 1
    log.info('Id-patches: %d toegepast', n)
    if unknown:
        unknown = list(dict.fromkeys(unknown))
        msg = f'{len(unknown)} id-patches voor onbekende entiteiten genegeerd: {_sample(unknown)}'
        log.warning(msg)
        warnings.append(msg)
    return out


def _check_memberships(memberships, entity_ids, municipal_population, warnings):
    if not len(memberships):
        return memberships
    out = memberships.drop_duplicates().reset_index(drop=True)
    bad = ~out['entity_id'].isin(entity_ids)
    if bad.any():
        ids = list(dict.fromkeys(out.loc[bad, 'entity_id']))
        msg = (f'{int(bad.sum())} lidmaatschappen van onbekende samenwerkingen verwijderd '
               f'({len(ids)} ids): {_sample(ids)}')
        log.error(msg)
        warnings.append(msg)
        out = out[~bad].reset_index(drop=True)
    # Onbekende leden blijven staan, maar tellen niet mee in sommen (geen bevolking bekend)
    unknown = ~out['member_entity_id'].isin(entity_ids) & ~out['member_entity_id'].isin(
        list(municipal_population))
    if unknown.any():
        ids = list(dict.fromkeys(out.loc[unknown, 'member_entity_id']))
        msg = (f'{int(unknown.sum())} lidmaatschappen met een onbekend lid ({len(ids)} ids; tellen '
               f'niet mee in bevolkingssommen): {_sample(ids)}')
        log.warning(msg)
        warnings.append(msg)
    return out


def _check_aliases(aliases, entity_ids, warnings):
    if not len(aliases):
        return aliases
    out = aliases.drop_duplicates().reset_index(drop=True)
    bad = ~out['entity_id'].isin(entity_ids)
    if bad.any():
        pairs = [f'{a} -> {e}' for a, e in out.loc[bad, ['alias_name', 'entity_id']].values]
        msg = f'{int(bad.sum())} aliassen naar onbekende entiteiten verwijderd: {_sample(pairs)}'
        log.error(msg)
        warnings.append(msg)
        out = out[~bad].reset_index(drop=True)
    return out


def _municipal_population(entities, extras_pop) -> dict:
    """extras uit alle bundels, aangevuld met NL/BE-gemeente-entiteiten en de landtotaalbasis
    van AW/CW/SX/BQ/SR (_COUNTRY_TOTAL_KINDS) met eigen bevolking."""
    pop = dict(extras_pop or {})
    gem = entities[entities['kind'].isin(_MUNICIPAL_KINDS + _COUNTRY_TOTAL_KINDS)]
    for eid, value in gem[['entity_id', 'population']].values:
        if eid not in pop and not _is_empty(value):
            pop[eid] = int(value)
    return pop


def _fill_same_as(entities, memberships, municipal_population, warnings):
    """'same as municipality': bevolking (en bron) van de gemeente uit het same_as-lidmaatschap."""
    out = entities.copy()
    target = {}
    if len(memberships):
        same = memberships[memberships['membership_type'] == 'same_as']
        for eid, mid in same[['entity_id', 'member_entity_id']].values:
            target.setdefault(eid, mid)
    by_id = out.set_index('entity_id')
    missing = []
    for idx in out.index[out['population_method'] == 'same as municipality']:
        if not _is_empty(out.at[idx, 'population']):
            continue
        eid = out.at[idx, 'entity_id']
        mid = target.get(eid)
        if mid is None or mid not in municipal_population:
            out.at[idx, 'population'] = float('nan')
            out.at[idx, 'population_method'] = 'unknown'
            missing.append(f'{eid} ({out.at[idx, "name"]})')
            continue
        out.at[idx, 'population'] = municipal_population[mid]
        if mid in by_id.index:
            out.at[idx, 'population_source'] = by_id.at[mid, 'population_source']
            out.at[idx, 'population_date'] = by_id.at[mid, 'population_date']
    if missing:
        msg = f"{len(missing)} 'same as municipality'-rijen zonder gemeentebevolking: {_sample(missing)}"
        log.warning(msg)
        warnings.append(msg)
    return out


def build_master(cache, loaders: list[tuple[str, Callable]] | None = None) -> SourceBundle:
    """Draai alle laders, voeg samen, vul bevolking en valideer.

    Geeft de samengevoegde SourceBundle; extras['municipal_population'] is de volledige
    gemeentebevolking (NL/BE/DE, plus de landtotaalbasis van AW/CW/SX/BQ/SR) en
    extras['warnings'] de waarschuwingen voor de runlog.
    """
    ctx = _run_loaders(cache, default_loaders() if loaders is None else loaders)
    merged = ctx.merged
    warnings: list[str] = list(ctx.warnings)
    extras = merged.extras

    entities = merged.entities.reset_index(drop=True)
    entities['population'] = pd.to_numeric(entities['population'], errors='coerce')
    entities = _drop_duplicate_ids(entities, warnings)
    entities = _drop_unknown_kinds(entities, warnings)
    entities = _apply_id_patches(entities, extras.get('id_patches'), warnings)
    entity_ids = set(entities['entity_id'])

    muni_pop = _municipal_population(entities, extras.get('municipal_population'))
    memberships = _check_memberships(merged.memberships, entity_ids, muni_pop, warnings)
    aliases = _check_aliases(merged.aliases, entity_ids, warnings)

    entities, sum_warnings = apply_member_population(entities, memberships, muni_pop)
    for w in sum_warnings:
        log.warning(w)
    warnings.extend(sum_warnings)
    entities = apply_country_totals(entities, muni_pop, warnings)
    entities = _fill_same_as(entities, memberships, muni_pop, warnings)
    entities['population'] = pd.to_numeric(entities['population'], errors='coerce')

    failed = [s.name for s in merged.status if not s.ok]
    if failed:
        msg = f'Bronnen met fouten: {", ".join(failed)}'
        log.error(msg)
        warnings.append(msg)

    extras = dict(extras)
    extras['municipal_population'] = muni_pop
    extras['warnings'] = warnings
    log.info('Masterlijst: %d entiteiten, %d lidmaatschappen, %d aliassen',
             len(entities), len(memberships), len(aliases))
    return SourceBundle(entities, memberships, aliases, list(merged.status), extras)
