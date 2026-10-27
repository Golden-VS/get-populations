"""Tests voor de downloadcache (geen netwerk)."""
import os
import time

import pytest
import requests

from tam.sources import common
from tam.sources.common import SourceCache


class FakeResp:
    def __init__(self, chunks, fail=False):
        self.chunks = chunks
        self.fail = fail

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=None):
        for i, c in enumerate(self.chunks):
            if self.fail and i == 1:
                raise requests.ConnectionError('verbroken')
            yield c

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def patch_get(monkeypatch, resp_factory):
    calls = []

    def fake_get(url, **kw):
        calls.append((url, kw))
        return resp_factory()

    monkeypatch.setattr(requests, 'get', fake_get)
    return calls


def test_fresh_cache_not_redownloaded(tmp_path, monkeypatch):
    calls = patch_get(monkeypatch, lambda: FakeResp([b'ab', b'cd']))
    cache = SourceCache(base_dir=tmp_path)
    p1 = cache.fetch('x', 'http://u', suffix='.xml')
    p2 = cache.fetch('x', 'http://u', suffix='.xml')
    assert p1 == p2 and p1.read_bytes() == b'abcd'
    assert len(calls) == 1
    assert calls[0][1]['headers']['User-Agent'].startswith('get-populations-tam/')
    assert calls[0][1]['timeout'] == 300


def test_stale_cache_redownloaded(tmp_path, monkeypatch):
    calls = patch_get(monkeypatch, lambda: FakeResp([b'a']))
    cache = SourceCache(base_dir=tmp_path)
    p = cache.fetch('x', 'http://u')
    old = time.time() - 10 * 86400
    os.utime(p, (old, old))
    cache.fetch('x', 'http://u', max_age_days=5)
    assert len(calls) == 2


def test_refresh_forces_download(tmp_path, monkeypatch):
    calls = patch_get(monkeypatch, lambda: FakeResp([b'a']))
    SourceCache(base_dir=tmp_path).fetch('x', 'http://u')
    SourceCache(refresh=True, base_dir=tmp_path).fetch('x', 'http://u')
    assert len(calls) == 2


def test_offline_missing_file_raises(tmp_path, monkeypatch):
    calls = patch_get(monkeypatch, lambda: FakeResp([b'a']))
    with pytest.raises(FileNotFoundError):
        SourceCache(offline=True, base_dir=tmp_path).fetch('x', 'http://u')
    assert calls == []


def test_offline_uses_stale_file(tmp_path, monkeypatch):
    calls = patch_get(monkeypatch, lambda: FakeResp([b'a']))
    p = SourceCache(base_dir=tmp_path).fetch('x', 'http://u')
    old = time.time() - 999 * 86400
    os.utime(p, (old, old))
    assert SourceCache(offline=True, base_dir=tmp_path).fetch('x', 'http://u') == p
    assert len(calls) == 1


def test_partial_download_not_left_behind(tmp_path, monkeypatch):
    patch_get(monkeypatch, lambda: FakeResp([b'a', b'b'], fail=True))
    cache = SourceCache(base_dir=tmp_path / 'sub')
    with pytest.raises(requests.ConnectionError):
        cache.fetch('x', 'http://u', suffix='.xml')
    assert list((tmp_path / 'sub').iterdir()) == []


def test_sparql_cached_and_flattened(tmp_path, monkeypatch):
    bindings = [{'a': {'type': 'literal', 'value': '1'}, 'b': {'type': 'uri', 'value': 'u'}}]
    calls = []

    def fake_sparql(query, ua):
        calls.append((query, ua))
        return bindings

    monkeypatch.setattr(common, 'sparql_query', fake_sparql)
    cache = SourceCache(base_dir=tmp_path)
    df = cache.sparql('q', 'SELECT')
    assert df.to_dict('records') == [{'a': '1', 'b': 'u'}]
    assert (tmp_path / 'q.json').exists()
    cache.sparql('q', 'SELECT')
    assert len(calls) == 1
    assert calls[0][1].startswith('get-populations-tam/')
