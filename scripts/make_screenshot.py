"""README용 스크린샷(docs/screenshot.png)을 가짜 데이터로 만든다.
실행: python scripts/make_screenshot.py   (Playwright와 Chromium 필요)"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from playwright.sync_api import sync_playwright  # noqa: E402

from helpers import open_app, run_trace, set_slider, themed_network  # noqa: E402

net = themed_network()
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1180, "height": 900}, color_scheme="light", device_scale_factor=1.5)
    open_app(page, net)
    set_slider(page, "depth", 6)
    set_slider(page, "topRefs", 30)
    set_slider(page, "maxPapers", 1000)
    run_trace(page, f"W{net.n}")
    set_slider(page, "laneN", 6)
    card = page.locator("#mapbox").locator("xpath=..")          # 지도 카드(도구 + 지도 + 범례)
    out = ROOT / "docs" / "screenshot.png"
    card.screenshot(path=str(out))
    browser.close()
print("저장:", out, out.stat().st_size // 1024, "KB")
