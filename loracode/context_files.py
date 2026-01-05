import os
import re
from pathlib import Path
from typing import List, Optional, Set

from loracode.i18n import t


DEFAULT_CONTEXT_FILENAMES = ["LORACODE.md", "CONTEXT.md", ".loracode.md"]


class ContextFileManager:
    def __init__(
        self,
        root: str = ".",
        context_filenames: Optional[List[str]] = None,
        encoding: str = "utf-8",
        respect_gitignore: bool = True,
    ):
        self.root = Path(root).resolve()
        self.context_filenames = context_filenames or DEFAULT_CONTEXT_FILENAMES
        self.encoding = encoding
        self.respect_gitignore = respect_gitignore
        self._cached_content: Optional[str] = None
        self._loaded_files: List[Path] = []
        self._gitignore_patterns: Set[str] = set()
        
    def get_global_context_dir(self) -> Path:
        return Path.home() / ".loracode"
    
    def get_global_context_file(self) -> Optional[Path]:
        global_dir = self.get_global_context_dir()
        for filename in self.context_filenames:
            path = global_dir / filename
            if path.exists() and path.is_file():
                return path
        return None
    
    def find_project_root(self) -> Path:
        current = self.root
        while current != current.parent:
            if (current / ".git").exists():
                return current
            current = current.parent
        return self.root
    
    def _load_gitignore_patterns(self, directory: Path) -> Set[str]:
        patterns = set()
        gitignore_path = directory / ".gitignore"
        loracodeignore_path = directory / ".loracodeignore"
        
        for ignore_file in [gitignore_path, loracodeignore_path]:
            if ignore_file.exists():
                try:
                    with open(ignore_file, "r", encoding=self.encoding) as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#"):
                                patterns.add(line)
                except Exception:
                    pass
        return patterns
    
    def _is_ignored(self, path: Path, patterns: Set[str]) -> bool:
        if not self.respect_gitignore:
            return False
            
        rel_path = str(path.relative_to(self.root) if path.is_relative_to(self.root) else path)
        
        for pattern in patterns:
            if pattern.endswith("/"):
                if rel_path.startswith(pattern[:-1]) or f"/{pattern[:-1]}" in rel_path:
                    return True
            elif "*" in pattern:
                import fnmatch
                if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(path.name, pattern):
                    return True
            else:
                if pattern in rel_path or path.name == pattern:
                    return True
        return False
    
    def _find_context_file(self, directory: Path) -> Optional[Path]:
        for filename in self.context_filenames:
            path = directory / filename
            if path.exists() and path.is_file():
                return path
        return None
    
    def _read_file_with_imports(self, filepath: Path, visited: Optional[Set[Path]] = None) -> str:
        if visited is None:
            visited = set()
            
        if filepath in visited:
            return ""
            
        visited.add(filepath)
        
        try:
            with open(filepath, "r", encoding=self.encoding) as f:
                content = f.read()
        except Exception:
            return ""
        import_pattern = re.compile(r"^@(.+\.md)\s*$", re.MULTILINE)
        
        def replace_import(match):
            import_path = match.group(1).strip()
            if import_path.startswith("./") or import_path.startswith("../"):
                full_path = (filepath.parent / import_path).resolve()
            elif import_path.startswith("/"):
                full_path = Path(import_path)
            else:
                full_path = (filepath.parent / import_path).resolve()
            
            if full_path.exists() and full_path.is_file():
                return self._read_file_with_imports(full_path, visited)
            return f"<!-- Import not found: {import_path} -->"
        
        return import_pattern.sub(replace_import, content)
    
    def discover_context_files(self) -> List[Path]:
        files = []
        project_root = self.find_project_root()
        global_file = self.get_global_context_file()
        if global_file:
            files.append(global_file)
        ancestors = []
        current = self.root
        while current != current.parent:
            ancestors.append(current)
            if current == project_root:
                break
            current = current.parent
        for directory in reversed(ancestors):
            context_file = self._find_context_file(directory)
            if context_file and context_file not in files:
                files.append(context_file)
        if self.root.exists():
            gitignore_patterns = self._load_gitignore_patterns(project_root)
            gitignore_patterns.update(self._load_gitignore_patterns(self.root))
            skip_dirs = {".git", ".svn", ".hg", "node_modules", "__pycache__", 
                        ".venv", "venv", ".tox", ".pytest_cache", "dist", "build"}
            
            for subdir in self.root.rglob("*"):
                if not subdir.is_dir():
                    continue
                if subdir.name in skip_dirs:
                    continue
                if self._is_ignored(subdir, gitignore_patterns):
                    continue
                    
                context_file = self._find_context_file(subdir)
                if context_file and context_file not in files:
                    if not self._is_ignored(context_file, gitignore_patterns):
                        files.append(context_file)
        
        return files
    
    def load_context(self, force_refresh: bool = False) -> str:
        if self._cached_content is not None and not force_refresh:
            return self._cached_content
        
        self._loaded_files = self.discover_context_files()
        
        if not self._loaded_files:
            self._cached_content = ""
            return ""
        
        contents = []
        for filepath in self._loaded_files:
            content = self._read_file_with_imports(filepath)
            if content.strip():
                rel_path = filepath.relative_to(Path.home()) if filepath.is_relative_to(Path.home()) else filepath
                contents.append(f"<!-- Source: {rel_path} -->\n{content}")
        
        self._cached_content = "\n\n---\n\n".join(contents)
        return self._cached_content
    
    def refresh(self) -> str:
        return self.load_context(force_refresh=True)
    
    def get_loaded_files(self) -> List[Path]:
        if self._cached_content is None:
            self.load_context()
        return self._loaded_files.copy()
    
    def get_loaded_files_count(self) -> int:
        return len(self.get_loaded_files())
    
    def add_to_global(self, text: str) -> bool:
        global_dir = self.get_global_context_dir()
        global_dir.mkdir(parents=True, exist_ok=True)
        global_file = global_dir / self.context_filenames[0]
        try:
            existing = ""
            if global_file.exists():
                with open(global_file, "r", encoding=self.encoding) as f:
                    existing = f.read()
            
            with open(global_file, "w", encoding=self.encoding) as f:
                if existing and not existing.endswith("\n"):
                    existing += "\n"
                f.write(existing + text + "\n")
            self._cached_content = None
            return True
        except Exception:
            return False
    
    def show_context(self) -> str:
        content = self.load_context()
        files = self.get_loaded_files()
        if not files:
            return t("context.no_files_loaded")
        header = t("context.loaded_files", count=len(files)) + "\n"
        for f in files:
            header += f"  - {f}\n"
        header += "\n" + "=" * 50 + "\n\n"
        
        return header + content


def create_sample_loracode_md(directory: Path, project_name: str = "My Project") -> Path:
    content = f"""# Project: {project_name}

## General Instructions

- Follow the existing coding style and conventions in this project.
- Write clear, self-documenting code with appropriate comments.
- Ensure all new functions have docstrings/documentation.

## Coding Style

- Use consistent indentation (spaces or tabs as per project convention).
- Keep functions small and focused on a single responsibility.
- Use meaningful variable and function names.

## Project Structure

<!-- Describe your project structure here -->

## Important Notes

<!-- Add any project-specific notes for the AI assistant -->
"""
    filepath = directory / "LORACODE.md"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    
    return filepath
