# -*- coding: utf-8 -*-
"""
UTF-8 encoding utilities for LoraCode.

This module provides utilities for ensuring proper UTF-8 encoding
throughout the codebase.
"""

import codecs
import os
from pathlib import Path
from typing import Optional, Tuple


def is_valid_utf8(content: bytes) -> bool:
    """
    Check if byte content is valid UTF-8.
    
    Args:
        content: Byte content to check
    
    Returns:
        True if content is valid UTF-8, False otherwise
    """
    try:
        content.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False


def read_file_with_encoding(file_path: str, encoding: str = 'utf-8') -> Tuple[Optional[str], Optional[str]]:
    """
    Read a file with the specified encoding, with fallback detection.
    
    Args:
        file_path: Path to the file to read
        encoding: Primary encoding to try (default: utf-8)
    
    Returns:
        Tuple of (content, detected_encoding) or (None, None) on failure
    """
    encodings_to_try = [encoding, 'utf-8-sig', 'latin-1', 'cp1252']
    
    for enc in encodings_to_try:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                content = f.read()
                return content, enc
        except (UnicodeDecodeError, UnicodeError):
            continue
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            return None, None
    
    return None, None


def ensure_utf8_encoding(file_path: str) -> bool:
    """
    Ensure a file is UTF-8 encoded.
    
    If the file is not UTF-8 encoded, attempt to convert it.
    
    Args:
        file_path: Path to the file
    
    Returns:
        True if file is now UTF-8 encoded, False on failure
    """
    content, detected_encoding = read_file_with_encoding(file_path)
    
    if content is None:
        return False
    
    if detected_encoding == 'utf-8':
        return True
    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except (PermissionError, OSError):
        return False


def has_encoding_declaration(content: str) -> bool:
    """
    Check if Python source code has an encoding declaration.
    
    Args:
        content: Python source code content
    
    Returns:
        True if encoding declaration is present
    """
    lines = content.split('\n')[:2]
    
    for line in lines:
        # Check for PEP 263 encoding declaration
        if 'coding' in line.lower() and ('utf-8' in line.lower() or 'utf8' in line.lower()):
            return True
        # Also check for -*- coding: -*- style
        if '-*- coding:' in line:
            return True
    
    return False


def add_encoding_declaration(content: str, encoding: str = 'utf-8') -> str:
    """
    Add UTF-8 encoding declaration to Python source code if missing.
    
    Args:
        content: Python source code content
        encoding: Encoding to declare (default: utf-8)
    
    Returns:
        Content with encoding declaration added if it was missing
    """
    if has_encoding_declaration(content):
        return content
    
    declaration = f"# -*- coding: {encoding} -*-\n"
    
    if content.startswith('#!'):
        lines = content.split('\n', 1)
        if len(lines) > 1:
            return lines[0] + '\n' + declaration + lines[1]
        return lines[0] + '\n' + declaration
    
    return declaration + content


def fix_corrupted_unicode(content: str) -> str:
    """
    Attempt to fix common corrupted Unicode characters.
    
    Args:
        content: Content that may have corrupted Unicode
    
    Returns:
        Content with common corruptions fixed
    """
    replacements = {
        'â€™': "'",
        'â€œ': '"',
        'â€': '"',
        'â€"': '—',
        'â€"': '–',
        'â€¦': '…',
        'Ã©': 'é',
        'Ã¨': 'è',
        'Ã ': 'à',
        'Ã¢': 'â',
        'Ã®': 'î',
        'Ã´': 'ô',
        'Ã»': 'û',
        'Ã§': 'ç',
    }
    
    for corrupted, fixed in replacements.items():
        content = content.replace(corrupted, fixed)
    
    return content


def encode_string_utf8(text: str) -> bytes:
    """
    Encode a string to UTF-8 bytes.
    
    Args:
        text: String to encode
    
    Returns:
        UTF-8 encoded bytes
    """
    return text.encode('utf-8')


def decode_bytes_utf8(data: bytes) -> str:
    """
    Decode UTF-8 bytes to string.
    
    Args:
        data: Bytes to decode
    
    Returns:
        Decoded string
    
    Raises:
        UnicodeDecodeError: If data is not valid UTF-8
    """
    return data.decode('utf-8')


def process_file_encoding(file_path: str, add_declaration: bool = True) -> Tuple[bool, str]:
    """
    Process a Python file to ensure proper UTF-8 encoding.
    
    Args:
        file_path: Path to the Python file
        add_declaration: Whether to add encoding declaration if missing
    
    Returns:
        Tuple of (success, message)
    """
    if not os.path.isfile(file_path):
        return False, f"File not found: {file_path}"
    
    if not file_path.endswith('.py'):
        return False, f"Not a Python file: {file_path}"
    
    content, detected_encoding = read_file_with_encoding(file_path)
    
    if content is None:
        return False, f"Could not read file: {file_path}"
    
    modified = False
    
    fixed_content = fix_corrupted_unicode(content)
    if fixed_content != content:
        content = fixed_content
        modified = True
    
    # Add encoding declaration if requested and missing
    if add_declaration and not has_encoding_declaration(content):
        content = add_encoding_declaration(content)
        modified = True
    
    if modified:
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True, f"Updated: {file_path}"
        except (PermissionError, OSError) as e:
            return False, f"Could not write file {file_path}: {e}"
    
    return True, f"No changes needed: {file_path}"
