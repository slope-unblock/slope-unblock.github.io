#!/usr/bin/env python3
import argparse, hashlib, json, re, time, urllib.request
from pathlib import Path
from PIL import Image

HERE=Path(__file__).resolve().parent
MANIFEST=HERE.parent/'media-manifest.json'
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/150 Safari/537.36 SlopeFanSiteRelease/3.0'

def ahash(path: Path):
    with Image.open(path) as im:
        im.seek(0)
        g=im.convert('L').resize((8,8))
        px=list(g.getdata())
        avg=sum(px)/len(px)
        bits=0
        for v in px:
            bits=(bits<<1) | (1 if v>=avg else 0)
        return f'{bits:016x}'

def fetch(url, dest, tries=4):
    last=None
    for n in range(tries):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'image/avif,image/webp,image/apng,image/*,*/*;q=0.8'})
            with urllib.request.urlopen(req,timeout=45) as r:
                if getattr(r,'status',200) >= 400:
                    raise RuntimeError(f'HTTP {r.status}')
                data=r.read()
            if len(data)<3000:
                raise RuntimeError(f'image payload too small: {len(data)} bytes')
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(data)
            return
        except Exception as e:
            last=e
            time.sleep(2*(n+1))
    raise RuntimeError(f'cannot download {url}: {last}')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',required=True)
    ap.add_argument('--strip-remote-fallbacks',action='store_true')
    args=ap.parse_args()
    root=Path(args.root).resolve()
    rows=json.loads(MANIFEST.read_text())
    results=[]
    byte_hashes={}
    perceptual={}
    for row in rows:
        rel=row['destination'].lstrip('/')
        dest=root/rel
        fetch(row['source_url'],dest)
        with Image.open(dest) as im:
            im.verify()
        with Image.open(dest) as im:
            w,h=im.size
            fmt=(im.format or '').upper()
        if w<row['min_width'] or h<row['min_height']:
            raise SystemExit(f"{row['entity']}: {w}x{h} below required minimum")
        sha=hashlib.sha256(dest.read_bytes()).hexdigest()
        ph=ahash(dest)
        if sha in byte_hashes:
            raise SystemExit(f"Exact duplicate media: {row['entity']} == {byte_hashes[sha]}")
        visual_candidate=perceptual.get(ph)
        byte_hashes[sha]=row['entity']; perceptual.setdefault(ph,row['entity'])
        results.append({**row,'width':w,'height':h,'format':fmt,'sha256':sha,'average_hash':ph,'visual_duplicate_candidate':visual_candidate,'status':'PASS'})

    # Rewrite remote gameplay images to same-origin local files in the deploy artifact.
    # Also synchronize visible img width/height and social-image dimensions with the downloaded bytes.
    dims={r['destination']:(r['width'],r['height']) for r in results}
    replaced=0
    for hp in root.rglob('*.html'):
        s=hp.read_text(encoding='utf-8')
        before=s
        for row in rows:
            remote=row['source_url']; local=row['destination']
            s=s.replace(f'src="{remote}" data-local-target="{local}"',f'src="{local}"')
        if args.strip_remote_fallbacks:
            s=re.sub(r'\sdata-local-target="[^"]+"','',s)
        # Update actual img element dimensions after localization.
        for local,(w,h) in dims.items():
            pattern=re.compile(r'<img\b[^>]*\bsrc="'+re.escape(local)+r'"[^>]*>',re.I)
            def fix_img(m):
                tag=m.group(0)
                if re.search(r'\bwidth="[^"]*"',tag,re.I): tag=re.sub(r'\bwidth="[^"]*"',f'width="{w}"',tag,flags=re.I)
                else: tag=tag[:-1]+f' width="{w}">'
                if re.search(r'\bheight="[^"]*"',tag,re.I): tag=re.sub(r'\bheight="[^"]*"',f'height="{h}"',tag,flags=re.I)
                else: tag=tag[:-1]+f' height="{h}">'
                return tag
            s=pattern.sub(fix_img,s)
            abs_url='https://slope-unblock.github.io'+local
            if abs_url in s:
                # If this local image is the page's OG image, synchronize declared dimensions.
                og_pat=re.compile(r'(<meta[^>]+property="og:image"[^>]+content="'+re.escape(abs_url)+r'"[^>]*>|<meta[^>]+content="'+re.escape(abs_url)+r'"[^>]+property="og:image"[^>]*>)',re.I)
                if og_pat.search(s):
                    s=re.sub(r'(<meta[^>]+property="og:image:width"[^>]+content=")[^"]*("[^>]*>)',lambda m:m.group(1)+str(w)+m.group(2),s,flags=re.I)
                    s=re.sub(r'(<meta[^>]+property="og:image:height"[^>]+content=")[^"]*("[^>]*>)',lambda m:m.group(1)+str(h)+m.group(2),s,flags=re.I)
        if s!=before:
            hp.write_text(s,encoding='utf-8'); replaced+=1

    # All intended slots must have been rewritten and no hotlinked game thumbnail may remain.
    combined='\n'.join(p.read_text(encoding='utf-8',errors='ignore') for p in root.rglob('*.html'))
    for row in rows:
        if row['source_url'] in combined:
            raise SystemExit(f"Remote gameplay image still present in HTML: {row['source_url']}")
        if row['destination'] not in combined:
            raise SystemExit(f"Local gameplay image is not referenced after rewrite: {row['destination']}")
    out=root/'assets'/'images'/'game'/'media-release.json'
    out.write_text(json.dumps({'status':'PASS','count':len(results),'items':results},indent=2),encoding='utf-8')
    print(json.dumps({'status':'PASS','downloaded':len(results),'html_files_rewritten':replaced},indent=2))
if __name__=='__main__': main()
