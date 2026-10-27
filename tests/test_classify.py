from types import SimpleNamespace

import pandas as pd
import pytest

from tam import classify as cl
from tam.ai import AIBatchError, AIRefusal, CostCapReached, CostTracker
from tam.entities import ENTITY_COLUMNS, new_entity


def _ents(*specs):
    rows = []
    for i, (name, kind) in enumerate(specs):
        rows.append(new_entity(entity_id=f'X-{i}', name=name, country='NL', kind=kind))
    return pd.DataFrame(rows, columns=ENTITY_COLUMNS)


class Fake:
    """Nep voor call_parsed; antwoordt per batch met een vaste waarde."""
    def __init__(self, value='Waste management', skip=(), exc=None):
        self.value, self.skip, self.exc, self.calls = value, set(skip), exc, []

    def __call__(self, client, tracker, **kw):
        self.calls.append(kw)
        if self.exc:
            exc = self.exc.pop(0) if isinstance(self.exc, list) else self.exc
            if exc:
                raise exc
        n = kw['user'].count('\nvolgnummer ') + kw['user'].startswith('volgnummer ')
        items = [cl.ClassItem(volgnummer=i, detailed_segment=self.value)
                 for i in range(1, n + 1) if i not in self.skip]
        return cl.ClassBatch(items=items)


def run(df, tmp_path, fake, **kw):
    return cl.classify_cooperations(df, object(), CostTracker(50), use_ai=kw.pop('use_ai', True),
                                    cache_path=tmp_path / 'c.csv', **kw)


@pytest.fixture
def patch(monkeypatch):
    def _p(fake):
        monkeypatch.setattr(cl, 'call_parsed', fake)
        return fake
    return _p


def test_rules_before_ai(tmp_path, patch):
    fake = patch(Fake())
    df = _ents(('Omgevingsdienst X', 'nl_samenwerking'), ('GGD Regio', 'be_samenwerking'),
               ('Belastingsamenwerking Y', 'be_intercommunale'))
    out, stats = run(df, tmp_path, fake)
    assert fake.calls == []
    assert list(out['detailed_segment']) == [
        'Environmental agency', 'Public health service (GGD)', 'Tax cooperation']
    assert stats['rule'] == 3


def test_fixed_kinds_untouched(tmp_path, patch):
    fake = patch(Fake())
    df = _ents(('Gemeente A', 'nl_gemeente'))
    out, stats = run(df, tmp_path, fake)
    assert out.loc[0, 'detailed_segment'] == 'Municipality'
    assert fake.calls == []


def test_ai_fills_and_caches(tmp_path, patch):
    fake = patch(Fake())
    df = _ents(('Afvalschap Z', 'nl_samenwerking'))
    out, stats = run(df, tmp_path, fake)
    assert out.loc[0, 'detailed_segment'] == 'Waste management'
    assert stats['ai'] == 1
    assert (tmp_path / 'c.csv').exists()


def test_cache_hit_skips_ai(tmp_path, patch):
    fake = patch(Fake())
    df = _ents(('Afvalschap Z', 'nl_samenwerking'))
    run(df, tmp_path, fake)
    fake2 = patch(Fake())
    out, stats = run(df, tmp_path, fake2)
    assert fake2.calls == []
    assert stats['cached'] == 1 and out.loc[0, 'detailed_segment'] == 'Waste management'


def test_name_change_invalidates_cache(tmp_path, patch):
    fake = patch(Fake())
    run(_ents(('Afvalschap Z', 'nl_samenwerking')), tmp_path, fake)
    fake2 = patch(Fake(value='Recreation authority'))
    out, stats = run(_ents(('Recreatieschap Q', 'nl_samenwerking')), tmp_path, fake2)
    assert len(fake2.calls) == 1
    assert out.loc[0, 'detailed_segment'] == 'Recreation authority'


def test_no_ai_marks_other_joint_arrangement(tmp_path, patch):
    fake = patch(Fake())
    out, stats = run(_ents(('Foo', 'nl_samenwerking')), tmp_path, fake, use_ai=False)
    assert fake.calls == []
    assert out.loc[0, 'detailed_segment'] == 'Other joint arrangement'
    assert stats['unclassified'] == 1


def test_rules_only_leaves_pending(tmp_path, patch):
    fake = patch(Fake())
    df = _ents(('Foo', 'nl_samenwerking'), ('Omgevingsdienst X', 'nl_samenwerking'))
    out, stats = run(df, tmp_path, fake, rules_only=True)
    assert fake.calls == []
    assert out.loc[0, 'detailed_segment'] == ''
    assert out.loc[1, 'detailed_segment'] == 'Environmental agency'
    assert stats == {'rule': 1, 'cached': 0, 'ai': 0, 'unclassified': 0, 'pending': 1}


def test_answer_missing_item_left_unclassified(tmp_path, patch):
    fake = patch(Fake(skip={2}))
    df = _ents(('A', 'nl_samenwerking'), ('B', 'nl_samenwerking'))
    out, stats = run(df, tmp_path, fake)
    assert out.loc[0, 'detailed_segment'] == 'Waste management'
    assert out.loc[1, 'detailed_segment'] == 'Other joint arrangement'
    assert stats['unclassified'] == 1 and stats['ai'] == 1


def test_failed_batch_does_not_stop_next_batch(tmp_path, patch):
    fake = patch(Fake(exc=[AIRefusal('x'), None]))
    df = _ents(('A', 'nl_samenwerking'), ('B', 'nl_samenwerking'))
    out, stats = run(df, tmp_path, fake, batch_size=1)
    assert len(fake.calls) == 2
    assert out.loc[0, 'detailed_segment'] == 'Other joint arrangement'
    assert out.loc[1, 'detailed_segment'] == 'Waste management'
    assert stats['unclassified'] == 1 and stats['ai'] == 1


def test_batch_error_continues(tmp_path, patch):
    fake = patch(Fake(exc=[AIBatchError('x'), None]))
    df = _ents(('A', 'nl_samenwerking'), ('B', 'nl_samenwerking'))
    out, stats = run(df, tmp_path, fake, batch_size=1)
    assert stats['unclassified'] == 1 and stats['ai'] == 1


def test_cost_cap_stops_rest(tmp_path, patch):
    fake = patch(Fake(exc=[None, CostCapReached('x')]))
    df = _ents(('A', 'nl_samenwerking'), ('B', 'nl_samenwerking'), ('C', 'nl_samenwerking'))
    out, stats = run(df, tmp_path, fake, batch_size=1)
    assert len(fake.calls) == 2
    assert list(out['detailed_segment']) == [
        'Waste management', 'Other joint arrangement', 'Other joint arrangement']
    assert stats['unclassified'] == 2


def test_estimate_classification_cost():
    assert cl.estimate_classification_cost(0) == 0
    assert cl.estimate_classification_cost(26) == pytest.approx(
        2 * (2500 * 4.0 + 1500 * 20.0) / 1e6)
