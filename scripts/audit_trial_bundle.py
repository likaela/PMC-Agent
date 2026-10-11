"""Audit emitted assets without importing enterprise services or touching facts."""
import argparse
import json
import re
from pathlib import Path

def audit(web_root):
    root = Path(web_root)
    if not (root / "index.html").is_file() or not (root / "module-closure.json").is_file():
        raise ValueError("Dedicated trial build manifest missing")
    forbidden = re.compile(r"KQ-|kq_z112|review_real_bom_simulation|data[\\/]raw|data[\\/]normalized|[CE]:[\\/]|sk-[A-Za-z0-9_-]{20,}", re.I)
    files = list(root.rglob("*"))
    if any(p.is_symlink() for p in files):
        raise ValueError("Trial resources must not be linked to other directories")
    checked = []
    for path in files:
        if not path.is_file():
            continue
        # Inspect all bytes, not just a CSS/JS subset; no publicDir copy-through.
        content = path.read_bytes().decode("utf-8", errors="replace")
        if path.suffix == ".map" or forbidden.search(content):
            raise ValueError("Unsafe trial resource; build must not be served")
        checked.append(path.relative_to(root).as_posix())
    manifest = json.loads((root / "module-closure.json").read_text(encoding="utf-8"))
    if "trial/useTrialAgent.ts" not in manifest or "trial/scenarioPolicy.ts" not in manifest:
        raise ValueError("Trial dependency isolation missing")
    if any(p in manifest for p in ["src/App.vue", "src/composables/useAgent.ts", "src/services/sessionStorage.ts", "src/services/scenarioPolicy.ts"]):
        raise ValueError("Private application entry entered trial bundle")
    return {"status": "passed", "files": checked, "application_modules": len(manifest), "source_maps": 0}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-root", type=Path, required=True)
    print(json.dumps(audit(parser.parse_args().web_root), ensure_ascii=False))
