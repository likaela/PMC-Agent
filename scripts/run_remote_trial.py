"""Dedicated process; no project .env, keys, enterprise routes or enterprise store."""
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ["PMC_TRIAL_MODE"] = "1"
os.environ["LLM_PROVIDER"] = ""
for key in ("DEEPSEEK_API_KEY", "MIMO_API_KEY", "OPENAI_API_KEY"):
    os.environ.pop(key, None)
# Defense in depth for accidentally called enterprise-store helpers: no real DB.
os.environ["PMC_FACT_DATABASE_URL"] = "sqlite:///" + (root / ".runtime/remote-trial/forbidden-enterprise.db").as_posix()
os.environ["PMC_DATA_SOURCE"] = "demo"


def isolation(event, args):
    # Process-local defense: future accidental imports/clients also fail closed.
    if event == "socket.connect" and (not isinstance(args[1], tuple) or args[1][0] not in {"127.0.0.1", "::1"}):
        raise PermissionError("Remote trial outbound connections are prohibited")
    if event in {"open", "sqlite3.connect"} and args and isinstance(args[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(args[0])).resolve()
        if path == root / ".env" or any(path.is_relative_to(root / "data" / name) for name in ("raw", "facts", "normalized")):
            raise PermissionError("Remote trial cannot read private enterprise data")


sys.addaudithook(isolation)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.trial_app:configured_app", factory=True, host="127.0.0.1", port=8010,
                access_log=False, workers=1)
