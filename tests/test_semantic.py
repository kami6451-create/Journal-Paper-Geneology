"""의미 키워드 기반 주제 묶기.

숨은 주제 6개가 섞인 가짜 인용망에서, OpenAlex 분류명은 주제와 무관하게 무작위로 붙어 있다.
분류명 방식은 못 맞히고, 의미 키워드 방식은 숨은 주제를 복원해야 한다."""
from helpers import THEMES, open_app, run_trace, set_slider, themed_network

NET = themed_network()
VOCAB = {w for _, words in THEMES for w in words} | {ph for ph, _ in THEMES}

GROUP_JS = """(mode) => { const ids = [...last.res.anc, last.seed.id].filter(n => last.papers.get(n).year);
  const g = mode === 'sem' ? groupSemantic(last.papers, last.sem, ids, 6, last.seed.id) : groupTopic(last.papers, ids, 6);
  return {idx: [...g.idx], names: g.names, seedLane: g.idx.get(last.seed.id)}; }"""


def purity(idx_pairs, theme):
    """묶음별로 가장 많은 숨은 주제의 비율 (전체 가중 평균). 1.0이면 완벽."""
    lanes: dict = {}
    for paper_id, lane in idx_pairs:
        lanes.setdefault(lane, []).append(theme[int(paper_id[1:])])
    total = sum(len(m) for m in lanes.values())
    return sum(max(m.count(t) for t in set(m)) for m in lanes.values()) / total


def _traced(make_page):
    page = make_page()
    open_app(page, NET)
    set_slider(page, "depth", 6)
    set_slider(page, "topRefs", 30)
    set_slider(page, "maxPapers", 1000)
    run_trace(page, f"W{NET.n}")
    return page


def test_의미_키워드_묶음이_숨은_주제를_복원한다(make_page):
    page = _traced(make_page)
    sem, top = page.evaluate(GROUP_JS, "sem"), page.evaluate(GROUP_JS, "topic")
    p_sem, p_top = purity(sem["idx"], NET.theme), purity(top["idx"], NET.theme)
    assert p_sem >= 0.85, p_sem
    assert p_sem > p_top + 0.3, (p_sem, p_top)                 # 무작위 분류명 방식보다 확실히 낫다
    assert sem["seedLane"] == 0                                 # 내 논문과 가까운 주제가 맨 위
    names = [n for n in sem["names"] if not n.startswith("기타")]
    assert sum(any(w in n for w in VOCAB) for n in names) >= len(names) - 1   # 주제 이름에 실제 주제어가 들어감


def test_핵심_키워드_기원이_정확하다(make_page):
    """각 키워드의 '가장 먼저 쓴 논문'이, 조상 논문을 직접 훑어 찾은 최초 연도와 같아야 한다."""
    page = _traced(make_page)
    rows = page.evaluate("termOrigins(last.papers, last.res, last.seed.id, last.sem, 8)"
                         ".map(r => ({name: r.name, firstYear: last.papers.get(r.first).year}))")
    assert rows
    anc = page.evaluate("[...last.res.anc]")
    recs = NET.recs
    for r in rows:
        w = r["name"].split()[0]
        years = [recs[int(a[1:])]["year"] for a in anc
                 if w in recs[int(a[1:])]["title"].split() or r["name"] in recs[int(a[1:])]["kw"] or w in recs[int(a[1:])]["kw"]]
        assert r["firstYear"] == min(years), (r, min(years))
    assert "핵심 키워드는 어디서 시작됐나" in page.inner_text("#out")


def test_묶는_방식_전환과_화면_요소(make_page):
    page = _traced(make_page)
    assert "의미 키워드 기반" in page.inner_text("#grpNote")
    assert "대표 키워드" in page.inner_text("#themebox")
    # 마우스를 올리면 보이는 설명에 키워드가 들어 있다
    assert page.eval_on_selector_all("#mapbox circle title", "t => t.every(x => x.textContent.includes('키워드:'))")
    page.select_option("#grp", "topic")
    assert "OpenAlex 분류명" in page.inner_text("#grpNote")
    page.select_option("#grp", "sem")
    set_slider(page, "laneN", 6)
    assert page.locator("#mapbox rect.lane0, #mapbox rect.lane1").count() <= 7


def test_논문_1000편에서도_즉시_계산된다(make_page):
    """성능 회귀 방지: 1000편 · 주제 20개를 묶는 데 3초를 넘지 않는다 (실측 약 0.15초)."""
    page = make_page()
    page.goto(__import__("helpers").APP_URL)
    ms = page.evaluate("""() => {
      let s = 12345; const rnd = () => (s = (s * 1103515245 + 12345) % 2147483648) / 2147483648;
      const V = Array.from({length: 400}, (_, i) => 'w' + i + 'x'), papers = new Map();
      for (let i = 0; i < 1000; i++) {
        const th = Math.floor(rnd() * 20), t = [];
        for (let k = 0; k < 5; k++) t.push(V[(th * 20 + Math.floor(rnd() * 20)) % 400]);
        papers.set('W' + i, {id: 'W' + i, title: t.join(' '), year: 1950 + (i % 70), cites: Math.floor(rnd() * 500),
          topic: 'T' + th, topics: ['T' + th], kw: [{t: t[0] + ' ' + t[1], s: .5}], authors: [], refs: []});
      }
      const t0 = performance.now(), sem = buildSemantic(papers);
      const g = groupSemantic(papers, sem, [...papers.keys()], 20, 'W0');
      return [performance.now() - t0, g.names.length]; }""")
    assert ms[0] < 3000 and ms[1] >= 15, ms
