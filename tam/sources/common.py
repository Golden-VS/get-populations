"""Gecachte downloads voor de bronbestanden (bestandsleeftijd op mtime).

Mislukt een download of SPARQL-query terwijl er al een gecacht bestand is, dan wordt dat
(verouderde) bestand gebruikt met een WARNING; `SourceCache.stale` houdt bij welke
bestanden zo gebruikt zijn (naam, datum), zodat de master het in de bronstatus zet.
"""
import json
import logging
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from step2_enrich import sparql_query
from tam.config import CACHE_MAX_AGE_DAYS, REFERENCE_DIR, USER_AGENT

log = logging.getLogger(__name__)
TIMEOUT_SECONDS = 300


class SourceCache:
    def __init__(self, refresh: bool = False, offline: bool = False,
                 base_dir: Path = REFERENCE_DIR):
        self.refresh = refresh
        self.offline = offline
        self.base_dir = Path(base_dir)
        # (naam, bestandsdatum) van gecachte bestanden die na een mislukte download dienden
        self.stale: list[tuple[str, str]] = []

    def use_stale(self, name: str, path: Path, error: Exception) -> bool:
        """Verouderde cache gebruiken na een mislukte download; False als er geen bestand is."""
        if not path.exists():
            return False
        stamp = date.fromtimestamp(path.stat().st_mtime).isoformat()
        log.warning('Download %s mislukt (%s); verouderde cache gebruikt, datum %s',
                    name, error, stamp)
        self.stale.append((name, stamp))
        return True

    def _is_fresh(self, path: Path, max_age_days: int) -> bool:
        if not path.exists():
            return False
        return (time.time() - path.stat().st_mtime) < max_age_days * 86400

    def fetch(self, name: str, url: str, *, params: dict | None = None,
              suffix: str = '', max_age_days: int = CACHE_MAX_AGE_DAYS) -> Path:
        """Geef pad naar gecachte download; download alleen als nodig."""
        path = self.base_dir / f'{name}{suffix}'
        if self.offline:
            if not path.exists():
                raise FileNotFoundError(f'Offline en niet in cache: {path}')
            return path
        if not self.refresh and self._is_fresh(path, max_age_days):
            return path
        self.base_dir.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + '.part')
        log.info('Downloaden: %s', name)
        try:
            with requests.get(url, params=params, stream=True,
                              headers={'User-Agent': USER_AGENT},
                              timeout=TIMEOUT_SECONDS) as r:
                r.raise_for_status()
                with open(part, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
            part.replace(path)
        except Exception as e:  # noqa: BLE001
            if not self.use_stale(name, path, e):
                raise
        finally:
            # Nooit een half bestand achterlaten
            part.unlink(missing_ok=True)
        return path

    def sparql(self, name: str, query: str) -> pd.DataFrame:
        """SPARQL-resultaat, gecachet als ruwe bindings; platgeslagen naar strings."""
        path = self.base_dir / f'{name}.json'
        use_cache = self.offline or (not self.refresh and self._is_fresh(path, CACHE_MAX_AGE_DAYS))
        if use_cache:
            if not path.exists():
                raise FileNotFoundError(f'Offline en niet in cache: {path}')
            bindings = json.loads(path.read_text(encoding='utf-8'))
        else:
            try:
                bindings = sparql_query(query, USER_AGENT)
            except Exception as e:  # noqa: BLE001
                if not self.use_stale(name, path, e):
                    raise
                bindings = json.loads(path.read_text(encoding='utf-8'))
            else:
                self.base_dir.mkdir(parents=True, exist_ok=True)
                part = path.with_name(path.name + '.part')
                try:
                    part.write_text(json.dumps(bindings), encoding='utf-8')
                    part.replace(path)
                finally:
                    part.unlink(missing_ok=True)
        rows = [{k: v['value'] for k, v in b.items()} for b in bindings]
        return pd.DataFrame(rows)
