import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def make_page(browser):
    """페이지를 만들어 주는 팩토리. 테스트가 끝날 때, 화면에서 자바스크립트 오류가 났으면 실패시킨다."""
    made = []

    def _make(color_scheme: str = "light"):
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme=color_scheme, accept_downloads=True)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        # 존재하지 않는 DOI를 일부러 조회하는 테스트의 404 로그는 정상이므로 제외
        page.on("console", lambda m: m.type == "error" and "404" not in m.text and errors.append(m.text))
        made.append((ctx, errors))
        return page

    yield _make
    all_errors = [e for _, errs in made for e in errs]
    for ctx, _ in made:
        ctx.close()
    assert not all_errors, f"화면에서 오류 발생: {all_errors}"
