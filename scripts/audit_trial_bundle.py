"""Audit emitted assets without importing enterprise services or touching facts."""
import argparse
import json
import re
import hashlib
import sqlite3
from pathlib import Path

def audit(web_root, entry="trial"):
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
    state = "review/useReviewAgent.ts" if entry == "review" else "trial/useTrialAgent.ts"
    if state not in manifest or entry + "/scenarioPolicy.ts" not in manifest:
        raise ValueError("Trial dependency isolation missing")
    if any(p in manifest for p in ["src/App.vue", "src/composables/useAgent.ts", "src/services/sessionStorage.ts", "src/services/scenarioPolicy.ts"]):
        raise ValueError("Private application entry entered trial bundle")
    return {"status": "passed", "files": checked, "application_modules": len(manifest), "source_maps": 0}


def private_identifier_scan(web_root, facts_path, raw_root):
    """Administrator-only comparison; prints counts, never source values."""
    connection = sqlite3.connect(Path(facts_path).resolve(strict=True).as_uri() + "?mode=ro", uri=True)
    try:
        patterns = {str(row[0]) for row in connection.execute("SELECT material_code FROM items")}
        for filename, digest in connection.execute("SELECT original_filename,content_sha256 FROM source_files"):
            patterns.update((filename, digest))
    finally:
        connection.close()
    for path in Path(raw_root).glob("*"):
        if path.is_file():
            patterns.update((path.name, str(path.resolve()), hashlib.sha256(path.read_bytes()).hexdigest()))
    patterns.update(("review_real_bom_simulation", "kq_z112_review_slim", "kq_z112_review_slim_synthetic"))
    hits = 0
    for path in Path(web_root).rglob("*"):
        if path.is_file():
            text = path.read_bytes().decode("utf-8", errors="replace")
            hits += sum(bool(value) and value in text for value in patterns)
    if hits:
        raise ValueError("Private identifiers detected; do not serve this build")
    return dict(private_patterns=len(patterns), private_matches=0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-root", type=Path, required=True)
    parser.add_argument("--entry", choices=["trial", "review"], default="trial")
    parser.add_argument("--private-facts", type=Path)
    parser.add_argument("--private-raw", type=Path)
    args = parser.parse_args()
    result = audit(args.web_root, args.entry)
    if bool(args.private_facts) != bool(args.private_raw):
        parser.error("Both private comparison inputs are required")
    if args.private_facts:
        result.update(private_identifier_scan(args.web_root, args.private_facts, args.private_raw))
    print(json.dumps(result, ensure_ascii=False))
