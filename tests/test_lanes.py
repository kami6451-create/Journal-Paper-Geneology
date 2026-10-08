"""연도×주제 지도: 분류명 방식에서 주제 20칸 + '기타', 칸 수 슬라이더, 노드 크기 = 인용수, 참고문헌 확장 최대 50."""
from helpers import flat_network, open_app, run_trace, set_slider

NET = flat_network(n=260, n_topics=30)


def _lane_count(page):
    return page.locator("#mapbox rect.lane0, #mapbox rect.lane1").count()


def test_주제_20칸과_노드_크기(make_page):
    page = make_page()
    open_app(page, NET)
    assert page.get_attribute("#topRefs", "max") == "50"
    set_slider(page, "topRefs", 50)
    assert page.inner_text("#topRefsV") == "50"
    set_slider(page, "depth", 6)
    set_slider(page, "maxPapers", 1000)
    run_trace(page, f"W{NET.n}")

    page.select_option("#grp", "topic")                       # 분류명 방식
    assert _lane_count(page) == 21                             # 상위 20개 + 기타
    assert "20개" in page.inner_text("#grpNote")
    fills = page.eval_on_selector_all("#mapbox circle", "els => new Set(els.map(e => e.getAttribute('fill'))).size")
    assert fills >= 15                                         # 20색 팔레트로 칸이 구분됨

    # 노드 크기: 반지름 = 3 + 9·√(인용수/최대 인용수)
    rs = page.eval_on_selector_all(
        "#mapbox circle",
        "els => els.map(e => [+e.querySelector('title').textContent.match(/인용 ([\\d,]+)/)[1].replace(/,/g, ''), +e.getAttribute('r')])")
    mx = max(c for c, _ in rs)
    bad = [(c, r) for c, r in rs if abs(r - (3 + 9 * (c / mx) ** 0.5)) > 0.06]
    assert len(rs) > 50 and not bad, bad[:3]

    set_slider(page, "laneN", 10)                              # 추적을 다시 하지 않고 지도만 갱신
    assert _lane_count(page) == 11
    set_slider(page, "laneN", 20)
    assert _lane_count(page) == 21
