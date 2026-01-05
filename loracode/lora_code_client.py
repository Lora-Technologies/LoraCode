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
class ModelCapabilities:
    chat: bool = True
    embedding: bool = False
    image_generation: bool = False
    tools: bool = False
    web_search: bool = False
    url_context: bool = False
    thinking: bool = False


@dataclass
class ModelInfo:
    id: str
    name: str
    description: str
    context_length: int
    owned_by: str
    capabilities: ModelCapabilities = None
    
    def __post_init__(self):
        if self.capabilities is None:
            self.capabilities = ModelCapabilities()
    
    @property
    def supports_thinking(self) -> bool:
        return self.capabilities.thinking if self.capabilities else False


class LoraCodeClientError(Exception):
    pass


class URLValidationError(LoraCodeClientError):
    pass


class AuthenticationError(LoraCodeClientError):
    pass


class ModelNotFoundError(LoraCodeClientError):
    pass


class RateLimitError(LoraCodeClientError):
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class APIError(LoraCodeClientError):
    def __init__(self, message: str, status_code: int, error_details: Optional[dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_details = error_details or {}


@dataclass
class ChatMessage:
    role: str
    content: str
    
    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class ThinkingConfig:
    enabled: bool = False
    budget: int = 10000
    
    def to_dict(self) -> dict:
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
    limit: Optional[int] = None
    remaining: Optional[int] = None
    reset: Optional[float] = None
    retry_after: Optional[float] = None
    
    @classmethod
    def from_headers(cls, headers: dict) -> "RateLimitInfo":
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
    DEFAULT_API_BASE = "https://api.loratech.dev"
    
    def __init__(
        self,
        api_base: str = None,
        api_key: str = None,
        auth: LoraCodeAuth = None
    ):
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
        if self._models_cache is not None and not force_refresh:
            return self._models_cache
        
        response = self._make_request("GET", "/v1/models")
        response.raise_for_status()
        
        data = response.json()
        models = []
        
        for model_data in data.get("data", []):
            caps_data = model_data.get("capabilities", {})
            capabilities = ModelCapabilities(
                chat=caps_data.get("chat", True),
                embedding=caps_data.get("embedding", False),
                image_generation=caps_data.get("image_generation", False),
                tools=caps_data.get("tools", False),
                web_search=caps_data.get("web_search", False),
                url_context=caps_data.get("url_context", False),
                thinking=caps_data.get("thinking", False),
            )
            
            model = ModelInfo(
                id=model_data.get("id", ""),
                name=model_data.get("id", ""),
                description=model_data.get("description", ""),
                context_length=model_data.get("context_length", 0),
                owned_by=model_data.get("owned_by", "lora-code"),
                capabilities=capabilities,
            )
            models.append(model)
        
        self._models_cache = models
        return models
    
    def validate_model(self, model_id: str) -> ModelInfo:
        models = self.list_models()
        
        for model in models:
            if model.id == model_id:
                return model
        
        available = [m.id for m in models]
        raise ModelNotFoundError(
            f"Model '{model_id}' not found. Available models: {', '.join(available)}"
        )
    
    def get_model_ids(self) -> List[str]:
        models = self.list_models()
        return [m.id for m in models]
    
    def is_authenticated(self) -> bool:
        try:
            self._get_auth_header()
            return True
        except AuthenticationError:
            return False
    
    def get_user_info(self) -> dict:
        response = self._make_request("GET", "/v1/me")
        response.raise_for_status()
        return response.json()
    
    def clear_cache(self) -> None:
        self._models_cache = None
    
    def _parse_rate_limit_headers(self, response: requests.Response) -> RateLimitInfo:
        return RateLimitInfo.from_headers(response.headers)
    
    def _handle_rate_limit(self, response: requests.Response) -> None:
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
