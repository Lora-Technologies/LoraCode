"""
Internationalization (i18n) module for LoraCode.
Provides multi-language support for Turkish and English.
"""

import json
import locale
import os
from pathlib import Path
from typing import Dict, Optional

DEFAULT_LANGUAGE = "en"

SUPPORTED_LANGUAGES = {
    "en": "English",
    "tr": "Türkçe",
}

LOCALE_MAPPINGS = {
    "tr": "tr",
    "tr_tr": "tr",
    "turkish": "tr",
    "en": "en",
    "en_us": "en",
    "en_gb": "en",
    "english": "en",
}

_translator: Optional["Translator"] = None


def detect_system_language() -> str:
    """
    Detect the system's preferred language.
    
    Checks in order:
    1. LORACODE_LANG environment variable
    2. LANG environment variable
    3. System locale
    
    Returns:
        Language code ('en', 'tr', etc.) or DEFAULT_LANGUAGE if not detected
    """
    loracode_lang = os.environ.get("LORACODE_LANG", "").lower().strip()
    if loracode_lang and loracode_lang in SUPPORTED_LANGUAGES:
        return loracode_lang
    
    lang_env = os.environ.get("LANG", "").lower().split(".")[0]  # Remove encoding like .UTF-8
    if lang_env:
        if lang_env in LOCALE_MAPPINGS:
            return LOCALE_MAPPINGS[lang_env]
        lang_part = lang_env.split("_")[0]
        if lang_part in LOCALE_MAPPINGS:
            return LOCALE_MAPPINGS[lang_part]
    
    try:
        system_locale = locale.getdefaultlocale()[0]
        if system_locale:
            system_locale = system_locale.lower()
            if system_locale in LOCALE_MAPPINGS:
                return LOCALE_MAPPINGS[system_locale]
            lang_part = system_locale.split("_")[0]
            if lang_part in LOCALE_MAPPINGS:
                return LOCALE_MAPPINGS[lang_part]
    except (ValueError, TypeError):
        pass
    
    try:
        import ctypes
        windll = ctypes.windll.kernel32
        lang_id = windll.GetUserDefaultUILanguage()
        if lang_id == 0x041F or lang_id == 1055:
            return "tr"
        elif lang_id in (0x0409, 0x0809, 1033, 2057):
            return "en"
    except (ImportError, AttributeError, OSError):
        pass
    
    return DEFAULT_LANGUAGE


class Translator:
    """Handles translation of messages to different languages."""

    def __init__(self, language: str = DEFAULT_LANGUAGE):
        self.language = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
        self.translations: Dict[str, str] = {}
        self.fallback_translations: Dict[str, str] = {}
        self._load_translations()

    def _get_locale_path(self) -> Path:
        """Get the path to the locales directory."""
        return Path(__file__).parent / "locales"

    def _load_translations(self) -> None:
        """Load translation files for current and fallback language."""
        locale_path = self._get_locale_path()

        fallback_file = locale_path / f"{DEFAULT_LANGUAGE}.json"
        if fallback_file.exists():
            try:
                with open(fallback_file, "r", encoding="utf-8") as f:
                    self.fallback_translations = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.fallback_translations = {}

        if self.language != DEFAULT_LANGUAGE:
            lang_file = locale_path / f"{self.language}.json"
            if lang_file.exists():
                try:
                    with open(lang_file, "r", encoding="utf-8") as f:
                        self.translations = json.load(f)
                except (json.JSONDecodeError, OSError):
                    self.translations = {}
        else:
            self.translations = self.fallback_translations

    def set_language(self, language: str) -> bool:
        """
        Change the current language.
        
        Args:
            language: Language code (e.g., 'en', 'tr')
            
        Returns:
            True if language was changed successfully, False otherwise
        """
        if language not in SUPPORTED_LANGUAGES:
            return False
        
        self.language = language
        self._load_translations()
        return True

    def get(self, key: str, **kwargs) -> str:
        """
        Get a translated message.
        
        Args:
            key: The translation key
            **kwargs: Format arguments for the message
            
        Returns:
            Translated and formatted message, or the key if not found
        """
        message = self.translations.get(key)
        
        if message is None:
            message = self.fallback_translations.get(key)
        
        if message is None:
            return key
        
        if kwargs:
            try:
                return message.format(**kwargs)
            except (KeyError, ValueError):
                return message
        
        return message

    def __call__(self, key: str, **kwargs) -> str:
        """Shortcut for get() method."""
        return self.get(key, **kwargs)


def get_translator() -> Translator:
    """Get the global translator instance."""
    global _translator
    if _translator is None:
        lang = detect_system_language()
        _translator = Translator(lang)
    return _translator


def set_language(language: str) -> bool:
    """
    Set the global language.
    
    Args:
        language: Language code (e.g., 'en', 'tr')
        
    Returns:
        True if language was set successfully
    """
    translator = get_translator()
    return translator.set_language(language)


def t(key: str, **kwargs) -> str:
    """
    Translate a message key.
    
    This is the main function to use for translations throughout the codebase.
    
    Args:
        key: The translation key
        **kwargs: Format arguments for the message
        
    Returns:
        Translated message
        
    Example:
        >>> t("error.file_not_found", filename="test.py")
        "test.py: file not found error"
    """
    return get_translator().get(key, **kwargs)


def get_supported_languages() -> Dict[str, str]:
    """Get dictionary of supported language codes and names."""
    return SUPPORTED_LANGUAGES.copy()


def get_current_language() -> str:
    """Get the current language code."""
    return get_translator().language


def validate_translations() -> Dict[str, list]:
    """
    Validate translation file completeness across all supported languages.
    
    Compares all locale files against the English (default) locale file
    to find missing translation keys.
    
    Returns:
        Dictionary mapping language codes to lists of missing keys.
        Empty lists indicate complete translations.
        
    Example:
        >>> result = validate_translations()
        >>> result
        {'tr': ['new.key.1', 'new.key.2']}
    """
    locale_path = Path(__file__).parent / "locales"
    missing_keys: Dict[str, list] = {}
    
    en_file = locale_path / f"{DEFAULT_LANGUAGE}.json"
    if not en_file.exists():
        return missing_keys
    
    try:
        with open(en_file, "r", encoding="utf-8") as f:
            en_translations = json.load(f)
    except (json.JSONDecodeError, OSError):
        return missing_keys
    
    en_keys = set(en_translations.keys())
    
    for lang_code in SUPPORTED_LANGUAGES:
        if lang_code == DEFAULT_LANGUAGE:
            continue
        
        lang_file = locale_path / f"{lang_code}.json"
        if not lang_file.exists():
            missing_keys[lang_code] = sorted(list(en_keys))
            continue
        
        try:
            with open(lang_file, "r", encoding="utf-8") as f:
                lang_translations = json.load(f)
        except (json.JSONDecodeError, OSError):
            missing_keys[lang_code] = sorted(list(en_keys))
            continue
        
        lang_keys = set(lang_translations.keys())
        missing = en_keys - lang_keys
        missing_keys[lang_code] = sorted(list(missing))
    
    return missing_keys


def get_missing_keys(language: str) -> list:
    """
    Get missing translation keys for a specific language.
    
    Compares the specified language's locale file against the English
    (default) locale file to find missing keys.
    
    Args:
        language: Language code (e.g., 'tr' for Turkish)
        
    Returns:
        List of missing translation keys, sorted alphabetically.
        Empty list if language is English or all keys are present.
        
    Example:
        >>> get_missing_keys('tr')
        ['new.key.1', 'new.key.2']
    """
    if language == DEFAULT_LANGUAGE:
        return []
    
    if language not in SUPPORTED_LANGUAGES:
        return []
    
    locale_path = Path(__file__).parent / "locales"
    
    en_file = locale_path / f"{DEFAULT_LANGUAGE}.json"
    if not en_file.exists():
        return []
    
    try:
        with open(en_file, "r", encoding="utf-8") as f:
            en_translations = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    
    en_keys = set(en_translations.keys())
    
    lang_file = locale_path / f"{language}.json"
    if not lang_file.exists():
        return sorted(list(en_keys))
    
    try:
        with open(lang_file, "r", encoding="utf-8") as f:
            lang_translations = json.load(f)
    except (json.JSONDecodeError, OSError):
        return sorted(list(en_keys))
    
    lang_keys = set(lang_translations.keys())
    missing = en_keys - lang_keys
    
    return sorted(list(missing))
