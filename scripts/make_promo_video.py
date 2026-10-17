"""Threads 홍보 영상(promo/threads.mp4)을 가짜 데이터로 만든다.
실행: python scripts/make_promo_video.py  → promo/build/raw.webm 생성 후,
  ffmpeg -i promo/build/raw.webm -vf scale=1080:1350,fps=30 -c:v libx264 -crf 18 -pix_fmt yuv420p promo/threads.mp4
(Playwright, Chromium, ffmpeg, 한글 폰트 Noto Sans CJK 필요)"""
import sys, time, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from playwright.sync_api import sync_playwright
from helpers import open_app, set_slider, themed_network

OUT = ROOT / "promo" / "build"; OUT.mkdir(parents=True, exist_ok=True)
URL = "kami6451-create.github.io/Journal-Paper-Geneology"
net = themed_network()

CSS = """
html{zoom:1.2}body{padding-top:64px!important}
#pc-cap,#pc-badge,#pc-card{zoom:.8333}

#pc-cap{position:fixed;left:0;right:0;top:0;z-index:99999;padding:22px 28px 26px;color:#fff;
 font:700 34px/1.25 'Noto Sans CJK KR','Noto Sans CJK JP',sans-serif;
 background:linear-gradient(#0b1f2aee,#0b1f2add 70%,#0b1f2a00);opacity:0;transform:translateY(-14px);
 transition:opacity .35s,transform .35s;pointer-events:none}
#pc-cap.on{opacity:1;transform:none}
#pc-cap b{display:inline-block;background:#ff8a80;color:#1d1d1b;border-radius:999px;padding:0 .55em;margin-right:.5em;font-size:.85em}
#pc-badge{position:fixed;right:14px;bottom:12px;z-index:99999;background:#000a;color:#fff;font:500 18px 'Noto Sans CJK KR','Noto Sans CJK JP',sans-serif;
 padding:6px 12px;border-radius:8px;pointer-events:none}
#pc-card{position:fixed;inset:0;z-index:100000;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;
 padding:40px;color:#fff;background:radial-gradient(circle at 30% 20%,#1d4b63,#0b1f2a 70%);opacity:0;transition:opacity .5s;pointer-events:none;
 font-family:'Noto Sans CJK KR','Noto Sans CJK JP',sans-serif}
#pc-card.on{opacity:1}
#pc-card h1{font-size:64px;line-height:1.25;margin:0 0 24px;font-weight:900;letter-spacing:-1px}
#pc-card p{font-size:30px;line-height:1.45;margin:0;color:#cfe3ee;font-weight:500}
#pc-card .url{margin-top:44px;font-size:30px;font-weight:700;background:#ff8a80;color:#1d1d1b;padding:14px 26px;border-radius:14px}
#pc-card .dots{margin-top:44px;display:flex;gap:10px}
#pc-card .dots i{width:14px;height:14px;border-radius:50%;background:#ff8a80;opacity:.35;animation:pulse 1.2s infinite}
#pc-card .dots i:nth-child(2){animation-delay:.2s}#pc-card .dots i:nth-child(3){animation-delay:.4s}
@keyframes pulse{50%{opacity:1;transform:scale(1.5)}}
"""
JS_INIT = """css=>{const s=document.createElement('style');s.textContent=css;document.head.append(s);
 for(const [id,html] of [['pc-cap',''],['pc-card',''],['pc-badge','예시 데이터로 만든 화면']]){const d=document.createElement('div');d.id=id;d.innerHTML=html;document.body.append(d);}
 window.cap=(h)=>{const c=document.getElementById('pc-cap');if(!h){c.classList.remove('on');return}c.innerHTML=h;c.classList.add('on')};
 window.card=(h)=>{const c=document.getElementById('pc-card');if(!h){c.classList.remove('on');return}c.innerHTML=h;c.classList.add('on')};}"""

def wait(page, s): page.wait_for_timeout(int(s*1000))
def cap(page, n, text): page.evaluate("([n,t])=>cap(`<b>${n}</b>${t}`)", [n, text])
def slide(page, el, a, b, steps=14, dt=45):
    for i in range(steps+1):
        v = round(a + (b-a)*i/steps)
        set_slider(page, el, v); wait(page, dt/1000)

with sync_playwright() as p:
    br = p.chromium.launch()
    ctx = br.new_context(viewport={"width":1080,"height":1350}, color_scheme="light",
                         record_video_dir=str(OUT/"raw"), record_video_size={"width":1080,"height":1350})
    page = ctx.new_page()
    open_app(page, net, delay=1.1)
    page.evaluate(JS_INIT, CSS)
    # 인트로
    page.evaluate("""()=>card(`<h1>내 논문의<br>시조는 누구일까?</h1><p>인용을 거슬러 올라가<br>연구 계보의 뿌리를 찾아요</p><div class=dots><i></i><i></i><i></i></div>`)""")
    wait(page, 3.4); page.evaluate("()=>card()"); wait(page, .7)
    # 1 입력
    cap(page, 1, "논문 제목이나 DOI를 입력"); wait(page, .6)
    page.click("#q"); page.type("#q", "Ethnicity, Insurgency, and Civil War", delay=55); wait(page, .9)
    # 2 슬라이더
    cap(page, 2, "범위는 슬라이더로 쓱쓱 조절")
    page.eval_on_selector("#depth", "e=>e.scrollIntoView({block:'center'})"); wait(page, .5)
    slide(page, "depth", 6, 3); slide(page, "depth", 3, 6)
    slide(page, "topRefs", 50, 20); slide(page, "topRefs", 20, 50); wait(page, .4)
    page.eval_on_selector("#go", "e=>e.scrollIntoView({block:'center'})"); wait(page, .4)
    # 3 실행
    cap(page, 3, "진행 상황을 실시간으로 확인")
    t0 = time.time()
    page.click("#go")
    page.wait_for_function("document.querySelector('#msg').innerText.startsWith('완료')", timeout=120000)
    page.wait_for_selector("#out #mapbox svg", timeout=60000)
    print("trace seconds", round(time.time()-t0,1))
    wait(page, .8)
    # 4 지도
    cap(page, 4, "연도 × 주제 지도 · 점이 클수록 많이 인용")
    page.eval_on_selector("#mapbox", "e=>e.scrollIntoView({block:'start'})"); wait(page, 1.0)
    page.evaluate("()=>window.scrollBy(0,-120)"); wait(page, 1.2)
    slide(page, "laneN", 20, 8, steps=12, dt=110); wait(page, .9)
    slide(page, "laneN", 8, 14, steps=8, dt=110); wait(page, 1.2)
    # 5 스크롤 (순위표)
    cap(page, 5, "시조 후보를 점수로 순위화")
    h = page.evaluate("document.documentElement.scrollHeight")
    y0 = page.evaluate("window.scrollY")
    for i in range(40):
        page.evaluate(f"window.scrollTo(0,{y0}+({min(h,y0+1700)}-{y0})*{(i+1)/40})"); wait(page, .06)
    wait(page, 2.2)
    # 아웃트로
    page.evaluate("()=>cap()"); 
    page.evaluate(f"""()=>card(`<h1>논문 시조 추적기</h1><p>제목이나 DOI만 넣으면<br>인용 계보의 뿌리를 찾아드려요</p><p style="margin-top:22px;font-size:26px">무료 · 설치 없이 브라우저에서 · 오픈소스</p><div class=url>{URL}</div>`)""")
    wait(page, 4.2)
    vid = page.video
    ctx.close(); path = vid.path(); br.close()
shutil.copy(path, OUT/"raw.webm"); print(path)
