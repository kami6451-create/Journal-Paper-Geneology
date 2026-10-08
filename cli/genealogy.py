#!/usr/bin/env python3
"""
paper_genealogy — 논문의 '시조'(조상 방향 인용 계보) 추적 도구

입력한 논문(DOI / OpenAlex ID / 제목)에서 출발해 참고문헌을 거슬러 올라가며
인용 네트워크를 만들고, 여러 갈래가 수렴하는 오래된 논문(시조 후보)을 점수로 뽑아
연도별 시계열·주제어별로 정리한 HTML 리포트를 만든다.

데이터: OpenAlex(주) + Semantic Scholar(참고문헌이 비어 있을 때 보완)
Google Scholar는 참고문헌 목록을 제공하지 않고 자동 수집이 막혀 있어 사용하지 않는다.

사용 예:
  python genealogy.py "10.1017/S0003055403000534"
  python genealogy.py "W2741809807" --depth 4 --top-refs 12 --max-papers 400
  python genealogy.py "Why Do Some Civil Wars Last So Much Longer Than Others" --field "Political Science"
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx
import requests

OPENALEX = "https://api.openalex.org"
S2 = "https://api.semanticscholar.org/graph/v1"
SELECT = ("id,doi,title,publication_year,cited_by_count,referenced_works,"
          "primary_topic,topics,authorships,primary_location")

# 시조 점수 가중치 (합계 1.0). 순위 백분위의 가중 평균으로 계산한다.
WEIGHTS = {"paths": 0.30, "indeg": 0.25, "cites": 0.15, "early": 0.20, "topic": 0.10}


# ───────────────────────────── 데이터 수집 ─────────────────────────────
def short_id(x: str) -> str:
    return x.rsplit("/", 1)[-1] if x else x


def norm_doi(d: str | None) -> str | None:
    if not d:
        return None
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", d.strip(), flags=re.I).lower()


def to_record(w: dict) -> dict:
    topics = [t.get("display_name") for t in (w.get("topics") or []) if t.get("display_name")]
    pt = w.get("primary_topic") or {}
    loc = (w.get("primary_location") or {}).get("source") or {}
    return {
        "id": short_id(w["id"]),
        "doi": norm_doi(w.get("doi")),
        "title": w.get("title") or "(제목 없음)",
        "year": w.get("publication_year"),
        "cites": w.get("cited_by_count") or 0,
        "refs": [short_id(r) for r in (w.get("referenced_works") or [])],
        "topic": pt.get("display_name") or (topics[0] if topics else "미분류"),
        "field": ((pt.get("field") or {}).get("display_name")) or "",
        "subfield": ((pt.get("subfield") or {}).get("display_name")) or "",
        "topics": topics,
        "authors": [a["author"]["display_name"] for a in (w.get("authorships") or [])[:3]
                    if a.get("author")],
        "venue": loc.get("display_name") or "",
    }


class Client:
    """OpenAlex + Semantic Scholar 클라이언트 (디스크 캐시, 재시도 포함)."""

    def __init__(self, cache_dir="cache", mailto=None, s2=True, delay=0.12):
        self.cache = Path(cache_dir)
        self.cache.mkdir(exist_ok=True)
        self.mailto = mailto          # 선택: 지정하면 OpenAlex polite pool 사용
        self.use_s2 = s2
        self.delay = delay
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "paper-genealogy/1.0"
        self.s2_key = os.environ.get("S2_API_KEY")

    # -- 공통 GET (캐시 + 재시도)
    def _get(self, url, params=None, headers=None):
        key = hashlib.md5((url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()
        f = self.cache / f"{key}.json"
        if f.exists():
            return json.loads(f.read_text())
        params = dict(params or {})
        if self.mailto and url.startswith(OPENALEX):
            params["mailto"] = self.mailto
        for attempt in range(5):
            try:
                r = self.s.get(url, params=params, headers=headers, timeout=30)
                if r.status_code == 429 or r.status_code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                data = r.json()
                f.write_text(json.dumps(data))
                time.sleep(self.delay)
                return data
            except requests.RequestException as e:
                if attempt == 4:
                    print(f"  ! 요청 실패: {url} ({e})", file=sys.stderr)
                    return None
                time.sleep(2 ** attempt)
        return None

    # -- 시드 논문 찾기
    def resolve(self, query: str) -> dict | None:
        q = query.strip()
        if re.fullmatch(r"W\d+", q, flags=re.I):
            w = self._get(f"{OPENALEX}/works/{q.upper()}", {"select": SELECT})
        elif norm_doi(q) and norm_doi(q).startswith("10."):
            w = self._get(f"{OPENALEX}/works/doi:{norm_doi(q)}", {"select": SELECT})
        else:
            res = self._get(f"{OPENALEX}/works", {"search": q, "per-page": 5, "select": SELECT})
            hits = (res or {}).get("results") or []
            if not hits:
                return None
            if len(hits) > 1:
                print("  제목 검색 후보 (첫 번째를 사용합니다):")
                for h in hits:
                    print(f"   - {h.get('publication_year')} | {h.get('title')} | {short_id(h['id'])}")
            w = hits[0]
        return to_record(w) if w else None

    # -- 여러 논문 메타데이터 일괄 조회 (OpenAlex는 OR 필터 100개까지)
    def works(self, ids: list[str]) -> list[dict]:
        out = []
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            res = self._get(f"{OPENALEX}/works", {
                "filter": "openalex:" + "|".join(chunk),
                "per-page": 100, "select": SELECT})
            out += [to_record(w) for w in (res or {}).get("results", [])]
        return out

    # -- 참고문헌이 비어 있을 때 Semantic Scholar로 보완 → OpenAlex ID로 변환
    def s2_references(self, doi: str) -> list[str]:
        if not (self.use_s2 and doi):
            return []
        h = {"x-api-key": self.s2_key} if self.s2_key else None
        data = self._get(f"{S2}/paper/DOI:{doi}/references",
                         {"fields": "externalIds", "limit": 1000}, headers=h)
        dois = []
        for item in (data or {}).get("data", []):
            d = ((item.get("citedPaper") or {}).get("externalIds") or {}).get("DOI")
            if d:
                dois.append(d.lower())
        ids = []
        for i in range(0, len(dois), 50):
            chunk = dois[i:i + 50]
            res = self._get(f"{OPENALEX}/works", {
                "filter": "doi:" + "|".join(f"https://doi.org/{d}" for d in chunk),
                "per-page": 100, "select": "id"})
            ids += [short_id(w["id"]) for w in (res or {}).get("results", [])]
        return ids


# ───────────────────────────── 계보 구축 ─────────────────────────────
def build_ancestry(client, seed: dict, depth=3, top_refs=12, max_papers=300,
                   field: str | None = None, verbose=True):
    """
    seed에서 참고문헌 방향으로 BFS. 한 논문당 '많이 인용된 상위 top_refs개'만 더 위로 확장해
    인용망이 폭발하지 않게 한다. 모든 참고 관계(간선)는 확보된 논문 사이에서 기록한다.
    """
    papers = {seed["id"]: seed}
    edges = set()                       # (인용한 논문, 인용된 논문)
    frontier = [seed["id"]]
    expanded = set()

    for d in range(1, depth + 1):
        if not frontier or len(papers) >= max_papers:
            break
        # 1) 프런티어 논문들의 참고문헌 ID 수집 (비어 있으면 S2 보완)
        ref_map = {}
        for pid in frontier:
            p = papers[pid]
            refs = list(p["refs"])
            if not refs:
                refs = client.s2_references(p["doi"])
                p["refs"] = refs
            ref_map[pid] = refs
            expanded.add(pid)
        # 2) 아직 모르는 참고문헌의 메타데이터 일괄 조회
        need = sorted({r for refs in ref_map.values() for r in refs} - set(papers))
        for rec in client.works(need):
            papers.setdefault(rec["id"], rec)
        # 3) 간선 기록 + 다음 프런티어 선정
        nxt = []
        for pid, refs in ref_map.items():
            known = [r for r in refs if r in papers]
            for r in known:
                edges.add((pid, r))
            cand = [r for r in known if r not in expanded]
            if field:
                cand = [r for r in cand if field.lower() in
                        (papers[r]["field"] + " " + papers[r]["subfield"] + " " + papers[r]["topic"]).lower()]
            cand.sort(key=lambda r: papers[r]["cites"], reverse=True)
            nxt += cand[:top_refs]
        frontier = []
        for r in dict.fromkeys(nxt):
            if len(papers) >= max_papers and r not in papers:
                continue
            frontier.append(r)
        if verbose:
            print(f"  깊이 {d}: 논문 {len(papers)}편, 간선 {len(edges)}개, 다음 확장 {len(frontier)}편")

    # 확장하지 않은 논문의 참고문헌 간선도, 이미 확보된 논문끼리라면 추가 (수렴 판별 정확도↑)
    for pid, p in papers.items():
        for r in p["refs"]:
            if r in papers:
                edges.add((pid, r))
    return papers, edges


# ───────────────────────────── 분석 ─────────────────────────────
def pct_rank(values: dict) -> dict:
    """값 → 0~1 백분위 순위 (동률은 평균 순위)."""
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n <= 1:
        return {k: 1.0 for k in values}
    out, i = {}, 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        r = (i + j) / 2 / (n - 1)
        for k in range(i, j + 1):
            out[items[k][0]] = r
        i = j + 1
    return out


def analyze(papers: dict, edges: set, seed_id: str) -> dict:
    # 인용 방향 u→v = "u가 v를 인용". 인용된 논문이 더 늦은 연도면 데이터 오류로 보고 제거.
    G = nx.DiGraph()
    G.add_nodes_from(papers)
    for u, v in edges:
        yu, yv = papers[u]["year"], papers[v]["year"]
        if u != v and (yu is None or yv is None or yv <= yu):
            G.add_edge(u, v)
    while True:                          # 같은 해 상호 인용 등 남은 순환 제거
        try:
            cyc = nx.find_cycle(G)
            G.remove_edge(*cyc[0][:2])
        except nx.NetworkXNoCycle:
            break

    anc = nx.descendants(G, seed_id)    # 시드가 (직·간접) 인용한 모든 논문 = 조상
    sub = G.subgraph(anc | {seed_id}).copy()

    # 시드에서 각 조상까지의 서로 다른 경로 수 (여러 갈래가 수렴할수록 큼)
    paths = defaultdict(float)
    paths[seed_id] = 1.0
    for u in nx.topological_sort(sub):
        for v in sub.successors(u):
            paths[v] += paths[u]

    seed_topics = set(papers[seed_id]["topics"]) | {papers[seed_id]["topic"]}
    years = [papers[a]["year"] for a in anc if papers[a]["year"]]
    ymin, ymax = (min(years), max(years)) if years else (0, 1)

    raw = {k: {} for k in WEIGHTS}
    for a in anc:
        p = papers[a]
        raw["paths"][a] = math.log1p(paths[a])
        raw["indeg"][a] = sub.in_degree(a)          # 조상 집합 안에서 이 논문을 인용한 논문 수
        raw["cites"][a] = math.log1p(p["cites"])
        y = p["year"] or ymax
        raw["early"][a] = (ymax - y) / max(1, ymax - ymin)
        t = set(p["topics"]) | {p["topic"]}
        raw["topic"][a] = len(t & seed_topics) / max(1, len(t | seed_topics))
    ranks = {k: pct_rank(v) for k, v in raw.items()}
    score = {a: sum(WEIGHTS[k] * ranks[k][a] for k in WEIGHTS) for a in anc}

    # 시드 → 최상위 시조 후보 사이의 '주 계보' 경로 (경로상 인용수 합이 최대인 사슬)
    ranking = sorted(anc, key=lambda a: score[a], reverse=True)
    lineage = []
    if ranking:
        target = ranking[0]
        best, prev = {seed_id: 0.0}, {}
        for u in nx.topological_sort(sub):
            if u not in best:
                continue
            for v in sub.successors(u):
                w = best[u] + math.log1p(papers[v]["cites"])
                if w > best.get(v, -1):
                    best[v], prev[v] = w, u
        if target in best:
            node = target
            while node != seed_id:
                lineage.append(node)
                node = prev[node]
            lineage.append(seed_id)
            lineage.reverse()

    return {"graph": sub, "ancestors": anc, "paths": paths, "score": score,
            "ranking": ranking, "lineage": lineage, "ranks": ranks}


# ───────────────────────────── 출력 ─────────────────────────────
def label(p):
    au = ", ".join(p["authors"][:2]) + (" 외" if len(p["authors"]) > 2 else "")
    return f"{au} ({p['year']}) {p['title']}"


def write_csv(path, papers, res, seed_id):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["순위", "시조점수", "연도", "제목", "저자", "주제", "인용수", "조상내 피인용", "경로수", "DOI", "OpenAlex"])
        for i, a in enumerate(res["ranking"], 1):
            p = papers[a]
            w.writerow([i, f"{res['score'][a]:.3f}", p["year"], p["title"], "; ".join(p["authors"]),
                        p["topic"], p["cites"], res["graph"].in_degree(a), int(res["paths"][a]),
                        p["doi"] or "", a])


def write_html(path, papers, res, seed_id, top_n=15):
    G, score, anc = res["graph"], res["score"], res["ancestors"]
    seed = papers[seed_id]
    nodes = [n for n in G.nodes if papers[n]["year"]]
    years = [papers[n]["year"] for n in nodes]
    y0, y1 = min(years), max(years)
    top = res["ranking"][:top_n]
    top_set, lineage = set(top[:5]), set(res["lineage"])

    # 주제 레인: 노드 수 상위 8개 + 기타
    cnt = Counter(papers[n]["topic"] for n in nodes)
    lanes = [t for t, _ in cnt.most_common(8)]
    lane_of = lambda n: lanes.index(papers[n]["topic"]) if papers[n]["topic"] in lanes else len(lanes)
    names = lanes + (["기타"] if any(papers[n]["topic"] not in lanes for n in nodes) else [])
    palette = ["#4e79a7", "#f28e2b", "#59a14f", "#b07aa1", "#76b7b2", "#edc948", "#9c755f", "#af7aa1", "#bab0ac"]

    W, LH, ML, MT = 1180, 74, 190, 36
    H = MT + LH * len(names) + 30
    px = lambda y: ML + 18 + (y - y0) / max(1, y1 - y0) * (W - ML - 60)

    def jitter(n):
        return (int(hashlib.md5(n.encode()).hexdigest()[:6], 16) % 1000) / 1000 - 0.5

    pos = {n: (px(papers[n]["year"]), MT + lane_of(n) * LH + LH / 2 + jitter(n) * (LH - 26)) for n in nodes}
    svg = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="연도×주제 인용 계보">']
    step = 5 if y1 - y0 > 30 else 2
    for y in range((y0 // step) * step, y1 + 1, step):
        if y < y0:
            continue
        svg.append(f'<line x1="{px(y):.0f}" y1="{MT-8}" x2="{px(y):.0f}" y2="{H-24}" class="grid"/>'
                   f'<text x="{px(y):.0f}" y="{H-8}" class="ax" text-anchor="middle">{y}</text>')
    for i, nm in enumerate(names):
        yy = MT + i * LH
        svg.append(f'<rect x="{ML}" y="{yy}" width="{W-ML-30}" height="{LH}" class="lane{i%2}"/>'
                   f'<text x="{ML-8}" y="{yy+LH/2+4}" class="ax" text-anchor="end">{html.escape(nm[:26])}</text>')
    for u, v in G.edges:
        if u in pos and v in pos:
            on = u in lineage and v in lineage
            svg.append(f'<line x1="{pos[u][0]:.1f}" y1="{pos[u][1]:.1f}" x2="{pos[v][0]:.1f}" y2="{pos[v][1]:.1f}" '
                       f'class="{"edge main" if on else "edge"}"/>')
    maxc = max(papers[n]["cites"] for n in nodes) or 1
    for n in sorted(nodes, key=lambda n: papers[n]["cites"]):
        p, (x, y) = papers[n], pos[n]
        r = 3 + 9 * math.sqrt(p["cites"] / maxc)
        col = palette[min(lane_of(n), len(palette) - 1)]
        cls = "node seed" if n == seed_id else ("node founder" if n in top_set else "node")
        tip = html.escape(f"{label(p)}\n주제: {p['topic']} · 인용 {p['cites']:,}" +
                          (f" · 시조점수 {score[n]:.2f}" if n in score else ""))
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{col}" class="{cls}"><title>{tip}</title></circle>')
    svg.append("</svg>")

    def row(i, a):
        p = papers[a]
        link = f'https://doi.org/{p["doi"]}' if p["doi"] else f'https://openalex.org/{a}'
        return (f'<tr><td>{i}</td><td>{score[a]:.2f}</td><td>{p["year"]}</td>'
                f'<td><a href="{link}" target="_blank" rel="noopener">{html.escape(p["title"])}</a>'
                f'<div class="sub">{html.escape(", ".join(p["authors"]))}</div></td>'
                f'<td>{html.escape(p["topic"])}</td><td>{p["cites"]:,}</td>'
                f'<td>{G.in_degree(a)}</td><td>{int(res["paths"][a]):,}</td></tr>')

    founder_rows = "".join(row(i, a) for i, a in enumerate(top, 1))
    lin = "".join(f'<li><b>{papers[n]["year"]}</b> · {html.escape(papers[n]["title"])}'
                  f'<span class="sub"> — {html.escape(", ".join(papers[n]["authors"]))}</span></li>'
                  for n in reversed(res["lineage"]))

    by_year = defaultdict(list)
    for a in anc:
        if papers[a]["year"]:
            by_year[papers[a]["year"]].append(a)
    decade = defaultdict(list)
    for y, l in by_year.items():
        decade[y // 10 * 10] += l
    tl = ""
    mx = max(len(v) for v in decade.values()) if decade else 1
    for d in sorted(decade):
        l = sorted(decade[d], key=lambda a: score[a], reverse=True)
        tl += (f'<div class="dec"><div class="dh"><b>{d}년대</b> <span class="sub">{len(l)}편</span>'
               f'<span class="bar" style="width:{int(160*len(l)/mx)}px"></span></div>'
               f'<ul>' + "".join(f'<li>{papers[a]["year"]} · {html.escape(papers[a]["title"][:90])}</li>' for a in l[:4]) +
               '</ul></div>')

    tcount = Counter(papers[a]["topic"] for a in anc)
    topic_rows = ""
    for t, c in tcount.most_common(12):
        mem = [a for a in anc if papers[a]["topic"] == t]
        oldest = min(mem, key=lambda a: papers[a]["year"] or 9999)
        topic_rows += (f'<tr><td>{html.escape(t)}</td><td>{c}</td><td>{papers[oldest]["year"]}</td>'
                       f'<td>{html.escape(papers[oldest]["title"][:80])}</td></tr>')

    doc = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>논문 계보 리포트 — {html.escape(seed['title'][:50])}</title>
<style>
:root{{--bg:#fafaf7;--fg:#1d1d1b;--mut:#6b6b66;--card:#fff;--line:#e3e1da;--acc:#b3261e}}
@media(prefers-color-scheme:dark){{:root{{--bg:#161614;--fg:#ecebe5;--mut:#9a9890;--card:#1f1f1c;--line:#34332e;--acc:#ff8a80}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,"Noto Sans KR",sans-serif}}
main{{max-width:1240px;margin:0 auto;padding:24px 16px 60px}}
h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:17px;margin:34px 0 10px}}
.sub{{color:var(--mut);font-size:12.5px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-top:10px;overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}}th,td{{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--mut);font-weight:600;font-size:12px}}a{{color:inherit}}
.grid{{stroke:var(--line);stroke-width:1}}.ax{{fill:var(--mut);font-size:11px}}
.lane0{{fill:transparent}}.lane1{{fill:rgba(128,128,120,.07)}}
.edge{{stroke:var(--mut);stroke-opacity:.14;stroke-width:1}}.edge.main{{stroke:var(--acc);stroke-opacity:.85;stroke-width:2.2}}
.node{{fill-opacity:.82;stroke:var(--card);stroke-width:1}}.node.founder{{stroke:var(--acc);stroke-width:2.5}}.node.seed{{stroke:var(--fg);stroke-width:3}}
.lin li{{margin:4px 0}}.dec{{margin:8px 0}}.dh{{display:flex;gap:10px;align-items:center}}
.bar{{display:inline-block;height:8px;background:var(--acc);opacity:.55;border-radius:4px}}.dec ul{{margin:2px 0 0;padding-left:18px;color:var(--mut);font-size:12.5px}}
.legend{{font-size:12.5px;color:var(--mut)}}
</style></head><body><main>
<h1>논문 계보 리포트</h1>
<div class="sub">시작 논문: <b>{html.escape(label(seed))}</b> · 조상 논문 {len(anc)}편 · 간선 {G.number_of_edges()}개 · {y0}–{y1}</div>

<h2>① 시조 후보 상위 {len(top)}편</h2>
<div class="card"><table><tr><th>#</th><th>점수</th><th>연도</th><th>논문</th><th>주제</th><th>총 인용</th><th>조상 내 피인용</th><th>경로 수</th></tr>{founder_rows}</table>
<p class="sub">점수 = 경로 수 {WEIGHTS['paths']:.0%} + 조상 내 피인용 {WEIGHTS['indeg']:.0%} + 전체 인용수 {WEIGHTS['cites']:.0%} + 오래됨 {WEIGHTS['early']:.0%} + 주제 유사도 {WEIGHTS['topic']:.0%} (각 항목은 순위 백분위). 결과는 휴리스틱이므로 후보를 직접 읽어 확인하세요.</p></div>

<h2>② 연도 × 주제 지도</h2>
<div class="card">{''.join(svg)}
<div class="legend">가로=출판연도, 세로=주제, 원 크기=총 인용수, 빨간 테두리=시조 후보 상위 5편, 굵은 테두리=시작 논문, 붉은 선=주 계보 경로. 원에 마우스를 올리면 제목이 보입니다.</div></div>

<h2>③ 시작 논문 → 시조 후보 1위 주 계보</h2>
<div class="card"><ol class="lin">{lin or '<li>경로를 찾지 못했습니다.</li>'}</ol></div>

<h2>④ 연대별 시계열</h2><div class="card">{tl}</div>

<h2>⑤ 주제별 정리 (주제별 가장 오래된 논문)</h2>
<div class="card"><table><tr><th>주제</th><th>편수</th><th>최초 연도</th><th>최초 논문</th></tr>{topic_rows}</table></div>
</main></body></html>"""
    Path(path).write_text(doc, encoding="utf-8")


# ───────────────────────────── CLI ─────────────────────────────
def run(client, query, args):
    print(f"[1/3] 시작 논문 확인: {query}")
    seed = client.resolve(query)
    if not seed:
        sys.exit("논문을 찾지 못했습니다. DOI나 OpenAlex ID(W...)로 다시 시도해 보세요.")
    print(f"  → {label(seed)}  [{seed['id']}]  참고문헌 {len(seed['refs'])}개")
    print("[2/3] 참고문헌을 거슬러 올라가며 인용망 구축")
    papers, edges = build_ancestry(client, seed, args.depth, args.top_refs, args.max_papers, args.field)
    print("[3/3] 시조 후보 분석 및 리포트 생성")
    res = analyze(papers, edges, seed["id"])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    base = out / seed["id"]
    write_csv(f"{base}_ancestors.csv", papers, res, seed["id"])
    write_html(f"{base}_report.html", papers, res, seed["id"], args.top_n)
    Path(f"{base}_graph.json").write_text(json.dumps({
        "seed": seed["id"], "papers": papers, "edges": sorted(res["graph"].edges),
        "scores": res["score"]}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n시조 후보 상위 {min(5, len(res['ranking']))}편:")
    for i, a in enumerate(res["ranking"][:5], 1):
        print(f"  {i}. [{res['score'][a]:.2f}] {label(papers[a])}")
    print(f"\n리포트: {base}_report.html")
    return res, papers


def main():
    ap = argparse.ArgumentParser(description="논문의 시조(조상 방향 인용 계보) 추적")
    ap.add_argument("query", help="DOI, OpenAlex ID(W...), 또는 제목")
    ap.add_argument("--depth", type=int, default=3, help="참고문헌을 거슬러 올라갈 단계 수 (기본 3)")
    ap.add_argument("--top-refs", type=int, default=12, help="논문당 더 위로 확장할 상위 인용 참고문헌 수 (기본 12)")
    ap.add_argument("--max-papers", type=int, default=300, help="수집 논문 상한 (기본 300)")
    ap.add_argument("--field", default=None, help='확장 대상을 분야 문자열로 제한 (예: "Political Science")')
    ap.add_argument("--top-n", type=int, default=15, help="리포트에 표시할 시조 후보 수")
    ap.add_argument("--out", default="output")
    ap.add_argument("--mailto", default=None, help="(선택) OpenAlex polite pool용 이메일. 지정하지 않으면 보내지 않음")
    ap.add_argument("--no-s2", action="store_true", help="Semantic Scholar 보완 끄기")
    args = ap.parse_args()
    run(Client(mailto=args.mailto, s2=not args.no_s2), args.query, args)


if __name__ == "__main__":
    main()
