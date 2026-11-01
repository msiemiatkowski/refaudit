"""Build the claude.ai claim-check page (web/claude/) into build/claude-page/, ready to publish as an artifact.

claude.ai pages cannot reach other hosts, so everything the page runs is published with it:
- Pyodide 0.29.5 (from npm; its integrity is checked against the registry's sha512);
- lxml, built for Pyodide (from Pyodide's own distribution; checked against pyodide-lock.json);
- the pure-Python packages refaudit needs (pinned wheels from PyPI) and refaudit itself, in one site.zip, with the
  claim-judge rules from .claude/agents/claim-judge.md beside refaudit/claims_web.py.

claude.ai serves no .zip or .whl files, so each archive is written base64-encoded as "<name>.txt"; web/claude/engine.js
decodes it. The page also gets the committed acceptance run (examples/claims_sample_claims.json) as its example.

Run: python tools/build_claude_page.py   ->  build/claude-page/ and build/claude-page/manifest.json
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "claude-page"
CACHE = ROOT / "build" / "cache"
PYODIDE = "0.29.5"
CORE = ("pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "pyodide-lock.json", "python_stdlib.zip")
WHEELS = ("python-docx==1.2.0", "openpyxl==3.1.5", "et-xmlfile==2.0.0", "pypdf==6.17.0", "typing-extensions==4.16.0")


def fetch(url: str, name: str) -> bytes:
    path = CACHE / name
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as response:
            path.write_bytes(response.read())
    return path.read_bytes()


def pyodide_core() -> dict[str, bytes]:
    meta = json.loads(fetch(f"https://registry.npmjs.org/pyodide/{PYODIDE}", f"pyodide-{PYODIDE}.json"))
    tarball = fetch(meta["dist"]["tarball"], f"pyodide-{PYODIDE}.tgz")
    algorithm, digest = meta["dist"]["integrity"].split("-", 1)
    if base64.b64encode(hashlib.new(algorithm, tarball).digest()).decode() != digest:
        sys.exit("the Pyodide tarball does not match the npm registry's integrity hash")
    with tarfile.open(fileobj=io.BytesIO(tarball)) as tar:
        return {name: tar.extractfile(f"package/{name}").read() for name in CORE}


def lxml(lock: dict) -> tuple[str, bytes]:
    entry = lock["packages"]["lxml"]
    assert not entry.get("depends"), entry
    data = fetch(f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE}/full/{entry['file_name']}", entry["file_name"])
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        sys.exit("the lxml wheel does not match pyodide-lock.json")
    return entry["file_name"], data


def site_zip() -> bytes:
    wheels = CACHE / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "pip", "download", "--quiet", "--no-deps", "--only-binary=:all:",
                    "--python-version", "3.13", "--platform", "any", "-d", str(wheels), *WHEELS], check=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
        for spec in WHEELS:
            name, version = spec.split("==")
            wheel = next(wheels.glob(f"{name.replace('-', '_')}-{version}-*.whl"))
            with zipfile.ZipFile(wheel) as z:
                for item in z.infolist():
                    if ".dist-info/" in item.filename and not item.filename.endswith(("METADATA", "top_level.txt")):
                        continue
                    out.writestr(item, z.read(item))
        for module in sorted((ROOT / "refaudit").glob("*.py")):
            out.write(module, f"refaudit/{module.name}")
        out.write(ROOT / ".claude" / "agents" / "claim-judge.md", "refaudit/claim-judge.md")
    return buffer.getvalue()


def example() -> dict:
    data = json.loads((ROOT / "examples" / "claims_sample_claims.json").read_text(encoding="utf-8"))
    keep = ("id", "sentence", "citation", "ref", "status", "verdict", "severity", "notes")
    rows = [dict({k: r.get(k) for k in keep}, explanation=(r.get("judge") or {}).get("explanation", ""),
                 fix=(r.get("judge") or {}).get("fix", ""), evidence=((r.get("judge") or {}).get("evidence") or [])[:1],
                 second=(r.get("second") or {}).get("verdict", "")) for r in data["rows"]]
    return {"version": data["run"]["version"], "rows": rows}


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "pyodide").mkdir(parents=True)
    (OUT / "py").mkdir()
    files = {}

    def write(published: str, data: bytes, base64_text: bool = False) -> None:
        if base64_text:
            published, data = published + ".txt", base64.b64encode(data)
        (OUT / published).write_bytes(data)
        files[published] = str(OUT / published)

    core = pyodide_core()
    for name, data in core.items():
        write(f"pyodide/{name}", data, base64_text=name.endswith(".zip"))
    wheel_name, wheel = lxml(json.loads(core["pyodide-lock.json"]))
    write(f"pyodide/{wheel_name}", wheel, base64_text=True)
    write("py/site.zip", site_zip(), base64_text=True)
    write("engine.js", (ROOT / "web" / "claude" / "engine.js").read_bytes())
    page = (ROOT / "web" / "claude" / "index.html").read_text(encoding="utf-8")
    marker = "const EXAMPLE = null;"
    assert page.count(marker) == 1
    page = page.replace(marker, "const EXAMPLE = " + json.dumps(example(), ensure_ascii=False) + ";")
    (OUT / "index.html").write_text(page, encoding="utf-8")
    manifest = {"page": str(OUT / "index.html"), "files": files}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    total = sum(Path(p).stat().st_size for p in files.values()) + (OUT / "index.html").stat().st_size
    print(f"Built {OUT}: {len(files) + 1} files, {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
