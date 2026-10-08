"""PDF 저장: 버튼 → 인쇄 호출/파일명, 다크 모드에서도 인쇄용 배치(흰 바탕, 입력창 숨김), 실제 PDF 생성."""
import re

from helpers import classic_network, open_app, run_trace, set_slider

NET = classic_network()


def test_PDF로_저장하면_파일명이_정해지고_인쇄용_화면이_적용된다(make_page, tmp_path):
    page = make_page(color_scheme="dark")                 # 다크 모드 사용자
    open_app(page, NET)
    set_slider(page, "depth", 3)
    run_trace(page, f"W{NET.n}")
    assert page.inner_text("#print") == "PDF로 저장"

    # 실제 인쇄 창 대신, 호출 시점의 문서 제목(= PDF 기본 파일명)만 기록한다
    page.evaluate("window.__printed = []; window.print = () => { window.__printed.push(document.title); }; 0")
    page.click("#print")
    printed = page.evaluate("window.__printed")
    assert len(printed) == 1 and re.fullmatch(r"시조추적_W260_\d{8}", printed[0]), printed
    page.evaluate("window.dispatchEvent(new Event('afterprint'))")
    assert page.title() == "논문 시조 추적기"             # 인쇄 후 제목 복원

    page.emulate_media(media="print")
    for sel in ["#f", "#status", ".actions", "#theme", ".maptools"]:
        assert not page.is_visible(sel), f"{sel} 이(가) 인쇄물에 포함됨"
    assert page.is_visible(".printonly")                   # 생성일·추적 범위 줄
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(255, 255, 255)"

    pdf = tmp_path / "report.pdf"
    page.pdf(path=str(pdf), prefer_css_page_size=True, print_background=True)
    data = pdf.read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 10_000
