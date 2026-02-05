"""
Validator Dispatcher: Routes validation requests to specific validators.

This module implements the Validator protocol from the orchestrator.
Each validation type has its own pure function that returns ValidationResult.

HOW IT PLUGS INTO ORCHESTRATOR:
1. Orchestrator calls: validator.validate(output, rule, llm_client)
2. ValidatorDispatcher.validate() dispatches based on rule.type
3. Specific validator function runs and returns ValidationResult
4. Orchestrator decides retry/continue based on result.passed
"""

import ast
import json
import re
from typing import Optional

from .models import ValidationRule, ValidationType, ModelName
from .orchestrator import LLMClient, ValidationResult


# =============================================================================
# INDIVIDUAL VALIDATORS — Pure functions, easy to test
# =============================================================================

def validate_python_syntax(output: str) -> ValidationResult:
    # Handle empty output
    if not output or not output.strip():
        return ValidationResult(
            passed=False,
            error="Empty output cannot be valid Python syntax",
        )
    
    try:
        ast.parse(output)
        return ValidationResult(passed=True)
    except SyntaxError as e:
        # Extract useful error info
        line_info = f" (line {e.lineno})" if e.lineno else ""
        return ValidationResult(
            passed=False,
            error=f"Python syntax error{line_info}: {e.msg}",
        )


def validate_json(output: str) -> ValidationResult:
    # Handle empty output
    if not output or not output.strip():
        return ValidationResult(
            passed=False,
            error="Empty output cannot be valid JSON",
        )
    
    try:
        json.loads(output)
        return ValidationResult(passed=True)
    except json.JSONDecodeError as e:
        return ValidationResult(
            passed=False,
            error=f"JSON parse error at position {e.pos}: {e.msg}",
        )


def validate_contains(output: str, expected: str) -> ValidationResult:
    """
    Check if output contains the expected substring.
    
    WHY simple substring check:
    - Fast and deterministic
    - Easy to understand
    - Good for checking presence of required elements
    
    Common use case:
    - Ensure LLM output includes specific keywords or phrases
    - e.g., "def " to ensure a function was defined
    
    Args:
        output: The LLM output to check
        expected: The substring that must be present
    
    Returns:
        ValidationResult with passed=True if substring found
    """
    # Handle missing expected value
    if expected is None:
        return ValidationResult(
            passed=False,
            error="ValidationRule.expected is required for CONTAINS validation",
        )
    
    if expected in output:
        return ValidationResult(passed=True)
    else:
        # Truncate for readability in error message
        output_preview = output[:100] + "..." if len(output) > 100 else output
        return ValidationResult(
            passed=False,
            error=f"Output does not contain '{expected}'. Got: {output_preview}",
        )


def validate_regex_match(output: str, pattern: str) -> ValidationResult:
    """
    Check if output matches a regex pattern using re.search().
    
    WHY re.search (not re.match):
    - re.search finds pattern anywhere in string
    - re.match only matches at the beginning
    - re.search is more intuitive for "does this contain X pattern?"
    
    Common use case:
    - Check if output matches expected format
    - e.g., r"def \\w+\\(" to ensure a function definition exists
    
    Args:
        output: The LLM output to check
        pattern: Regex pattern to search for
    
    Returns:
        ValidationResult with passed=True if pattern found
    """
    # Handle missing pattern
    if pattern is None:
        return ValidationResult(
            passed=False,
            error="ValidationRule.pattern is required for REGEX_MATCH validation",
        )
    
    try:
        if re.search(pattern, output):
            return ValidationResult(passed=True)
        else:
            output_preview = output[:100] + "..." if len(output) > 100 else output
            return ValidationResult(
                passed=False,
                error=f"Output does not match pattern '{pattern}'. Got: {output_preview}",
            )
    except re.error as e:
        # Invalid regex pattern
        return ValidationResult(
            passed=False,
            error=f"Invalid regex pattern '{pattern}': {e}",
        )


def validate_test_exec(output: str, test_code: str) -> ValidationResult:
    """
    Execute test code against the LLM output in a sandboxed environment.
    
    WHY this approach:
    - Allows custom assertions beyond simple pattern matching
    - The test_code can reference `output` variable
    - Runs in restricted globals (no file/network access)
    
    SECURITY NOTES:
    - This is NOT fully sandboxed (Python exec can't be truly sandboxed)
    - For hackathon: acceptable risk with controlled test_code
    - For production: use a proper sandbox (Docker, subprocess, etc.)
    
    Common use case:
    - test_code: "assert 'def ' in output and 'return' in output"
    - test_code: "import json; data = json.loads(output); assert 'name' in data"
    
    Args:
        output: The LLM output to validate
        test_code: Python code with assertions to run
    
    Returns:
        ValidationResult with passed=True if no assertion fails
    """
    # Handle missing test_code
    if test_code is None:
        return ValidationResult(
            passed=False,
            error="ValidationRule.test_code is required for TEST_EXEC validation",
        )
    
    # Create a restricted execution environment
    # WHY restricted: Prevent access to dangerous builtins
    safe_builtins = {
        "len": len,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "tuple": tuple,
        "set": set,
        "range": range,
        "enumerate": enumerate,
        "zip": zip,
        "map": map,
        "filter": filter,
        "sorted": sorted,
        "reversed": reversed,
        "min": min,
        "max": max,
        "sum": sum,
        "abs": abs,
        "all": all,
        "any": any,
        "isinstance": isinstance,
        "hasattr": hasattr,
        "getattr": getattr,
        "True": True,
        "False": False,
        "None": None,
        # Allow json for structured output testing
        "json": json,
    }
    
    # Execution namespace with output available
    exec_globals = {"__builtins__": safe_builtins}
    exec_locals = {"output": output}
    
    try:
        # Execute the test code
        exec(test_code, exec_globals, exec_locals)
        return ValidationResult(passed=True)
    
    except AssertionError as e:
        # Assertion failed — this is expected failure mode
        error_msg = str(e) if str(e) else "Assertion failed"
        return ValidationResult(
            passed=False,
            error=f"Test assertion failed: {error_msg}",
        )
    
    except SyntaxError as e:
        # Test code itself is invalid
        return ValidationResult(
            passed=False,
            error=f"Test code syntax error: {e.msg}",
        )
    
    except NameError as e:
        # Test code references undefined variable
        return ValidationResult(
            passed=False,
            error=f"Test code error: {e}",
        )
    
    except Exception as e:
        # Any other error during execution
        return ValidationResult(
            passed=False,
            error=f"Test execution error: {type(e).__name__}: {e}",
        )


async def validate_llm_judge(
    output: str,
    criteria: str,
    llm_client: LLMClient,
) -> ValidationResult:
    """
    Use an LLM to judge whether output meets criteria.
    
    WHY LLM-as-a-judge:
    - Some validations can't be expressed as code (e.g., "is this helpful?")
    - LLM can evaluate semantic correctness
    - Useful for subjective quality checks
    
    HOW IT WORKS:
    1. Sends output + criteria to LLM with strict YES/NO prompt
    2. Parses response for YES or NO
    3. Returns passed=True only if LLM says YES
    
    CONSTRAINTS:
    - LLM must respond with YES or NO (enforced by prompt)
    - Uses kimi-k2-instruct for consistency (good at following instructions)
    - Low temperature for deterministic responses
    
    Args:
        output: The LLM output to judge
        criteria: The criteria to evaluate against
        llm_client: LLM client for making the judge call
    
    Returns:
        ValidationResult based on LLM's YES/NO response
    """
    # Handle missing criteria
    if criteria is None:
        return ValidationResult(
            passed=False,
            error="ValidationRule.criteria is required for LLM_JUDGE validation",
        )
    
    # Handle missing LLM client
    if llm_client is None:
        return ValidationResult(
            passed=False,
            error="LLM client is required for LLM_JUDGE validation",
        )
    
    # Build the judge prompt
    # WHY this format: Forces binary YES/NO response
    judge_prompt = f"""You are a strict validator. Evaluate if the following output meets the given criteria.

CRITERIA: {criteria}

OUTPUT TO EVALUATE:
{output}

Does this output meet the criteria? 
Respond with ONLY "YES" or "NO". Do not explain."""

    system_prompt = "You are a validation judge. You MUST respond with exactly YES or NO, nothing else."
    
    try:
        response = await llm_client.call(
            model=ModelName.KIMI_K2_INSTRUCT,  # Use instruct model for following instructions
            prompt=judge_prompt,
            system_prompt=system_prompt,
        )
        
        # Parse response — look for YES or NO
        # WHY uppercase + strip: Handle variations like "yes", "Yes.", " YES "
        answer = response.content.strip().upper()
        
        # Check for YES
        if answer == "YES" or answer.startswith("YES"):
            return ValidationResult(passed=True)
        
        # Check for NO
        if answer == "NO" or answer.startswith("NO"):
            return ValidationResult(
                passed=False,
                error=f"LLM judge rejected output. Criteria: {criteria}",
            )
        
        # Unexpected response — treat as failure
        return ValidationResult(
            passed=False,
            error=f"LLM judge gave unclear response: '{response.content[:50]}'. Expected YES or NO.",
        )
    
    except Exception as e:
        # LLM call failed
        return ValidationResult(
            passed=False,
            error=f"LLM judge error: {type(e).__name__}: {e}",
        )


# =============================================================================
# VALIDATOR DISPATCHER — Implements the Validator protocol
# =============================================================================

class ValidatorDispatcher:
    async def validate(
        self,
        output: str,
        rule: ValidationRule,
        llm_client: Optional[LLMClient] = None,
    ) -> ValidationResult:
        # ─────────────────────────────────────────────────────────────────
        # DISPATCH based on rule.type
        # WHY match statement: Clear, exhaustive, Pythonic (3.10+)
        # ─────────────────────────────────────────────────────────────────
        
        match rule.type:
            case ValidationType.PYTHON_SYNTAX:
                return validate_python_syntax(output)
            
            case ValidationType.JSON_VALID:
                return validate_json(output)
            
            case ValidationType.CONTAINS:
                return validate_contains(output, rule.expected)
            
            case ValidationType.REGEX_MATCH:
                return validate_regex_match(output, rule.pattern)
            
            case ValidationType.TEST_EXEC:
                return validate_test_exec(output, rule.test_code)
            
            case ValidationType.LLM_JUDGE:
                return await validate_llm_judge(output, rule.criteria, llm_client)
            
            case _:
                # Unknown validation type — should never happen if enum is used
                return ValidationResult(
                    passed=False,
                    error=f"Unknown validation type: {rule.type}",
                )
