import os

from loracode.dump import dump  # noqa: F401

LORACODE_SITE_URL = "https://loratech.dev"
LORACODE_APP_NAME = "LoraCode"

os.environ["OR_SITE_URL"] = LORACODE_SITE_URL
os.environ["OR_APP_NAME"] = LORACODE_APP_NAME

VERBOSE = False


class LoraCodeLLM:
    _client = None

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from loracode.lora_code_client import LoraCodeClient
                self._client = LoraCodeClient()
            except Exception:
                pass
        return self._client

    def completion(self, model, messages, stream=True, **kwargs):
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
        return 0

    def transcription(self, model, file, prompt=None, language=None, **kwargs):
        raise self.OpenAIError(
            "Transcription is not currently supported by Lora Code API. "
            "Please use OpenAI API directly for voice transcription."
        )

    class RateLimitError(Exception):
        def __init__(self, message="Rate limit exceeded", llm_provider=None, model=None, response=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            self.response = response
            super().__init__(message)

    class AuthenticationError(Exception):
        def __init__(self, message="Authentication failed", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    class APIConnectionError(Exception):
        def __init__(self, message="Connection failed", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    class APIError(Exception):
        def __init__(self, message="API error", llm_provider=None, model=None, status_code=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            self.status_code = status_code
            super().__init__(message)

    class NotFoundError(Exception):
        def __init__(self, message="Not found", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    class ContextWindowExceededError(Exception):
        def __init__(self, message="Context window exceeded", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    class BadRequestError(Exception):
        def __init__(self, message="Bad request", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    class ServiceUnavailableError(Exception):
        def __init__(self, message="Service unavailable", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    class InternalServerError(Exception):
        def __init__(self, message="Internal server error", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    class Timeout(Exception):
        def __init__(self, message="Request timed out", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    class OpenAIError(Exception):
        def __init__(self, message="OpenAI error", llm_provider=None, model=None):
            self.message = message
            self.llm_provider = llm_provider
            self.model = model
            super().__init__(message)

    @property
    def model_cost(self):
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
