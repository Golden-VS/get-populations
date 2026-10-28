"""Claude-wrapper met kostenbewaking en kostenplafond, plus atomair wegschrijven van AI-caches."""
import math
import os
from pathlib import Path

import anthropic
import pandas as pd
from pydantic import ValidationError

from tam.config import MODEL, PRICES_PER_MTOK

MAX_TOKENS = 16000
# Ruime bovengrens voor de invoer: hooguit 1 token per 2 tekens, plus vaste overhead voor het
# uitvoerschema en de berichtopbouw
CHARS_PER_TOKEN_MIN = 2
INPUT_OVERHEAD_TOKENS = 1000


def atomic_write_csv(df: pd.DataFrame, path) -> None:
    """CSV schrijven via '<bestand>.part' + os.replace: een fout laat het oude bestand heel."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + '.part')
    try:
        df.to_csv(part, index=False)
        os.replace(part, path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


class CostCapReached(Exception):
    """Het kostenplafond zou overschreden worden; run stopt netjes."""


class AIRefusal(Exception):
    """Het model weigerde te antwoorden (stop_reason == 'refusal')."""


class AIBatchError(Exception):
    """Een batch is mislukt (API- of validatiefout); aanroeper gaat door."""


class CostTracker:
    def __init__(self, max_cost: float):
        self.max_cost = max_cost
        self.spent = 0.0

    def add_usage(self, usage) -> float:
        """Telt het gebruik op; ontbrekende/None velden tellen als 0."""
        def tok(name):
            return getattr(usage, name, None) or 0

        cost = (
            tok('input_tokens') * PRICES_PER_MTOK['input']
            + tok('output_tokens') * PRICES_PER_MTOK['output']
            + tok('cache_creation_input_tokens') * PRICES_PER_MTOK['cache_write']
            + tok('cache_read_input_tokens') * PRICES_PER_MTOK['cache_read']
        ) / 1_000_000
        self.spent += cost
        return cost

    def check_room(self, estimated_next: float) -> None:
        if self.spent + estimated_next > self.max_cost:
            raise CostCapReached(
                f'Kostenplafond bereikt: besteed ${self.spent:.2f} + '
                f'geschat ${estimated_next:.2f} > max ${self.max_cost:.2f}')


def estimate_cost(n_items: int, batch_size: int, in_tokens_per_batch: int,
                  out_tokens_per_batch: int) -> float:
    """Grove kostenschatting (zonder cache-korting) in USD."""
    n_batches = math.ceil(n_items / batch_size) if n_items > 0 else 0
    per_batch = (in_tokens_per_batch * PRICES_PER_MTOK['input']
                 + out_tokens_per_batch * PRICES_PER_MTOK['output']) / 1_000_000
    return n_batches * per_batch


def worst_case_cost(system: str, user: str, max_tokens: int = MAX_TOKENS) -> float:
    """Bovengrens (USD) voor een aanroep: invoer tegen het (hogere) cache-schrijftarief plus
    max_tokens aan uitvoer (incl. denkwerk). Basis van de plafondcontrole (M1)."""
    in_tokens = (len(system) + len(user)) // CHARS_PER_TOKEN_MIN + INPUT_OVERHEAD_TOKENS
    in_price = max(PRICES_PER_MTOK['input'], PRICES_PER_MTOK['cache_write'])
    return (in_tokens * in_price + max_tokens * PRICES_PER_MTOK['output']) / 1_000_000


def call_parsed(client, tracker: CostTracker, *, system: str, user: str,
                output_model, estimated_cost: float, effort: str = 'medium'):
    """
    Eén gestructureerde Claude-aanroep. output_model moet een BaseModel-wrapper
    zijn (geen kale list[...]). Gebruik wordt eerst bijgeteld, daarna pas op
    weigering gecontroleerd. Let op: bij server-side fallback kan een beurt
    tegen het tarief van een ander model gefactureerd worden; die afwijking
    wordt niet bijgehouden (geaccepteerde onderschatting). Hetzelfde geldt voor
    een ValidationError binnen parse: het gebruik van die aanroep gaat verloren.
    Het plafond wordt getoetst tegen het slechtste geval (worst_case_cost, minstens
    estimated_cost), zodat ook een maximaal lang antwoord het plafond niet overschrijdt.
    """
    tracker.check_room(max(estimated_cost, worst_case_cost(system, user)))
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[{'type': 'text', 'text': system,
                     'cache_control': {'type': 'ephemeral'}}],
            messages=[{'role': 'user', 'content': user}],
            output_format=output_model,
            output_config={'effort': effort},
            extra_body={'fallbacks': 'default'},
            extra_headers={'anthropic-beta': 'server-side-fallback-2026-07-01'},
        )
    except (anthropic.APIError, ValidationError) as e:
        raise AIBatchError(f'{type(e).__name__}: {e}') from e
    tracker.add_usage(getattr(response, 'usage', None))
    if response.stop_reason == 'refusal':
        raise AIRefusal('Model weigerde het verzoek')
    try:
        return response.parsed_output
    except ValidationError as e:
        raise AIBatchError(f'{type(e).__name__}: {e}') from e
