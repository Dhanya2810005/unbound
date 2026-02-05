"""
Test script for the Unbound LLM client.

Run with: python -m app.test_llm_client

This validates:
1. Client can connect to Unbound API
2. Both models work (kimi-k2-instruct-0905, kimi-k2p5)
3. System prompts are respected
4. Token usage is returned
5. Errors are handled gracefully
"""

import asyncio
import os
import sys
from pathlib import Path

# Allow running as: `python backend/app/test_llm_client.py`
# by ensuring the backend root (which contains the `app` package) is on sys.path.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.llm_client import UnboundLLMClient, UnboundAPIError, create_unbound_client
from app.models import ModelName


async def test_basic_call():
    """Test a basic API call with kimi-k2-instruct."""
    print("\n--- BASIC CALL (kimi-k2-instruct-0905) ---")
    
    client = create_unbound_client()
    
    response = await client.call(
        model=ModelName.KIMI_K2_INSTRUCT,
        prompt="What is 2 + 2? Reply with just the number.",
    )
    
    print(f"Content: {response.content}")
    print(f"Prompt tokens: {response.prompt_tokens}")
    print(f"Completion tokens: {response.completion_tokens}")
    
    assert response.content, "Expected non-empty response"
    assert response.prompt_tokens > 0, "Expected prompt tokens"
    print("✓ Basic call works")


async def test_with_system_prompt():
    """Test call with system prompt."""
    print("\n--- WITH SYSTEM PROMPT ---")
    
    client = create_unbound_client()
    
    response = await client.call(
        model=ModelName.KIMI_K2_INSTRUCT,
        prompt="Greet the user.",
        system_prompt="You are a pirate. Always speak like a pirate.",
    )
    
    print(f"Content: {response.content}")
    
    assert response.content, "Expected non-empty response"
    print("✓ System prompt works")


async def test_kimi_k2p5():
    """Test kimi-k2p5 model."""
    print("\n--- KIMI-K2P5 MODEL ---")
    
    client = create_unbound_client()
    
    response = await client.call(
        model=ModelName.KIMI_K2P5,
        prompt="Explain what an API is in one sentence.",
    )
    
    print(f"Content: {response.content}")
    print(f"Tokens: {response.prompt_tokens} prompt, {response.completion_tokens} completion")
    
    assert response.content, "Expected non-empty response"
    print("✓ kimi-k2p5 model works")


async def test_code_generation():
    """Test code generation (common use case)."""
    print("\n--- CODE GENERATION ---")
    
    client = create_unbound_client()
    
    response = await client.call(
        model=ModelName.KIMI_K2_INSTRUCT,
        prompt="Write a Python function that doubles a number. Only output the code, no explanation.",
        system_prompt="You are a Python expert. Output only valid Python code.",
    )
    
    print(f"Content:\n{response.content}")
    
    assert "def" in response.content, "Expected function definition"
    print("✓ Code generation works")


async def test_invalid_api_key():
    """Test error handling with invalid API key."""
    print("\n--- INVALID API KEY ---")
    
    client = UnboundLLMClient(api_key="invalid-key-12345")
    
    try:
        await client.call(
            model=ModelName.KIMI_K2_INSTRUCT,
            prompt="Hello",
        )
        print("✗ Expected UnboundAPIError")
        assert False, "Should have raised UnboundAPIError"
    except UnboundAPIError as e:
        print(f"✓ Got expected error: {e.message[:80]}...")
        assert e.status_code in [401, 403, None], f"Expected 401/403, got {e.status_code}"


async def main():
    """Run all LLM client tests."""
    print("=" * 60)
    print("UNBOUND LLM CLIENT TESTS")
    print("=" * 60)
    
    # Check API key is set
    api_key = os.getenv("UNBOUND_API_KEY")
    if not api_key:
        print("\n⚠️  UNBOUND_API_KEY not set!")
        print("Set it with: $env:UNBOUND_API_KEY = 'your-key'")
        print("Then run this test again.\n")
        return
    
    print("UNBOUND_API_KEY detected (value hidden)")
    
    try:
        await test_basic_call()
        await test_with_system_prompt()
        await test_kimi_k2p5()
        await test_code_generation()
        await test_invalid_api_key()
        
        print("\n" + "=" * 60)
        print("✅ All LLM client tests passed!")
        print("=" * 60)
        
    except UnboundAPIError as e:
        print(f"\n❌ API Error: {e.message}")
        if e.status_code:
            print(f"   Status code: {e.status_code}")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
