from __future__ import annotations

import base64
import json
from typing import Any


def parse_jwt_claims(jwt_str: str) -> dict[str, Any] | None:
    """Safely decode and parse JSON claims from a JWT string."""
    if not jwt_str:
        return None
    try:
        parts = jwt_str.split(".")
        if len(parts) >= 2:
            payload = parts[1]
            payload += "=" * (-len(payload) % 4)
            decoded = base64.urlsafe_b64decode(payload)
            data = json.loads(decoded)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return None
