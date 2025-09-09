from datetime import datetime, timezone
import json
from typing import Any, Dict

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def make_envelope(request_fields: Dict[str, Any], response_fields: Dict[str, Any]) -> str:
    payload = {
        "EXTSYSTEM": {
            "REQUEST": request_fields,
            "TIME": _now_iso(),
            "RESPONSE": response_fields,
        }
    }
    return json.dumps(payload, separators=(",", ":"))
