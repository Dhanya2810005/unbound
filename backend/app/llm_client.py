import os
from pathlib import Path
from typing import Optional

import httpx

try:
    from dotenv import load_dotenv

    # Prefer a project-local .env in backend/.env regardless of CWD.
    load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env", override=False)
except Exception:
    # Optional: env loading should never prevent the app from starting.
    pass

from .models import ModelName
from .orchestrator import LLMResponse


# =============================================================================
# CONFIGURATION
# =============================================================================

# API endpoint
UNBOUND_API_URL = "https://api.getunbound.ai/v1/chat/completions"

# Environment variable name for API key
UNBOUND_API_KEY_ENV = "UNBOUND_API_KEY"

DEFAULT_TIMEOUT = 60.0

# EXCEPTIONS

class UnboundAPIError(Exception):
    """
    Raised when Unbound API call fails.
    """
    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# LLM CLIENT

class UnboundLLMClient:
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: str = UNBOUND_API_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.api_key = api_key or os.getenv(UNBOUND_API_KEY_ENV)
        self.api_url = api_url
        self.timeout = timeout
        
        if not self.api_key:
            raise ValueError(
                f"Unbound API key not provided. "
                f"Set {UNBOUND_API_KEY_ENV} environment variable or pass api_key parameter."
            )
    
    async def call(
        self,
        model: ModelName,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        messages = []
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt,
            })
        
        messages.append({
            "role": "user",
            "content": prompt,
        })
        
        request_body = {
            "model": model.value, 
            "messages": messages,
            "temperature": temperature,
        }
        
        # Only include max_tokens if explicitly set
        # WHY: Some models have their own defaults; omitting lets API decide
        if max_tokens is not None:
            request_body["max_tokens"] = max_tokens
        
        # SEND REQUEST
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                http2=True,
                follow_redirects=True,
            ) as client:
                response = await client.post(
                    self.api_url,
                    headers=headers,
                    json=request_body,
                )
        except httpx.TimeoutException:
            raise UnboundAPIError(
                f"Request timed out after {self.timeout}s (url={self.api_url})",
                status_code=None,
            )
        except httpx.RequestError as e:
            detail = str(e) or repr(e)
            raise UnboundAPIError(
                f"Network error ({type(e).__name__}): {detail} (url={self.api_url})",
                status_code=None,
            )
        
        # HANDLE RESPONSE
        if response.status_code != 200:
            # Try to extract error message from response body
            try:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
            except Exception:
                error_msg = response.text
            
            raise UnboundAPIError(
                f"API error ({response.status_code}): {error_msg}",
                status_code=response.status_code,
            )
        
        # PARSE RESPONSE
        # Expected format:
        # {
        #   "choices": [{"message": {"role": "assistant", "content": "..."}}],
        #   "usage": {"prompt_tokens": 123, "completion_tokens": 456}
        # }
        try:
            data = response.json()
            
            # Extract assistant message
            choices = data.get("choices", [])
            if not choices:
                raise UnboundAPIError("No choices in API response")
            
            content = choices[0].get("message", {}).get("content", "")
            
            # Extract token usage (may not always be present)
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            
            return LLMResponse(
                content=content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            
        except KeyError as e:
            raise UnboundAPIError(f"Unexpected response format: missing {e}")
        except Exception as e:
            if isinstance(e, UnboundAPIError):
                raise
            raise UnboundAPIError(f"Failed to parse response: {str(e)}")


def create_unbound_client(
    api_key: Optional[str] = None,
) -> UnboundLLMClient:
    return UnboundLLMClient(api_key=api_key)
