"""Eenmalige live smoke-test van tam.ai.call_parsed (kost centen).
Gebruik: ANTHROPIC_API_KEY=... venv/bin/python tools/ai_smoke.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from tam.ai import CostTracker, call_parsed  # noqa: E402


class Item(BaseModel):
    word: str
    length: int


class Batch(BaseModel):
    items: list[Item]


tracker = CostTracker(1.0)
out = call_parsed(anthropic.Anthropic(), tracker, system='Je geeft woordlengtes.',
                  user='Geef woord en lengte voor: kat, olifant.',
                  output_model=Batch, estimated_cost=0.05, effort='low')
print(out)
print(f'spent=${tracker.spent:.5f}')
