import glob
import os
import re
import subprocess
import sys
import tempfile
from collections import OrderedDict
from os.path import expanduser
from pathlib import Path

import pyperclip
from PIL import Image, ImageGrab
from prompt_toolkit.completion import Completion, PathCompleter
from prompt_toolkit.document import Document

from loracode import models, prompts, voice
from loracode.editor import pipe_editor
from loracode.format_settings import format_settings
from loracode.help import Help, install_help_extra
from loracode.i18n import t
from loracode.auto_approve import ApprovalCategory, ApprovalRule
from loracode.io import CommandCompletionException
from loracode.llm import litellm
from loracode.lora_code_auth import LoraCodeAuth
from loracode.lora_code_client import LoraCodeClient, LoraCodeClientError
from loracode.repo import ANY_GIT_ERROR
from loracode.run_cmd import run_cmd
from loracode.scrape import Scraper, install_playwright
from loracode.utils import is_image_file

from .dump import dump  # noqa: F401


class SwitchCoder(Exception):
    def __init__(self, placeholder=None, **kwargs):
        self.kwargs = kwargs
        self.placeholder = placeholder


class Commands:
    voice = None
    scraper = None

    def clone(self):
        return Commands(
            self.io,
            None,
            voice_language=self.voice_language,
            verify_ssl=self.verify_ssl,
            args=self.args,
            parser=self.parser,
            verbose=self.verbose,
            editor=self.editor,
            original_read_only_fnames=self.original_read_only_fnames,
        )

    def __init__(
        self,
        io,
        coder,
        voice_language=None,
        voice_input_device=None,
        voice_format=None,
        verify_ssl=True,
        args=None,
        parser=None,
        verbose=False,
        editor=None,
        original_read_only_fnames=None,
    ):
        self.io = io
        self.coder = coder
        self.parser = parser
        self.args = args
        self.verbose = verbose

        self.verify_ssl = verify_ssl
        if voice_language == "auto":
            voice_language = None

        self.voice_language = voice_language
        self.voice_format = voice_format
        self.voice_input_device = voice_input_device

        self.help = None
        self.editor = editor

        self.original_read_only_fnames = set(original_read_only_fnames or [])

    def cmd_model(self, args):
        "Switch the Main Model to a new LLM"

        model_name = args.strip()
        if not model_name:
            announcements = "\n".join(self.coder.get_announcements())
            self.io.tool_output(announcements)
            return

        model = models.Model(
            model_name,
            editor_model=self.coder.main_model.editor_model.name,
            weak_model=self.coder.main_model.weak_model.name,
        )
        models.sanity_check_models(self.io, model)

        old_model_edit_format = self.coder.main_model.edit_format
        current_edit_format = self.coder.edit_format

        new_edit_format = current_edit_format
        if current_edit_format == old_model_edit_format:
            new_edit_format = model.edit_format

        raise SwitchCoder(main_model=model, edit_format=new_edit_format)

    def cmd_editor_model(self, args):
        "Switch the Editor Model to a new LLM"

        model_name = args.strip()
        model = models.Model(
            self.coder.main_model.name,
            editor_model=model_name,
            weak_model=self.coder.main_model.weak_model.name,
        )
        models.sanity_check_models(self.io, model)
        raise SwitchCoder(main_model=model)

    def cmd_weak_model(self, args):
        "Switch the Weak Model to a new LLM"

        model_name = args.strip()
        model = models.Model(
            self.coder.main_model.name,
            editor_model=self.coder.main_model.editor_model.name,
            weak_model=model_name,
        )
        models.sanity_check_models(self.io, model)
        raise SwitchCoder(main_model=model)

    def cmd_chat_mode(self, args):
        "Switch to a new chat mode"

        from loracode import coders

        ef = args.strip()
        valid_formats = OrderedDict(
            sorted(
                (
                    coder.edit_format,
                    coder.__doc__.strip().split("\n")[0] if coder.__doc__ else "No description",
                )
                for coder in coders.__all__
                if getattr(coder, "edit_format", None)
            )
        )

        show_formats = OrderedDict(
            [
                ("help", "Get help about using Lora Code (usage, config, troubleshoot)."),
                ("ask", "Ask questions about your code without making any changes."),
                ("code", "Ask for changes to your code (using the best edit format)."),
                (
                    "architect",
                    (
                        "Work with an architect model to design code changes, and an editor to make"
                        " them."
                    ),
                ),
                (
                    "context",
                    "Automatically identify which files will need to be edited.",
                ),
            ]
        )

        if ef not in valid_formats and ef not in show_formats:
            if ef:
                self.io.tool_error(t("chat.mode_invalid", mode=ef) + "\n")
            else:
                self.io.tool_output(t("chat.mode_should_be") + "\n")

            max_format_length = max(len(format) for format in valid_formats.keys())
            for format, description in show_formats.items():
                self.io.tool_output(f"- {format:<{max_format_length}} : {description}")

            self.io.tool_output("\n" + t("chat.or_valid_format") + "\n")
            for format, description in valid_formats.items():
                if format not in show_formats:
                    self.io.tool_output(f"- {format:<{max_format_length}} : {description}")

            return

        summarize_from_coder = True
        edit_format = ef

        if ef == "code":
            edit_format = self.coder.main_model.edit_format
            summarize_from_coder = False
        elif ef == "ask":
            summarize_from_coder = False

        raise SwitchCoder(
            edit_format=edit_format,
            summarize_from_coder=summarize_from_coder,
        )

    def completions_model(self):
        models = litellm.model_cost.keys()
        return models

    def cmd_models(self, args):
        "Search the list of available models"

        args = args.strip()

        if args:
            models.print_matching_models(self.io, args)
        else:
            self.io.tool_output(t("search.provide_name"))

    def cmd_web(self, args, return_content=False):
        "Scrape a webpage, convert to markdown and send in a message"

        url = args.strip()
        if not url:
            self.io.tool_error(t("web.provide_url"))
            return

        self.io.tool_output(t("cmd.scraping", url=url))
        if not self.scraper:
            disable_playwright = getattr(self.args, "disable_playwright", False)
            if disable_playwright:
                res = False
            else:
                res = install_playwright(self.io)
                if not res:
                    self.io.tool_warning(t("web.playwright_error"))

            self.scraper = Scraper(
                print_error=self.io.tool_error,
                playwright_available=res,
                verify_ssl=self.verify_ssl,
            )

        content = self.scraper.scrape(url) or ""
        content = f"Here is the content of {url}:\n\n" + content
        if return_content:
            return content

        self.io.tool_output(t("web.added_to_chat"))

        self.coder.cur_messages += [
            dict(role="user", content=content),
            dict(role="assistant", content="Ok."),
        ]

    def is_command(self, inp):
        return inp[0] in "/!"

    def get_raw_completions(self, cmd):
        assert cmd.startswith("/")
        cmd = cmd[1:]
        cmd = cmd.replace("-", "_")

        raw_completer = getattr(self, f"completions_raw_{cmd}", None)
        return raw_completer

    def get_completions(self, cmd):
        assert cmd.startswith("/")
        cmd = cmd[1:]

        cmd = cmd.replace("-", "_")
        fun = getattr(self, f"completions_{cmd}", None)
        if not fun:
            return
        return sorted(fun())

    def get_commands(self):
        commands = []
        for attr in dir(self):
            if not attr.startswith("cmd_"):
                continue
            cmd = attr[4:]
            cmd = cmd.replace("_", "-")
            commands.append("/" + cmd)

        return commands

    def do_run(self, cmd_name, args):
        cmd_name = cmd_name.replace("-", "_")
        cmd_method_name = f"cmd_{cmd_name}"
        cmd_method = getattr(self, cmd_method_name, None)
        if not cmd_method:
            self.io.tool_output(t("cmd.error_not_found", cmd_name=cmd_name))
            return

        try:
            return cmd_method(args)
        except ANY_GIT_ERROR as err:
            self.io.tool_error(t("cmd.unable_complete", cmd_name=cmd_name, error=err))

    def matching_commands(self, inp):
        words = inp.strip().split()
        if not words:
            return

        first_word = words[0]
        rest_inp = inp[len(words[0]) :].strip()

        all_commands = self.get_commands()
        matching_commands = [cmd for cmd in all_commands if cmd.startswith(first_word)]
        return matching_commands, first_word, rest_inp

    def run(self, inp):
        if inp.startswith("!"):
            self.coder.event("command_run")
            return self.do_run("run", inp[1:])

        res = self.matching_commands(inp)
        if res is None:
            return
        matching_commands, first_word, rest_inp = res
        if len(matching_commands) == 1:
            command = matching_commands[0][1:]
            self.coder.event(f"command_{command}")
            return self.do_run(command, rest_inp)
        elif first_word in matching_commands:
            command = first_word[1:]
            self.coder.event(f"command_{command}")
            return self.do_run(command, rest_inp)
        elif len(matching_commands) > 1:
            self.io.tool_error(t("cmd.ambiguous", commands=", ".join(matching_commands)))
        else:
            self.io.tool_error(t("cmd.invalid", command=first_word))


    def cmd_commit(self, args=None):
        "Commit edits to the repo made outside the chat (commit message optional)"
        try:
            self.raw_cmd_commit(args)
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to complete commit: {err}")

    def raw_cmd_commit(self, args=None):
        if not self.coder.repo:
            self.io.tool_error(t("git.no_repo"))
            return

        if not self.coder.repo.is_dirty():
            self.io.tool_warning(t("git.no_changes"))
            return

        commit_message = args.strip() if args else None
        self.coder.repo.commit(message=commit_message, coder=self.coder)

    def cmd_lint(self, args="", fnames=None):
        "Lint and fix in-chat files or all dirty files if none in chat"

        if not self.coder.repo:
            self.io.tool_error(t("git.no_repo"))
            return

        if not fnames:
            fnames = self.coder.get_inchat_relative_files()

        if not fnames and self.coder.repo:
            fnames = self.coder.repo.get_dirty_files()

        if not fnames:
            self.io.tool_warning(t("lint.no_dirty_files"))
            return

        fnames = [self.coder.abs_root_path(fname) for fname in fnames]

        lint_coder = None
        for fname in fnames:
            try:
                errors = self.coder.linter.lint(fname)
            except FileNotFoundError as err:
                self.io.tool_error(t("lint.unable", filename=fname))
                self.io.tool_output(str(err))
                continue

            if not errors:
                continue

            self.io.tool_output(errors)
            if not self.io.confirm_ask(t("lint.fix_confirm", filename=fname), default="y",
                    category=ApprovalCategory.LINT_FIX):
                continue

            if self.coder.repo.is_dirty() and self.coder.dirty_commits:
                self.cmd_commit("")

            if not lint_coder:
                lint_coder = self.coder.clone(
                    cur_messages=[],
                    done_messages=[],
                    fnames=None,
                )

            lint_coder.add_rel_fname(fname)
            lint_coder.run(errors)
            lint_coder.abs_fnames = set()

        if lint_coder and self.coder.repo.is_dirty() and self.coder.auto_commits:
            self.cmd_commit("")

    def cmd_clear(self, args):
        "Clear the chat history"

        self._clear_chat_history()
        self.io.tool_output(t("history.cleared"))

    def _drop_all_files(self):
        self.coder.abs_fnames = set()

        if self.original_read_only_fnames:
            to_keep = set()
            for abs_fname in self.coder.abs_read_only_fnames:
                rel_fname = self.coder.get_rel_fname(abs_fname)
                if (
                    abs_fname in self.original_read_only_fnames
                    or rel_fname in self.original_read_only_fnames
                ):
                    to_keep.add(abs_fname)
            self.coder.abs_read_only_fnames = to_keep
        else:
            self.coder.abs_read_only_fnames = set()

    def _clear_chat_history(self):
        self.coder.done_messages = []
        self.coder.cur_messages = []

    def cmd_reset(self, args):
        "Drop all files and clear the chat history"
        self._drop_all_files()
        self._clear_chat_history()
        self.io.tool_output(t("chat.all_dropped"))

    def cmd_tokens(self, args):
        "Report on the number of tokens used by the current chat context"

        res = []

        self.coder.choose_fence()

        main_sys = self.coder.fmt_system_prompt(self.coder.gpt_prompts.main_system)
        main_sys += "\n" + self.coder.fmt_system_prompt(self.coder.gpt_prompts.system_reminder)
        msgs = [
            dict(role="system", content=main_sys),
            dict(
                role="system",
                content=self.coder.fmt_system_prompt(self.coder.gpt_prompts.system_reminder),
            ),
        ]

        tokens = self.coder.main_model.token_count(msgs)
        res.append((tokens, "system messages", ""))

        msgs = self.coder.done_messages + self.coder.cur_messages
        if msgs:
            tokens = self.coder.main_model.token_count(msgs)
            res.append((tokens, "chat history", "use /clear to clear"))

        other_files = set(self.coder.get_all_abs_files()) - set(self.coder.abs_fnames)
        if self.coder.repo_map:
            repo_content = self.coder.repo_map.get_repo_map(self.coder.abs_fnames, other_files)
            if repo_content:
                tokens = self.coder.main_model.token_count(repo_content)
                res.append((tokens, "repository map", "use --map-tokens to resize"))

        fence = "`" * 3

        file_res = []
        for fname in self.coder.abs_fnames:
            relative_fname = self.coder.get_rel_fname(fname)
            content = self.io.read_text(fname)
            if is_image_file(relative_fname):
                tokens = self.coder.main_model.token_count_for_image(fname)
            else:
                content = f"{relative_fname}\n{fence}\n" + content + "{fence}\n"
                tokens = self.coder.main_model.token_count(content)
            file_res.append((tokens, f"{relative_fname}", "/drop to remove"))

        for fname in self.coder.abs_read_only_fnames:
            relative_fname = self.coder.get_rel_fname(fname)
            content = self.io.read_text(fname)
            if content is not None and not is_image_file(relative_fname):
                content = f"{relative_fname}\n{fence}\n" + content + "{fence}\n"
                tokens = self.coder.main_model.token_count(content)
                file_res.append((tokens, f"{relative_fname} (read-only)", "/drop to remove"))

        file_res.sort()
        res.extend(file_res)

        self.io.tool_output(
            t("tokens.context_usage", model=self.coder.main_model.name)
        )
        self.io.tool_output()

        width = 8
        cost_width = 9

        def fmt(v):
            return format(int(v), ",").rjust(width)

        col_width = max(len(row[1]) for row in res)

        cost_pad = " " * cost_width
        total = 0
        total_cost = 0.0
        for tk, msg, tip in res:
            total += tk
            cost = tk * (self.coder.main_model.info.get("input_cost_per_token") or 0)
            total_cost += cost
            msg = msg.ljust(col_width)
            self.io.tool_output(f"${cost:7.4f} {fmt(tk)} {msg} {tip}")  # noqa: E231

        self.io.tool_output("=" * (width + cost_width + 1))
        self.io.tool_output(f"${total_cost:7.4f} {fmt(total)} {t('tokens.total')}")  # noqa: E231

        limit = self.coder.main_model.info.get("max_input_tokens") or 0
        if not limit:
            return

        remaining = limit - total
        if remaining > 1024:
            self.io.tool_output(f"{cost_pad}{fmt(remaining)} {t('tokens.remaining', count=remaining)}")
        elif remaining > 0:
            self.io.tool_error(
                f"{cost_pad}{fmt(remaining)} {t('tokens.remaining_warning', count=remaining)}"
            )
        else:
            self.io.tool_error(
                f"{cost_pad}{fmt(remaining)} {t('tokens.exhausted', count=remaining)}"
            )
        self.io.tool_output(f"{cost_pad}{fmt(limit)} {t('tokens.max_size', count=limit)}")

    def cmd_undo(self, args):
        "Undo the last git commit if it was done by Lora Code"
        try:
            self.raw_cmd_undo(args)
        except ANY_GIT_ERROR as err:
            self.io.tool_error(t("cmd.unable_complete", cmd_name="undo", error=err))

    def raw_cmd_undo(self, args):
        if not self.coder.repo:
            self.io.tool_error(t("git.no_repo"))
            return

        last_commit = self.coder.repo.get_head_commit()
        if not last_commit or not last_commit.parents:
            self.io.tool_error(t("git.first_commit"))
            return

        last_commit_hash = self.coder.repo.get_head_commit_sha(short=True)
        last_commit_message = self.coder.repo.get_head_commit_message("(unknown)").strip()
        last_commit_message = (last_commit_message.splitlines() or [""])[0]
        if last_commit_hash not in self.coder.loracode_commit_hashes:
            self.io.tool_error(t("undo.not_loracode"))
            self.io.tool_output(t("undo.destructive_hint"))
            return

        if len(last_commit.parents) > 1:
            self.io.tool_error(t("undo.multiple_parents", hash=last_commit.hexsha))
            return

        prev_commit = last_commit.parents[0]
        changed_files_last_commit = [item.a_path for item in last_commit.diff(prev_commit)]

        for fname in changed_files_last_commit:
            if self.coder.repo.repo.is_dirty(path=fname):
                self.io.tool_error(t("undo.uncommitted_changes", filename=fname))
                return

            try:
                prev_commit.tree[fname]
            except KeyError:
                self.io.tool_error(t("undo.not_in_previous", filename=fname))
                return

        local_head = self.coder.repo.repo.git.rev_parse("HEAD")
        current_branch = self.coder.repo.repo.active_branch.name
        try:
            remote_head = self.coder.repo.repo.git.rev_parse(f"origin/{current_branch}")
            has_origin = True
        except ANY_GIT_ERROR:
            has_origin = False

        if has_origin:
            if local_head == remote_head:
                self.io.tool_error(t("undo.already_pushed"))
                return

        restored = set()
        unrestored = set()
        for file_path in changed_files_last_commit:
            try:
                self.coder.repo.repo.git.checkout("HEAD~1", file_path)
                restored.add(file_path)
            except ANY_GIT_ERROR:
                unrestored.add(file_path)

        if unrestored:
            self.io.tool_error(t("undo.error_restoring", filename=file_path))
            self.io.tool_output(t("undo.restored_files"))
            for file in restored:
                self.io.tool_output(f"  {file}")
            self.io.tool_output(t("undo.unable_restore"))
            for file in unrestored:
                self.io.tool_output(f"  {file}")
            return

        self.coder.repo.repo.git.reset("--soft", "HEAD~1")

        self.io.tool_output(t("undo.removed", hash=last_commit_hash, message=last_commit_message))

        current_head_hash = self.coder.repo.get_head_commit_sha(short=True)
        current_head_message = self.coder.repo.get_head_commit_message("(unknown)").strip()
        current_head_message = (current_head_message.splitlines() or [""])[0]
        self.io.tool_output(t("undo.now_at", hash=current_head_hash, message=current_head_message))

        if self.coder.main_model.send_undo_reply:
            return prompts.undo_command_reply

    def cmd_diff(self, args=""):
        "Display the diff of changes since the last message"
        try:
            self.raw_cmd_diff(args)
        except ANY_GIT_ERROR as err:
            self.io.tool_error(t("cmd.unable_complete", cmd_name="diff", error=err))

    def raw_cmd_diff(self, args=""):
        if not self.coder.repo:
            self.io.tool_error(t("git.no_repo"))
            return

        current_head = self.coder.repo.get_head_commit_sha()
        if current_head is None:
            self.io.tool_error(t("git.unable_get_commit"))
            return

        if len(self.coder.commit_before_message) < 2:
            commit_before_message = current_head + "^"
        else:
            commit_before_message = self.coder.commit_before_message[-2]

        if not commit_before_message or commit_before_message == current_head:
            self.io.tool_warning(t("git.no_changes_display"))
            return

        self.io.tool_output(t("diff.since", commit=commit_before_message[:7]))

        if self.coder.pretty:
            run_cmd(f"git diff {commit_before_message}")
            return

        diff = self.coder.repo.diff_commits(
            self.coder.pretty,
            commit_before_message,
            "HEAD",
        )

        self.io.print(diff)

    def quote_fname(self, fname):
        if " " in fname and '"' not in fname:
            fname = f'"{fname}"'
        return fname

    def completions_raw_read_only(self, document, complete_event):
        text = document.text_before_cursor

        after_command = text.split()[-1]

        new_document = Document(after_command, cursor_position=len(after_command))

        def get_paths():
            return [self.coder.root] if self.coder.root else None

        path_completer = PathCompleter(
            get_paths=get_paths,
            only_directories=False,
            expanduser=True,
        )

        adjusted_start_position = -len(after_command)

        all_completions = []

        for completion in path_completer.get_completions(new_document, complete_event):
            quoted_text = self.quote_fname(after_command + completion.text)
            all_completions.append(
                Completion(
                    text=quoted_text,
                    start_position=adjusted_start_position,
                    display=completion.display,
                    style=completion.style,
                    selected_style=completion.selected_style,
                )
            )

        add_completions = self.completions_add()
        for completion in add_completions:
            if after_command in completion:
                all_completions.append(
                    Completion(
                        text=completion,
                        start_position=adjusted_start_position,
                        display=completion,
                    )
                )

        sorted_completions = sorted(all_completions, key=lambda c: c.text)

        for completion in sorted_completions:
            yield completion

    def completions_add(self):
        files = set(self.coder.get_all_relative_files())
        files = files - set(self.coder.get_inchat_relative_files())
        files = [self.quote_fname(fn) for fn in files]
        return files

    def glob_filtered_to_repo(self, pattern):
        if not pattern.strip():
            return []
        try:
            if os.path.isabs(pattern):
                raw_matched_files = [Path(pattern)]
            else:
                try:
                    raw_matched_files = list(Path(self.coder.root).glob(pattern))
                except (IndexError, AttributeError):
                    raw_matched_files = []
        except ValueError as err:
            self.io.tool_error(f"Error matching {pattern}: {err}")
            raw_matched_files = []

        matched_files = []
        for fn in raw_matched_files:
            matched_files += expand_subdir(fn)

        matched_files = [
            fn.relative_to(self.coder.root)
            for fn in matched_files
            if fn.is_relative_to(self.coder.root)
        ]

        if self.coder.repo:
            git_files = self.coder.repo.get_tracked_files()
            matched_files = [fn for fn in matched_files if str(fn) in git_files]

        res = list(map(str, matched_files))
        return res

    def cmd_add(self, args):
        "Add files to the chat so Lora Code can edit them or review them in detail"

        all_matched_files = set()

        filenames = parse_quoted_filenames(args)
        for word in filenames:
            if Path(word).is_absolute():
                fname = Path(word)
            else:
                fname = Path(self.coder.root) / word

            if self.coder.repo and self.coder.repo.ignored_file(fname):
                self.io.tool_warning(t("file.skipping_ignore", filename=fname))
                continue

            if fname.exists():
                if fname.is_file():
                    all_matched_files.add(str(fname))
                    continue
                word = re.sub(r"([\*\?\[\]])", r"[\1]", word)

            matched_files = self.glob_filtered_to_repo(word)
            if matched_files:
                all_matched_files.update(matched_files)
                continue

            if "*" in str(fname) or "?" in str(fname):
                self.io.tool_error(t("file.no_match_wildcard", filename=fname))
                continue

            if fname.exists() and fname.is_dir() and self.coder.repo:
                self.io.tool_error(t("git.not_in_git", filename=fname))
                self.io.tool_output(t("git.add_hint", filename=fname))
                continue

            if self.io.confirm_ask(t("file.create_confirm", pattern=word, filename=fname),
                    category=ApprovalCategory.FILE_CREATE):
                try:
                    fname.parent.mkdir(parents=True, exist_ok=True)
                    fname.touch()
                    all_matched_files.add(str(fname))
                except OSError as e:
                    self.io.tool_error(t("file.error_creating", filename=fname, error=e))

        for matched_file in sorted(all_matched_files):
            abs_file_path = self.coder.abs_root_path(matched_file)

            if not abs_file_path.startswith(self.coder.root) and not is_image_file(matched_file):
                self.io.tool_error(t("file.not_within_root", filename=abs_file_path, root=self.coder.root))
                continue

            if (
                self.coder.repo
                and self.coder.repo.git_ignored_file(matched_file)
                and not self.coder.add_gitignore_files
            ):
                self.io.tool_error(t("file.cant_add_gitignore", filename=matched_file))
                continue

            if abs_file_path in self.coder.abs_fnames:
                self.io.tool_error(t("file.already_editable", filename=matched_file))
                continue
            elif abs_file_path in self.coder.abs_read_only_fnames:
                if self.coder.repo and self.coder.repo.path_in_repo(matched_file):
                    self.coder.abs_read_only_fnames.remove(abs_file_path)
                    self.coder.abs_fnames.add(abs_file_path)
                    self.io.tool_output(t("file.moved_to_editable", filename=matched_file))
                else:
                    self.io.tool_error(t("file.not_in_repo", filename=matched_file))
            else:
                if is_image_file(matched_file) and not self.coder.main_model.info.get(
                    "supports_vision"
                ):
                    self.io.tool_error(t("file.no_vision_support", filename=matched_file, model=self.coder.main_model.name))
                    continue
                content = self.io.read_text(abs_file_path)
                if content is None:
                    self.io.tool_error(t("file.unable_read", filename=matched_file))
                else:
                    self.coder.abs_fnames.add(abs_file_path)
                    fname = self.coder.get_rel_fname(abs_file_path)
                    self.io.tool_output(t("file.added", filename=fname))
                    self.coder.check_added_files()

    def completions_drop(self):
        files = self.coder.get_inchat_relative_files()
        read_only_files = [self.coder.get_rel_fname(fn) for fn in self.coder.abs_read_only_fnames]
        all_files = files + read_only_files
        all_files = [self.quote_fname(fn) for fn in all_files]
        return all_files

    def cmd_drop(self, args=""):
        "Remove files from the chat session to free up context space"

        if not args.strip():
            if self.original_read_only_fnames:
                self.io.tool_output(t("file.dropping_all_except"))
            else:
                self.io.tool_output(t("file.dropping_all"))
            self._drop_all_files()
            return

        filenames = parse_quoted_filenames(args)
        for word in filenames:
            expanded_word = os.path.expanduser(word)

            read_only_matched = []
            for f in self.coder.abs_read_only_fnames:
                if expanded_word in f:
                    read_only_matched.append(f)
                    continue

                try:
                    abs_word = os.path.abspath(expanded_word)
                    if os.path.samefile(abs_word, f):
                        read_only_matched.append(f)
                except (FileNotFoundError, OSError):
                    continue

            for matched_file in read_only_matched:
                self.coder.abs_read_only_fnames.remove(matched_file)
                self.io.tool_output(t("file.removed_readonly", filename=matched_file))

            if any(c in expanded_word for c in "*?[]"):
                matched_files = self.glob_filtered_to_repo(expanded_word)
            else:
                matched_files = [
                    self.coder.get_rel_fname(f) for f in self.coder.abs_fnames if expanded_word in f
                ]

            if not matched_files:
                matched_files.append(expanded_word)

            for matched_file in matched_files:
                abs_fname = self.coder.abs_root_path(matched_file)
                if abs_fname in self.coder.abs_fnames:
                    self.coder.abs_fnames.remove(abs_fname)
                    self.io.tool_output(t("file.removed", filename=matched_file))

    def cmd_git(self, args):
        "Run a git command (output excluded from chat)"
        combined_output = None
        try:
            args = "git " + args
            env = dict(subprocess.os.environ)
            env["GIT_EDITOR"] = "true"
            result = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                shell=True,
                encoding=self.io.encoding,
                errors="replace",
            )
            combined_output = result.stdout
        except Exception as e:
            self.io.tool_error(t("git.error_running", error=e))

        if combined_output is None:
            return

        self.io.tool_output(combined_output)

    def cmd_test(self, args):
        "Run a shell command and add the output to the chat on non-zero exit code"
        if not args and self.coder.test_cmd:
            args = self.coder.test_cmd

        if not args:
            return

        if not callable(args):
            if type(args) is not str:
                raise ValueError(repr(args))
            return self.cmd_run(args, True)

        errors = args()
        if not errors:
            return

        self.io.tool_output(errors)
        return errors

    def cmd_run(self, args, add_on_nonzero_exit=False):
        "Run a shell command and optionally add the output to the chat (alias: !)"
        exit_status, combined_output = run_cmd(
            args, verbose=self.verbose, error_print=self.io.tool_error, cwd=self.coder.root
        )

        if combined_output is None:
            return

        token_count = self.coder.main_model.token_count(combined_output)
        k_tokens = token_count / 1000

        if add_on_nonzero_exit:
            add = exit_status != 0
        else:
            add = self.io.confirm_ask(f"Add {k_tokens:.1f}k tokens of command output to the chat?")

        if add:
            num_lines = len(combined_output.strip().splitlines())
            line_plural = "line" if num_lines == 1 else "lines"
            self.io.tool_output(f"Added {num_lines} {line_plural} of output to the chat.")

            msg = prompts.run_output.format(
                command=args,
                output=combined_output,
            )

            self.coder.cur_messages += [
                dict(role="user", content=msg),
                dict(role="assistant", content="Ok."),
            ]

            if add_on_nonzero_exit and exit_status != 0:
                return msg
            elif add and exit_status != 0:
                self.io.placeholder = "What's wrong? Fix"

        return None

    def cmd_exit(self, args):
        "Exit the application"
        self.coder.event("exit", reason="/exit")
        sys.exit()

    def cmd_quit(self, args):
        "Exit the application"
        self.cmd_exit(args)

    def cmd_ls(self, args):
        "List all known files and indicate which are included in the chat session"

        files = self.coder.get_all_relative_files()

        other_files = []
        chat_files = []
        read_only_files = []
        for file in files:
            abs_file_path = self.coder.abs_root_path(file)
            if abs_file_path in self.coder.abs_fnames:
                chat_files.append(file)
            else:
                other_files.append(file)

        for abs_file_path in self.coder.abs_read_only_fnames:
            rel_file_path = self.coder.get_rel_fname(abs_file_path)
            read_only_files.append(rel_file_path)

        if not chat_files and not other_files and not read_only_files:
            self.io.tool_output("\n" + t("ls.no_files"))
            return

        if other_files:
            self.io.tool_output(t("ls.repo_files") + "\n")
        for file in other_files:
            self.io.tool_output(f"  {file}")

        if read_only_files:
            self.io.tool_output("\n" + t("ls.read_only") + "\n")
        for file in read_only_files:
            self.io.tool_output(f"  {file}")

        if chat_files:
            self.io.tool_output("\n" + t("ls.chat_files") + "\n")
        for file in chat_files:
            self.io.tool_output(f"  {file}")

    def basic_help(self):
        commands = sorted(self.get_commands())
        pad = max(len(cmd) for cmd in commands)
        pad = "{cmd:" + str(pad) + "}"
        for cmd in commands:
            cmd_method_name = f"cmd_{cmd[1:]}".replace("-", "_")
            cmd_method = getattr(self, cmd_method_name, None)
            cmd_name = cmd[1:].replace("-", "_")
            cmd_display = pad.format(cmd=cmd)
            
            i18n_key = f"cmd.{cmd_name}"
            description = t(i18n_key)
            
            if description == i18n_key and cmd_method and cmd_method.__doc__:
                description = cmd_method.__doc__
            elif description == i18n_key:
                description = t('command.no_description')
                
            self.io.tool_output(f"{cmd_display} {description}")
        self.io.tool_output()
        self.io.tool_output(t("help.usage"))

    def cmd_help(self, args):
        "Ask questions about Lora Code"

        if not args.strip():
            self.basic_help()
            return

        self.coder.event("interactive help")
        from loracode.coders.base_coder import Coder

        if not self.help:
            res = install_help_extra(self.io)
            if not res:
                self.io.tool_error(t("help.unable_init"))
                return

            self.help = Help()

        coder = Coder.create(
            io=self.io,
            from_coder=self.coder,
            edit_format="help",
            summarize_from_coder=False,
            map_tokens=512,
            map_mul_no_files=1,
        )
        user_msg = self.help.ask(args)
        user_msg += """
# Announcement lines from when this session of Lora Code was launched:

"""
        user_msg += "\n".join(self.coder.get_announcements()) + "\n"

        coder.run(user_msg, preproc=False)

        if self.coder.repo_map:
            map_tokens = self.coder.repo_map.max_map_tokens
            map_mul_no_files = self.coder.repo_map.map_mul_no_files
        else:
            map_tokens = 0
            map_mul_no_files = 1

        raise SwitchCoder(
            edit_format=self.coder.edit_format,
            summarize_from_coder=False,
            from_coder=coder,
            map_tokens=map_tokens,
            map_mul_no_files=map_mul_no_files,
            show_announcements=False,
        )

    def completions_ask(self):
        raise CommandCompletionException()

    def completions_code(self):
        raise CommandCompletionException()

    def completions_architect(self):
        raise CommandCompletionException()

    def completions_context(self):
        raise CommandCompletionException()

    def cmd_ask(self, args):
        """Ask questions about the code base without editing any files. If no prompt provided, switches to ask mode."""  # noqa
        return self._generic_chat_command(args, "ask")

    def cmd_code(self, args):
        """Ask for changes to your code. If no prompt provided, switches to code mode."""  # noqa
        return self._generic_chat_command(args, self.coder.main_model.edit_format)

    def cmd_architect(self, args):
        """Enter architect/editor mode using 2 different models. If no prompt provided, switches to architect/editor mode."""  # noqa
        return self._generic_chat_command(args, "architect")

    def cmd_context(self, args):
        """Enter context mode to see surrounding code context. If no prompt provided, switches to context mode."""  # noqa
        return self._generic_chat_command(args, "context", placeholder=args.strip() or None)

    def _generic_chat_command(self, args, edit_format, placeholder=None):
        if not args.strip():
            return self.cmd_chat_mode(edit_format)

        from loracode.coders.base_coder import Coder

        coder = Coder.create(
            io=self.io,
            from_coder=self.coder,
            edit_format=edit_format,
            summarize_from_coder=False,
        )

        user_msg = args
        coder.run(user_msg)

        raise SwitchCoder(
            edit_format=self.coder.edit_format,
            summarize_from_coder=False,
            from_coder=coder,
            show_announcements=False,
            placeholder=placeholder,
        )

    def get_help_md(self):
        "Show help about all commands in markdown"

        res = """
|Command|Description|
|:------|:----------|
"""
        commands = sorted(self.get_commands())
        for cmd in commands:
            cmd_method_name = f"cmd_{cmd[1:]}".replace("-", "_")
            cmd_method = getattr(self, cmd_method_name, None)
            if cmd_method:
                description = cmd_method.__doc__
                res += f"| **{cmd}** | {description} |\n"
            else:
                res += f"| **{cmd}** | |\n"

        res += "\n"
        return res

    def cmd_voice(self, args):
        "Record and transcribe voice input"

        if not self.voice:
            if "OPENAI_API_KEY" not in os.environ:
                self.io.tool_error("To use /voice you must provide an OpenAI API key.")
                return
            try:
                self.voice = voice.Voice(
                    audio_format=self.voice_format or "wav", device_name=self.voice_input_device
                )
            except voice.SoundDeviceError:
                self.io.tool_error(
                    "Unable to import `sounddevice` and/or `soundfile`, is portaudio installed?"
                )
                return

        try:
            text = self.voice.record_and_transcribe(None, language=self.voice_language)
        except litellm.OpenAIError as err:
            self.io.tool_error(f"Unable to use OpenAI whisper model: {err}")
            return

        if text:
            self.io.placeholder = text

    def cmd_paste(self, args):
        """Paste image/text from the clipboard into the chat.\
        Optionally provide a name for the image."""
        try:
            image = ImageGrab.grabclipboard()
            if isinstance(image, Image.Image):
                if args.strip():
                    filename = args.strip()
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in (".jpg", ".jpeg", ".png"):
                        basename = filename
                    else:
                        basename = f"{filename}.png"
                else:
                    basename = "clipboard_image.png"

                temp_dir = tempfile.mkdtemp()
                temp_file_path = os.path.join(temp_dir, basename)
                image_format = "PNG" if basename.lower().endswith(".png") else "JPEG"
                image.save(temp_file_path, image_format)

                abs_file_path = Path(temp_file_path).resolve()

                existing_file = next(
                    (f for f in self.coder.abs_fnames if Path(f).name == abs_file_path.name), None
                )
                if existing_file:
                    self.coder.abs_fnames.remove(existing_file)
                    self.io.tool_output(f"Replaced existing image in the chat: {existing_file}")

                self.coder.abs_fnames.add(str(abs_file_path))
                self.io.tool_output(f"Added clipboard image to the chat: {abs_file_path}")
                self.coder.check_added_files()

                return

            text = pyperclip.paste()
            if text:
                self.io.tool_output(text)
                return text

            self.io.tool_error(t("clipboard.no_content"))
            return

        except Exception as e:
            self.io.tool_error(f"Error processing clipboard content: {e}")

    def cmd_read_only(self, args):
        "Add files to the chat that are for reference only, or turn added files to read-only"
        if not args.strip():
            for fname in list(self.coder.abs_fnames):
                self.coder.abs_fnames.remove(fname)
                self.coder.abs_read_only_fnames.add(fname)
                rel_fname = self.coder.get_rel_fname(fname)
                self.io.tool_output(f"Converted {rel_fname} to read-only")
            return

        filenames = parse_quoted_filenames(args)
        all_paths = []

        for pattern in filenames:
            expanded_pattern = expanduser(pattern)
            path_obj = Path(expanded_pattern)
            is_abs = path_obj.is_absolute()
            if not is_abs:
                path_obj = Path(self.coder.root) / path_obj

            matches = []
            if path_obj.exists():
                matches = [path_obj]
            else:
                if is_abs:
                    matches = [Path(p) for p in glob.glob(expanded_pattern)]
                else:
                    matches = list(Path(self.coder.root).glob(expanded_pattern))

            if not matches:
                self.io.tool_error(f"No matches found for: {pattern}")
            else:
                all_paths.extend(matches)

        for path in sorted(all_paths):
            abs_path = self.coder.abs_root_path(path)
            if os.path.isfile(abs_path):
                self._add_read_only_file(abs_path, path)
            elif os.path.isdir(abs_path):
                self._add_read_only_directory(abs_path, path)
            else:
                self.io.tool_error(f"Not a file or directory: {abs_path}")

    def _add_read_only_file(self, abs_path, original_name):
        if is_image_file(original_name) and not self.coder.main_model.info.get("supports_vision"):
            self.io.tool_error(
                f"Cannot add image file {original_name} as the"
                f" {self.coder.main_model.name} does not support images."
            )
            return

        if abs_path in self.coder.abs_read_only_fnames:
            self.io.tool_error(f"{original_name} is already in the chat as a read-only file")
            return
        elif abs_path in self.coder.abs_fnames:
            self.coder.abs_fnames.remove(abs_path)
            self.coder.abs_read_only_fnames.add(abs_path)
            self.io.tool_output(
                f"Moved {original_name} from editable to read-only files in the chat"
            )
        else:
            self.coder.abs_read_only_fnames.add(abs_path)
            self.io.tool_output(f"Added {original_name} to read-only files.")

    def _add_read_only_directory(self, abs_path, original_name):
        added_files = 0
        for root, _, files in os.walk(abs_path):
            for file in files:
                file_path = os.path.join(root, file)
                if (
                    file_path not in self.coder.abs_fnames
                    and file_path not in self.coder.abs_read_only_fnames
                ):
                    self.coder.abs_read_only_fnames.add(file_path)
                    added_files += 1

        if added_files > 0:
            self.io.tool_output(
                f"Added {added_files} files from directory {original_name} to read-only files."
            )
        else:
            self.io.tool_output(f"No new files added from directory {original_name}.")

    def cmd_map(self, args):
        "Print out the current repository map"
        repo_map = self.coder.get_repo_map()
        if repo_map:
            self.io.tool_output(repo_map)
        else:
            self.io.tool_output(t("repomap.no_map"))

    def cmd_map_refresh(self, args):
        "Force a refresh of the repository map"
        repo_map = self.coder.get_repo_map(force_refresh=True)
        if repo_map:
            self.io.tool_output(t("repomap.refreshed"))

    def cmd_settings(self, args):
        "Print out the current settings"
        settings = format_settings(self.parser, self.args)
        announcements = "\n".join(self.coder.get_announcements())

        model_sections = []
        active_models = [
            ("Main model", self.coder.main_model),
            ("Editor model", getattr(self.coder.main_model, "editor_model", None)),
            ("Weak model", getattr(self.coder.main_model, "weak_model", None)),
        ]
        for label, model in active_models:
            if not model:
                continue
            info = getattr(model, "info", {}) or {}
            if not info:
                continue
            model_sections.append(f"{label} ({model.name}):")
            for k, v in sorted(info.items()):
                model_sections.append(f"  {k}: {v}")
            model_sections.append("")

        model_metadata = "\n".join(model_sections)

        output = f"{announcements}\n{settings}"
        if model_metadata:
            output += "\n" + model_metadata
        self.io.tool_output(output)

    def completions_raw_load(self, document, complete_event):
        return self.completions_raw_read_only(document, complete_event)

    def cmd_load(self, args):
        "Load and execute commands from a file"
        if not args.strip():
            self.io.tool_error(t("load.provide_file"))
            return

        try:
            with open(args.strip(), "r", encoding=self.io.encoding, errors="replace") as f:
                commands = f.readlines()
        except FileNotFoundError:
            self.io.tool_error(f"File not found: {args}")
            return
        except Exception as e:
            self.io.tool_error(f"Error reading file: {e}")
            return

        for cmd in commands:
            cmd = cmd.strip()
            if not cmd or cmd.startswith("#"):
                continue

            self.io.tool_output(f"\nExecuting: {cmd}")
            try:
                self.run(cmd)
            except SwitchCoder:
                self.io.tool_error(
                    f"Command '{cmd}' is only supported in interactive mode, skipping."
                )

    def completions_raw_save(self, document, complete_event):
        return self.completions_raw_read_only(document, complete_event)

    def cmd_save(self, args):
        "Save commands to a file that can reconstruct the current chat session's files"
        if not args.strip():
            self.io.tool_error(t("save.provide_file"))
            return

        try:
            with open(args.strip(), "w", encoding=self.io.encoding) as f:
                f.write("/drop\n")
                for fname in sorted(self.coder.abs_fnames):
                    rel_fname = self.coder.get_rel_fname(fname)
                    f.write(f"/add       {rel_fname}\n")

                for fname in sorted(self.coder.abs_read_only_fnames):
                    if Path(fname).is_relative_to(self.coder.root):
                        rel_fname = self.coder.get_rel_fname(fname)
                        f.write(f"/read-only {rel_fname}\n")
                    else:
                        f.write(f"/read-only {fname}\n")

            self.io.tool_output(f"Saved commands to {args.strip()}")
        except Exception as e:
            self.io.tool_error(t("save.error", error=str(e)))

    def cmd_multiline_mode(self, args):
        "Toggle multiline mode (swaps behavior of Enter and Meta+Enter)"
        self.io.toggle_multiline_mode()

    def cmd_language(self, args):
        "Switch the UI language (en=English, tr=Türkçe)"
        from loracode.i18n import set_language, get_current_language, get_supported_languages, t
        
        args = args.strip().lower()
        
        if not args:
            current = get_current_language()
            supported = get_supported_languages()
            self.io.tool_output(f"Current language: {supported.get(current, current)} ({current})")
            self.io.tool_output("Available languages:")
            for code, name in supported.items():
                marker = " *" if code == current else ""
                self.io.tool_output(f"  {code}: {name}{marker}")
            return
        
        if set_language(args):
            supported = get_supported_languages()
            self.io.tool_output(f"Language changed to: {supported.get(args, args)} ({args})")
        else:
            supported = get_supported_languages()
            self.io.tool_error(f"Invalid language: {args}")
            self.io.tool_output(f"Available languages: {', '.join(supported.keys())}")

    def completions_language(self):
        "Completions for /language command"
        from loracode.i18n import get_supported_languages
        return list(get_supported_languages().keys())

    def cmd_copy(self, args):
        "Copy the last assistant message to the clipboard"
        all_messages = self.coder.done_messages + self.coder.cur_messages
        assistant_messages = [msg for msg in reversed(all_messages) if msg["role"] == "assistant"]

        if not assistant_messages:
            self.io.tool_error(t("clipboard.no_messages"))
            return

        last_assistant_message = assistant_messages[0]["content"]

        try:
            pyperclip.copy(last_assistant_message)
            preview = (
                last_assistant_message[:50] + "..."
                if len(last_assistant_message) > 50
                else last_assistant_message
            )
            self.io.tool_output(t("clipboard.copied") + f" Preview: {preview}")
        except pyperclip.PyperclipException as e:
            self.io.tool_error(t("clipboard.copy_failed", error=str(e)))
            self.io.tool_output(
                "You may need to install xclip or xsel on Linux, or pbcopy on macOS."
            )
        except Exception as e:
            self.io.tool_error(t("clipboard.unexpected_error", error=str(e)))

    def cmd_report(self, args):
        "Report a problem by opening a GitHub Issue"
        from loracode.report import report_github_issue

        announcements = "\n".join(self.coder.get_announcements())
        issue_text = announcements

        if args.strip():
            title = args.strip()
        else:
            title = None

        report_github_issue(issue_text, title=title, confirm=False)

    def cmd_editor(self, initial_content=""):
        "Open an editor to write a prompt"

        user_input = pipe_editor(initial_content, suffix="md", editor=self.editor)
        if user_input.strip():
            self.io.set_placeholder(user_input.rstrip())

    def cmd_edit(self, args=""):
        "Alias for /editor: Open an editor to write a prompt"
        return self.cmd_editor(args)

    def cmd_think_tokens(self, args):
        """Set the thinking token budget, eg: 8096, 8k, 10.5k, 0.5M, or 0 to disable."""
        model = self.coder.main_model

        if not args.strip():
            formatted_budget = model.get_thinking_tokens()
            if formatted_budget is None:
                self.io.tool_output("Thinking tokens are not currently set.")
            else:
                budget = model.get_raw_thinking_tokens()
                self.io.tool_output(
                    f"Current thinking token budget: {budget:,} tokens ({formatted_budget})."
                )
            return

        value = args.strip()
        model.set_thinking_tokens(value)

        if value == "0":
            self.io.tool_output("Thinking tokens disabled.")
        else:
            formatted_budget = model.get_thinking_tokens()
            budget = model.get_raw_thinking_tokens()
            self.io.tool_output(
                f"Set thinking token budget to {budget:,} tokens ({formatted_budget})."
            )

        self.io.tool_output()

        announcements = "\n".join(self.coder.get_announcements())
        self.io.tool_output(announcements)

    def cmd_copy_context(self, args=None):
        """Copy the current chat context as markdown, suitable to paste into a web UI"""

        chunks = self.coder.format_chat_chunks()

        markdown = ""

        for messages in [chunks.repo, chunks.readonly_files, chunks.chat_files]:
            for msg in messages:
                if msg["role"] != "user":
                    continue

                content = msg["content"]

                if isinstance(content, list):
                    for part in content:
                        if part.get("type") == "text":
                            markdown += part["text"] + "\n\n"
                else:
                    markdown += content + "\n\n"

        args = args or ""
        markdown += f"""
Just tell me how to edit the files to make the changes.
Don't give me back entire files.
Just show me the edits I need to make.

{args}
"""

        try:
            pyperclip.copy(markdown)
            self.io.tool_output(t("clipboard.context_copied"))
        except pyperclip.PyperclipException as e:
            self.io.tool_error(t("clipboard.copy_failed", error=str(e)))
            self.io.tool_output(
                "You may need to install xclip or xsel on Linux, or pbcopy on macOS."
            )
        except Exception as e:
            self.io.tool_error(t("clipboard.unexpected_error", error=str(e)))

    def cmd_auth(self, args):
        "Manage Lora Code authentication (login, logout, status)"
        args = args.strip().lower()
        
        if args == "login":
            self._auth_login()
        elif args == "logout":
            self._auth_logout()
        elif args == "status":
            self._auth_status()
        else:
            self.io.tool_output(t("auth.usage"))
            self.io.tool_output("")
            self.io.tool_output(t("auth.commands"))
            self.io.tool_output("  " + t("auth.cmd_login"))
            self.io.tool_output("  " + t("auth.cmd_logout"))
            self.io.tool_output("  " + t("auth.cmd_status"))

    def _auth_login(self):
        """Initiate login flow using GitHub Device Flow."""
        try:
            auth = LoraCodeAuth()
            
            if auth.is_authenticated():
                credentials = auth.get_credentials()
                if credentials:
                    self.io.tool_output(t("auth.already_authenticated", email=credentials.email))
                    if not self.io.confirm_ask(t("auth.reauth_prompt"), default="n"):
                        return
            
            self.io.tool_output(t("auth.starting"))
            self.io.tool_output("")
            
            def display_callback(user_code, verification_uri):
                self.io.tool_output(t("auth.to_authenticate"))
                self.io.tool_output("  " + t("auth.open_url", url=verification_uri))
                self.io.tool_output("  " + t("auth.enter_code", code=user_code))
                self.io.tool_output("")
                self.io.tool_output(t("auth.waiting"))
            
            def poll_callback():
                return True
            
            result = auth.login_with_device_flow(
                display_callback=display_callback,
                poll_callback=poll_callback
            )
            
            if result.success:
                auth.save_credentials(result.credentials)
                self.io.tool_output("")
                self.io.tool_output(t("auth.successful"))
                self.io.tool_output("  " + t("auth.email", email=result.credentials.email))
                self.io.tool_output("  " + t("auth.plan", plan=result.credentials.plan))
            else:
                self.io.tool_error(t("auth.failed", error=result.error_message))
                
        except Exception as e:
            self.io.tool_error(t("auth.error", error=str(e)))

    def _auth_logout(self):
        """Clear stored credentials."""
        try:
            auth = LoraCodeAuth()
            
            if not auth.is_authenticated():
                credentials = auth.get_credentials()
                if credentials is None:
                    self.io.tool_output(t("auth.no_credentials"))
                    return
            
            if not self.io.confirm_ask(t("auth.logout_confirm"), default="y"):
                return
            
            auth.delete_credentials()
            self.io.tool_output(t("auth.logged_out"))
            
        except Exception as e:
            self.io.tool_error(t("auth.logout_error", error=str(e)))

    def _auth_status(self):
        """Show current authentication status and user info."""
        try:
            auth = LoraCodeAuth()
            credentials = auth.get_credentials()
            
            if credentials is None:
                self.io.tool_output(t("auth.not_authenticated"))
                self.io.tool_output(t("auth.run_login"))
                return
            
            is_expired = auth.is_token_expired(credentials)
            
            self.io.tool_output(t("auth.status_title"))
            self.io.tool_output("=" * 35)
            self.io.tool_output("  " + t("auth.email", email=credentials.email))
            self.io.tool_output("  " + t("auth.plan", plan=credentials.plan))
            self.io.tool_output(f"  User ID: {credentials.user_id}")
            self.io.tool_output(f"  Token Status: {t('auth.token_expired') if is_expired else t('auth.token_valid')}")
            
            if not is_expired:
                try:
                    client = LoraCodeClient(auth=auth)
                    user_info = client.get_user_info()
                    
                    self.io.tool_output("")
                    self.io.tool_output(t("user.account") + ":")
                    self.io.tool_output("-" * 35)
                    
                    if "email" in user_info:
                        self.io.tool_output("  " + t("auth.email", email=user_info['email']))
                    
                    if "plan" in user_info:
                        self.io.tool_output("  " + t("user.plan") + f": {user_info['plan']}")
                    
                    usage = user_info.get("usage", {})
                    limits = user_info.get("limits", {})
                    
                    if usage or limits:
                        self.io.tool_output("")
                        self.io.tool_output(t("user.usage_stats") + ":")
                        self.io.tool_output("-" * 35)
                        
                        requests_used = usage.get("requests", usage.get("requests_used", 0))
                        requests_limit = limits.get("requests", limits.get("requests_limit", 0))
                        if requests_limit > 0:
                            remaining = requests_limit - requests_used
                            self.io.tool_output(f"  {t('user.requests')}: {requests_used:,} / {requests_limit:,} ({t('user.remaining')}: {remaining:,})")
                        elif requests_used > 0:
                            self.io.tool_output(f"  {t('user.requests')}: {requests_used:,}")
                        
                        tokens_used = usage.get("tokens", usage.get("tokens_used", 0))
                        tokens_limit = limits.get("tokens", limits.get("tokens_limit", 0))
                        if tokens_limit > 0:
                            remaining = tokens_limit - tokens_used
                            self.io.tool_output(f"  {t('user.tokens')}: {tokens_used:,} / {tokens_limit:,} ({t('user.remaining')}: {remaining:,})")
                        elif tokens_used > 0:
                            self.io.tool_output(f"  {t('user.tokens')}: {tokens_used:,}")
                        
                        if "remaining" in usage:
                            self.io.tool_output(f"  {t('user.remaining_quota')}: {usage['remaining']:,}")
                        
                        if "period_start" in user_info:
                            self.io.tool_output(f"  {t('user.period_start')}: {user_info['period_start']}")
                        if "period_end" in user_info:
                            self.io.tool_output(f"  {t('user.period_end')}: {user_info['period_end']}")
                            
                except LoraCodeClientError as e:
                    self.io.tool_warning(t("auth.fetch_info_failed", error=str(e)))
            else:
                self.io.tool_output("")
                self.io.tool_warning(t("auth.token_expired_reauth"))
                
        except Exception as e:
            self.io.tool_error(t("auth.status_error", error=str(e)))

    def completions_auth(self):
        """Provide completions for auth subcommands."""
        return ["login", "logout", "status"]

    def cmd_auto_approve(self, args):
        "Set categories to auto-approve (always accept)"
        if not args.strip():
            self.io.tool_output("Usage: /auto-approve <category1,category2,...>")
            self.io.tool_output(f"Available categories: {', '.join(ApprovalCategory.all_categories())}, all")
            return
        
        categories = [cat.strip().lower() for cat in args.split(",") if cat.strip()]
        
        if not categories:
            self.io.tool_error("No categories specified")
            return
        
        manager = self.io.auto_approve_manager
        if not manager:
            self.io.tool_error("Auto-approve manager not available")
            return
        
        # Handle 'all' special case
        if "all" in categories:
            manager.set_all(ApprovalRule.ALWAYS)
            self.io.tool_output("All categories set to auto-approve")
            return
        
        # Validate and apply categories
        valid_categories = ApprovalCategory.all_categories()
        applied = []
        invalid = []
        
        for cat_name in categories:
            if cat_name in valid_categories:
                category = ApprovalCategory.from_string(cat_name)
                manager.set_rule(category, ApprovalRule.ALWAYS)
                applied.append(cat_name)
            else:
                invalid.append(cat_name)
        
        if applied:
            self.io.tool_output(f"Set to auto-approve: {', '.join(applied)}")
        if invalid:
            self.io.tool_warning(f"Invalid categories ignored: {', '.join(invalid)}")

    def completions_auto_approve(self):
        """Provide completions for auto-approve command."""
        return ApprovalCategory.all_categories() + ["all"]

    def cmd_auto_reject(self, args):
        "Set categories to auto-reject (always deny)"
        if not args.strip():
            self.io.tool_output("Usage: /auto-reject <category1,category2,...>")
            self.io.tool_output(f"Available categories: {', '.join(ApprovalCategory.all_categories())}, all")
            return
        
        categories = [cat.strip().lower() for cat in args.split(",") if cat.strip()]
        
        if not categories:
            self.io.tool_error("No categories specified")
            return
        
        manager = self.io.auto_approve_manager
        if not manager:
            self.io.tool_error("Auto-approve manager not available")
            return
        
        # Handle 'all' special case
        if "all" in categories:
            manager.set_all(ApprovalRule.NEVER)
            self.io.tool_output("All categories set to auto-reject")
            return
        
        # Validate and apply categories
        valid_categories = ApprovalCategory.all_categories()
        applied = []
        invalid = []
        
        for cat_name in categories:
            if cat_name in valid_categories:
                category = ApprovalCategory.from_string(cat_name)
                manager.set_rule(category, ApprovalRule.NEVER)
                applied.append(cat_name)
            else:
                invalid.append(cat_name)
        
        if applied:
            self.io.tool_output(f"Set to auto-reject: {', '.join(applied)}")
        if invalid:
            self.io.tool_warning(f"Invalid categories ignored: {', '.join(invalid)}")

    def completions_auto_reject(self):
        """Provide completions for auto-reject command."""
        return ApprovalCategory.all_categories() + ["all"]

    def cmd_auto_ask(self, args):
        "Reset categories to prompt mode (ask user)"
        if not args.strip():
            self.io.tool_output("Usage: /auto-ask <category1,category2,...>")
            self.io.tool_output(f"Available categories: {', '.join(ApprovalCategory.all_categories())}, all")
            return
        
        categories = [cat.strip().lower() for cat in args.split(",") if cat.strip()]
        
        if not categories:
            self.io.tool_error("No categories specified")
            return
        
        manager = self.io.auto_approve_manager
        if not manager:
            self.io.tool_error("Auto-approve manager not available")
            return
        
        # Handle 'all' special case
        if "all" in categories:
            manager.set_all(ApprovalRule.ASK)
            self.io.tool_output("All categories reset to ask mode")
            return
        
        # Validate and apply categories
        valid_categories = ApprovalCategory.all_categories()
        applied = []
        invalid = []
        
        for cat_name in categories:
            if cat_name in valid_categories:
                category = ApprovalCategory.from_string(cat_name)
                manager.set_rule(category, ApprovalRule.ASK)
                applied.append(cat_name)
            else:
                invalid.append(cat_name)
        
        if applied:
            self.io.tool_output(f"Reset to ask mode: {', '.join(applied)}")
        if invalid:
            self.io.tool_warning(f"Invalid categories ignored: {', '.join(invalid)}")

    def completions_auto_ask(self):
        """Provide completions for auto-ask command."""
        return ApprovalCategory.all_categories() + ["all"]

    def cmd_auto_status(self, args):
        "Display current auto-approval settings"
        manager = self.io.auto_approve_manager
        if not manager:
            self.io.tool_error("Auto-approve manager not available")
            return
        
        self.io.tool_output(manager.get_status_display())

    def cmd_auto_history(self, args):
        "Display recent auto-approval decisions"
        manager = self.io.auto_approve_manager
        if not manager:
            self.io.tool_error("Auto-approve manager not available")
            return
        
        history = manager.get_history(limit=20)
        
        if not history:
            self.io.tool_output("No auto-approval decisions recorded yet.")
            return
        
        self.io.tool_output("Recent Auto-Approval Decisions:")
        self.io.tool_output("-" * 50)
        
        for decision in history:
            timestamp = decision.timestamp.strftime("%H:%M:%S")
            result_str = "✓ approved" if decision.result else "✗ rejected"
            auto_str = "(auto)" if decision.auto_decided else "(user)"
            
            self.io.tool_output(
                f"  [{timestamp}] {decision.category.value}: {result_str} {auto_str}"
            )
            if decision.subject:
                # Truncate long subjects
                subject = decision.subject[:50] + "..." if len(decision.subject) > 50 else decision.subject
                self.io.tool_output(f"           Subject: {subject}")


def expand_subdir(file_path):
    if file_path.is_file():
        yield file_path
        return

    if file_path.is_dir():
        for file in file_path.rglob("*"):
            if file.is_file():
                yield file


def parse_quoted_filenames(args):
    filenames = re.findall(r"\"(.+?)\"|(\S+)", args)
    filenames = [name for sublist in filenames for name in sublist if name]
    return filenames


def get_help_md():
    md = Commands(None, None).get_help_md()
    return md


def main():
    md = get_help_md()
    print(md)


if __name__ == "__main__":
    status = main()
    sys.exit(status)
