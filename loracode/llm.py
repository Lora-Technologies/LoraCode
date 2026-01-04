"""
Lora Code LLM module.

This module provides the interface for LLM completions using Lora Code API.
The litellm dependency has been removed in favor of direct Lora Code API integration.
"""
import os

from loracode.dump import dump  # noqa: F401

LORACODE_SITE_URL = "https://loratech.dev"
LORACODE_APP_NAME = "LoraCode"

os.environ["OR_SITE_URL"] = LORACODE_SITE_URL
os.environ["OR_APP_NAME"] = LORACODE_APP_NAME

VERBOSE = False


class LoraCodeLLM:
    """
    Lora Code LLM interface.
    
    This class provides a compatible interface for LLM completions
    using the Lora Code API instead of litellm.
    """
    _client = None

    def __init__(self):
        self._client = None

    def _get_client(self):
        """Get or create the Lora Code client."""
        if self._client is None:
            try:
                from loracode.lora_code_client import LoraCodeClient
                self._client = LoraCodeClient()
            except Exception:
                pass
        return self._client

    def completion(self, model, messages, stream=True, **kwargs):
        """
        Send a completion request to Lora Code API.
        
        Args:
            model: The model name to use
            messages: List of message dictionaries
            stream: Whether to stream the response
            **kwargs: Additional parameters
            
        Returns:
            Response object compatible with litellm response format
        """
        client = self._get_client()
        if client is None:
            raise Exception("Lora Code client not available. Please authenticate first.")
        
        temperature = kwargs.get("temperature", 0)
        
        if stream:
            return client.chat_completion(
                messages=messages,
                model=model,
                stream=True,
                temperature=temperature
            )
        else:
            return client.chat_completion(
                messages=messages,
                model=model,
                stream=False,
                temperature=temperature
            )

    def completion_cost(self, completion_response):
        """
        Calculate the cost of a completion.
        
        For Lora Code API, cost calculation is handled server-side.
        This method returns 0 as a placeholder.
        """
        return 0

    def transcription(self, model, file, prompt=None, language=None, **kwargs):
        """
        Transcribe audio using speech-to-text.
        
        Note: This is a placeholder for compatibility. Lora Code API may not
        support transcription directly. Falls back to raising an error.
        
        Args:
            model: The model to use (e.g., "whisper-1")
            file: Audio file object
            prompt: Optional prompt for context
            language: Optional language code
            **kwargs: Additional parameters
            
        Returns:
            Transcription response object
            
        Raises:
            OpenAIError: If transcription is not supported
        """
        raise self.OpenAIError(
            "Transcription is not currently supported by Lora Code API. "
            "Please use OpenAI API directly for voice transcription."
        )

    class RateLimitError(Exception):
        """Rate limit exceeded error."""
        def __init__(self, message="Rate limit exceeded", llm_provider=None, model=None, response=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            self.response = response
            super().__init__(message)

    class AuthenticationError(Exception):
        """Authentication error."""
        def __init__(self, message="Authentication failed", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    class APIConnectionError(Exception):
        """API connection error."""
        def __init__(self, message="Connection failed", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    class APIError(Exception):
        """General API error."""
        def __init__(self, message="API error", llm_provider=None, model=None, status_code=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            self.status_code = status_code
            super().__init__(message)

    class NotFoundError(Exception):
        """Resource not found error."""
        def __init__(self, message="Not found", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    class ContextWindowExceededError(Exception):
        """Context window exceeded error."""
        def __init__(self, message="Context window exceeded", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    class BadRequestError(Exception):
        """Bad request error."""
        def __init__(self, message="Bad request", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    class ServiceUnavailableError(Exception):
        """Service unavailable error."""
        def __init__(self, message="Service unavailable", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    class InternalServerError(Exception):
        """Internal server error."""
        def __init__(self, message="Internal server error", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    class Timeout(Exception):
        """Timeout error."""
        def __init__(self, message="Request timed out", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    class OpenAIError(Exception):
        """OpenAI-compatible error for voice/whisper operations."""
        def __init__(self, message="OpenAI error", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    @property
    def model_cost(self):
        """
        Return a dict-like object with model IDs as keys for compatibility.
        
        This provides compatibility with code that accesses litellm.model_cost.keys()
        for model autocompletion.
        """
        try:
            client = self._get_client()
            if client:
                model_ids = client.get_model_ids()
                return {model_id: {} for model_id in model_ids}
        except Exception:
            pass
        return {}


litellm = LoraCodeLLM()

__all__ = ["litellm", "LoraCodeLLM"]
