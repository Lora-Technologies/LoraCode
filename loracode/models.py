import difflib
import hashlib
import importlib.resources
import json
import math
import os
import platform
import sys
import time
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import json5
import yaml
from PIL import Image

from loracode import __version__
from loracode.dump import dump 
from loracode.i18n import t
from loracode.sendchat import ensure_alternating_roles, sanity_check_messages
from loracode.utils import check_pip_install_extra

RETRY_TIMEOUT = 60

request_timeout = 600

DEFAULT_MODEL_NAME = "lora-code-v1"

LORA_CODE_MODELS = []

MODEL_ALIASES = {
    "lora": "lora-code-v1",
    "lora-v1": "lora-code-v1",
    "default": "lora-code-v1",
}


class LoraCodeMessage:
    def __init__(self, content, thinking=None):
        self.content = content
        self.thinking = thinking
        self.role = "assistant"


class LoraCodeChoice:
    def __init__(self, message_content, thinking=None):
        self.message = LoraCodeMessage(message_content, thinking)
        self.delta = LoraCodeMessage(message_content, thinking)
        self.finish_reason = "stop"


class LoraCodeResponse:
    def __init__(self, response_data):
        self._data = response_data
        content = ""
        thinking = None
        if isinstance(response_data, dict):
            choices = response_data.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                content = message.get("content", "")
                thinking = message.get("thinking")
        self.choices = [LoraCodeChoice(content, thinking)]

    def __iter__(self):
        return iter([self])


class LoraCodeStreamResponse:
    def __init__(self, response_iter, include_thinking=False):
        self._iter = response_iter
        self._content_buffer = []
        self._thinking_buffer = []
        self._include_thinking = include_thinking
        self.choices = []

    def __iter__(self):
        for chunk in self._iter:
            if isinstance(chunk, dict):
                chunk_type = chunk.get("type")
                text = chunk.get("text", "")
                if chunk_type == "thinking":
                    self._thinking_buffer.append(text)
                    yield LoraCodeStreamChunk(text, is_thinking=True)
                elif chunk_type == "content":
                    self._content_buffer.append(text)
                    yield LoraCodeStreamChunk(text, is_thinking=False)
            else:
                self._content_buffer.append(chunk)
                yield LoraCodeStreamChunk(chunk, is_thinking=False)
        
        full_content = "".join(self._content_buffer)
        full_thinking = "".join(self._thinking_buffer) if self._thinking_buffer else None
        self.choices = [LoraCodeChoice(full_content, full_thinking)]


class LoraCodeStreamChunk:
    def __init__(self, content, is_thinking=False):
        self.choices = [LoraCodeStreamChoice(content, is_thinking)]


class LoraCodeStreamChoice:
    def __init__(self, content, is_thinking=False):
        self.delta = LoraCodeDelta(content, is_thinking)
        self.finish_reason = None


class LoraCodeDelta:
    def __init__(self, content, is_thinking=False):
        self.content = content if not is_thinking else None
        self.thinking = content if is_thinking else None




@dataclass
class ModelSettings:
    name: str
    edit_format: str = "whole"
    weak_model_name: Optional[str] = None
    use_repo_map: bool = False
    send_undo_reply: bool = False
    lazy: bool = False
    overeager: bool = False
    reminder: str = "user"
    examples_as_sys_msg: bool = False
    extra_params: Optional[dict] = None
    cache_control: bool = False
    caches_by_default: bool = False
    use_system_prompt: bool = True
    use_temperature: Union[bool, float] = True
    streaming: bool = True
    editor_model_name: Optional[str] = None
    editor_edit_format: Optional[str] = None
    reasoning_tag: Optional[str] = None
    remove_reasoning: Optional[str] = None
    system_prompt_prefix: Optional[str] = None
    accepts_settings: Optional[list] = None


MODEL_SETTINGS = []
with importlib.resources.open_text("loracode.resources", "model-settings.yml") as f:
    model_settings_list = yaml.safe_load(f)
    for model_settings_dict in model_settings_list:
        MODEL_SETTINGS.append(ModelSettings(**model_settings_dict))


class LoraCodeModelInfoManager:
    CACHE_TTL = 60 * 60 * 24

    def __init__(self):
        self.cache_dir = Path.home() / ".loracode" / "caches"
        self.cache_file = self.cache_dir / "lora_code_models.json"
        self.content = None
        self.local_model_metadata = {}
        self.verify_ssl = True
        self._cache_loaded = False
        self._lora_code_client = None

    def set_verify_ssl(self, verify_ssl):
        self.verify_ssl = verify_ssl

    def _get_client(self):
        if self._lora_code_client is None:
            try:
                from loracode.lora_code_client import LoraCodeClient
                self._lora_code_client = LoraCodeClient()
            except Exception:
                pass
        return self._lora_code_client

    def _load_cache(self):
        if self._cache_loaded:
            return

        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            if self.cache_file.exists():
                cache_age = time.time() - self.cache_file.stat().st_mtime
                if cache_age < self.CACHE_TTL:
                    try:
                        self.content = json.loads(self.cache_file.read_text())
                    except json.JSONDecodeError:
                        self.content = None
        except OSError:
            pass

        self._cache_loaded = True

    def _update_cache(self):
        try:
            client = self._get_client()
            if client:
                models = client.list_models(force_refresh=True)
                self.content = {}
                for model in models:
                    self.content[model.id] = {
                        "max_input_tokens": model.context_length,
                        "max_tokens": model.context_length,
                        "max_output_tokens": model.context_length,
                        "mode": "chat",
                        "lora_code_provider": model.owned_by,
                    }
                try:
                    self.cache_file.write_text(json.dumps(self.content, indent=4))
                except OSError:
                    pass
        except Exception as ex:
            print(t("model.fetch_error", error=ex))
            try:
                self.cache_file.write_text("{}")
            except OSError:
                pass

    def get_model_from_cached_json_db(self, model):
        data = self.local_model_metadata.get(model)
        if data:
            return data

        self._load_cache()

        if not self.content:
            self._update_cache()

        if not self.content:
            return dict()

        return self.content.get(model, dict())

    def get_model_info(self, model):
        cached_info = self.get_model_from_cached_json_db(model)
        if cached_info:
            return cached_info

        self._update_cache()
        return self.get_model_from_cached_json_db(model)


model_info_manager = LoraCodeModelInfoManager()


class LoraCodeModel:    
    def __init__(self, model_id: str, client=None):
        self.name = model_id
        self._client = client
        self._info = None
    
    @property
    def client(self):
        if self._client is None:
            try:
                from loracode.lora_code_client import LoraCodeClient
                self._client = LoraCodeClient()
            except Exception:
                pass
        return self._client
    
    @property
    def info(self) -> dict:
        if self._info is None:
            self._info = self._fetch_model_info()
        return self._info
    
    def _fetch_model_info(self) -> dict:
        if self.client is None:
            return {}
        
        try:
            models = self.client.list_models()
            for model in models:
                if model.id == self.name:
                    return {
                        "id": model.id,
                        "name": model.name,
                        "description": model.description,
                        "context_length": model.context_length,
                        "max_input_tokens": model.context_length,
                        "max_tokens": model.context_length,
                        "owned_by": model.owned_by,
                    }
        except Exception:
            pass
        
        return {}
    
    def is_valid(self) -> bool:
        return bool(self.info)
    
    def get_context_length(self) -> int:
        return self.info.get("context_length", 0)
    
    def __str__(self):
        return self.name
    
    def __repr__(self):
        return f"LoraCodeModel({self.name!r})"


class Model(ModelSettings):
    def __init__(
        self, model, weak_model=None, editor_model=None, editor_edit_format=None, verbose=False
    ):
        model = MODEL_ALIASES.get(model, model)

        self.name = model
        self.verbose = verbose

        self.max_chat_history_tokens = 1024
        self.weak_model = None
        self.editor_model = None

        self.extra_model_settings = next(
            (ms for ms in MODEL_SETTINGS if ms.name == "loracode/extra_params"), None
        )

        self.info = self.get_model_info(model)

        res = self.validate_environment()
        self.missing_keys = res.get("missing_keys")
        self.keys_in_environment = res.get("keys_in_environment")

        max_input_tokens = self.info.get("max_input_tokens") or 0
        self.max_chat_history_tokens = min(max(max_input_tokens / 16, 1024), 8192)

        self.configure_model_settings(model)
        if weak_model is False:
            self.weak_model_name = None
        else:
            self.get_weak_model(weak_model)

        if editor_model is False:
            self.editor_model_name = None
        else:
            self.get_editor_model(editor_model, editor_edit_format)

    def get_model_info(self, model):
        return model_info_manager.get_model_info(model)

    def _copy_fields(self, source):
        for field in fields(ModelSettings):
            val = getattr(source, field.name)
            setattr(self, field.name, val)

        if self.reasoning_tag is None and self.remove_reasoning is not None:
            self.reasoning_tag = self.remove_reasoning

    def configure_model_settings(self, model):
        exact_match = False
        for ms in MODEL_SETTINGS:
            if model == ms.name:
                self._copy_fields(ms)
                exact_match = True
                break

        if self.accepts_settings is None:
            self.accepts_settings = []

        model_lower = model.lower()

        if not exact_match:
            self.apply_generic_model_settings(model_lower)

        self._apply_api_capabilities(model)

        if (
            self.extra_model_settings
            and self.extra_model_settings.extra_params
            and self.extra_model_settings.name == "loracode/extra_params"
        ):
            if not self.extra_params:
                self.extra_params = {}

            for key, value in self.extra_model_settings.extra_params.items():
                if isinstance(value, dict) and isinstance(self.extra_params.get(key), dict):
                    self.extra_params[key] = {**self.extra_params[key], **value}
                else:
                    self.extra_params[key] = value

    def _apply_api_capabilities(self, model_name):
        try:
            from loracode.lora_code_client import LoraCodeClient
            client = LoraCodeClient()
            models = client.list_models()
            
            for model_info in models:
                if model_info.id == model_name:
                    if model_info.supports_thinking:
                        if "thinking_tokens" not in self.accepts_settings:
                            self.accepts_settings.append("thinking_tokens")
                        if not self.extra_params or "thinking" not in self.extra_params:
                            self.set_thinking_tokens("8096")
                    break
        except Exception:
            pass

    def apply_generic_model_settings(self, model):
        if "/o3-mini" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.use_temperature = False
            self.system_prompt_prefix = "Formatting re-enabled. "
            return

        if "gpt-4.1-mini" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.reminder = "sys"
            self.examples_as_sys_msg = False
            return

        if "gpt-4.1" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.reminder = "sys"
            self.examples_as_sys_msg = False
            return

        last_segment = model.split("/")[-1]
        if last_segment in ("gpt-5", "gpt-5-2025-08-07"):
            self.use_temperature = False
            self.edit_format = "diff"
            return

        if "/o1-mini" in model:
            self.use_repo_map = True
            self.use_temperature = False
            self.use_system_prompt = False
            return

        if "/o1-preview" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.use_temperature = False
            self.use_system_prompt = False
            return

        if "/o1" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.use_temperature = False
            self.streaming = False
            self.system_prompt_prefix = "Formatting re-enabled. "
            return

        if "deepseek" in model and "v3" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.reminder = "sys"
            self.examples_as_sys_msg = True
            return

        if "deepseek" in model and ("r1" in model or "reasoning" in model):
            self.edit_format = "diff"
            self.use_repo_map = True
            self.examples_as_sys_msg = True
            self.use_temperature = False
            self.reasoning_tag = "think"
            return

        if ("llama3" in model or "llama-3" in model) and "70b" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.send_undo_reply = True
            self.examples_as_sys_msg = True
            return

        if "gpt-4-turbo" in model or ("gpt-4-" in model and "-preview" in model):
            self.edit_format = "udiff"
            self.use_repo_map = True
            self.send_undo_reply = True
            return

        if "gpt-4" in model or "claude-3-opus" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.send_undo_reply = True
            return

        if "gpt-3.5" in model or "gpt-4" in model:
            self.reminder = "sys"
            return

        if "3-7-sonnet" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.examples_as_sys_msg = True
            self.reminder = "user"
            if "thinking_tokens" not in self.accepts_settings:
                self.accepts_settings.append("thinking_tokens")
            return

        if "3.5-sonnet" in model or "3-5-sonnet" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.examples_as_sys_msg = True
            self.reminder = "user"
            if "thinking_tokens" not in self.accepts_settings:
                self.accepts_settings.append("thinking_tokens")
            return

        if "claude-4" in model or "sonnet-4" in model or "claude-sonnet-4" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.examples_as_sys_msg = True
            if "thinking_tokens" not in self.accepts_settings:
                self.accepts_settings.append("thinking_tokens")
            return

        if "claude-3-opus" in model or "3-opus" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.send_undo_reply = True
            if "thinking_tokens" not in self.accepts_settings:
                self.accepts_settings.append("thinking_tokens")
            return

        if "gemini-2.5" in model or "gemini-2-5" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            if "thinking_tokens" not in self.accepts_settings:
                self.accepts_settings.append("thinking_tokens")
            return

        if "gemini-3" in model or "gemini3" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            if "thinking_tokens" not in self.accepts_settings:
                self.accepts_settings.append("thinking_tokens")
            return

        if model.startswith("o1-") or "/o1-" in model:
            self.use_system_prompt = False
            self.use_temperature = False
            return

        if (
            "qwen" in model
            and "coder" in model
            and ("2.5" in model or "2-5" in model)
            and "32b" in model
        ):
            self.edit_format = "diff"
            self.editor_edit_format = "editor-diff"
            self.use_repo_map = True
            return

        if "qwq" in model and "32b" in model and "preview" not in model:
            self.edit_format = "diff"
            self.editor_edit_format = "editor-diff"
            self.use_repo_map = True
            self.reasoning_tag = "think"
            self.examples_as_sys_msg = True
            self.use_temperature = 0.6
            self.extra_params = dict(top_p=0.95)
            return

        if "qwen3" in model and "235b" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.system_prompt_prefix = "/no_think"
            self.use_temperature = 0.7
            self.extra_params = {"top_p": 0.8, "top_k": 20, "min_p": 0.0}
            return

        if self.edit_format == "diff":
            self.use_repo_map = True
            return

    def __str__(self):
        return self.name

    def get_weak_model(self, provided_weak_model_name):
        if provided_weak_model_name:
            self.weak_model_name = provided_weak_model_name

        if not self.weak_model_name:
            self.weak_model = self
            return

        if self.weak_model_name == self.name:
            self.weak_model = self
            return

        self.weak_model = Model(
            self.weak_model_name,
            weak_model=False,
        )
        return self.weak_model

    def commit_message_models(self):
        return [self.weak_model, self]

    def get_editor_model(self, provided_editor_model_name, editor_edit_format):
        if provided_editor_model_name:
            self.editor_model_name = provided_editor_model_name
        if editor_edit_format:
            self.editor_edit_format = editor_edit_format

        if not self.editor_model_name or self.editor_model_name == self.name:
            self.editor_model = self
        else:
            self.editor_model = Model(
                self.editor_model_name,
                editor_model=False,
            )

        if not self.editor_edit_format:
            self.editor_edit_format = self.editor_model.edit_format
            if self.editor_edit_format in ("diff", "whole", "diff-fenced"):
                self.editor_edit_format = "editor-" + self.editor_edit_format

        return self.editor_model

    def tokenizer(self, text):
        if isinstance(text, str):
            return len(text) // 4
        return 0

    def token_count(self, messages):
        if type(messages) is list:
            try:
                total = 0
                for msg in messages:
                    if isinstance(msg, dict):
                        content = msg.get("content", "")
                        if isinstance(content, str):
                            total += len(content) // 4
                    elif isinstance(msg, str):
                        total += len(msg) // 4
                return total
            except Exception as err:
                print(t("model.token_count_error", error=err))
                return 0

        if type(messages) is str:
            msgs = messages
        else:
            msgs = json.dumps(messages)

        try:
            return len(msgs) // 4
        except Exception as err:
            print(t("model.token_count_error", error=err))
            return 0

    def token_count_for_image(self, fname):
        width, height = self.get_image_size(fname)

        max_dimension = max(width, height)
        if max_dimension > 2048:
            scale_factor = 2048 / max_dimension
            width = int(width * scale_factor)
            height = int(height * scale_factor)

        min_dimension = min(width, height)
        scale_factor = 768 / min_dimension
        width = int(width * scale_factor)
        height = int(height * scale_factor)

        tiles_width = math.ceil(width / 512)
        tiles_height = math.ceil(height / 512)
        num_tiles = tiles_width * tiles_height

        token_cost = num_tiles * 170 + 85
        return token_cost

    def get_image_size(self, fname):
        with Image.open(fname) as img:
            return img.size

    def fast_validate_environment(self):
        if os.environ.get("LORA_CODE_API_KEY"):
            return dict(keys_in_environment=["LORA_CODE_API_KEY"], missing_keys=[])
        
        try:
            from loracode.lora_code_auth import LoraCodeAuth
            auth = LoraCodeAuth()
            if auth.is_authenticated():
                return dict(keys_in_environment=["LORA_CODE_CREDENTIALS"], missing_keys=[])
        except Exception:
            pass
        
        return None

    def validate_environment(self):
        res = self.fast_validate_environment()
        if res:
            return res

        return dict(
            keys_in_environment=False,
            missing_keys=["LORA_CODE_API_KEY"]
        )

    def get_repo_map_tokens(self):
        map_tokens = 1024
        max_inp_tokens = self.info.get("max_input_tokens")
        if max_inp_tokens:
            map_tokens = max_inp_tokens / 8
            map_tokens = min(map_tokens, 4096)
            map_tokens = max(map_tokens, 1024)
        return map_tokens

    def parse_token_value(self, value):
        if isinstance(value, int):
            return value

        if not isinstance(value, str):
            return int(value)

        value = value.strip().upper()

        if value.endswith("K"):
            multiplier = 1024
            value = value[:-1]
        elif value.endswith("M"):
            multiplier = 1024 * 1024
            value = value[:-1]
        else:
            multiplier = 1

        return int(float(value) * multiplier)

    def set_thinking_tokens(self, value):
        if value is not None:
            num_tokens = self.parse_token_value(value)
            self.use_temperature = False
            if not self.extra_params:
                self.extra_params = {}

            if num_tokens > 0:
                self.extra_params["thinking"] = {"type": "enabled", "budget_tokens": num_tokens}
            else:
                if "thinking" in self.extra_params:
                    del self.extra_params["thinking"]

    def get_raw_thinking_tokens(self):
        budget = None

        if self.extra_params:
            if "thinking" in self.extra_params:
                thinking = self.extra_params["thinking"]
                if isinstance(thinking, dict):
                    if "budget_tokens" in thinking:
                        budget = thinking["budget_tokens"]
                    elif "budget" in thinking:
                        budget = thinking["budget"]

        return budget

    def get_thinking_tokens(self):
        budget = self.get_raw_thinking_tokens()

        if budget is not None:
            if budget >= 1024 * 1024:
                value = budget / (1024 * 1024)
                if value == int(value):
                    return f"{int(value)}M"
                else:
                    return f"{value:.1f}M"
            else:
                value = budget / 1024
                if value == int(value):
                    return f"{int(value)}k"
                else:
                    return f"{value:.1f}k"
        return None

    def is_deepseek_r1(self):
        name = self.name.lower()
        if "deepseek" not in name:
            return
        return "r1" in name or "reasoner" in name

    def is_ollama(self):
        return self.name.startswith("ollama/") or self.name.startswith("ollama_chat/")

    def _get_lora_code_client(self):
        if not hasattr(self, '_lora_client') or self._lora_client is None:
            try:
                from loracode.main import get_lora_code_client
                self._lora_client = get_lora_code_client()
            except Exception:
                try:
                    from loracode.lora_code_client import LoraCodeClient
                    from loracode.lora_code_auth import LoraCodeAuth
                    import os
                    
                    api_base = os.environ.get("LORA_CODE_API_BASE")
                    api_key = os.environ.get("LORA_CODE_API_KEY")
                    auth = LoraCodeAuth(api_base=api_base)
                    
                    self._lora_client = LoraCodeClient(
                        api_base=api_base,
                        api_key=api_key,
                        auth=auth
                    )
                except Exception:
                    self._lora_client = None
        return self._lora_client

    def send_completion(self, messages, functions, stream, temperature=None):
        if os.environ.get("LORACODE_SANITY_CHECK_TURNS"):
            sanity_check_messages(messages)

        if self.is_deepseek_r1():
            messages = ensure_alternating_roles(messages)

        kwargs = dict(
            model=self.name,
            stream=stream,
        )

        if self.use_temperature is not False:
            if temperature is None:
                if isinstance(self.use_temperature, bool):
                    temperature = 0
                else:
                    temperature = float(self.use_temperature)

            kwargs["temperature"] = temperature

        if self.extra_params:
            kwargs.update(self.extra_params)

        key = json.dumps(kwargs, sort_keys=True).encode()
        hash_object = hashlib.sha1(key)

        if self.verbose:
            dump(kwargs)

        client = self._get_lora_code_client()
        if client is None:
            raise Exception(t("model.client_unavailable"))

        thinking_config = None
        include_thinking = False
        if self.extra_params and "thinking" in self.extra_params:
            thinking_param = self.extra_params["thinking"]
            if isinstance(thinking_param, dict):
                if thinking_param.get("type") == "enabled":
                    budget = thinking_param.get("budget_tokens", 10000)
                    thinking_config = {"enabled": True, "budget": budget}
                    include_thinking = True
                elif thinking_param.get("enabled"):
                    thinking_config = thinking_param
                    include_thinking = True

        try:
            if stream:
                response_iter = client.chat_completion(
                    messages=messages,
                    model=self.name,
                    stream=True,
                    temperature=kwargs.get("temperature"),
                    max_tokens=kwargs.get("max_tokens"),
                    thinking=thinking_config,
                )
                return hash_object, LoraCodeStreamResponse(response_iter, include_thinking=include_thinking)
            else:
                response = client.chat_completion(
                    messages=messages,
                    model=self.name,
                    stream=False,
                    temperature=kwargs.get("temperature"),
                    max_tokens=kwargs.get("max_tokens"),
                    thinking=thinking_config,
                )
                return hash_object, LoraCodeResponse(response)
        except Exception as e:
            raise Exception(t("model.api_error_generic", error=e))

    def simple_send_with_retries(self, messages):
        if "deepseek-reasoner" in self.name:
            messages = ensure_alternating_roles(messages)
        retry_delay = 0.125

        if self.verbose:
            dump(messages)

        while True:
            try:
                kwargs = {
                    "messages": messages,
                    "functions": None,
                    "stream": False,
                }

                _hash, response = self.send_completion(**kwargs)
                if not response or not hasattr(response, "choices") or not response.choices:
                    return None
                res = response.choices[0].message.content
                from loracode.reasoning_tags import remove_reasoning_content

                return remove_reasoning_content(res, self.reasoning_tag)

            except Exception as err:
                print(str(err))
                retry_delay *= 2
                if retry_delay > RETRY_TIMEOUT:
                    return None
                print(t("model.retrying", delay=f"{retry_delay:.1f}"))
                time.sleep(retry_delay)
                continue
            except AttributeError:
                return None


def register_models(model_settings_fnames):
    files_loaded = []
    for model_settings_fname in model_settings_fnames:
        if not os.path.exists(model_settings_fname):
            continue

        if not Path(model_settings_fname).read_text().strip():
            continue

        try:
            with open(model_settings_fname, "r") as model_settings_file:
                model_settings_list = yaml.safe_load(model_settings_file)

            for model_settings_dict in model_settings_list:
                model_settings = ModelSettings(**model_settings_dict)

                MODEL_SETTINGS[:] = [ms for ms in MODEL_SETTINGS if ms.name != model_settings.name]
                MODEL_SETTINGS.append(model_settings)
        except Exception as e:
            raise Exception(f"Error loading model settings from {model_settings_fname}: {e}")
        files_loaded.append(model_settings_fname)

    return files_loaded


def validate_variables(vars):
    missing = []
    for var in vars:
        if var not in os.environ:
            missing.append(var)
    if missing:
        return dict(keys_in_environment=False, missing_keys=missing)
    return dict(keys_in_environment=True, missing_keys=missing)


def sanity_check_models(io, main_model):
    problem_main = sanity_check_model(io, main_model)

    problem_weak = None
    if main_model.weak_model and main_model.weak_model is not main_model:
        problem_weak = sanity_check_model(io, main_model.weak_model)

    problem_editor = None
    if (
        main_model.editor_model
        and main_model.editor_model is not main_model
        and main_model.editor_model is not main_model.weak_model
    ):
        problem_editor = sanity_check_model(io, main_model.editor_model)

    return problem_main or problem_weak or problem_editor


def sanity_check_model(io, model):
    show = False

    if model.missing_keys:
        show = True
        io.tool_warning(t("model.missing_keys", model=model))
        for key in model.missing_keys:
            value = os.environ.get(key, "")
            status = t("model.key_set") if value else t("model.key_not_set")
            io.tool_output(f"- {key}: {status}")

        if platform.system() == "Windows":
            io.tool_output(t("model.windows_setx_note"))

    elif not model.keys_in_environment:
        show = True
        io.tool_warning(t("model.unknown_keys", model=model))

    check_for_dependencies(io, model.name)

    if not model.info:
        show = True
        io.tool_warning(t("model.unknown_context", model=model))

        possible_matches = fuzzy_match_models(model.name)
        if possible_matches:
            io.tool_output(t("model.did_you_mean"))
            for match in possible_matches:
                io.tool_output(f"- {match}")

    return show


def check_for_dependencies(io, model_name):
    if model_name.startswith("bedrock/"):
        check_pip_install_extra(
            io, "boto3", "AWS Bedrock models require the boto3 package.", ["boto3"]
        )

    elif model_name.startswith("vertex_ai/"):
        check_pip_install_extra(
            io,
            "google.cloud.aiplatform",
            "Google Vertex AI models require the google-cloud-aiplatform package.",
            ["google-cloud-aiplatform"],
        )


def fuzzy_match_models(name):
    name = name.lower()

    chat_models = set()
    
    model_metadata = list(model_info_manager.local_model_metadata.items())
    if model_info_manager.content:
        model_metadata += list(model_info_manager.content.items())

    for orig_model, attrs in model_metadata:
        model = orig_model.lower()
        if attrs.get("mode") != "chat":
            continue
        chat_models.add(orig_model)

    chat_models = sorted(chat_models)

    matching_models = [m for m in chat_models if name in m.lower()]
    if matching_models:
        return sorted(set(matching_models))

    models = set(chat_models)
    matching_models = difflib.get_close_matches(name, models, n=3, cutoff=0.8)

    return sorted(set(matching_models))


def print_matching_models(io, search):
    matches = fuzzy_match_models(search)
    if matches:
        io.tool_output(t("model.matches", search=search))
        for model in matches:
            io.tool_output(f"- {model}")
    else:
        io.tool_output(t("model.no_matches", search=search))


def get_model_settings_as_yaml():
    from dataclasses import fields

    import yaml

    model_settings_list = []
    defaults = {}
    for field in fields(ModelSettings):
        defaults[field.name] = field.default
    defaults["name"] = "(default values)"
    model_settings_list.append(defaults)

    for ms in sorted(MODEL_SETTINGS, key=lambda x: x.name):
        model_settings_dict = {}
        for field in fields(ModelSettings):
            value = getattr(ms, field.name)
            if value != field.default:
                model_settings_dict[field.name] = value
        model_settings_list.append(model_settings_dict)
        model_settings_list.append(None)

    yaml_str = yaml.dump(
        [ms for ms in model_settings_list if ms is not None],
        default_flow_style=False,
        sort_keys=False,
    )
    return yaml_str.replace("\n- ", "\n\n- ")


def main():
    if len(sys.argv) < 2:
        print(t("model.usage_hint"))
        sys.exit(1)

    if sys.argv[1] == "--yaml":
        yaml_string = get_model_settings_as_yaml()
        print(yaml_string)
    else:
        model_name = sys.argv[1]
        matching_models = fuzzy_match_models(model_name)

        if matching_models:
            print(t("model.matching_for", name=model_name))
            for model in matching_models:
                print(model)
        else:
            print(t("model.no_matching_found", name=model_name))


if __name__ == "__main__":
    main()
