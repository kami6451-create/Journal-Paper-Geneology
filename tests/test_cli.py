"""cli/genealogy.py (초기 버전 명령줄 도구)를 가짜 데이터로 검증한다. 네트워크는 쓰지 않는다."""
import argparse
import importlib.util
import random
from pathlib import Path

import pytest

pytest.importorskip("networkx")
ROOT = Path(__file__).resolve().parents[1]


def _load_cli():
    spec = importlib.util.spec_from_file_location("genealogy_cli", ROOT / "cli" / "genealogy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MockClient:
    def __init__(self, recs):
        self.recs = recs

    def resolve(self, q):
        return self.recs[q]

    def works(self, ids):
        return [self.recs[i] for i in ids if i in self.recs]

    def s2_references(self, doi):
        return []


def _recs(n=260, seed=7):
    rng = random.Random(seed)
    topics = ["Political Behavior", "Institutional Theory", "Comparative Politics", "Electoral Systems",
              "International Relations", "Public Administration"]
    recs = {}
    for i in range(1, n + 1):
        t = rng.choice(topics)
        recs[f"W{i}"] = {"id": f"W{i}", "doi": f"10.0000/x{i}", "title": f"Paper {i}", "year": 1950 + int(74 * (i / n) ** 0.9),
                         "cites": 0, "refs": [], "topic": t, "field": "Political Science", "subfield": "",
                         "topics": [t], "authors": [f"Author{i % 40}"], "venue": ""}
    for i in range(3, n + 1):
        pool = list(range(1, i))
        w = [1 + recs[f"W{j}"]["cites"] ** 1.3 + (30 if j in (1, 2) else 0) for j in pool]
        chosen: set[int] = set()
        while len(chosen) < min(len(pool), rng.randint(5, 12)):
            chosen.add(rng.choices(pool, w)[0])
        recs[f"W{i}"]["refs"] = [f"W{j}" for j in chosen]
        for j in chosen:
            recs[f"W{j}"]["cites"] += 1
    return recs


def test_CLI가_시조를_찾고_결과_파일을_만든다(tmp_path):
    cli = _load_cli()
    args = argparse.Namespace(depth=4, top_refs=10, max_papers=200, field=None, top_n=15, out=str(tmp_path))
    res, papers = cli.run(MockClient(_recs()), "W260", args)
    assert any(t in ("W1", "W2") for t in res["ranking"][:3])     # 심어 둔 고전이 상위권
    assert res["lineage"][0] == "W260" and res["lineage"][-1] == res["ranking"][0]
    names = {p.name for p in tmp_path.iterdir()}
    assert {"W260_report.html", "W260_ancestors.csv", "W260_graph.json"} <= names
