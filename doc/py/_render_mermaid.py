"""Extract mermaid blocks from MD and render via mermaid.ink to PNG."""
import re
import base64
import urllib.request
import urllib.error
from pathlib import Path

DOC_DIR = Path(__file__).parent
MD_FILE = DOC_DIR / "MiroFish_需求规格说明书.md"
OUT_DIR = DOC_DIR / "_mermaid_imgs"
OUT_DIR.mkdir(exist_ok=True)

text = MD_FILE.read_text(encoding="utf-8")
blocks = re.findall(r"```mermaid\n(.*?)\n```", text, re.DOTALL)
print(f"Found {len(blocks)} mermaid blocks")

for i, code in enumerate(blocks, 1):
    out = OUT_DIR / f"mermaid_{i}.png"
    if out.exists() and out.stat().st_size > 1000:
        print(f"[{i}] cached: {out}")
        continue
    encoded = base64.urlsafe_b64encode(code.encode("utf-8")).decode("ascii").rstrip("=")
    url = f"https://mermaid.ink/img/{encoded}?type=png&bgColor=FFFFFF"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        out.write_bytes(data)
        print(f"[{i}] rendered: {out} ({len(data)} bytes)")
    except urllib.error.HTTPError as e:
        print(f"[{i}] HTTP {e.code}: {e.reason}")
        print(f"     URL len: {len(url)}")
        # Try POST or kroki as fallback
        kroki_url = "https://kroki.io/mermaid/png"
        try:
            req2 = urllib.request.Request(kroki_url, data=code.encode("utf-8"),
                                           headers={"Content-Type": "text/plain"})
            with urllib.request.urlopen(req2, timeout=60) as resp:
                data = resp.read()
            out.write_bytes(data)
            print(f"[{i}] kroki rendered: {out} ({len(data)} bytes)")
        except Exception as e2:
            print(f"[{i}] kroki fallback failed: {e2}")
    except Exception as e:
        print(f"[{i}] failed: {e}")
