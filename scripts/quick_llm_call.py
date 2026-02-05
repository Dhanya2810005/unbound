import asyncio
import os
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.llm_client import UNBOUND_API_KEY_ENV, UNBOUND_API_URL, UnboundAPIError, UnboundLLMClient
from app.models import ModelName


async def main() -> int:
    api_key = os.getenv(UNBOUND_API_KEY_ENV)
    print(f"UNBOUND_API_KEY set? {bool(api_key)} len={(len(api_key) if api_key else 0)}")
    print(f"UNBOUND_API_URL={UNBOUND_API_URL}")

    # Short timeout so we get a fast, actionable error.
    client = UnboundLLMClient(timeout=10.0)

    try:
        resp = await client.call(
            model=ModelName.KIMI_K2_INSTRUCT,
            prompt="Reply with exactly: hello",
            temperature=0.0,
            max_tokens=16,
        )
        print("OK")
        print("content:", resp.content)
        print("prompt_tokens:", resp.prompt_tokens, "completion_tokens:", resp.completion_tokens)
        return 0
    except UnboundAPIError as e:
        print("UnboundAPIError:", e.message)
        print("status_code:", e.status_code)
        return 2
    except Exception as e:
        print("Unexpected error:", type(e).__name__, repr(e))
        return 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
