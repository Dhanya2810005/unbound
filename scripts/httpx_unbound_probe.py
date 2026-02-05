import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / "backend" / ".env", override=False)
except Exception:
    pass

UNBOUND_API_URL = "https://api.getunbound.ai/v1/chat/completions"


def _body() -> dict[str, Any]:
    return {
        "model": "kimi-k2-instruct-0905",
        "messages": [{"role": "user", "content": "Reply with exactly: hello"}],
        "temperature": 0.0,
        "max_tokens": 16,
    }


async def probe(http2: bool) -> int:
    api_key = os.getenv("UNBOUND_API_KEY")
    print(f"UNBOUND_API_KEY set? {bool(api_key)}")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "unbound-workflow-builder/0.1",
    }

    timeout = httpx.Timeout(10.0, connect=10.0, read=10.0, write=10.0)

    try:
        async with httpx.AsyncClient(timeout=timeout, http2=http2, follow_redirects=True) as client:
            r = await client.post(UNBOUND_API_URL, headers=headers, json=_body())
            # Force reading body to catch read errors
            content = r.content
            print(f"http2={http2} status={r.status_code} bytes={len(content)}")
            print(content[:200])
            # Try json parse (may fail)
            try:
                data = r.json()
                print("json_keys=", list(data.keys()))
            except Exception as e:
                print("json_parse_error=", type(e).__name__, repr(e))
            return 0
    except Exception as e:
        print(f"http2={http2} error=", type(e).__name__, repr(e))
        return 2


async def main() -> int:
    rc1 = await probe(http2=False)
    rc2 = await probe(http2=True)
    return rc1 or rc2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
