"""테스트 공통 코드: 가짜 OpenAlex 서버와 가짜 인용망 생성기.

실제 네트워크에 접속하지 않고 브라우저의 API 요청(api.openalex.org, api.semanticscholar.org)을
Playwright로 가로채 가짜 응답을 돌려준다. 그래서 테스트는 인터넷 없이, 결과가 항상 같게 돌아간다.
"""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
APP_URL = (ROOT / "index.html").as_uri()
CORS = {"access-control-allow-origin": "*", "content-type": "application/json"}


# ───────────── 가짜 인용망 ─────────────
@dataclass
class Network:
    n: int
    recs: dict                      # id(int) -> {year, cites, refs, topic, title, kw}
    theme: dict = field(default_factory=dict)

    def work(self, i: int) -> dict:
        """레코드를 OpenAlex 'work' JSON 모양으로 바꾼다."""
        r = self.recs[i]
        return {
            "id": f"https://openalex.org/W{i}", "doi": f"https://doi.org/10.0000/x{i}",
            "title": r["title"], "publication_year": r["year"], "cited_by_count": r["cites"],
            "referenced_works": [f"https://openalex.org/W{j}" for j in r["refs"]],
            "primary_topic": {"display_name": r["topic"], "field": {"display_name": "Political Science"},
                              "subfield": {"display_name": "x"}},
            "topics": [{"display_name": r["topic"]}],
            "keywords": [{"id": "k", "display_name": k, "score": 0.6} for k in r.get("kw", [])],
            "authorships": [{"author": {"display_name": f"Author{i % 40}"}}],
            "primary_location": {"source": {"display_name": "Journal"}},
        }


def _year(i: int, n: int) -> int:
    return 1950 + int(74 * (i / n) ** 0.9)


def _attach(recs: dict, n: int, rng: random.Random, weight) -> None:
    for i in range(3, n + 1):
        pool = list(range(1, i))
        w = [weight(j, i) for j in pool]
        chosen: set[int] = set()
        k = min(len(pool), rng.randint(5, 12))
        while len(chosen) < k:
            chosen.add(rng.choices(pool, w)[0])
        recs[i]["refs"] = sorted(chosen)
        for j in chosen:
            recs[j]["cites"] += 1


def classic_network(n: int = 260, seed: int = 7) -> Network:
    """초기 고전 W1, W2가 압도적으로 인용되는 망. 제목에 <b> 태그를 넣어 이스케이프도 함께 검증한다."""
    rng = random.Random(seed)
    topics = ["Political Behavior", "Institutional Theory", "Comparative Politics",
              "Electoral Systems", "International Relations", "Public Administration"]
    recs = {i: {"year": _year(i, n), "cites": 0, "refs": [], "topic": rng.choice(topics),
                "title": f"Paper {i} <b>x</b>"} for i in range(1, n + 1)}
    _attach(recs, n, rng, lambda j, i: 1 + recs[j]["cites"] ** 1.3 + (30 if j in (1, 2) else 0))
    return Network(n, recs)


def flat_network(n: int = 260, n_topics: int = 30, seed: int = 7) -> Network:
    """인용이 넓게 퍼지고 분류명이 n_topics종인 망 (주제 칸 수·노드 크기 검증용)."""
    rng = random.Random(seed)
    recs = {i: {"year": _year(i, n), "cites": 0, "refs": [], "topic": f"주제 {rng.randrange(n_topics):02d} Topic",
                "title": f"Paper {i}"} for i in range(1, n + 1)}
    _attach(recs, n, rng, lambda j, i: 1 + recs[j]["cites"] ** 0.15)
    return Network(n, recs)


THEMES = [
    ("civil war", ["insurgency", "rebellion", "ethnic", "secession", "guerrilla", "ceasefire", "militia", "warlord"]),
    ("voter turnout", ["voting", "ballot", "turnout", "electorate", "campaign", "partisan", "polling", "candidate"]),
    ("legislative process", ["legislature", "parliament", "committee", "bicameral", "lawmaking", "caucus", "filibuster", "amendment"]),
    ("trade policy", ["tariff", "trade", "sanction", "embargo", "export", "import", "customs", "protectionism"]),
    ("regime change", ["democratization", "regime", "authoritarian", "transition", "autocracy", "coup", "junta", "dictatorship"]),
    ("public administration", ["bureaucracy", "agency", "regulation", "administration", "delegation", "oversight", "patronage", "accountability"]),
]


def themed_network(n: int = 240, seed: int = 11) -> Network:
    """숨은 주제 6개. 제목·키워드는 자기 주제의 단어로 만들고, OpenAlex 분류명은 주제와 무관하게 무작위로 붙인다."""
    rng = random.Random(seed)
    noise = [f"Social Science {c}" for c in "ABCDEFGHIJ"]
    theme, recs = {}, {}
    for i in range(1, n + 1):
        theme[i] = (i - 1) % 6 if i <= 6 else rng.randrange(6)
        phrase, vocab = THEMES[theme[i]]
        w = rng.sample(vocab, 4)
        recs[i] = {"year": _year(i, n), "cites": 0, "refs": [], "topic": rng.choice(noise),
                   "title": f"{w[0]} {w[1]} and {w[2]} in politics", "kw": [phrase, w[0], w[3]]}
    for i in range(7, n + 1):
        pool = list(range(1, i))
        wt = [(1 + recs[j]["cites"]) * (5 if theme[j] == theme[i] else 1) + (40 if j <= 6 and theme[j] == theme[i] else 0) for j in pool]
        chosen: set[int] = set()
        while len(chosen) < min(len(pool), rng.randint(6, 12)):
            chosen.add(rng.choices(pool, wt)[0])
        recs[i]["refs"] = sorted(chosen)
        for j in chosen:
            recs[j]["cites"] += 1
    return Network(n, recs, theme)


# ───────────── 가짜 서버 ─────────────
class MockOpenAlex:
    """브라우저의 OpenAlex 요청을 가로채 Network의 데이터로 응답한다. delay(초)로 느린 서버를 흉내 낼 수 있다."""

    def __init__(self, net: Network, delay: float = 0.0):
        self.net, self.delay, self.requests = net, delay, 0

    def handler(self, route):
        self.requests += 1
        if self.delay:
            time.sleep(self.delay)
        u = urlparse(route.request.url)
        q = parse_qs(u.query)
        path = unquote(u.path)
        recs, body = self.net.recs, None
        if m := re.fullmatch(r"/works/W(\d+)", path):
            body = self.net.work(int(m.group(1))) if int(m.group(1)) in recs else None
        elif m := re.fullmatch(r"/works/doi:10\.0000/x(\d+)", path):
            body = self.net.work(int(m.group(1))) if int(m.group(1)) in recs else None
        elif "filter" in q and q["filter"][0].startswith("openalex:"):
            ids = [int(x[1:]) for x in q["filter"][0][len("openalex:"):].split("|")]
            body = {"results": [self.net.work(i) for i in ids if i in recs]}
        elif "search" in q:
            n = self.net.n
            body = {"results": [self.net.work(i) for i in (n, n - 1, n - 2) if i in recs]}
        route.fulfill(status=200 if body is not None else 404, headers=CORS, body=json.dumps(body if body is not None else {}))


def open_app(page, net: Network, delay: float = 0.0) -> MockOpenAlex:
    """가짜 서버를 연결하고 앱(index.html)을 연다."""
    mock = MockOpenAlex(net, delay)
    page.route("https://api.openalex.org/**", mock.handler)
    page.route("https://api.semanticscholar.org/**",
               lambda r: r.fulfill(status=200, headers=CORS, body='{"data":[]}'))
    page.goto(APP_URL)
    return mock


# ───────────── 화면 조작 ─────────────
def set_slider(page, element_id: str, value: int) -> None:
    page.eval_on_selector(f"#{element_id}", f"e => {{ e.value = {value}; e.dispatchEvent(new Event('input')); }}")


def run_trace(page, query: str, timeout: int = 60000) -> None:
    """질의를 넣고 추적이 끝날 때까지(진행 문구가 '완료'로 시작할 때까지) 기다린다."""
    page.fill("#q", query)
    page.click("#go")
    page.wait_for_function("document.querySelector('#msg').innerText.startsWith('완료')", timeout=timeout)
    page.wait_for_selector("#out #mapbox svg", timeout=timeout)
