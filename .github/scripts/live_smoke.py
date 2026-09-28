#!/usr/bin/env python3
import argparse, json, time, re
from pathlib import Path
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

CASES=[
 ('Slope','/play/','/embed/slope'),
 ('Slope Multiplayer','/similar-games/slope-multiplayer/','/embed/slope-multiplayer'),
 ('Slope Xtreme','/similar-games/slope-xtreme/','/embed/slope-xtreme'),
 ('Slope Run','/similar-games/slope-run/','/embed/slope-run'),
 ('Going Balls','/similar-games/going-balls/','/embed/going-balls'),
 ('Super Ball 3D','/similar-games/super-ball-3d/','/embed/super-ball-3d'),
 ('Color Race','/similar-games/color-race/','/embed/color-race'),
]

def visible_game_surface(page):
    evidence=[]
    for frame in page.frames:
        try:
            for sel,kind in [('canvas','canvas'),('video','video')]:
                for el in frame.locator(sel).all():
                    if not el.is_visible(): continue
                    box=el.bounding_box()
                    if box and box['width']>=200 and box['height']>=120:
                        evidence.append({'frame_url':frame.url,'kind':kind,'width':round(box['width']),'height':round(box['height'])})
        except Exception:
            pass
    return evidence

def try_provider_play(page):
    patterns=[re.compile(r'^play$',re.I),re.compile(r'play game',re.I),re.compile(r'^start$',re.I),re.compile(r'^continue$',re.I)]
    for frame in page.frames:
        for patt in patterns:
            try:
                for role in ('button','link'):
                    loc=frame.get_by_role(role,name=patt).first
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=2500); return True
            except Exception:
                pass
    return False

def wait_real_game(page, seconds=90):
    deadline=time.time()+seconds; clicked=False
    while time.time()<deadline:
        ev=visible_game_surface(page)
        if ev: return ev
        if not clicked and time.time()>deadline-seconds+8:
            clicked=try_provider_play(page)
        page.wait_for_timeout(750)
    return []

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--origin',required=True)
    ap.add_argument('--browser',choices=['chromium','firefox'],default='chromium')
    ap.add_argument('--out',default='live-smoke-results.json')
    ap.add_argument('--screenshots',default='live-smoke-screenshots')
    a=ap.parse_args()
    origin=a.origin.rstrip('/')+'/'
    shotdir=Path(a.screenshots); shotdir.mkdir(parents=True,exist_ok=True)
    results=[]; failures=[]
    with sync_playwright() as pw:
        bt=getattr(pw,a.browser)
        browser=bt.launch(headless=True)
        ctx=browser.new_context(viewport={'width':1280,'height':900})
        page=ctx.new_page()
        for name,path,fragment in CASES:
            row={'browser':a.browser,'game':name,'path':path,'status':'FAIL'}
            try:
                resp=page.goto(urljoin(origin,path.lstrip('/')),wait_until='domcontentloaded',timeout=45000)
                if not resp or resp.status>=400: raise RuntimeError(f'page HTTP {resp.status if resp else "none"}')
                if page.locator('[data-launcher] iframe').count()!=0: raise RuntimeError('game iframe exists before Play')
                img=page.locator('[data-launcher] img').first
                if not img.is_visible() or page.evaluate('(img)=>!img.complete||img.naturalWidth===0',img.element_handle()):
                    raise RuntimeError('local launcher image is not loaded')
                page.locator('[data-play]').click(timeout=10000)
                frame_el=page.locator('[data-launcher] iframe'); frame_el.wait_for(state='attached',timeout=10000)
                src=frame_el.get_attribute('src') or ''
                if fragment not in src: raise RuntimeError(f'unexpected iframe src {src}')
                dims=page.evaluate('''()=>{const s=document.querySelector('.launcher-stage').getBoundingClientRect(),f=document.querySelector('[data-launcher] iframe').getBoundingClientRect();return {sw:s.width,sh:s.height,fw:f.width,fh:f.height,dx:Math.abs(s.left-f.left),dy:Math.abs(s.top-f.top)}}''')
                if abs(dims['sw']-dims['fw'])>3 or abs(dims['sh']-dims['fh'])>3 or dims['dx']>3 or dims['dy']>3: raise RuntimeError(f'iframe does not fill launcher stage: {dims}')
                handle=frame_el.element_handle(timeout=10000); fr=handle.content_frame() if handle else None
                deadline=time.time()+40
                while time.time()<deadline and (not fr or not fr.url or fr.url=='about:blank'):
                    page.wait_for_timeout(500); handle=frame_el.element_handle(); fr=handle.content_frame() if handle else None
                if not fr: raise RuntimeError('provider frame not created')
                fr.wait_for_load_state('domcontentloaded',timeout=30000)
                evidence=wait_real_game(page,90)
                if not evidence: raise RuntimeError('no visible game canvas/video >=200x120 appeared')
                slug=path.strip('/').replace('/','-') or 'home'; shot=shotdir/f'{a.browser}-{slug}.png'
                page.locator('[data-launcher]').screenshot(path=str(shot))
                page.locator('[data-fullscreen]').click(timeout=5000); page.wait_for_timeout(500)
                if not page.evaluate('!!document.fullscreenElement'): raise RuntimeError('Fullscreen API did not enter fullscreen')
                page.evaluate('document.exitFullscreen()'); page.wait_for_function('!document.fullscreenElement',timeout=5000)
                old_src=frame_el.get_attribute('src'); page.locator('[data-reload]').click(timeout=5000); page.wait_for_timeout(800)
                if page.locator('[data-launcher] iframe').count()!=1: raise RuntimeError('Reload did not leave exactly one iframe')
                if page.locator('[data-launcher] iframe').get_attribute('src')!=old_src: raise RuntimeError('Reload changed endpoint')
                page.locator('[data-close]').click(timeout=5000)
                if page.locator('[data-launcher] iframe').count()!=0: raise RuntimeError('Close did not remove iframe')
                if not page.locator('[data-play]').is_visible(): raise RuntimeError('Close did not restore Play')
                row.update(status='PASS',frame_url=fr.url,evidence=evidence,screenshot=str(shot),fullscreen='PASS',reload='PASS',close='PASS',click_to_load='PASS',local_image='PASS')
            except Exception as e:
                row['error']=str(e); failures.append(f'{name}: {e}')
            results.append(row)
        browser.close()
    out={'origin':origin,'browser':a.browser,'status':'PASS' if not failures else 'FAIL','results':results,'failures':failures}
    Path(a.out).write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'browser':a.browser,'status':out['status'],'failures':failures},indent=2))
    raise SystemExit(1 if failures else 0)
if __name__=='__main__': main()
