import re
import threading
from pathlib import Path
from typing import Optional

from grep_ast import TreeContext
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern
from watchfiles import watch

from loracode.dump import dump  # noqa
from loracode.i18n import t
from loracode.watch_prompts import watch_ask_prompt, watch_code_prompt


def load_gitignores(gitignore_paths: list[Path]) -> Optional[PathSpec]:
    if not gitignore_paths:
        return None

    patterns = [
        ".loracode*",
        ".git",
        "*~",
        "*.bak",
        "*.swp",
        "*.swo",
        "\\#*\\#",
        ".#*",
        "*.tmp",
        "*.temp",
        "*.orig",
        "*.pyc",
        "__pycache__/",
        ".DS_Store",
        "Thumbs.db",
        "*.svg",
        "*.pdf",
        ".idea/",
        ".vscode/",
        "*.sublime-*",
        ".project",
        ".settings/",
        "*.code-workspace",
        ".env",
        ".venv/",
        "node_modules/",
        "vendor/",
        "*.log",
        ".cache/",
        ".pytest_cache/",
        "coverage/",
    ]
    for path in gitignore_paths:
        if path.exists():
            with open(path) as f:
                patterns.extend(f.readlines())

    return PathSpec.from_lines(GitWildMatchPattern, patterns) if patterns else None


class FileWatcher:
    ai_comment_pattern = re.compile(
        r"(?:#|//|--|;+) *(ai\b.*|ai\b.*|.*\bai[?!]?) *$", re.IGNORECASE
    )

    def __init__(self, coder, gitignores=None, verbose=False, analytics=None, root=None):
        self.coder = coder
        self.io = coder.io
        self.root = Path(root) if root else Path(coder.root)
        self.verbose = verbose
        self.analytics = analytics
        self.stop_event = None
        self.watcher_thread = None
        self.changed_files = set()
        self.gitignores = gitignores

        self.gitignore_spec = load_gitignores(
            [Path(g) for g in self.gitignores] if self.gitignores else []
        )

        coder.io.file_watcher = self

    def filter_func(self, change_type, path):
        path_obj = Path(path)
        path_abs = path_obj.absolute()

        if not path_abs.is_relative_to(self.root.absolute()):
            return False

        rel_path = path_abs.relative_to(self.root)
        if self.verbose:
            print(t("watch.changed", path=rel_path))

        if self.gitignore_spec and self.gitignore_spec.match_file(
            rel_path.as_posix() + ("/" if path_abs.is_dir() else "")
        ):
            return False

        if path_abs.is_file() and path_abs.stat().st_size > 1 * 1024 * 1024:
            return False

        if self.verbose:
            print(t("watch.checking", path=rel_path))

        try:
            comments, _, _ = self.get_ai_comments(str(path_abs))
            return bool(comments)
        except Exception:
            return

    def get_roots_to_watch(self):
        if self.gitignore_spec:
            roots = [
                str(path)
                for path in self.root.iterdir()
                if not self.gitignore_spec.match_file(
                    path.relative_to(self.root).as_posix() + ("/" if path.is_dir() else "")
                )
            ]
            return roots if roots else [str(self.root)]
        return [str(self.root)]

    def handle_changes(self, changes):
        if not changes:
            return False

        changed_files = {str(Path(change[1])) for change in changes}
        self.changed_files.update(changed_files)
        self.io.interrupt_input()
        return True

    def watch_files(self):
        try:
            roots_to_watch = self.get_roots_to_watch()

            for changes in watch(
                *roots_to_watch,
                watch_filter=self.filter_func,
                stop_event=self.stop_event,
                ignore_permission_denied=True,
            ):
                if self.handle_changes(changes):
                    return

        except Exception as e:
            if self.verbose:
                dump(f"File watcher error: {e}")
            raise e

    def start(self):
        self.stop_event = threading.Event()
        self.changed_files = set()

        self.watcher_thread = threading.Thread(target=self.watch_files, daemon=True)
        self.watcher_thread.start()

    def stop(self):
        if self.stop_event:
            self.stop_event.set()
        if self.watcher_thread:
            self.watcher_thread.join()
            self.watcher_thread = None
            self.stop_event = None

    def process_changes(self):
        has_action = None
        added = False
        for fname in self.changed_files:
            _, _, action = self.get_ai_comments(fname)
            if action in ("!", "?"):
                has_action = action

            if fname in self.coder.abs_fnames:
                continue
            if self.analytics:
                self.analytics.event("ai-comments file-add")
            self.coder.abs_fnames.add(fname)
            rel_fname = self.coder.get_rel_fname(fname)
            if not added:
                self.io.tool_output()
                added = True
            self.io.tool_output(t("watch.added", filename=rel_fname))

        if not has_action:
            if added:
                self.io.tool_output(t("watch.hint"))
            return ""

        if self.analytics:
            self.analytics.event("ai-comments execute")
        self.io.tool_output(t("input.processing"))

        if has_action == "!":
            res = watch_code_prompt
        elif has_action == "?":
            res = watch_ask_prompt

        for fname in self.coder.abs_fnames:
            line_nums, comments, _action = self.get_ai_comments(fname)
            if not line_nums:
                continue

            code = self.io.read_text(fname)
            if not code:
                continue

            rel_fname = self.coder.get_rel_fname(fname)
            res += f"\n{rel_fname}:\n"

            lois = [ln - 1 for ln, _ in zip(line_nums, comments) if ln > 0]

            try:
                context = TreeContext(
                    rel_fname,
                    code,
                    color=False,
                    line_number=False,
                    child_context=False,
                    last_line=False,
                    margin=0,
                    mark_lois=True,
                    loi_pad=3,
                    show_top_of_file_parent_scope=False,
                )
                context.lines_of_interest = set()
                context.add_lines_of_interest(lois)
                context.add_context()
                res += context.format()
            except ValueError:
                for ln, comment in zip(line_nums, comments):
                    res += f"  Line {ln}: {comment}\n"

        return res

    def get_ai_comments(self, filepath):
        line_nums = []
        comments = []
        has_action = None
        content = self.io.read_text(filepath, silent=True)
        if not content:
            return None, None, None

        for i, line in enumerate(content.splitlines(), 1):
            if match := self.ai_comment_pattern.search(line):
                comment = match.group(0).strip()
                if comment:
                    line_nums.append(i)
                    comments.append(comment)
                    comment = comment.lower()
                    comment = comment.lstrip("/#-;")
                    comment = comment.strip()
                    if comment.startswith("ai!") or comment.endswith("ai!"):
                        has_action = "!"
                    elif comment.startswith("ai?") or comment.endswith("ai?"):
                        has_action = "?"
        if not line_nums:
            return None, None, None
        return line_nums, comments, has_action


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Watch source files for changes")
    parser.add_argument("directory", help="Directory to watch")
    parser.add_argument(
        "--gitignore",
        action="append",
        help="Path to .gitignore file (can be specified multiple times)",
    )
    args = parser.parse_args()

    directory = args.directory
    print(t("watch.watching", directory=directory))

    def ignore_test_files(path):
        return "test" in path.name.lower()

    watcher = FileWatcher(directory, gitignores=args.gitignore)
    try:
        watcher.start()
        while True:
            if changes := watcher.get_changes():
                for file in sorted(changes.keys()):
                    print(file)
                watcher.changed_files = None
    except KeyboardInterrupt:
        print("\n" + t("watch.stopped"))
        watcher.stop()


if __name__ == "__main__":
    main()
