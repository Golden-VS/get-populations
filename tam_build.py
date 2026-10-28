"""TAM/whitespace-lijstbouwer: sjabloon maken of een volledige run draaien.

    python tam_build.py --make-template [--update] [--products ...] [--config ...] [--template ...]
    python tam_build.py --template tam_template.xlsx [--crm step1b_segmented.xlsx]
                        [--output tam_<datum>.xlsx] [--refresh-cache] [--offline]
                        [--dry-run] [--no-ai] [--max-cost 50]

Volgorde van een run: sjabloon lezen en valideren (fout = stoppen voor alles), API-key
controleren (behalve bij --no-ai/--dry-run), logbestand, masterlijst, classificatie
(regels + cache), CRM laden, scope, pass 1, overrides, kandidaten; dan de AI-schatting
tegen het plafond. --dry-run stopt daar (geen AI-aanroep, geen uitvoerbestand). Anders:
AI-classificatie, pass 2, TAM-rijen, uitvoer schrijven en samenvatting tonen.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

import anthropic
import pandas as pd

from step2_enrich import setup_file_logging
from tam.ai import CostTracker
from tam.classify import classify_cooperations, estimate_classification_cost
from tam.config import COUNTRIES, DEFAULT_MAX_COST, IN_TAM_STATUSES, MODEL, REFERENCE_DIR
from tam.master import build_master
from tam.matching import (
    MATCH_COLUMNS, UNMATCHED_COLUMNS, apply_overrides, build_name_index, crm_in_scope, entities_by_country,
    estimate_matching_cost, load_crm, pass1, pass2, pass2_pending,
)
from tam.output import build_run_log, check_known_detailed, write_output
from tam.sources.common import SourceCache
from tam.tam_rows import build_tam_rows
from tam.template import TemplateError, load_products, make_template, read_template

log = logging.getLogger('tam_build')

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / '.env'
EXAMPLE_CONFIG = 'tam_config.example.json'
DEFAULT_PRODUCTS = 'doc/Product_Categories_Business_Units_Core_Products_CRM2.xlsx'
CLASSIFY_CACHE = REFERENCE_DIR / 'classify_cache.csv'
MATCH_CACHE = REFERENCE_DIR / 'match_cache.csv'
REASON_OVERRIDE_NONE = 'override: geen match'
# Open punten die elke runlog noemt (spec 4.2)
OPEN_POINTS = ['OP-dump (BE, Agentschap Binnenland): licentie niet vermeld in de '
               'dataset-metadata; hergebruik nog te bevestigen']
MAX_IDS_IN_LOG = 200
EXIT_USAGE = 2


class UsageError(Exception):
    """Fout in invoer of instellingen; melden en stoppen met exitcode 2."""


# ---------------------------------------------------------------------------
# Hulpfuncties
# ---------------------------------------------------------------------------
def load_env_key(path: Path, key: str = 'ANTHROPIC_API_KEY') -> bool:
    """Zet `key` uit een .env-bestand (KEY=value) als hij nog niet in de omgeving staat.

    Alleen deze ene sleutel wordt overgenomen; de waarde wordt nooit getoond.
    Geeft True als de sleutel daarna in de omgeving staat.
    """
    if os.environ.get(key):
        return True
    path = Path(path)
    if not path.is_file():
        return False
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        if line.startswith('export '):
            line = line[len('export '):].lstrip()
        name, value = line.split('=', 1)
        if name.strip() != key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        if value:
            os.environ[key] = value
    return bool(os.environ.get(key))


def load_config(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise UsageError(f'Configuratie {path} niet gevonden. Kopieer {EXAMPLE_CONFIG} naar '
                         f'{path.name} en vul de bedrijfsnamen en de negeerlijst in.')
    try:
        config = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        raise UsageError(f'Configuratie {path} is geen geldige JSON: {e}') from e
    if not isinstance(config, dict) or not isinstance(config.get('companies'), list):
        raise UsageError(f"Configuratie {path} mist de lijst 'companies' (zie {EXAMPLE_CONFIG}).")
    return config


def _require_file(path: Path, what: str, hint: str = '') -> None:
    if not Path(path).is_file():
        raise UsageError(f'{what} niet gevonden: {path}' + (f' ({hint})' if hint else ''))


def _text(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ''
    return str(value).strip()


def _final_overrides(overrides: pd.DataFrame, entity_ids: set,
                     crm_ids: set | None = None) -> dict[str, str]:
    """accountid -> entity_id ('' = geforceerd geen match) voor geldige overrides; laatste wint.

    Overrides met een onbekende entity_id tellen niet (apply_overrides meldt ze als FOUT),
    zodat zo'n account gewoon door pass 2 gaat. Met `crm_ids` tellen overrides voor
    accounts die niet in de CRM staan ook niet (apply_overrides waarschuwt).
    """
    final: dict[str, str] = {}
    if overrides is None or not len(overrides):
        return final
    for accountid, entity_id in zip(overrides['accountid'], overrides['entity_id']):
        accountid, entity_id = _text(accountid), _text(entity_id)
        if crm_ids is not None and accountid not in crm_ids:
            continue
        if accountid and (not entity_id or entity_id in entity_ids):
            final[accountid] = entity_id
    return final


def _concat(frames: list[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
    frames = [f for f in frames if len(f)]
    if not frames:
        return pd.DataFrame(columns=columns)
    return pd.concat([f[columns] for f in frames], ignore_index=True)


def _float_score(frame: pd.DataFrame) -> pd.DataFrame:
    """best_score altijd float (NaN = geen score), zodat concat geen dtype-gok hoeft te doen."""
    return frame.assign(best_score=pd.to_numeric(frame['best_score'], errors='coerce').astype(float))


def check_output_writable(path: Path) -> None:
    """Map aanmaken en schrijftest; geopend (lockbestand) of niet schrijfbaar = UsageError."""
    path = Path(path)
    for lock in (path.with_name(f'~${path.name}'), path.with_name(f'.~lock.{path.name}#')):
        if lock.exists():
            raise UsageError(f'Uitvoerbestand {path} is geopend in een ander programma '
                             f'(lockbestand {lock.name}); sluit het eerst.')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            with open(path, 'r+b'):
                pass
        else:
            probe = path.with_name(f'.{path.name}.schrijftest')
            probe.write_bytes(b'')
            probe.unlink()
    except OSError as e:
        raise UsageError(f'Uitvoerbestand {path} is niet schrijfbaar: {e}') from e


def _id_list(ids: list) -> str:
    ids = list(ids)
    more = f' (+{len(ids) - MAX_IDS_IN_LOG} meer)' if len(ids) > MAX_IDS_IN_LOG else ''
    return ', '.join(str(i) for i in ids[:MAX_IDS_IN_LOG]) + more


def _member_counts(memberships: pd.DataFrame) -> dict:
    if not len(memberships):
        return {}
    coop = memberships[memberships['membership_type'] == 'cooperation']
    return coop.groupby('entity_id').size().to_dict()


def _population_unknown(entities: pd.DataFrame) -> dict:
    missing = pd.to_numeric(entities['population'], errors='coerce').isna()
    counts = entities[missing].groupby('country').size()
    return {country: int(counts.get(country, 0)) for country in sorted(entities['country'].unique())}


# ---------------------------------------------------------------------------
# --make-template
# ---------------------------------------------------------------------------
def run_make_template(args) -> int:
    config = load_config(args.config)
    _require_file(args.products, 'Productbestand')
    products, strays = load_products(Path(args.products), config)
    try:
        n = make_template(products, Path(args.template), update=args.update)
    except FileExistsError:
        raise UsageError(f'{args.template} bestaat al; gebruik --update om nieuwe rijen toe te '
                         f'voegen (ingevulde rijen blijven staan).')
    verb = 'toegevoegd aan' if args.update else 'geschreven naar'
    print(f'{n} rijen {verb} {args.template} ({len(products)} producten x {len(COUNTRIES)} landen).')
    if strays:
        print(f'{len(strays)} product/sales unit-combinaties buiten de hoofdlijst '
              f'(komen in de runlog).')
    return 0


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
def _read_template_or_exit(path: Path):
    _require_file(path, 'Sjabloon', 'maak het met --make-template')
    try:
        return read_template(path)
    except TemplateError as e:
        lines = str(e).splitlines()
        raise UsageError(f'Sjabloon {path} bevat {len(lines)} fout(en):\n' + '\n'.join(lines)) from e


def run_build(args) -> int:
    # 1. sjabloon eerst: een fout stopt alles, nog voor enige download
    definitions, overrides = _read_template_or_exit(Path(args.template))
    if not definitions:
        print(f'Geen TAM-definities ingevuld in {args.template}: vul per product en land de '
              f'kolom segments in. Niets gedaan.')
        return 0
    config = load_config(args.config)
    _require_file(args.products, 'Productbestand')
    _require_file(args.crm, 'CRM-bestand', 'output van stap 1b')
    if not args.dry_run:
        check_output_writable(Path(args.output))

    use_ai = not (args.no_ai or args.dry_run)
    if use_ai and not load_env_key(ENV_PATH):
        raise UsageError('ANTHROPIC_API_KEY ontbreekt (niet in de omgeving en niet in .env). '
                         'Zet de key, of draai met --no-ai of --dry-run.')

    setup_file_logging('tam_build')
    _, strays = load_products(Path(args.products), config)
    log.info('Run gestart: %d TAM-definities, %d overrides, model %s, plafond $%.2f%s%s%s',
             len(definitions), len(overrides), MODEL, args.max_cost,
             ', --dry-run' if args.dry_run else '', ', --no-ai' if args.no_ai else '',
             ', --offline' if args.offline else '')

    # 2. masterlijst
    bundle = build_master(SourceCache(refresh=args.refresh_cache, offline=args.offline))
    entities, memberships, aliases = bundle.entities, bundle.memberships, bundle.aliases
    entity_ids = set(entities['entity_id'])
    failed_sources = [s.name for s in bundle.status if not s.ok]
    print(f'Masterlijst: {len(entities)} entiteiten, {len(memberships)} lidmaatschappen, '
          f'{len(aliases)} aliassen; mislukte bronnen: {", ".join(failed_sources) or "geen"}')

    # 3. classificatie: alleen regels + cache (voor de schatting)
    member_counts = _member_counts(memberships)
    # doel/OWMS-naam per samenwerking uit het OO-register (F5)
    descriptions = bundle.extras.get('coop_descriptions') or {}
    tracker = CostTracker(args.max_cost)
    _, pre = classify_cooperations(entities, None, tracker, use_ai=False, rules_only=True,
                                   cache_path=CLASSIFY_CACHE, member_counts=member_counts,
                                   descriptions=descriptions)
    print(f"Classificatie: {pre['rule']} via regel, {pre['cached']} uit cache, "
          f"{pre['pending']} nog voor AI")

    # 4. CRM, scope, pass 1, overrides, kandidaten
    crm = load_crm(Path(args.crm))
    scope, out_of_scope_gov = crm_in_scope(crm)
    index = build_name_index(entities, aliases)
    by_country = entities_by_country(entities, aliases)
    matched1, rest = pass1(scope, entities, index)
    crm_names = dict(zip(crm['accountid'].map(_text), crm['name'].map(_text)))
    forced = _final_overrides(overrides, entity_ids, set(crm_names))
    rest = rest[~rest['accountid'].map(_text).isin(forced.keys())]
    n_pass2 = pass2_pending(rest, by_country, index, cache_path=MATCH_CACHE)
    print(f'CRM: {len(crm)} accounts, {len(scope)} in scope, {len(out_of_scope_gov)} '
          f'buitenlandse overheidsaccounts buiten scope')
    print(f'Pass 1: {len(matched1)} gematcht op regels; {len(forced)} accounts met override; '
          f'{len(rest)} over voor pass 2, waarvan {n_pass2} naar AI (na cache)')

    # 5. schatting tegen het plafond
    est_class = estimate_classification_cost(pre['pending'])
    est_match = estimate_matching_cost(n_pass2)
    estimate = est_class + est_match
    print(f'AI-schatting: ${estimate:.2f} (classificatie {pre["pending"]} items ${est_class:.2f}, '
          f'matching {n_pass2} accounts ${est_match:.2f}), plafond ${args.max_cost:.2f}')
    if args.no_ai:
        print("--no-ai: geen AI-aanroepen; open samenwerkingen krijgen 'Other joint arrangement', "
              'open accounts blijven ongematcht.')
    elif estimate > args.max_cost:
        print('Let op: de schatting ligt boven het plafond; de run stopt netjes zodra het plafond '
              'bereikt is (caches blijven bewaard, volgende run gaat verder).')
    if args.dry_run:
        print('--dry-run: gestopt voor de AI-stap; geen uitvoerbestand geschreven.')
        return 0

    # 6. AI-classificatie en pass 2 (een gedeelde kostenteller)
    client = anthropic.Anthropic() if use_ai else None
    entities, cstats = classify_cooperations(entities, client, tracker, use_ai=use_ai,
                                             cache_path=CLASSIFY_CACHE,
                                             member_counts=member_counts,
                                             descriptions=descriptions)
    matched2, unmatched2, pstats = pass2(rest, entities, aliases, client, tracker, use_ai=use_ai,
                                         cache_path=MATCH_CACHE, index=index,
                                         by_country=by_country)
    capped = [stage for stage, n in (('classificatie', cstats['cap']), ('matching', pstats['cap']))
              if n]
    if capped:
        print(f'Kostenplafond bereikt tijdens {"/".join(capped)}: classificatie {cstats["cap"]} '
              f'samenwerkingen, matching {pstats["cap"]} accounts niet naar AI (caches bewaard; '
              f'een volgende run gaat verder).')
    matches, override_warnings = apply_overrides(
        _concat([matched1, matched2], MATCH_COLUMNS), overrides, entity_ids,
        crm_names=crm_names)

    forced_none = scope[scope['accountid'].map(_text).isin(
        [a for a, e in forced.items() if not e])]
    override_none = pd.DataFrame({
        'accountid': forced_none['accountid'].map(_text).values,
        'crm_name': forced_none['name'].map(_text).values,
        'tam_country': forced_none['tam_country'].values,
        'best_candidate': '', 'best_score': float('nan'), 'reason': REASON_OVERRIDE_NONE,
    }, columns=UNMATCHED_COLUMNS)
    unmatched = _concat([_float_score(f) for f in (unmatched2, override_none, out_of_scope_gov)],
                        UNMATCHED_COLUMNS)
    unmatched = unmatched[~unmatched['accountid'].isin(set(matches['accountid']))]
    unmatched = unmatched.reset_index(drop=True)

    # 7. TAM-rijen
    match_counts = matches.groupby('entity_id')['accountid'].nunique().to_dict() if len(matches) else {}
    tam = build_tam_rows(entities, definitions, match_counts)

    # 8. runlog en uitvoer
    warnings = list(bundle.extras.get('warnings', [])) + list(override_warnings)
    if cstats['unclassified_ids']:
        warnings.append(f"{len(cstats['unclassified_ids'])} samenwerkingen niet geclassificeerd "
                        f"(Other joint arrangement; kostenplafond {cstats['cap']}, AI uit "
                        f"{cstats['no_ai']}, AI-fout {cstats['failed']}): "
                        f"{_id_list(cstats['unclassified_ids'])}")
    if pstats.get('cap'):
        warnings.append(f"Kostenplafond bereikt tijdens matching: {pstats['cap']} accounts niet "
                        f"naar AI gestuurd")
    ai_stats = {f'classificatie {k}': v for k, v in cstats.items() if k != 'unclassified_ids'}
    # open na regels + cache komt uit de voorronde; de echte aanroep zet pending niet
    ai_stats['classificatie pending'] = pre['pending']
    ai_stats.update({f'matching {k}': v for k, v in pstats.items()})
    ai_stats['schatting vooraf (USD)'] = f'{estimate:.2f}'
    detailed = {_text(v) for v in entities['detailed_segment']} - {''}
    by_pass = matches['match_pass'].value_counts() if len(matches) else pd.Series(dtype=int)
    match_stats = {
        'CRM-accounts in scope': len(scope),
        'buitenlandse overheidsaccounts': len(out_of_scope_gov),
        **{f'matches {p}': int(by_pass.get(p, 0)) for p in ('rule', 'ai', 'override')},
        'overrides naar entiteit': sum(1 for e in forced.values() if e),
        'overrides geen match': sum(1 for e in forced.values() if not e),
        'niet gematcht': len(unmatched),
    }
    run_log = build_run_log(
        inputs={
            'datum': date.today().isoformat(), 'model': MODEL, 'sjabloon': args.template,
            'crm': args.crm,
            'crm gewijzigd': date.fromtimestamp(Path(args.crm).stat().st_mtime).isoformat(),
            'producten': args.products, 'configuratie': args.config,
            'uitvoer': args.output, 'plafond (USD)': f'{args.max_cost:.2f}',
            'opties': ' '.join(o for o, on in [('--refresh-cache', args.refresh_cache),
                                               ('--offline', args.offline),
                                               ('--no-ai', args.no_ai)] if on) or '-',
        },
        source_status=bundle.status,
        entity_counts=entities.groupby(['country', 'kind']).size().reset_index(name='count'),
        tam_status_counts=tam.groupby(['company', 'sales_unit', 'core_product', 'country',
                                       'in_tam']).size().reset_index(name='count'),
        population_unknown=_population_unknown(entities),
        match_stats=match_stats,
        ai_stats=ai_stats,
        spend=tracker.spent,
        strays=strays,
        # alleen bepalen; bewaren pas na geslaagd wegschrijven
        new_detailed=check_known_detailed(detailed, save=False),
        open_points=OPEN_POINTS,
        warnings=warnings,
    )
    write_output(Path(args.output), tam=tam, matches=matches, entities=entities,
                 memberships=memberships, unmatched=unmatched, run_log=run_log)
    log.info('Uitvoer geschreven: %s', args.output)
    check_known_detailed(detailed)

    _print_summary(definitions, tam, matches, unmatched, cstats, tracker.spent, failed_sources,
                   args.output)
    return 0


def _print_summary(definitions, tam, matches, unmatched, cstats, spent, failed_sources,
                   output) -> None:
    print('\n== Samenvatting ==')
    print('TAM per definitie:')
    counts = tam.groupby(['company', 'sales_unit', 'core_product', 'country', 'in_tam']).size()
    for d in definitions:
        key = (d.company, d.sales_unit, d.core_product, d.country)
        parts = [f'{status}: {int(counts.get(key + (status,), 0))}' for status in IN_TAM_STATUSES
                 if counts.get(key + (status,), 0)]
        print(f'  {d.company} / {d.sales_unit} / {d.core_product} / {d.country}: '
              f'{", ".join(parts) or "0 entiteiten"}')
    by_pass = matches['match_pass'].value_counts() if len(matches) else pd.Series(dtype=int)
    passes = ', '.join(f'{p}: {int(by_pass.get(p, 0))}' for p in ('rule', 'ai', 'override'))
    print(f'Matches: {len(matches)} ({passes})')
    print(f'Niet gematcht: {len(unmatched)}')
    print(f"Niet geclassificeerd: {cstats['unclassified']}")
    print(f'AI-uitgaven: ${spent:.2f}')
    print(f'Mislukte bronnen: {", ".join(failed_sources) or "geen"}')
    print(f'Uitvoer: {output}')


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='TAM/whitespace-lijstbouwer')
    p.add_argument('--make-template', action='store_true',
                   help='maak (of met --update: vul aan) het invoersjabloon')
    p.add_argument('--update', action='store_true', help='met --make-template: nieuwe rijen toevoegen')
    p.add_argument('--products', default=DEFAULT_PRODUCTS)
    p.add_argument('--config', default='tam_config.json')
    p.add_argument('--template', default='tam_template.xlsx')
    p.add_argument('--crm', default='step1b_segmented.xlsx')
    p.add_argument('--output', default=f'tam_{date.today().isoformat()}.xlsx')
    p.add_argument('--refresh-cache', action='store_true', help='registerdownloads vernieuwen')
    p.add_argument('--offline', action='store_true', help='alleen gecachte downloads gebruiken')
    p.add_argument('--dry-run', action='store_true',
                   help='tot en met de AI-schatting; geen AI-aanroep, geen uitvoer')
    p.add_argument('--no-ai', action='store_true',
                   help='geen AI: classificatie en pass 2 overslaan (gemarkeerd)')
    p.add_argument('--max-cost', type=float, default=DEFAULT_MAX_COST,
                   help=f'kostenplafond in USD (standaard {DEFAULT_MAX_COST:g})')
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        datefmt='%H:%M:%S')
    args = build_parser().parse_args(argv)
    try:
        if args.make_template:
            return run_make_template(args)
        if args.update:
            raise UsageError('--update hoort bij --make-template')
        return run_build(args)
    except UsageError as e:
        print(f'FOUT: {e}', file=sys.stderr)
        return EXIT_USAGE


if __name__ == '__main__':
    sys.exit(main())
