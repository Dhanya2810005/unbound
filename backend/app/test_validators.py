"""
Test script for validators.

Run with: python -m app.test_validators

This validates:
1. Each validator correctly passes valid input
2. Each validator correctly fails invalid input
3. Error messages are clear and helpful
4. Edge cases are handled (empty input, missing config)
"""

import asyncio
import os

from app.models import ValidationRule, ValidationType
from app.validators import (
    ValidatorDispatcher,
    validate_contains,
    validate_json,
    validate_python_syntax,
    validate_regex_match,
    validate_test_exec,
)


def test_python_syntax():
    """Test PYTHON_SYNTAX validator."""
    print("\n--- PYTHON_SYNTAX ---")
    
    # Valid Python
    result = validate_python_syntax("def foo():\n    return 42")
    assert result.passed, f"Expected pass, got: {result.error}"
    print("✓ Valid Python passes")
    
    # Invalid Python
    result = validate_python_syntax("def foo(\n    return 42")
    assert not result.passed, "Expected fail for invalid syntax"
    assert "syntax error" in result.error.lower()
    print(f"✓ Invalid Python fails: {result.error}")
    
    # Empty input
    result = validate_python_syntax("")
    assert not result.passed, "Expected fail for empty input"
    print(f"✓ Empty input fails: {result.error}")
    
    # Just whitespace
    result = validate_python_syntax("   \n\t  ")
    assert not result.passed, "Expected fail for whitespace-only"
    print(f"✓ Whitespace-only fails: {result.error}")


def test_json_valid():
    """Test JSON_VALID validator."""
    print("\n--- JSON_VALID ---")
    
    # Valid JSON object
    result = validate_json('{"name": "test", "value": 123}')
    assert result.passed, f"Expected pass, got: {result.error}"
    print("✓ Valid JSON object passes")
    
    # Valid JSON array
    result = validate_json('[1, 2, 3]')
    assert result.passed, f"Expected pass, got: {result.error}"
    print("✓ Valid JSON array passes")
    
    # Valid JSON primitive
    result = validate_json('"just a string"')
    assert result.passed, f"Expected pass, got: {result.error}"
    print("✓ Valid JSON string passes")
    
    # Invalid JSON
    result = validate_json('{"name": "test",}')  # Trailing comma
    assert not result.passed, "Expected fail for invalid JSON"
    assert "parse error" in result.error.lower()
    print(f"✓ Invalid JSON fails: {result.error}")
    
    # Empty input
    result = validate_json("")
    assert not result.passed, "Expected fail for empty input"
    print(f"✓ Empty input fails: {result.error}")


def test_contains():
    """Test CONTAINS validator."""
    print("\n--- CONTAINS ---")
    
    # Contains substring
    result = validate_contains("def double(x): return x * 2", "def ")
    assert result.passed, f"Expected pass, got: {result.error}"
    print("✓ Substring present passes")
    
    # Missing substring
    result = validate_contains("print('hello')", "def ")
    assert not result.passed, "Expected fail for missing substring"
    assert "does not contain" in result.error.lower()
    print(f"✓ Missing substring fails: {result.error}")
    
    # Case sensitivity
    result = validate_contains("DEF foo():", "def ")
    assert not result.passed, "Expected fail for case mismatch"
    print("✓ Case-sensitive check works")
    
    # Missing expected value
    result = validate_contains("some output", None)
    assert not result.passed, "Expected fail for missing expected"
    assert "required" in result.error.lower()
    print(f"✓ Missing config fails: {result.error}")


def test_regex_match():
    """Test REGEX_MATCH validator."""
    print("\n--- REGEX_MATCH ---")
    
    # Matches pattern
    result = validate_regex_match("def foo(): return 42", r"def \w+\(")
    assert result.passed, f"Expected pass, got: {result.error}"
    print("✓ Matching pattern passes")
    
    # Pattern not found
    result = validate_regex_match("print('hello')", r"def \w+\(")
    assert not result.passed, "Expected fail for no match"
    assert "does not match" in result.error.lower()
    print(f"✓ No match fails: {result.error}")
    
    # Pattern in middle of string (re.search, not re.match)
    result = validate_regex_match("# comment\ndef foo(): pass", r"def \w+\(")
    assert result.passed, "Expected pass for pattern in middle"
    print("✓ Pattern found in middle (re.search works)")
    
    # Invalid regex pattern
    result = validate_regex_match("some text", r"[invalid(")
    assert not result.passed, "Expected fail for invalid regex"
    assert "invalid regex" in result.error.lower()
    print(f"✓ Invalid regex fails: {result.error}")
    
    # Missing pattern
    result = validate_regex_match("some output", None)
    assert not result.passed, "Expected fail for missing pattern"
    assert "required" in result.error.lower()
    print(f"✓ Missing config fails: {result.error}")


def test_test_exec():
    """Test TEST_EXEC validator."""
    print("\n--- TEST_EXEC ---")
    
    # Simple assertion passes
    result = validate_test_exec("hello world", "assert 'hello' in output")
    assert result.passed, f"Expected pass, got: {result.error}"
    print("✓ Simple assertion passes")
    
    # Multiple assertions pass
    result = validate_test_exec(
        "def foo(): return 42",
        "assert 'def' in output\nassert 'return' in output"
    )
    assert result.passed, f"Expected pass, got: {result.error}"
    print("✓ Multiple assertions pass")
    
    # JSON parsing in test
    result = validate_test_exec(
        '{"name": "test", "value": 123}',
        "data = json.loads(output); assert data['name'] == 'test'"
    )
    assert result.passed, f"Expected pass, got: {result.error}"
    print("✓ JSON parsing in test works")
    
    # Assertion fails
    result = validate_test_exec("hello", "assert 'goodbye' in output")
    assert not result.passed, "Expected fail for failed assertion"
    assert "assertion failed" in result.error.lower()
    print(f"✓ Failed assertion returns error: {result.error}")
    
    # Test code has syntax error
    result = validate_test_exec("hello", "assert 'hello' in")
    assert not result.passed, "Expected fail for syntax error"
    assert "syntax error" in result.error.lower()
    print(f"✓ Test code syntax error handled: {result.error}")
    
    # Test code references undefined variable
    result = validate_test_exec("hello", "assert undefined_var")
    assert not result.passed, "Expected fail for undefined var"
    assert "error" in result.error.lower()
    print(f"✓ Undefined variable handled: {result.error}")
    
    # Missing test_code
    result = validate_test_exec("some output", None)
    assert not result.passed, "Expected fail for missing test_code"
    assert "required" in result.error.lower()
    print(f"✓ Missing config fails: {result.error}")
    
    # Dangerous builtins are blocked
    result = validate_test_exec("hello", "open('file.txt')")
    assert not result.passed, "Expected fail for blocked builtin"
    print(f"✓ Dangerous builtins blocked: {result.error}")


async def test_llm_judge():
    """Test LLM_JUDGE validator (requires API key)."""
    print("\n--- LLM_JUDGE ---")
    
    # Check if API key is available
    if not os.getenv("UNBOUND_API_KEY"):
        print("⚠️  Skipping LLM_JUDGE tests (UNBOUND_API_KEY not set)")
        return
    
    from app.llm_client import create_unbound_client
    from app.validators import validate_llm_judge
    
    llm_client = create_unbound_client()
    
    # Valid Python code should pass
    result = await validate_llm_judge(
        output="def double(x):\n    return x * 2",
        criteria="Is this valid Python code that doubles a number?",
        llm_client=llm_client,
    )
    print(f"LLM judge response for valid code: passed={result.passed}")
    if not result.passed:
        print(f"  Error: {result.error}")
    
    # Gibberish should fail
    result = await validate_llm_judge(
        output="asdfghjkl qwerty zxcvbn",
        criteria="Is this valid Python code?",
        llm_client=llm_client,
    )
    print(f"LLM judge response for gibberish: passed={result.passed}")
    if not result.passed:
        print(f"  Error: {result.error}")
    
    # Missing criteria
    result = await validate_llm_judge(
        output="some output",
        criteria=None,
        llm_client=llm_client,
    )
    assert not result.passed, "Expected fail for missing criteria"
    assert "required" in result.error.lower()
    print(f"✓ Missing criteria fails: {result.error}")
    
    # Missing LLM client
    result = await validate_llm_judge(
        output="some output",
        criteria="Is this good?",
        llm_client=None,
    )
    assert not result.passed, "Expected fail for missing client"
    assert "required" in result.error.lower()
    print(f"✓ Missing LLM client fails: {result.error}")


async def test_dispatcher():
    """Test ValidatorDispatcher routing."""
    print("\n--- DISPATCHER ---")
    
    dispatcher = ValidatorDispatcher()
    
    # PYTHON_SYNTAX via dispatcher
    rule = ValidationRule(type=ValidationType.PYTHON_SYNTAX)
    result = await dispatcher.validate("x = 1", rule)
    assert result.passed, f"Expected pass, got: {result.error}"
    print("✓ PYTHON_SYNTAX routed correctly")
    
    # JSON_VALID via dispatcher
    rule = ValidationRule(type=ValidationType.JSON_VALID)
    result = await dispatcher.validate('{"a": 1}', rule)
    assert result.passed, f"Expected pass, got: {result.error}"
    print("✓ JSON_VALID routed correctly")
    
    # CONTAINS via dispatcher
    rule = ValidationRule(type=ValidationType.CONTAINS, expected="hello")
    result = await dispatcher.validate("hello world", rule)
    assert result.passed, f"Expected pass, got: {result.error}"
    print("✓ CONTAINS routed correctly")
    
    # REGEX_MATCH via dispatcher
    rule = ValidationRule(type=ValidationType.REGEX_MATCH, pattern=r"\d+")
    result = await dispatcher.validate("value: 123", rule)
    assert result.passed, f"Expected pass, got: {result.error}"
    print("✓ REGEX_MATCH routed correctly")
    
    # TEST_EXEC via dispatcher
    rule = ValidationRule(type=ValidationType.TEST_EXEC, test_code="assert 'code' in output")
    result = await dispatcher.validate("some code here", rule)
    assert result.passed, f"Expected pass, got: {result.error}"
    print("✓ TEST_EXEC routed correctly")
    
    # LLM_JUDGE via dispatcher (skip if no API key)
    if os.getenv("UNBOUND_API_KEY"):
        from app.llm_client import create_unbound_client
        dispatcher_with_llm = ValidatorDispatcher()
        llm_client = create_unbound_client()
        rule = ValidationRule(type=ValidationType.LLM_JUDGE, criteria="Is this a greeting?")
        result = await dispatcher_with_llm.validate("Hello, how are you?", rule, llm_client)
        print(f"✓ LLM_JUDGE routed correctly (passed={result.passed})")
    else:
        print("⚠️  LLM_JUDGE dispatcher test skipped (no API key)")


def main():
    """Run all validator tests."""
    print("=" * 60)
    print("VALIDATOR TESTS")
    print("=" * 60)
    
    test_python_syntax()
    test_json_valid()
    test_contains()
    test_regex_match()
    test_test_exec()
    
    async def run_async_tests():
        await test_llm_judge()
        await test_dispatcher()
    
    asyncio.run(run_async_tests())
    
    print("\n" + "=" * 60)
    print("✅ All validator tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
