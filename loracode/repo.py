import contextlib
import os
import time
from pathlib import Path, PurePosixPath

try:
    import git

    ANY_GIT_ERROR = [
        git.exc.ODBError,
        git.exc.GitError,
        git.exc.InvalidGitRepositoryError,
        git.exc.GitCommandNotFound,
    ]
except ImportError:
    git = None
    ANY_GIT_ERROR = []

import pathspec

from loracode import prompts, utils
from loracode.i18n import t

from .dump import dump  # noqa: F401
from .waiting import WaitingSpinner

ANY_GIT_ERROR += [
    OSError,
    IndexError,
    BufferError,
    TypeError,
    ValueError,
    AttributeError,
    AssertionError,
    TimeoutError,
]
ANY_GIT_ERROR = tuple(ANY_GIT_ERROR)


@contextlib.contextmanager
def set_git_env(var_name, value, original_value):
    os.environ[var_name] = value
    try:
        yield
    finally:
        if original_value is not None:
            os.environ[var_name] = original_value
        elif var_name in os.environ:
            del os.environ[var_name]


class GitRepo:
    repo = None
    loracode_ignore_file = None
    loracode_ignore_spec = None
    loracode_ignore_ts = 0
    loracode_ignore_last_check = 0
    subtree_only = False
    ignore_file_cache = {}
    git_repo_error = None

    def __init__(
        self,
        io,
        fnames,
        git_dname,
        loracode_ignore_file=None,
        models=None,
        attribute_author=True,
        attribute_committer=True,
        attribute_commit_message_author=False,
        attribute_commit_message_committer=False,
        commit_prompt=None,
        subtree_only=False,
        git_commit_verify=True,
        attribute_co_authored_by=False,
    ):
        self.io = io
        self.models = models

        self.normalized_path = {}
        self.tree_files = {}

        self.attribute_author = attribute_author
        self.attribute_committer = attribute_committer
        self.attribute_commit_message_author = attribute_commit_message_author
        self.attribute_commit_message_committer = attribute_commit_message_committer
        self.attribute_co_authored_by = attribute_co_authored_by
        self.commit_prompt = commit_prompt
        self.subtree_only = subtree_only
        self.git_commit_verify = git_commit_verify
        self.ignore_file_cache = {}

        if git_dname:
            check_fnames = [git_dname]
        elif fnames:
            check_fnames = fnames
        else:
            check_fnames = ["."]

        repo_paths = []
        for fname in check_fnames:
            fname = Path(fname)
            fname = fname.resolve()

            if not fname.exists() and fname.parent.exists():
                fname = fname.parent

            try:
                repo_path = git.Repo(fname, search_parent_directories=True).working_dir
                repo_path = utils.safe_abs_path(repo_path)
                repo_paths.append(repo_path)
            except ANY_GIT_ERROR:
                pass

        num_repos = len(set(repo_paths))

        if num_repos == 0:
            raise FileNotFoundError
        if num_repos > 1:
            self.io.tool_error(t("git.files_different_repos"))
            raise FileNotFoundError

        self.repo = git.Repo(repo_paths.pop(), odbt=git.GitDB)
        self.root = utils.safe_abs_path(self.repo.working_tree_dir)

        if loracode_ignore_file:
            self.loracode_ignore_file = Path(loracode_ignore_file)

    def commit(self, fnames=None, context=None, message=None, loracode_edits=False, coder=None):
        if not fnames and not self.repo.is_dirty():
            return

        diffs = self.get_diffs(fnames)
        if not diffs:
            return

        if message:
            commit_message = message
        else:
            user_language = None
            if coder:
                user_language = coder.commit_language
                if not user_language:
                    user_language = coder.get_user_language()
            commit_message = self.get_commit_message(diffs, context, user_language)

        if coder and hasattr(coder, "args"):
            attribute_author = coder.args.attribute_author
            attribute_committer = coder.args.attribute_committer
            attribute_commit_message_author = coder.args.attribute_commit_message_author
            attribute_commit_message_committer = coder.args.attribute_commit_message_committer
            attribute_co_authored_by = coder.args.attribute_co_authored_by
        else:
            attribute_author = self.attribute_author
            attribute_committer = self.attribute_committer
            attribute_commit_message_author = self.attribute_commit_message_author
            attribute_commit_message_committer = self.attribute_commit_message_committer
            attribute_co_authored_by = self.attribute_co_authored_by

        author_explicit = attribute_author is not None
        committer_explicit = attribute_committer is not None

        effective_author = True if attribute_author is None else attribute_author
        effective_committer = True if attribute_committer is None else attribute_committer

        prefix_commit_message = loracode_edits and (
            attribute_commit_message_author or attribute_commit_message_committer
        )

        commit_message_trailer = ""
        if loracode_edits and attribute_co_authored_by:
            model_name = "unknown-model"
            if coder and hasattr(coder, "main_model") and coder.main_model.name:
                model_name = coder.main_model.name
            commit_message_trailer = f"\n\nCo-authored-by: loracode ({model_name}) <loracode@loratech.dev>"

        use_attribute_author = (
            loracode_edits and effective_author and (not attribute_co_authored_by or author_explicit)
        )

        use_attribute_committer = effective_committer and (
            not (loracode_edits and attribute_co_authored_by) or committer_explicit
        )

        if not commit_message:
            commit_message = "(no commit message provided)"

        if prefix_commit_message:
            commit_message = "loracode: " + commit_message

        full_commit_message = commit_message + commit_message_trailer

        cmd = ["-m", full_commit_message]
        if not self.git_commit_verify:
            cmd.append("--no-verify")
        if fnames:
            fnames = [str(self.abs_root_path(fn)) for fn in fnames]
            for fname in fnames:
                try:
                    self.repo.git.add(fname)
                except ANY_GIT_ERROR as err:
                    self.io.tool_error(t("git.unable_add", filename=fname, error=err))
            cmd += ["--"] + fnames
        else:
            cmd += ["-a"]

        original_user_name = self.repo.git.config("--get", "user.name")
        original_committer_name_env = os.environ.get("GIT_COMMITTER_NAME")
        original_author_name_env = os.environ.get("GIT_AUTHOR_NAME")
        committer_name = f"{original_user_name} (loracode)"

        try:
            with contextlib.ExitStack() as stack:
                if use_attribute_committer:
                    stack.enter_context(
                        set_git_env(
                            "GIT_COMMITTER_NAME", committer_name, original_committer_name_env
                        )
                    )
                if use_attribute_author:
                    stack.enter_context(
                        set_git_env("GIT_AUTHOR_NAME", committer_name, original_author_name_env)
                    )

                self.repo.git.commit(cmd)
                commit_hash = self.get_head_commit_sha(short=True)
                self.io.tool_output(t("git.commit_success", hash=commit_hash, message=commit_message), bold=True)
                return commit_hash, commit_message

        except ANY_GIT_ERROR as err:
            self.io.tool_error(t("git.unable_commit", error=err))

    def get_rel_repo_dir(self):
        try:
            return os.path.relpath(self.repo.git_dir, os.getcwd())
        except (ValueError, OSError):
            return self.repo.git_dir

    def get_commit_message(self, diffs, context, user_language=None):
        diffs = "# Diffs:\n" + diffs

        content = ""
        if context:
            content += context + "\n"
        content += diffs

        system_content = self.commit_prompt or prompts.commit_system

        language_instruction = ""
        if user_language:
            language_instruction = f"\n- Is written in {user_language}."
        system_content = system_content.format(language_instruction=language_instruction)

        commit_message = None
        for model in self.models:
            model_display = model.name.split("/")[-1]
            spinner_text = f"Writing commit message with {model_display}..."
            with WaitingSpinner(spinner_text):
                if model.system_prompt_prefix:
                    current_system_content = model.system_prompt_prefix + "\n" + system_content
                else:
                    current_system_content = system_content

                messages = [
                    dict(role="system", content=current_system_content),
                    dict(role="user", content=content),
                ]

                num_tokens = model.token_count(messages)
                max_tokens = model.info.get("max_input_tokens") or 0

                if max_tokens and num_tokens > max_tokens:
                    continue

                commit_message = model.simple_send_with_retries(messages)
                if commit_message:
                    break

        if not commit_message:
            self.io.tool_error(t("git.commit_failed"))
            return

        commit_message = commit_message.strip()
        if commit_message and commit_message[0] == '"' and commit_message[-1] == '"':
            commit_message = commit_message[1:-1].strip()

        return commit_message

    def get_diffs(self, fnames=None):

        current_branch_has_commits = False
        try:
            active_branch = self.repo.active_branch
            try:
                commits = self.repo.iter_commits(active_branch)
                current_branch_has_commits = any(commits)
            except ANY_GIT_ERROR:
                pass
        except (TypeError,) + ANY_GIT_ERROR:
            pass

        if not fnames:
            fnames = []

        diffs = ""
        for fname in fnames:
            if not self.path_in_repo(fname):
                diffs += f"Added {fname}\n"

        try:
            if current_branch_has_commits:
                args = ["HEAD", "--"] + list(fnames)
                diffs += self.repo.git.diff(*args, stdout_as_string=False).decode(
                    self.io.encoding, "replace"
                )
                return diffs

            wd_args = ["--"] + list(fnames)
            index_args = ["--cached"] + wd_args

            diffs += self.repo.git.diff(*index_args, stdout_as_string=False).decode(
                self.io.encoding, "replace"
            )
            diffs += self.repo.git.diff(*wd_args, stdout_as_string=False).decode(
                self.io.encoding, "replace"
            )

            return diffs
        except ANY_GIT_ERROR as err:
            self.io.tool_error(t("git.unable_diff", error=err))

    def diff_commits(self, pretty, from_commit, to_commit):
        args = []
        if pretty:
            args += ["--color"]
        else:
            args += ["--color=never"]

        args += [from_commit, to_commit]
        diffs = self.repo.git.diff(*args, stdout_as_string=False).decode(
            self.io.encoding, "replace"
        )

        return diffs

    def get_tracked_files(self):
        if not self.repo:
            return []

        try:
            commit = self.repo.head.commit
        except ValueError:
            commit = None
        except ANY_GIT_ERROR as err:
            self.git_repo_error = err
            self.io.tool_error(t("git.unable_list_files", error=err))
            self.io.tool_output(t("git.corrupt_question"))
            return []

        files = set()
        if commit:
            if commit in self.tree_files:
                files = self.tree_files[commit]
            else:
                try:
                    iterator = commit.tree.traverse()
                    blob = None
                    while True:
                        try:
                            blob = next(iterator)
                            if blob.type == "blob":
                                files.add(blob.path)
                        except IndexError:
                            self.io.tool_warning(t("git.index_error_tree"))
                            continue
                        except StopIteration:
                            break
                except ANY_GIT_ERROR as err:
                    self.git_repo_error = err
                    self.io.tool_error(t("git.unable_list_files", error=err))
                    self.io.tool_output(t("git.corrupt_question"))
                    return []
                files = set(self.normalize_path(path) for path in files)
                self.tree_files[commit] = set(files)

        index = self.repo.index
        try:
            staged_files = [path for path, _ in index.entries.keys()]
            files.update(self.normalize_path(path) for path in staged_files)
        except ANY_GIT_ERROR as err:
            self.io.tool_error(t("git.unable_read_staged", error=err))

        res = [fname for fname in files if not self.ignored_file(fname)]

        return res

    def normalize_path(self, path):
        orig_path = path
        res = self.normalized_path.get(orig_path)
        if res:
            return res

        path = str(Path(PurePosixPath((Path(self.root) / path).relative_to(self.root))))
        self.normalized_path[orig_path] = path
        return path

    def refresh_loracode_ignore(self):
        if not self.loracode_ignore_file:
            return

        current_time = time.time()
        if current_time - self.loracode_ignore_last_check < 1:
            return

        self.loracode_ignore_last_check = current_time

        if not self.loracode_ignore_file.is_file():
            return

        mtime = self.loracode_ignore_file.stat().st_mtime
        if mtime != self.loracode_ignore_ts:
            self.loracode_ignore_ts = mtime
            self.ignore_file_cache = {}
            lines = self.loracode_ignore_file.read_text().splitlines()
            self.loracode_ignore_spec = pathspec.PathSpec.from_lines(
                pathspec.patterns.GitWildMatchPattern,
                lines,
            )

    def git_ignored_file(self, path):
        if not self.repo:
            return
        try:
            if self.repo.ignored(path):
                return True
        except ANY_GIT_ERROR:
            return False

    def ignored_file(self, fname):
        self.refresh_loracode_ignore()

        if fname in self.ignore_file_cache:
            return self.ignore_file_cache[fname]

        result = self.ignored_file_raw(fname)
        self.ignore_file_cache[fname] = result
        return result

    def ignored_file_raw(self, fname):
        if self.subtree_only:
            try:
                fname_path = Path(self.normalize_path(fname))
                cwd_path = Path.cwd().resolve().relative_to(Path(self.root).resolve())
            except ValueError:
                return True

            if cwd_path not in fname_path.parents and fname_path != cwd_path:
                return True

        if not self.loracode_ignore_file or not self.loracode_ignore_file.is_file():
            return False

        try:
            fname = self.normalize_path(fname)
        except ValueError:
            return True

        return self.loracode_ignore_spec.match_file(fname)

    def path_in_repo(self, path):
        if not self.repo:
            return
        if not path:
            return

        tracked_files = set(self.get_tracked_files())
        return self.normalize_path(path) in tracked_files

    def abs_root_path(self, path):
        res = Path(self.root) / path
        return utils.safe_abs_path(res)

    def get_dirty_files(self):
        dirty_files = set()

        staged_files = self.repo.git.diff("--name-only", "--cached").splitlines()
        dirty_files.update(staged_files)

        unstaged_files = self.repo.git.diff("--name-only").splitlines()
        dirty_files.update(unstaged_files)

        return list(dirty_files)

    def is_dirty(self, path=None):
        if path and not self.path_in_repo(path):
            return True

        return self.repo.is_dirty(path=path)

    def get_head_commit(self):
        try:
            return self.repo.head.commit
        except (ValueError,) + ANY_GIT_ERROR:
            return None

    def get_head_commit_sha(self, short=False):
        commit = self.get_head_commit()
        if not commit:
            return
        if short:
            return commit.hexsha[:7]
        return commit.hexsha

    def get_head_commit_message(self, default=None):
        commit = self.get_head_commit()
        if not commit:
            return default
        return commit.message
