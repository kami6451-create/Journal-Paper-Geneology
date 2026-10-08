"""웹 앱(index.html)의 기본 동작: 첫 화면 설정, 검색 입력 방식, 결과, 오류 처리, 진행 표시, CSV 저장."""
import re

import pytest

from helpers import APP_URL, classic_network, open_app, run_trace, set_slider

NET = classic_network()
N = NET.n


def test_첫_화면_기본값은_6단계_50편_500편(make_page):
    page = make_page()
    page.goto(APP_URL)
    vals = page.evaluate("['depth','topRefs','maxPapers'].map(i => [document.getElementById(i).value, document.getElementById(i+'V').textContent])")
    assert vals == [["6", "6"], ["50", "50"], ["500", "500"]]
    assert page.get_attribute("#topRefs", "max") == "50"


@pytest.mark.parametrize("query", [f"W{N}", f"10.0000/x{N}", f"https://doi.org/10.0000/x{N}", "Paper 260"],
                         ids=["OpenAlex-ID", "DOI", "DOI-URL", "제목"])
def test_어떤_방식으로_입력해도_시조가_1위(make_page, query):
    page = make_page()
    open_app(page, NET)
    set_slider(page, "depth", 4)
    run_trace(page, query)
    first_row = page.inner_text("#out table tr:nth-child(2)")
    assert re.search(r"\bPaper [12]\b", first_row), first_row      # 심어 둔 고전 W1/W2


def test_외부_데이터의_HTML은_글자로만_표시된다(make_page):
    page = make_page()
    open_app(page, NET)
    set_slider(page, "depth", 3)
    run_trace(page, f"W{N}")
    assert "<b>x</b>" in page.inner_text("#out table")        # 글자 그대로 보임
    assert page.locator("#out table a b").count() == 0          # <b> 요소로 해석되지 않음


def test_없는_논문은_오류_문구를_보여준다(make_page):
    page = make_page()
    open_app(page, NET)
    page.fill("#q", "10.9999/nope")
    page.click("#go")
    page.wait_for_selector("#msg .err", timeout=10000)
    assert "논문을 찾지 못했습니다" in page.inner_text("#msg")
    assert page.is_enabled("#go")


def test_슬라이더_값이_추적_범위에_반영된다(make_page):
    page = make_page()
    open_app(page, NET)
    set_slider(page, "depth", 1)
    assert page.inner_text("#depthV") == "1"
    run_trace(page, f"W{N}")
    shallow = int(re.search(r"조상 논문 (\d+)편", page.inner_text("#out")).group(1))
    set_slider(page, "depth", 4)
    set_slider(page, "maxPapers", 50)
    assert page.inner_text("#maxPapersV") == "50"
    run_trace(page, f"W{N}")
    deep = int(re.search(r"조상 논문 (\d+)편", page.inner_text("#out")).group(1))
    assert shallow <= 12          # 깊이 1이면 시작 논문의 참고문헌(5~12편)까지만
    assert shallow < deep <= 50   # 더 깊이 가되 수집 상한(50편)을 넘지 않음


def test_추적_중에는_진행_표시가_보이고_끝나면_사라진다(make_page):
    page = make_page()
    open_app(page, NET, delay=1.0)                 # 서버가 느린 상황
    set_slider(page, "depth", 3)
    page.fill("#q", f"W{N}")
    page.click("#go")
    # 실행 중 상태가 관찰될 때까지 브라우저 안에서 기다린 뒤, 값을 한 번에 읽는다
    page.wait_for_function("!document.getElementById('spin').classList.contains('off')")
    st = page.evaluate("""({spin: !document.getElementById('spin').classList.contains('off'),
        stats: document.getElementById('stats').innerText, btn: document.getElementById('go').innerText,
        disabled: document.getElementById('go').disabled, title: document.title})""")
    assert st["spin"] and st["disabled"] and st["btn"] == "추적 중…"
    assert "경과" in st["stats"] and "서버 요청" in st["stats"] and "수집한 논문" in st["stats"]
    assert "추적 중" in st["title"]
    page.wait_for_function("document.querySelector('#msg').innerText.startsWith('완료')", timeout=90000)
    page.wait_for_function("document.getElementById('spin').classList.contains('off')")
    assert page.inner_text("#go") == "시조 추적" and page.is_enabled("#go")
    assert page.title() == "논문 시조 추적기"


def test_CSV_저장(make_page):
    page = make_page()
    open_app(page, NET)
    set_slider(page, "depth", 3)
    run_trace(page, f"W{N}")
    with page.expect_download() as dl:
        page.click("#csv")
    path = dl.value.path()
    assert dl.value.suggested_filename == f"W{N}_ancestors.csv"
    text = open(path, encoding="utf-8").read()
    assert text.startswith("﻿")                  # 엑셀에서 한글이 깨지지 않도록 BOM 포함
    assert "의미 키워드" in text.splitlines()[0]
