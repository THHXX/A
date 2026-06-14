"""Extract plantuml blocks from MD and render via kroki.io to PNG."""
import re
import urllib.request
import urllib.error
from pathlib import Path

DOC_DIR = Path(__file__).parent
MD_FILE = DOC_DIR / "MiroFish_需求规格说明书.md"
OUT_DIR = DOC_DIR / "_mermaid_imgs"
OUT_DIR.mkdir(exist_ok=True)

text = MD_FILE.read_text(encoding="utf-8")
blocks = re.findall(r"```plantuml\n(.*?)\n```", text, re.DOTALL)
print(f"Found {len(blocks)} plantuml blocks")

for i, code in enumerate(blocks, 1):
    out = OUT_DIR / f"plantuml_{i}.png"
    kroki_url = "https://kroki.io/plantuml/png"
    try:
        req = urllib.request.Request(
            kroki_url,
            data=code.encode("utf-8"),
            headers={
                "Content-Type": "text/plain",
                "User-Agent": "Mozilla/5.0",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        out.write_bytes(data)
        print(f"[{i}] rendered: {out} ({len(data)} bytes)")
    except urllib.error.HTTPError as e:
        print(f"[{i}] HTTP {e.code}: {e.reason}")
        try:
            print(f"     body: {e.read().decode('utf-8', errors='replace')[:500]}")
        except Exception:
            pass
    except Exception as e:
        print(f"[{i}] failed: {e}")
