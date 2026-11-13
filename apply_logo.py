"""One-shot: generate Modish Enterprises logo assets and wire them into all templates (idempotent)."""
import os, re, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
IMG = os.path.join(ROOT, 'static', 'img')
DIMG = os.path.join(ROOT, 'deploy-ready', 'static', 'img')

print("== assets ==")
r = subprocess.run([PY, os.path.join(ROOT, 'process_logo.py')], capture_output=True, text=True)
print("process_logo:", "OK" if r.returncode == 0 else "FAIL " + r.stderr[-200:])
os.makedirs(DIMG, exist_ok=True)
names = []
if os.path.isdir(IMG):
    for f in sorted(os.listdir(IMG)):
        shutil.copy2(os.path.join(IMG, f), os.path.join(DIMG, f))
        names.append(f)
print("copied:", ", ".join(names) if names else "NONE")

# Sidebar/login brand tile: any small div centered-content holding 1-3 chars -> white tile + mark img
TILE_RE = re.compile(
    r'<div\s+class="([^"]*justify-center[^"]*)"\s*>\s*(?:<span[^>]*>[^<]{1,3}</span>|[A-Za-z]{1,2})\s*</div>'
)

def tile_repl(_m):
    return ('<div class="w-10 h-10 shrink-0 rounded-xl bg-white flex items-center justify-center '
            'shadow-sm"><img src="/static/img/ekkaa-mark.png" alt="Modish" '
            'class="h-7 w-7 object-contain"></div>')

def patch(path, label):
    try:
        with open(path, encoding='utf-8') as fh:
            t = fh.read()
    except FileNotFoundError:
        print(label + ": FILE NOT FOUND")
        return
    out = []
    if 'img/favicon.png' in t:
        out.append("favicon: SKIP")
    else:
        t2, n = re.subn(r'(<link[^>]*rel="[^"]*icon[^"]*"[^>]*href=")[^"]*(")',
                        r'\g<1>/static/img/favicon.png\g<2>', t)
        if n:
            t = t2; out.append("favicon: OK x%d" % n)
        else:
            t2, n = re.subn(r'(<head\b[^>]*>)',
                            r'\1\n    <link rel="icon" type="image/png" href="/static/img/favicon.png">',
                            t, count=1)
            out.append("favicon: " + ("INSERTED" if n else "MISS"))
            if n: t = t2
    if 'img/ekkaa-mark.png' in t:
        out.append("tile: SKIP")
    else:
        t, n = TILE_RE.subn(tile_repl, t)
        out.append("tile: " + ("OK" if n else "MISS") + " x%d" % n)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(t)
    print("%s: %s | imgtags=%d" % (label, " | ".join(out), t.count('img/ekkaa')))

for base in ('templates', os.path.join('deploy-ready', 'templates')):
    patch(os.path.join(ROOT, base, 'base.html'), base + '/base.html')
    patch(os.path.join(ROOT, base, 'dashboard.html'), base + '/dashboard.html')
    patch(os.path.join(ROOT, base, 'login.html'), base + '/login.html')
print("DONE")