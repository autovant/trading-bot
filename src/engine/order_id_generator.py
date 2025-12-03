from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional


def generate_order_id(
    symbol: str,
    side: str,
    timestamp: Optional[datetime] = None,
    nonce: Optional[str] = None,
) -> str:
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    
    ts_str = timestamp.strftime("%Y%m%d%H%M%S")
    
    components = [symbol, side, ts_str]
    if nonce:
        components.append(nonce)
    
    data = "_".join(components)
    hash_digest = hashlib.sha256(data.encode()).hexdigest()
    
    return f"{symbol[:3]}{side[0]}{ts_str[-6:]}{hash_digest[:8]}"
