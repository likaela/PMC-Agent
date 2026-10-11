"""Explicit local review process, no tunnel, .env or third-party model egress."""
import os
import sys
import logging
import json
from urllib.parse import unquote, urlparse
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ["PMC_REVIEW_MODE"] = "1"
os.environ["LLM_PROVIDER"] = ""
os.environ.pop("PMC_TRIAL_MODE", None)
for key in ("DEEPSEEK_API_KEY", "MIMO_API_KEY", "OPENAI_API_KEY"):
    os.environ.pop(key, None)

settings_path = Path(os.environ["PMC_REVIEW_SETTINGS"]).resolve(strict=True)
settings = json.loads(settings_path.read_text(encoding="utf-8"))
approved = {(root / settings[k]).resolve(strict=True) for k in ("facts_path", "inventory_path", "units_path", "quantity_path", "slim_dataset_path")}
private_roots = tuple((root / "data" / d).resolve() for d in ("raw", "facts", "normalized"))

def controlled_path(value):
    if not isinstance(value, (str, bytes, os.PathLike)):
        return None
    value = os.fsdecode(value)
    if value.startswith("file:"):
        value = unquote(urlparse(value).path).lstrip("/")
    return Path(value).resolve()

def isolation(event, args):
    if event == "socket.connect" and (not isinstance(args[1], tuple) or args[1][0] not in {"127.0.0.1", "::1"}):
        raise PermissionError("Review model/network egress is prohibited")
    if event in {"open", "sqlite3.connect"}:
        path = controlled_path(args[0])
        if path is None:
            return
        if path.name == ".env" or path.name.startswith(".env."):
            raise PermissionError("Review cannot read environment secrets")
        if any(path == base or base in path.parents for base in private_roots):
            if path not in approved:
                raise PermissionError("Review cannot read unapproved enterprise sources")
            if event == "open" and ((args[1] and any(c in args[1] for c in "wa+")) or (args[2] & (os.O_WRONLY | os.O_RDWR))):
                raise PermissionError("Review sources are read-only")

sys.addaudithook(isolation)
class ReviewLogFilter(logging.Filter):
    def filter(self, record):
        if record.exc_info or record.levelno >= logging.ERROR:
            record.msg, record.args = "Review operation failed; private diagnostics withheld", ()
            record.exc_info, record.exc_text, record.stack_info = None, None, None
        return True

if __name__ == "__main__":
    import uvicorn
    from uvicorn.config import LOGGING_CONFIG
    import copy
    logs = copy.deepcopy(LOGGING_CONFIG)
    logs["filters"] = {"private_review": {"()": ReviewLogFilter}}
    for handler in logs["handlers"].values():
        handler["filters"] = ["private_review"]
    root_handler = logging.StreamHandler()
    root_handler.addFilter(ReviewLogFilter())
    logging.getLogger().addHandler(root_handler)
    uvicorn.run("api.review_app:configured_app", factory=True, host="127.0.0.1", port=8020, workers=1, access_log=False, log_config=logs)
