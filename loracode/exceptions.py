from dataclasses import dataclass

from loracode.dump import dump


@dataclass
class ExInfo:
    name: str
    retry: bool
    description: str


EXCEPTIONS = [
    ExInfo("APIConnectionError", True, None),
    ExInfo("APIError", True, None),
    ExInfo("APIResponseValidationError", True, None),
    ExInfo(
        "AuthenticationError",
        False,
        "The API provider is not able to authenticate you. Check your API key.",
    ),
    ExInfo("BadGatewayError", True, "The API provider's servers are down or overloaded."),
    ExInfo("BadRequestError", False, None),
    ExInfo("BudgetExceededError", True, None),
    ExInfo(
        "ContentPolicyViolationError",
        True,
        "The API provider has refused the request due to a safety policy about the content.",
    ),
    ExInfo("ContextWindowExceededError", False, None),
    ExInfo("ErrorEventError", True, None),
    ExInfo("ImageFetchError", False, "The API provider was unable to fetch one or more images."),
    ExInfo("InternalServerError", True, "The API provider's servers are down or overloaded."),
    ExInfo("InvalidRequestError", True, None),
    ExInfo("JSONSchemaValidationError", True, None),
    ExInfo("NotFoundError", False, None),
    ExInfo(
        "RateLimitError",
        True,
        "The API provider has rate limited you. Try again later or check your quotas.",
    ),
    ExInfo("RouterRateLimitError", True, None),
    ExInfo("ServiceUnavailableError", True, "The API provider's servers are down or overloaded."),
    ExInfo("UnprocessableEntityError", True, None),
    ExInfo("UnsupportedParamsError", True, None),
    ExInfo(
        "Timeout",
        True,
        "The API provider timed out without returning a response. They may be down or overloaded.",
    ),
]


class LiteLLMExceptions:
    exceptions = dict()
    exception_info = {exi.name: exi for exi in EXCEPTIONS}

    def __init__(self):
        self._load()

    def _load(self, strict=False):
        """Load exception classes from loracode.llm module."""
        from loracode.llm import litellm

        exception_classes = {
            "RateLimitError": litellm.RateLimitError,
            "AuthenticationError": litellm.AuthenticationError,
            "APIConnectionError": litellm.APIConnectionError,
            "APIError": litellm.APIError,
            "NotFoundError": litellm.NotFoundError,
            "ContextWindowExceededError": litellm.ContextWindowExceededError,
            "BadRequestError": litellm.BadRequestError,
            "ServiceUnavailableError": litellm.ServiceUnavailableError,
            "InternalServerError": litellm.InternalServerError,
            "Timeout": litellm.Timeout,
        }

        for name, ex_class in exception_classes.items():
            if name in self.exception_info:
                self.exceptions[ex_class] = self.exception_info[name]

    def exceptions_tuple(self):
        return tuple(self.exceptions.keys())

    def get_ex_info(self, ex):
        from loracode.llm import litellm

        if ex.__class__ is litellm.APIConnectionError:
            if "google.auth" in str(ex):
                return ExInfo(
                    "APIConnectionError", False, "You need to: pip install google-generativeai"
                )
            if "boto3" in str(ex):
                return ExInfo("APIConnectionError", False, "You need to: pip install boto3")

        if ex.__class__ is litellm.APIError:
            err_str = str(ex).lower()
            if "insufficient credits" in err_str and '"code":402' in err_str:
                return ExInfo(
                    "APIError",
                    False,
                    "Insufficient credits with the API provider. Please add credits.",
                )

        return self.exceptions.get(ex.__class__, ExInfo(None, None, None))
