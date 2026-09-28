#!/usr/bin/env python3
import argparse, json, os, subprocess, time
from pathlib import Path
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

WIDTHS=(320,375,768,1024,1440)
BROWSERS=('chromium','firefox')

def urls_for(root: Path):
    out=[]
    for hp in sorted(root.rglob('*.html')):
        rel=hp.relative_to(root).as_posix()
        if rel=='index.html': url='/'
        elif rel=='404.html': url='/404.html'
        elif rel.endswith('/index.html'): url='/' + rel[:-10]
        else: url='/' + rel
        out.append(url)
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',required=True)
    ap.add_argument('--out',default='predeploy-browser-results.json')
    a=ap.parse_args()
    root=Path(a.root).resolve()
    port=8765
    srv=subprocess.Popen(['python','-m','http.server',str(port),'--bind','127.0.0.1'],cwd=root,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.2)
        origin=f'http://127.0.0.1:{port}'
        results=[]; failures=[]
        with sync_playwright() as pw:
            for browser_name in BROWSERS:
                bt=getattr(pw,browser_name)
                browser=bt.launch(headless=True)
                page=browser.new_page(viewport={'width':1440,'height':900})
                # Layout validation should not depend on third-party ad/statistics response time.
                page.route('https://pagead2.googlesyndication.com/**', lambda route: route.abort())
                page.route('https://counter.yadro.ru/**', lambda route: route.abort())
                page.route('https://www.liveinternet.ru/**', lambda route: route.abort())
                for url in urls_for(root):
                    for width in WIDTHS:
                        row={'browser':browser_name,'url':url,'width':width,'status':'FAIL'}
                        try:
                            page.set_viewport_size({'width':width,'height':900})
                            resp=page.goto(urljoin(origin,url.lstrip('/')),wait_until='networkidle',timeout=20000)
                            if not resp or resp.status >= 400:
                                raise RuntimeError(f'HTTP status {resp.status if resp else "none"}')
                            h1=page.locator('h1').count()
                            if h1 != 1:
                                raise RuntimeError(f'h1 count {h1}')
                            overflow=page.evaluate('document.documentElement.scrollWidth > document.documentElement.clientWidth + 2')
                            if overflow:
                                raise RuntimeError('document horizontal overflow')
                            bad=page.evaluate('''()=>[...document.querySelectorAll('main *')].filter(el=>!el.closest('.table-wrap')).some(el=>{const s=getComputedStyle(el);if(s.position==='fixed')return false;const r=el.getBoundingClientRect();return r.right>document.documentElement.clientWidth+3||r.left<-3})''')
                            if bad:
                                raise RuntimeError('content element exceeds viewport')
                            broken=page.evaluate('''()=>[...document.images].filter(i=>i.getClientRects().length && (!i.complete || i.naturalWidth===0)).map(i=>i.getAttribute('src'))''')
                            if broken:
                                raise RuntimeError('broken images: '+','.join(broken[:3]))
                            if page.locator('[data-launcher]').count():
                                if page.locator('[data-launcher] iframe').count()!=0:
                                    raise RuntimeError('iframe present before Play')
                                if not page.locator('[data-play]').is_visible():
                                    raise RuntimeError('Play not visible')
                            row['status']='PASS'
                        except Exception as e:
                            row['error']=str(e); failures.append(f'{browser_name} {url} {width}: {e}')
                        results.append(row)
                page.close(); browser.close()
        data={'status':'PASS' if not failures else 'FAIL','root':str(root),'browsers':list(BROWSERS),'widths':list(WIDTHS),'checks':len(results),'failures':failures,'results':results}
        Path(a.out).write_text(json.dumps(data,indent=2),encoding='utf-8')
        print(json.dumps({'status':data['status'],'checks':len(results),'failures':len(failures)},indent=2))
        raise SystemExit(1 if failures else 0)
    finally:
        srv.terminate()
        try: srv.wait(timeout=3)
        except Exception: srv.kill()

if __name__=='__main__': main()
