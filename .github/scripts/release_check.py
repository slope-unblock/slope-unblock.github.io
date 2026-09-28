#!/usr/bin/env python3
import argparse, json, re
from pathlib import Path
from html.parser import HTMLParser

class ImgParser(HTMLParser):
    def __init__(self): super().__init__(); self.img=[]; self.iframes=[]
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag=='img' and d.get('src'): self.img.append(d['src'])
        if tag=='iframe' and d.get('src'): self.iframes.append(d['src'])

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',required=True); a=ap.parse_args()
    root=Path(a.root).resolve(); errors=[]; htmls=list(root.rglob('*.html'))
    if not (root/'index.html').exists(): errors.append('missing root index.html')
    if not (root/'.nojekyll').exists(): errors.append('missing .nojekyll')
    for hp in htmls:
        p=ImgParser(); p.feed(hp.read_text(encoding='utf-8',errors='ignore'))
        for src in p.img:
            if src.startswith(('http://','https://')):
                errors.append(f'{hp.relative_to(root)}: remote image {src}')
            elif src.startswith('/'):
                target=root/src.lstrip('/')
                if not target.exists(): errors.append(f'{hp.relative_to(root)}: missing image {src}')
    media=root/'assets/images/game/media-release.json'
    if not media.exists(): errors.append('missing media release audit')
    else:
        data=json.loads(media.read_text())
        expected=len(json.loads((root.parent/'.github/media-manifest.json').read_text())) if (root.parent/'.github/media-manifest.json').exists() else data.get('count');
        if data.get('status')!='PASS' or data.get('count')!=expected: errors.append(f'media release audit not PASS/{expected}')
    # Required monetization/statistics snippets must appear exactly once on every public HTML file.
    for hp in htmls:
        ht=hp.read_text(encoding='utf-8',errors='ignore')
        if ht.count('pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-7305083056611385') != 1:
            errors.append(f'{hp.relative_to(root)}: AdSense loader count is not 1')
        if ht.count('counter.yadro.ru/hit?t45.5') != 1 or ht.count('id=\"licntDFBE\"') != 1:
            errors.append(f'{hp.relative_to(root)}: LiveInternet counter count is not 1')
    text='\n'.join(p.read_text(encoding='utf-8',errors='ignore') for p in htmls)
    forbidden=['G-XXXX','AI-generated','auto-generated','ChatGPT','OpenAI','data-local-target=']
    if 'gamedistribution.com' in text.lower(): errors.append('GameDistribution reference remains in public HTML')
    for x in forbidden:
        if x.lower() in text.lower(): errors.append(f'forbidden public token: {x}')
    result={'status':'PASS' if not errors else 'FAIL','html_total':len(htmls),'errors':errors}
    (root/'assets/release-check.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    raise SystemExit(1 if errors else 0)
if __name__=='__main__': main()
