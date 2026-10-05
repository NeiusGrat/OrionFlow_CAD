"""Part-level geometry cache: unchanged parts are not re-analysed.

    geometry_hash = sha256(BRep serialisation of the part in its own frame
                           + EXTRACTION_VERSION)

The BRep text is written without triangulation, so it is a function of the
exact geometry the STEP carried; it is streamed to a temp file and hashed in
blocks, never held in memory whole. Two exports of an unchanged part hash the
same, so Rev C re-uses Rev B's features for every part that did not change.

What is cached: the extracted features (holes, bosses, planar faces with their
face *index*, mass properties, mesh classification). The B-rep itself is never
cached; planar faces are re-attached from the live shape by index on a hit.

Backends: a directory (local, or a Modal volume path) or any :class:`Storage`
(object storage under ``cache/features/``). Entries are gzip JSON written only
by workers, never by users.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from pathlib import Path

from OCP.BRepTools import BRepTools
from OCP.TopTools import TopTools_FormatVersion

from .features import extract, from_record, to_record
from .models import Features
from .version import EXTRACTION_VERSION


def geometry_hash(shape, workdir: str | Path | None = None) -> str:
    fd, tmp = tempfile.mkstemp(suffix=".brep", dir=workdir)
    os.close(fd)
    try:
        BRepTools.Write_s(shape, tmp, False, False, TopTools_FormatVersion.TopTools_FormatVersion_VERSION_3)
        h = hashlib.sha256(EXTRACTION_VERSION.encode())
        with open(tmp, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    finally:
        os.unlink(tmp)


class FeatureCache:
    """get/put extracted features by geometry hash."""

    def __init__(self, root: str | Path | None = None, storage=None, prefix: str = "cache/features"):
        self.root = Path(root) if root else None
        self.storage = storage
        self.prefix = prefix
        self.hits = 0
        self.misses = 0

    def _key(self, h: str) -> str:
        return f"{self.prefix}/{h[:2]}/{h}.json.gz"

    def get(self, h: str) -> dict | None:
        data = None
        if self.root is not None:
            p = self.root / self._key(h)
            if p.exists():
                data = p.read_bytes()
        elif self.storage is not None and self.storage.exists(self._key(h)):
            data = self.storage.get_bytes(self._key(h))
        if data is None:
            return None
        try:
            rec = json.loads(gzip.decompress(data))
        except (OSError, ValueError):
            return None                     # a corrupt entry is a miss, never an error
        return rec if rec.get("extraction_version") == EXTRACTION_VERSION else None

    def put(self, h: str, rec: dict) -> None:
        data = gzip.compress(json.dumps(rec).encode())
        if self.root is not None:
            p = self.root / self._key(h)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, p)               # atomic: concurrent workers never read half an entry
        elif self.storage is not None:
            self.storage.put_bytes(self._key(h), data)

    def features(self, shape, workdir: str | Path | None = None) -> tuple[Features, str]:
        h = geometry_hash(shape, workdir)
        rec = self.get(h)
        if rec is not None:
            self.hits += 1
            return from_record(rec, shape), h
        self.misses += 1
        f = extract(shape)
        self.put(h, to_record(f))
        return f, h

    @property
    def hit_rate(self) -> float:
        n = self.hits + self.misses
        return round(self.hits / n, 4) if n else 0.0


class NoCache(FeatureCache):
    def __init__(self):
        super().__init__()

    def features(self, shape, workdir=None) -> tuple[Features, str]:
        self.misses += 1
        return extract(shape), ""
