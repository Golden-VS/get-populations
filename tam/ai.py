"""Claude-wrapper met kostenbewaking en kostenplafond."""
import math

import anthropic
from pydantic import ValidationError

from tam.config import MODEL, PRICES_PER_MTOK


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


def call_parsed(client, tracker: CostTracker, *, system: str, user: str,
                output_model, estimated_cost: float, effort: str = 'medium'):
    """
    Eén gestructureerde Claude-aanroep. output_model moet een BaseModel-wrapper
    zijn (geen kale list[...]). Gebruik wordt eerst bijgeteld, daarna pas op
    weigering gecontroleerd. Let op: bij server-side fallback kan een beurt
    tegen het tarief van een ander model gefactureerd worden; die afwijking
    wordt niet bijgehouden (geaccepteerde onderschatting).
    """
    tracker.check_room(estimated_cost)
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=16000,
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
