"""
Lora Code API Client Module

Handles all communication with Lora Code API including:
- HTTP session management
- Authorization header injection
- URL validation
- Model listing and validation
- Chat completions with streaming support
- Rate limiting and error handling
"""

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Optional, List, Iterator, Dict, Any, Union
from urllib.parse import urlparse

import requests

from loracode.lora_code_auth import LoraCodeAuth, Credentials


@dataclass
class ModelInfo:
    """Information about a Lora Code model."""
    id: str
    name: str
    description: str
    context_length: int
    owned_by: str


class LoraCodeClientError(Exception):
    """Base exception for Lora Code client errors."""
    pass


class URLValidationError(LoraCodeClientError):
    """Raised when URL validation fails."""
    pass


class AuthenticationError(LoraCodeClientError):
    """Raised when authentication fails."""
    pass


class ModelNotFoundError(LoraCodeClientError):
    """Raised when a requested model is not found."""
    pass


class RateLimitError(LoraCodeClientError):
    """Raised when rate limit is exceeded."""
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class APIError(LoraCodeClientError):
    """Raised when API returns an error response."""
    def __init__(self, message: str, status_code: int, error_details: Optional[dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_details = error_details or {}


@dataclass
class ChatMessage:
    """A chat message."""
    role: str
    content: str
    
    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class ThinkingConfig:
    """Configuration for thinking/extended reasoning mode."""
    enabled: bool = False
    budget: int = 10000
    
    def to_dict(self) -> dict:
        """Convert to API request format."""
        if not self.enabled:
            return {}
        return {
            "thinking": {
                "enabled": True,
                "budget": self.budget
            }
        }


@dataclass
class RateLimitInfo:
    """Rate limit information from API response headers."""
    limit: Optional[int] = None
    remaining: Optional[int] = None
    reset: Optional[float] = None
    retry_after: Optional[float] = None
    
    @classmethod
    def from_headers(cls, headers: dict) -> "RateLimitInfo":
        """Parse rate limit info from response headers."""
        def parse_int(key: str) -> Optional[int]:
            value = headers.get(key)
            if value is not None:
                try:
                    return int(value)
                except (ValueError, TypeError):
                    return None
            return None
        
        def parse_float(key: str) -> Optional[float]:
            value = headers.get(key)
            if value is not None:
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return None
            return None
        
        return cls(
            limit=parse_int("X-RateLimit-Limit"),
            remaining=parse_int("X-RateLimit-Remaining"),
            reset=parse_float("X-RateLimit-Reset"),
            retry_after=parse_float("Retry-After"),
        )


def validate_api_base_url(url: str) -> bool:
    """
    Validate that the API base URL is a valid HTTPS URL.
    
    Args:
        url: The URL to validate
        
    Returns:
        True if valid
        
    Raises:
        URLValidationError: If the URL is invalid or not HTTPS
    """
    if not url:
        raise URLValidationError("API base URL cannot be empty")
    
    try:
        parsed = urlparse(url)
        
        if parsed.scheme != "https":
            raise URLValidationError(
                f"API base URL must use HTTPS. Got: {parsed.scheme or 'no scheme'}"
            )
        
        if not parsed.netloc:
            raise URLValidationError("API base URL must have a valid domain")
        
        domain_pattern = re.compile(
            r'^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?'
            r'(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*'
            r'(:\d+)?$'
        )
        if not domain_pattern.match(parsed.netloc):
            raise URLValidationError(
                f"API base URL has invalid domain: {parsed.netloc}"
            )
        
        return True
        
    except URLValidationError:
        raise
    except Exception as e:
        raise URLValidationError(f"Invalid API base URL: {str(e)}")


class LoraCodeClient:
    """
    Client for Lora Code API.
    
    Handles HTTP communication with Lora Code API including:
    - Session management
    - Authorization header injection
    - Model listing and validation
    """
    
    DEFAULT_API_BASE = "https://api.loratech.dev"
    
    def __init__(
        self,
        api_base: str = None,
        api_key: str = None,
        auth: LoraCodeAuth = None
    ):
        """
        Initialize the Lora Code client.
        
        Args:
            api_base: Lora Code API base URL. Defaults to LORA_CODE_API_BASE env var
                     or https://api.loratech.dev
            api_key: API key for authentication. Defaults to LORA_CODE_API_KEY env var
            auth: LoraCodeAuth instance for credential management. If not provided,
                  a new instance will be created.
        """
        self.api_base = api_base or os.environ.get(
            "LORA_CODE_API_BASE",
            self.DEFAULT_API_BASE
        )
        
        validate_api_base_url(self.api_base)
        
        self.api_base = self.api_base.rstrip('/')
        
        self._api_key = api_key or os.environ.get("LORA_CODE_API_KEY")
        
        self._auth = auth or LoraCodeAuth(api_base=self.api_base)
        
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "loracode-lora-code-client/1.0"
        })
        
        self._models_cache: Optional[List[ModelInfo]] = None
    
    def _get_auth_header(self) -> dict:
        """
        Get the authorization header for API requests.
        
        Returns:
            Dict with Authorization header
            
        Raises:
            AuthenticationError: If no valid credentials are available
        """
        import os
        debug = os.environ.get("LORACODE_DEBUG")
        
        if self._api_key:
            if debug:
                print(f"[DEBUG] Using API key for auth")
            return {"Authorization": f"Bearer {self._api_key}"}
        
        if self._auth:
            try:
                creds = self._auth.get_credentials()
                if debug:
                    if creds:
                        print(f"[DEBUG] Credentials found: email={creds.email}, expires_at={creds.token_expires_at}")
                        print(f"[DEBUG] JWT token exists: {bool(creds.jwt_token)}")
                        print(f"[DEBUG] Is expired: {self._auth.is_token_expired(creds)}")
                    else:
                        print(f"[DEBUG] No credentials found")
                
                token = self._auth.get_valid_token()
                if token:
                    if debug:
                        print(f"[DEBUG] Using JWT token for auth")
                    return {"Authorization": f"Bearer {token}"}
                elif debug:
                    print(f"[DEBUG] get_valid_token returned None")
            except Exception as e:
                if debug:
                    print(f"[DEBUG] Auth error: {e}")
        
        raise AuthenticationError(
            "No valid credentials available. Please authenticate first."
        )

    
    def _make_request(
        self,
        method: str,
        endpoint: str,
        authenticated: bool = True,
        **kwargs
    ) -> requests.Response:
        """
        Make an HTTP request to the Lora Code API.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., "/v1/models")
            authenticated: Whether to include auth header
            **kwargs: Additional arguments to pass to requests
            
        Returns:
            Response object
            
        Raises:
            AuthenticationError: If authentication fails
            LoraCodeClientError: If the request fails
        """
        url = f"{self.api_base}{endpoint}"
        
        headers = kwargs.pop("headers", {})
        
        if authenticated:
            auth_header = self._get_auth_header()
            headers.update(auth_header)
        
        try:
            response = self._session.request(
                method,
                url,
                headers=headers,
                timeout=kwargs.pop("timeout", 30),
                **kwargs
            )
            
            if response.status_code == 401:
                raise AuthenticationError(
                    "Authentication failed. Please check your credentials."
                )
            
            return response
            
        except requests.exceptions.ConnectionError:
            raise LoraCodeClientError(
                f"Cannot connect to Lora Code API at {self.api_base}"
            )
        except requests.exceptions.Timeout:
            raise LoraCodeClientError(
                "Connection to Lora Code API timed out"
            )
        except requests.exceptions.RequestException as e:
            raise LoraCodeClientError(f"Request failed: {str(e)}")
    
    def list_models(self, force_refresh: bool = False) -> List[ModelInfo]:
        """
        List available models from Lora Code API.
        
        Args:
            force_refresh: If True, bypass cache and fetch fresh data
            
        Returns:
            List of ModelInfo objects
            
        Raises:
            LoraCodeClientError: If the request fails
        """
        if self._models_cache is not None and not force_refresh:
            return self._models_cache
        
        response = self._make_request("GET", "/v1/models")
        response.raise_for_status()
        
        data = response.json()
        models = []
        
        for model_data in data.get("data", []):
            model = ModelInfo(
                id=model_data.get("id", ""),
                name=model_data.get("id", ""),
                description=model_data.get("description", ""),
                context_length=model_data.get("context_length", 0),
                owned_by=model_data.get("owned_by", "lora-code")
            )
            models.append(model)
        
        self._models_cache = models
        return models
    
    def validate_model(self, model_id: str) -> ModelInfo:
        """
        Validate that a model exists and return its info.
        
        Args:
            model_id: The model ID to validate
            
        Returns:
            ModelInfo for the validated model
            
        Raises:
            ModelNotFoundError: If the model doesn't exist
        """
        models = self.list_models()
        
        for model in models:
            if model.id == model_id:
                return model
        
        available = [m.id for m in models]
        raise ModelNotFoundError(
            f"Model '{model_id}' not found. Available models: {', '.join(available)}"
        )
    
    def get_model_ids(self) -> List[str]:
        """
        Get list of available model IDs.
        
        Returns:
            List of model ID strings
        """
        models = self.list_models()
        return [m.id for m in models]
    
    def is_authenticated(self) -> bool:
        """
        Check if the client has valid authentication.
        
        Returns:
            True if authenticated, False otherwise
        """
        try:
            self._get_auth_header()
            return True
        except AuthenticationError:
            return False
    
    def get_user_info(self) -> dict:
        """
        Get current user information from Lora Code API.
        
        Returns:
            Dict with user information
            
        Raises:
            LoraCodeClientError: If the request fails
        """
        response = self._make_request("GET", "/v1/me")
        response.raise_for_status()
        return response.json()
    
    def clear_cache(self) -> None:
        """Clear the models cache."""
        self._models_cache = None
    
    def _parse_rate_limit_headers(self, response: requests.Response) -> RateLimitInfo:
        """
        Parse rate limit information from response headers.
        
        Args:
            response: HTTP response object
            
        Returns:
            RateLimitInfo with parsed rate limit data
        """
        return RateLimitInfo.from_headers(response.headers)
    
    def _handle_rate_limit(self, response: requests.Response) -> None:
        """
        Handle rate limit response (429 status).
        
        Args:
            response: HTTP response with 429 status
            
        Raises:
            RateLimitError: With retry_after information
        """
        rate_info = self._parse_rate_limit_headers(response)
        retry_after = rate_info.retry_after
        
        if retry_after is None:
            try:
                data = response.json()
                retry_after = data.get("retry_after")
            except (json.JSONDecodeError, ValueError):
                pass
        
        raise RateLimitError(
            "Rate limit exceeded. Please wait before making more requests.",
            retry_after=retry_after
        )
    
    def _parse_api_error(self, response: requests.Response) -> APIError:
        """
        Parse error details from API response.
        
        Args:
            response: HTTP response with error status
            
        Returns:
            APIError with parsed details
        """
        try:
            data = response.json()
            error_msg = data.get("error", {}).get("message", response.text)
            error_details = data.get("error", {})
        except (json.JSONDecodeError, ValueError):
            error_msg = response.text or f"HTTP {response.status_code}"
            error_details = {}
        
        return APIError(
            message=error_msg,
            status_code=response.status_code,
            error_details=error_details
        )
    
    def _parse_sse_line(self, line: str) -> Optional[dict]:
        """
        Parse a Server-Sent Events line.
        
        Args:
            line: A single line from SSE stream
            
        Returns:
            Parsed JSON data or None if not a data line
        """
        line = line.strip()
        
        if not line:
            return None
        
        if line.startswith("data: "):
            data_str = line[6:]
            
            if data_str == "[DONE]":
                return {"done": True}
            
            try:
                return json.loads(data_str)
            except json.JSONDecodeError:
                return None
        
        return None
    
    def _stream_response(
        self, 
        response: requests.Response,
        include_thinking: bool = False
    ) -> Iterator[Union[str, Dict[str, str]]]:
        """
        Stream and parse SSE response chunks.
        
        Args:
            response: HTTP response with streaming content
            include_thinking: If True, yield thinking content separately
            
        Yields:
            If include_thinking=False: Content strings from each chunk
            If include_thinking=True: Dicts with 'type' ('thinking' or 'content') and 'text' keys
        """
        # Force UTF-8 encoding for response
        response.encoding = 'utf-8'
        
        for line in response.iter_lines():
            if line:
                if isinstance(line, bytes):
                    line = line.decode('utf-8', errors='replace')
                
                parsed = self._parse_sse_line(line)
                if parsed:
                    if parsed.get("done"):
                        break
                    
                    choices = parsed.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        
                        thinking = delta.get("thinking")
                        if thinking and include_thinking:
                            yield {"type": "thinking", "text": thinking}
                        
                        content = delta.get("content")
                        if content:
                            if include_thinking:
                                yield {"type": "content", "text": content}
                            else:
                                yield content
    
    def chat_completion(
        self,
        messages: List[Union[Dict[str, str], ChatMessage]],
        model: str,
        stream: bool = True,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        thinking: Optional[Union[ThinkingConfig, Dict[str, Any]]] = None,
        **kwargs
    ) -> Union[Iterator[Union[str, Dict[str, str]]], Dict[str, Any]]:
        """
        Send a chat completion request to Lora Code API.
        
        Args:
            messages: List of chat messages (dicts or ChatMessage objects)
            model: Model ID to use
            stream: Whether to stream the response (default: True)
            temperature: Sampling temperature (optional)
            max_tokens: Maximum tokens to generate (optional)
            thinking: Thinking/extended reasoning configuration (optional)
                     Can be ThinkingConfig object or dict with 'enabled' and 'budget' keys
            **kwargs: Additional parameters to pass to the API
            
        Returns:
            If stream=True: Iterator yielding content strings (or dicts if thinking enabled)
            If stream=False: Dict with full response including 'thinking' field if enabled
            
        Raises:
            AuthenticationError: If not authenticated
            RateLimitError: If rate limited
            APIError: If API returns an error
            LoraCodeClientError: If request fails
        """
        formatted_messages = []
        for msg in messages:
            if isinstance(msg, ChatMessage):
                formatted_messages.append(msg.to_dict())
            else:
                formatted_messages.append(msg)
        
        payload = {
            "model": model,
            "messages": formatted_messages,
            "stream": stream,
        }
        
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        
        include_thinking = False
        if thinking is not None:
            if isinstance(thinking, ThinkingConfig):
                thinking_dict = thinking.to_dict()
            elif isinstance(thinking, dict):
                thinking_dict = thinking
            else:
                thinking_dict = {}
            
            if thinking_dict:
                payload["thinking"] = thinking_dict.get("thinking", thinking_dict)
                include_thinking = thinking_dict.get("thinking", {}).get("enabled", False) or \
                                   thinking_dict.get("enabled", False)
        
        payload.update(kwargs)
        
        response = self._make_request(
            "POST",
            "/v1/chat/completions",
            json=payload,
            stream=stream,
            timeout=120 if stream else 60
        )
        
        if response.status_code == 429:
            self._handle_rate_limit(response)
        
        if response.status_code >= 400:
            raise self._parse_api_error(response)
        
        if stream:
            return self._stream_response(response, include_thinking=include_thinking)
        else:
            return response.json()
    
    def chat_completion_with_retry(
        self,
        messages: List[Union[Dict[str, str], ChatMessage]],
        model: str,
        stream: bool = True,
        max_retries: int = 3,
        **kwargs
    ) -> Union[Iterator[str], Dict[str, Any]]:
        """
        Send a chat completion request with automatic retry on rate limits.
        
        Args:
            messages: List of chat messages
            model: Model ID to use
            stream: Whether to stream the response
            max_retries: Maximum number of retries on rate limit
            **kwargs: Additional parameters
            
        Returns:
            Same as chat_completion
            
        Raises:
            RateLimitError: If rate limited after all retries
            Other exceptions from chat_completion
        """
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                return self.chat_completion(
                    messages=messages,
                    model=model,
                    stream=stream,
                    **kwargs
                )
            except RateLimitError as e:
                last_error = e
                if attempt < max_retries:
                    wait_time = e.retry_after or (2 ** attempt)
                    time.sleep(min(wait_time, 60))
                else:
                    raise
        
        if last_error:
            raise last_error
