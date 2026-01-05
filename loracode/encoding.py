import codecs
import os
from pathlib import Path
from typing import Optional, Tuple


def is_valid_utf8(content: bytes) -> bool:
    try:
        content.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False


def read_file_with_encoding(file_path: str, encoding: str = 'utf-8') -> Tuple[Optional[str], Optional[str]]:
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
    lines = content.split('\n')[:2]
    
    for line in lines:
        if 'coding' in line.lower() and ('utf-8' in line.lower() or 'utf8' in line.lower()):
            return True
        if '-*- coding:' in line:
            return True
    
    return False


def add_encoding_declaration(content: str, encoding: str = 'utf-8') -> str:
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
    return text.encode('utf-8')


def decode_bytes_utf8(data: bytes) -> str:
    return data.decode('utf-8')


def process_file_encoding(file_path: str, add_declaration: bool = True) -> Tuple[bool, str]:
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
