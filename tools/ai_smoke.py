"""Eenmalige live smoke-test van tam.ai.call_parsed (kost centen).
Gebruik: ANTHROPIC_API_KEY=... venv/bin/python tools/ai_smoke.py"""
import anthropic
from pydantic import BaseModel

from tam.ai import CostTracker, call_parsed


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
