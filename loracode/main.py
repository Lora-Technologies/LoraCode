import json
import os
import re
import sys
import threading
import traceback
import webbrowser
from dataclasses import fields
from pathlib import Path

try:
    import git
except ImportError:
    git = None

import importlib_resources
import shtab
from dotenv import load_dotenv
from prompt_toolkit.enums import EditingMode

from loracode import __version__, models, urls, utils
from loracode.analytics import Analytics
from loracode.i18n import set_language, t, get_current_language
from loracode.args import get_parser
from loracode.coders import Coder
from loracode.coders.base_coder import UnknownEditFormat
from loracode.commands import Commands, SwitchCoder
from loracode.hooks import HookEvent
from loracode.copypaste import ClipboardWatcher
from loracode.deprecated import handle_deprecated_model_args
from loracode.format_settings import format_settings, scrub_sensitive_info
from loracode.history import ChatSummary
from loracode.auto_approve import (
    ApprovalCategory,
    AutoApproveManager,
    validate_auto_approve_args,
    apply_auto_approve_args,
)
from loracode.io import InputOutput
from loracode.lora_code_auth import LoraCodeAuth
from loracode.lora_code_client import LoraCodeClient, LoraCodeClientError
from loracode.models import ModelSettings
from loracode.repo import ANY_GIT_ERROR, GitRepo
from loracode.report import report_uncaught_exceptions
from loracode.versioncheck import check_version, install_from_main_branch, install_upgrade
from loracode.watch import FileWatcher

from .dump import dump


_lora_code_client = None
_lora_code_auth = None


def get_lora_code_client():
    global _lora_code_client, _lora_code_auth
    
    api_base = os.environ.get("LORA_CODE_API_BASE")
    api_key = os.environ.get("LORA_CODE_API_KEY")
    
    _lora_code_auth = LoraCodeAuth(api_base=api_base)
    
    if _lora_code_client is None:
        _lora_code_client = LoraCodeClient(
            api_base=api_base,
            api_key=api_key,
            auth=_lora_code_auth
        )
    else:
        _lora_code_client._auth = _lora_code_auth
        if api_key:
            _lora_code_client._api_key = api_key
    
    return _lora_code_client


def get_lora_code_auth():
    global _lora_code_auth
    
    if _lora_code_auth is None:
        api_base = os.environ.get("LORA_CODE_API_BASE")
        _lora_code_auth = LoraCodeAuth(api_base=api_base)
    
    return _lora_code_auth


def select_lora_code_model(args, io, analytics):
    if args.model:
        return args.model
    
    auth = get_lora_code_auth()
    api_key = os.environ.get("LORA_CODE_API_KEY")
    
    if api_key and not auth.is_authenticated():
        result = auth.login_with_api_key(api_key)
        if result.success:
            auth.save_credentials(result.credentials)
            io.tool_output(t("auth.authenticated"))
        else:
            io.tool_warning(t("auth.failed", error=result.error_message))
    
    if not auth.is_authenticated() and not api_key:
        io.tool_warning(t("auth.no_key"))
        io.tool_output(t("auth.provide_key"))
        io.tool_output(t("auth.or_login"))
        analytics.event("exit", reason="No Lora Code credentials")
        return None
    
    import time
    max_retries = 5
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            client = get_lora_code_client()
            model_ids = client.get_model_ids()
            
            if model_ids:
                default_model = model_ids[0]
                io.tool_output(t("model.using", model=default_model))
                analytics.event("auto_model_selection", model=default_model)
                return default_model
            else:
                io.tool_error(t("model.no_available"))
                analytics.event("exit", reason="No Lora Code models available")
                return None
                
        except LoraCodeClientError as e:
            io.tool_error(t("model.connection_failed", error=e))
            analytics.event("exit", reason="Lora Code API connection failed")
            return None
        except Exception as e:
            error_str = str(e).lower()
            is_rate_limit = "429" in str(e) or "too many requests" in error_str or "rate limit" in error_str
            
            if is_rate_limit and attempt < max_retries - 1:
                wait_time = retry_delay * (attempt + 1)
                io.tool_warning(t("main.rate_limit_retry", wait_time=wait_time, attempt=attempt + 1, max_retries=max_retries))
                time.sleep(wait_time)
                continue
            elif is_rate_limit:
                io.tool_error(t("main.rate_limit_exceeded"))
                io.tool_output(t("main.model_tip"))
            else:
                io.tool_error(t("main.api_error", error=e))
            analytics.event("exit", reason="API error")
            return None
    
    return None


def check_config_files_for_yes(config_files):
    found = False
    for config_file in config_files:
        if Path(config_file).exists():
            try:
                with open(config_file, "r") as f:
                    for line in f:
                        if line.strip().startswith("yes:"):
                            print(t("config.error_detected"))
                            print(t("config.yes_line", filename=config_file))
                            print(t("config.yes_replace"))
                            found = True
            except Exception:
                pass
    return found


def get_git_root():
    try:
        repo = git.Repo(search_parent_directories=True)
        return repo.working_tree_dir
    except (git.InvalidGitRepositoryError, FileNotFoundError):
        return None


def guessed_wrong_repo(io, git_root, fnames, git_dname):
    try:
        check_repo = Path(GitRepo(io, fnames, git_dname).root).resolve()
    except (OSError,) + ANY_GIT_ERROR:
        return

    if not git_root:
        return str(check_repo)

    git_root = Path(git_root).resolve()
    if check_repo == git_root:
        return

    return str(check_repo)


def make_new_repo(git_root, io):
    try:
        repo = git.Repo.init(git_root)
        check_gitignore(git_root, io, False)
    except ANY_GIT_ERROR as err:
        io.tool_error(t("git.unable_to_create", path=git_root))
        io.tool_output(str(err))
        return

    io.tool_output(t("git.repo_created", path=git_root))
    return repo


def setup_git(git_root, io):
    if git is None:
        return

    try:
        cwd = Path.cwd()
    except OSError:
        cwd = None

    repo = None

    if git_root:
        try:
            repo = git.Repo(git_root)
        except ANY_GIT_ERROR:
            pass
    elif cwd == Path.home():
        io.tool_warning(t("git.home_dir_warning"))
        return
    elif cwd and io.confirm_ask(t("git.no_repo_found"),
            category=ApprovalCategory.GIT_REPO):
        git_root = str(cwd.resolve())
        repo = make_new_repo(git_root, io)

    if not repo:
        return

    try:
        user_name = repo.git.config("--get", "user.name") or None
    except git.exc.GitCommandError:
        user_name = None

    try:
        user_email = repo.git.config("--get", "user.email") or None
    except git.exc.GitCommandError:
        user_email = None

    if user_name and user_email:
        return repo.working_tree_dir

    with repo.config_writer() as git_config:
        if not user_name:
            git_config.set_value("user", "name", "Your Name")
            io.tool_warning(t("git.update_name"))
        if not user_email:
            git_config.set_value("user", "email", "you@example.com")
            io.tool_warning(t("git.update_email"))

    return repo.working_tree_dir


def check_gitignore(git_root, io, ask=True):
    if not git_root:
        return

    try:
        repo = git.Repo(git_root)
        patterns_to_add = []

        if not repo.ignored(".loracode"):
            patterns_to_add.append(".loracode*")

        env_path = Path(git_root) / ".env"
        if env_path.exists() and not repo.ignored(".env"):
            patterns_to_add.append(".env")

        if not patterns_to_add:
            return

        gitignore_file = Path(git_root) / ".gitignore"
        if gitignore_file.exists():
            try:
                content = io.read_text(gitignore_file)
                if content is None:
                    return
                if not content.endswith("\n"):
                    content += "\n"
            except OSError as e:
                io.tool_error(t("git.gitignore_error", filename=gitignore_file, error=e))
                return
        else:
            content = ""
    except ANY_GIT_ERROR:
        return

    if ask:
        io.tool_output(t("git.gitignore_skip"))
        patterns_str = ', '.join(patterns_to_add)
        if not io.confirm_ask(t("git.gitignore_add", patterns=patterns_str),
                category=ApprovalCategory.GIT_REPO):
            return

    content += "\n".join(patterns_to_add) + "\n"

    try:
        io.write_text(gitignore_file, content)
        io.tool_output(t("git.gitignore_added", patterns=', '.join(patterns_to_add)))
    except OSError as e:
        io.tool_error(t("git.gitignore_write_error", filename=gitignore_file, error=e))
        io.tool_output(t("git.gitignore_manual"))
        for pattern in patterns_to_add:
            io.tool_output(f"  {pattern}")


def check_streamlit_install(io):
    return utils.check_pip_install_extra(
        io,
        "streamlit",
        "You need to install the LoraCode browser feature",
        ["loracode[browser]"],
    )


def write_streamlit_credentials():
    from streamlit.file_util import get_streamlit_file_path

    credential_path = Path(get_streamlit_file_path()) / "credentials.toml"
    if not os.path.exists(credential_path):
        empty_creds = '[general]\nemail = ""\n'

        os.makedirs(os.path.dirname(credential_path), exist_ok=True)
        with open(credential_path, "w") as f:
            f.write(empty_creds)
    else:
        print("Streamlit credentials already exist.")


def launch_gui(args):
    from streamlit.web import cli

    from loracode import gui

    print()
    print("CONTROL-C to exit...")

    write_streamlit_credentials()

    target = gui.__file__

    st_args = ["run", target]

    st_args += [
        "--browser.gatherUsageStats=false",
        "--runner.magicEnabled=false",
        "--server.runOnSave=false",
    ]

    is_dev = "-dev" in str(__version__)

    if is_dev:
        print("Watching for file changes.")
    else:
        st_args += [
            "--global.developmentMode=false",
            "--server.fileWatcherType=none",
            "--client.toolbarMode=viewer",
        ]

    st_args += ["--"] + args

    cli.main(st_args)



def parse_lint_cmds(lint_cmds, io):
    err = False
    res = dict()
    for lint_cmd in lint_cmds:
        if re.match(r"^[a-z]+:.*", lint_cmd):
            pieces = lint_cmd.split(":")
            lang = pieces[0]
            cmd = lint_cmd[len(lang) + 1 :]
            lang = lang.strip()
        else:
            lang = None
            cmd = lint_cmd

        cmd = cmd.strip()

        if cmd:
            res[lang] = cmd
        else:
            io.tool_error(t("lint.parse_error", cmd=lint_cmd))
            io.tool_output(t("lint.format_hint"))
            io.tool_output(t("lint.example"))
            err = True
    if err:
        return
    return res


def generate_search_path_list(default_file, git_root, command_line_file):
    files = []
    files.append(Path.home() / default_file)
    if git_root:
        files.append(Path(git_root) / default_file)
    files.append(default_file)
    if command_line_file:
        files.append(command_line_file)

    resolved_files = []
    for fn in files:
        try:
            resolved_files.append(Path(fn).resolve())
        except OSError:
            pass

    files = resolved_files
    files.reverse()
    uniq = []
    for fn in files:
        if fn not in uniq:
            uniq.append(fn)
    uniq.reverse()
    files = uniq
    files = list(map(str, files))
    files = list(dict.fromkeys(files))

    return files


def register_models(git_root, model_settings_fname, io, verbose=False):
    model_settings_files = generate_search_path_list(
        ".loracode.model.settings.yml", git_root, model_settings_fname
    )

    try:
        files_loaded = models.register_models(model_settings_files)
        if len(files_loaded) > 0:
            if verbose:
                io.tool_output(t("model.settings_loaded"))
                for file_loaded in files_loaded:
                    io.tool_output(f"  - {file_loaded}")
        elif verbose:
            io.tool_output(t("model.settings_none"))
    except Exception as e:
        io.tool_error(t("model.settings_error", error=e))
        return 1

    if verbose:
        io.tool_output(t("model.settings_searched"))
        for file in model_settings_files:
            io.tool_output(f"  - {file}")

    return None


def load_dotenv_files(git_root, dotenv_fname, encoding="utf-8"):
    dotenv_files = generate_search_path_list(
        ".env",
        git_root,
        dotenv_fname,
    )

    oauth_keys_file = Path.home() / ".loracode" / "oauth-keys.env"
    if oauth_keys_file.exists():
        dotenv_files.insert(0, str(oauth_keys_file.resolve()))
        dotenv_files = list(dict.fromkeys(dotenv_files))

    loaded = []
    for fname in dotenv_files:
        try:
            if Path(fname).exists():
                load_dotenv(fname, override=True, encoding=encoding)
                loaded.append(fname)
        except OSError as e:
            print(f"OSError loading {fname}: {e}")
        except Exception as e:
            print(f"Error loading {fname}: {e}")
    return loaded


def sanity_check_repo(repo, io):
    if not repo:
        return True

    if not repo.repo.working_tree_dir:
        io.tool_error("The git repo does not seem to have a working tree?")
        return False

    bad_ver = False
    try:
        repo.get_tracked_files()
        if not repo.git_repo_error:
            return True
        error_msg = str(repo.git_repo_error)
    except UnicodeDecodeError as exc:
        error_msg = (
            "Failed to read the Git repository. This issue is likely caused by a path encoded "
            f'in a format different from the expected encoding "{sys.getfilesystemencoding()}".\n'
            f"Internal error: {str(exc)}"
        )
    except ANY_GIT_ERROR as exc:
        error_msg = str(exc)
        bad_ver = "version in (1, 2)" in error_msg
    except AssertionError as exc:
        error_msg = str(exc)
        bad_ver = True

    if bad_ver:
        io.tool_error(t("git.version_error"))
        io.tool_output(t("git.version_convert"))
        io.tool_output(t("git.version_no_git"))
        io.offer_url(urls.git_index_version, "Open documentation url for more info?")
        return False

    io.tool_error(t("git.corrupt_repo"))
    io.tool_output(error_msg)
    return False


def main(argv=None, input=None, output=None, force_git_root=None, return_coder=False):
    report_uncaught_exceptions()

    if argv is None:
        argv = sys.argv[1:]

    if git is None:
        git_root = None
    elif force_git_root:
        git_root = force_git_root
    else:
        git_root = get_git_root()

    conf_fname = Path(".loracode.conf.yml")

    default_config_files = []
    try:
        default_config_files += [conf_fname.resolve()]
    except OSError:
        pass

    if git_root:
        git_conf = Path(git_root) / conf_fname
        if git_conf not in default_config_files:
            default_config_files.append(git_conf)
    default_config_files.append(Path.home() / conf_fname)
    default_config_files = list(map(str, default_config_files))

    parser = get_parser(default_config_files, git_root)
    try:
        args, unknown = parser.parse_known_args(argv)
    except AttributeError as e:
        if all(word in str(e) for word in ["bool", "object", "has", "no", "attribute", "strip"]):
            if check_config_files_for_yes(default_config_files):
                return 1
        raise e

    if args.verbose:
        print("Config files search order, if no --config:")
        for file in default_config_files:
            exists = "(exists)" if Path(file).exists() else ""
            print(f"  - {file} {exists}")

    default_config_files.reverse()

    parser = get_parser(default_config_files, git_root)

    args, unknown = parser.parse_known_args(argv)

    loaded_dotenvs = load_dotenv_files(git_root, args.env_file, args.encoding)

    args = parser.parse_args(argv)

    if args.language:
        set_language(args.language)

    if args.shell_completions:
        parser.prog = "loracode"
        print(shtab.complete(parser, shell=args.shell_completions))
        sys.exit(0)

    if git is None:
        args.git = False

    if args.analytics_disable:
        analytics = Analytics(permanently_disable=True)
        print("Analytics have been permanently disabled.")

    if not args.verify_ssl:
        os.environ["SSL_VERIFY"] = ""

    if args.timeout:
        models.request_timeout = args.timeout

    if args.dark_mode:
        args.user_input_color = "#C5C5C5"
        args.tool_output_color = "#8B8B8B"
        args.tool_error_color = "#F44747"
        args.tool_warning_color = "#CCA700"
        args.assistant_output_color = "#D4D4D4"
        args.code_theme = "monokai"

    if args.light_mode:
        args.user_input_color = "#383A42"
        args.tool_output_color = "#696C77"
        args.tool_error_color = "#E45649"
        args.tool_warning_color = "#C18401"
        args.assistant_output_color = "#383A42"
        args.code_theme = "github-dark"

    if return_coder and args.yes_always is None:
        args.yes_always = True

    auto_approve_manager = AutoApproveManager()
    
    is_valid, error_msg, approve_cats, reject_cats = validate_auto_approve_args(
        args.auto_approve, args.auto_reject
    )
    
    if not is_valid:
        print(f"Error: {error_msg}")
        return 1
    
    apply_auto_approve_args(
        auto_approve_manager,
        approve_cats,
        reject_cats,
        yes_always=args.yes_always or False
    )

    editing_mode = EditingMode.VI if args.vim else EditingMode.EMACS

    def get_io(pretty):
        return InputOutput(
            pretty,
            args.yes_always,
            args.input_history_file,
            args.chat_history_file,
            input=input,
            output=output,
            user_input_color=args.user_input_color,
            tool_output_color=args.tool_output_color,
            tool_warning_color=args.tool_warning_color,
            tool_error_color=args.tool_error_color,
            completion_menu_color=args.completion_menu_color,
            completion_menu_bg_color=args.completion_menu_bg_color,
            completion_menu_current_color=args.completion_menu_current_color,
            completion_menu_current_bg_color=args.completion_menu_current_bg_color,
            assistant_output_color=args.assistant_output_color,
            code_theme=args.code_theme,
            dry_run=args.dry_run,
            encoding=args.encoding,
            line_endings=args.line_endings,
            llm_history_file=args.llm_history_file,
            editingmode=editing_mode,
            fancy_input=args.fancy_input,
            multiline_mode=args.multiline,
            notifications=args.notifications,
            notifications_command=args.notifications_command,
            auto_approve_manager=auto_approve_manager,
        )

    io = get_io(args.pretty)
    try:
        io.show_banner(version=__version__)
        
        try:
            api_key = args.api_key or os.environ.get("LORA_CODE_API_KEY")
            if api_key:
                os.environ["LORA_CODE_API_KEY"] = api_key
            if args.api_base:
                os.environ["LORA_CODE_API_BASE"] = args.api_base
            
            global _lora_code_client
            _lora_code_client = None
            
            client = get_lora_code_client()
            if client.is_authenticated():
                user_info = client.get_user_info()
                io.show_user_info(user_info)
        except Exception as e:
            import traceback
            if os.environ.get("LORACODE_DEBUG"):
                traceback.print_exc()
        
        io.rule()
    except UnicodeEncodeError as err:
        if not io.pretty:
            raise err
        io = get_io(False)
        io.tool_warning("Terminal does not support pretty output (UnicodeDecodeError)")

    if args.set_env:
        for env_setting in args.set_env:
            try:
                name, value = env_setting.split("=", 1)
                os.environ[name.strip()] = value.strip()
            except ValueError:
                io.tool_error(t("env.invalid_format", setting=env_setting))
                io.tool_output(t("env.format_hint"))
                return 1

    if args.api_key:
        os.environ["LORA_CODE_API_KEY"] = args.api_key

    if args.api_base:
        os.environ["LORA_CODE_API_BASE"] = args.api_base

    handle_deprecated_model_args(args, io)

    analytics = Analytics(
        logfile=args.analytics_log,
        permanently_disable=args.analytics_disable,
        posthog_host=args.analytics_posthog_host,
        posthog_project_api_key=args.analytics_posthog_project_api_key,
    )
    if args.analytics is not False:
        if analytics.need_to_ask(args.analytics):
            io.tool_output(t("analytics.privacy"))
            io.tool_output(t("analytics.more_info", url=urls.analytics))
            disable = not io.confirm_ask(t("analytics.ask"),
                category=ApprovalCategory.ANALYTICS)

            analytics.asked_opt_in = True
            if disable:
                analytics.disable(permanently=True)
                io.tool_output(t("analytics.disabled"))

            analytics.save_data()
            io.tool_output()

        analytics.enable()

    analytics.event("launched")

    if args.gui and not return_coder:
        if not check_streamlit_install(io):
            analytics.event("exit", reason="Streamlit not installed")
            return
        analytics.event("gui session")
        launch_gui(argv)
        analytics.event("exit", reason="GUI session ended")
        return

    if args.verbose:
        for fname in loaded_dotenvs:
            io.tool_output(t("env.loaded", filename=fname))

    all_files = args.files + (args.file or [])
    fnames = [str(Path(fn).resolve()) for fn in all_files]
    read_only_fnames = []
    for fn in args.read or []:
        path = Path(fn).expanduser().resolve()
        if path.is_dir():
            read_only_fnames.extend(str(f) for f in path.rglob("*") if f.is_file())
        else:
            read_only_fnames.append(str(path))

    if len(all_files) > 1:
        good = True
        for fname in all_files:
            if Path(fname).is_dir():
                io.tool_error(f"{fname} is a directory, not provided alone.")
                good = False
        if not good:
            io.tool_output(
                "Provide either a single directory of a git repo, or a list of one or more files."
            )
            analytics.event("exit", reason="Invalid directory input")
            return 1

    git_dname = None
    if len(all_files) == 1:
        if Path(all_files[0]).is_dir():
            if args.git:
                git_dname = str(Path(all_files[0]).resolve())
                fnames = []
            else:
                io.tool_error(f"{all_files[0]} is a directory, but --no-git selected.")
                analytics.event("exit", reason="Directory with --no-git")
                return 1

    if args.git and not force_git_root and git is not None:
        right_repo_root = guessed_wrong_repo(io, git_root, fnames, git_dname)
        if right_repo_root:
            analytics.event("exit", reason="Recursing with correct repo")
            return main(argv, input, output, right_repo_root, return_coder=return_coder)

    if args.just_check_update:
        update_available = check_version(io, just_check=True, verbose=args.verbose)
        analytics.event("exit", reason="Just checking update")
        return 0 if not update_available else 1

    if args.install_main_branch:
        success = install_from_main_branch(io)
        analytics.event("exit", reason="Installed main branch")
        return 0 if success else 1

    if args.upgrade:
        success = install_upgrade(io)
        analytics.event("exit", reason="Upgrade completed")
        return 0 if success else 1

    if args.check_update:
        check_version(io, verbose=args.verbose)

    if args.git:
        git_root = setup_git(git_root, io)
        if args.gitignore:
            check_gitignore(git_root, io)

    if args.verbose:
        show = format_settings(parser, args)
        io.tool_output(show)

    cmd_line = " ".join(sys.argv)
    cmd_line = scrub_sensitive_info(args, cmd_line)
    io.tool_output(cmd_line, log_only=True)

    is_first_run = is_first_run_of_new_version(io, verbose=args.verbose)
    check_and_load_imports(io, is_first_run, verbose=args.verbose)

    register_models(git_root, args.model_settings_file, io, verbose=args.verbose)

    if args.list_models:
        try:
            client = get_lora_code_client()
            lora_models = client.list_models()
            io.tool_output(t("model.available"))
            for model in lora_models:
                io.tool_output(f"  - {model.id}: {model.description or 'No description'}")
        except LoraCodeClientError as e:
            io.tool_error(t("model.list_failed", error=e))
        analytics.event("exit", reason="Listed models")
        return 0

    if args.alias:
        for alias_def in args.alias:
            parts = alias_def.split(":", 1)
            if len(parts) != 2:
                io.tool_error(t("alias.invalid_format", alias=alias_def))
                io.tool_output(t("alias.format_hint"))
                analytics.event("exit", reason="Invalid alias format error")
                return 1
            alias, model = parts
            models.MODEL_ALIASES[alias.strip()] = model.strip()

    selected_model_name = select_lora_code_model(args, io, analytics)
    if not selected_model_name:
        return 1
    args.model = selected_model_name

    try:
        client = get_lora_code_client()
        client.validate_model(args.model)
    except LoraCodeClientError as e:
        io.tool_error(t("main.model_validation_failed", error=e))
        analytics.event("exit", reason="Lora Code model validation failed")
        return 1

    main_model = models.Model(
        args.model,
        weak_model=args.weak_model,
        editor_model=args.editor_model,
        editor_edit_format=args.editor_edit_format,
        verbose=args.verbose,
    )

    if main_model.remove_reasoning is not None:
        io.tool_warning(t("model.deprecated_reasoning"))

    if args.thinking_tokens is not None:
        if not args.check_model_accepts_settings or (
            main_model.accepts_settings and "thinking_tokens" in main_model.accepts_settings
        ):
            main_model.set_thinking_tokens(args.thinking_tokens)

    if args.check_model_accepts_settings:
        settings_to_check = [
            {"arg": args.thinking_tokens, "name": "thinking_tokens"},
        ]

        for setting in settings_to_check:
            if setting["arg"] is not None and (
                not main_model.accepts_settings
                or setting["name"] not in main_model.accepts_settings
            ):
                io.tool_warning(
                    t("main.setting_not_supported", model=main_model.name, setting=setting["name"])
                )
                io.tool_output(
                    t("main.force_setting_hint", setting=setting["name"])
                )

    if args.copy_paste and args.edit_format is None:
        if main_model.edit_format in ("diff", "whole", "diff-fenced"):
            main_model.edit_format = "editor-" + main_model.edit_format

    if args.verbose:
        io.tool_output(t("model.metadata"))
        io.tool_output(json.dumps(main_model.info, indent=4))

        io.tool_output(t("model.settings"))
        for attr in sorted(fields(ModelSettings), key=lambda x: x.name):
            val = getattr(main_model, attr.name)
            val = json.dumps(val, indent=4)
            io.tool_output(f"{attr.name}: {val}")

    lint_cmds = parse_lint_cmds(args.lint_cmd, io)
    if lint_cmds is None:
        analytics.event("exit", reason="Invalid lint command format")
        return 1

    if args.show_model_warnings:
        problem = models.sanity_check_models(io, main_model)
        if problem:
            analytics.event("model warning", main_model=main_model)
            io.tool_output(t("model.skip_warning"))

            try:
                io.offer_url(urls.model_warnings, "Open documentation url for more info?")
                io.tool_output()
            except KeyboardInterrupt:
                analytics.event("exit", reason="Keyboard interrupt during model warnings")
                return 1

    repo = None
    if args.git:
        try:
            repo = GitRepo(
                io,
                fnames,
                git_dname,
                args.loracodeignore,
                models=main_model.commit_message_models(),
                attribute_author=args.attribute_author,
                attribute_committer=args.attribute_committer,
                attribute_commit_message_author=args.attribute_commit_message_author,
                attribute_commit_message_committer=args.attribute_commit_message_committer,
                commit_prompt=args.commit_prompt,
                subtree_only=args.subtree_only,
                git_commit_verify=args.git_commit_verify,
                attribute_co_authored_by=args.attribute_co_authored_by,
            )
        except FileNotFoundError:
            pass

    if not args.skip_sanity_check_repo:
        if not sanity_check_repo(repo, io):
            analytics.event("exit", reason="Repository sanity check failed")
            return 1

    if repo and not args.skip_sanity_check_repo:
        num_files = len(repo.get_tracked_files())
        analytics.event("repo", num_files=num_files)
    else:
        analytics.event("no-repo")

    commands = Commands(
        io,
        None,
        voice_language=args.voice_language,
        voice_input_device=args.voice_input_device,
        voice_format=args.voice_format,
        verify_ssl=args.verify_ssl,
        args=args,
        parser=parser,
        verbose=args.verbose,
        editor=args.editor,
        original_read_only_fnames=read_only_fnames,
    )

    summarizer = ChatSummary(
        [main_model.weak_model, main_model],
        args.max_chat_history_tokens or main_model.max_chat_history_tokens,
    )

    if args.cache_prompts and args.map_refresh == "auto":
        args.map_refresh = "files"

    if not main_model.streaming:
        if args.stream:
            io.tool_warning(
                t("main.streaming_not_supported", model=main_model.name)
            )
        args.stream = False

    if args.map_tokens is None:
        map_tokens = main_model.get_repo_map_tokens()
    else:
        map_tokens = args.map_tokens

    analytics.event("auto_commits", enabled=bool(args.auto_commits))

    try:
        coder = Coder.create(
            main_model=main_model,
            edit_format=args.edit_format,
            io=io,
            repo=repo,
            fnames=fnames,
            read_only_fnames=read_only_fnames,
            show_diffs=args.show_diffs,
            auto_commits=args.auto_commits,
            dirty_commits=args.dirty_commits,
            dry_run=args.dry_run,
            map_tokens=map_tokens,
            verbose=args.verbose,
            stream=args.stream,
            use_git=args.git,
            restore_chat_history=args.restore_chat_history,
            auto_lint=args.auto_lint,
            auto_test=args.auto_test,
            lint_cmds=lint_cmds,
            test_cmd=args.test_cmd,
            commands=commands,
            summarizer=summarizer,
            analytics=analytics,
            map_refresh=args.map_refresh,
            cache_prompts=args.cache_prompts,
            map_mul_no_files=args.map_multiplier_no_files,
            num_cache_warming_pings=args.cache_keepalive_pings,
            suggest_shell_commands=args.suggest_shell_commands,
            chat_language=args.chat_language,
            commit_language=args.commit_language,
            detect_urls=args.detect_urls,
            auto_copy_context=args.copy_paste,
            auto_accept_architect=args.auto_accept_architect,
            add_gitignore_files=args.add_gitignore_files,
        )
    except UnknownEditFormat as err:
        io.tool_error(str(err))
        io.offer_url(urls.edit_formats, "Open documentation about edit formats?")
        analytics.event("exit", reason="Unknown edit format")
        return 1
    except ValueError as err:
        io.tool_error(str(err))
        analytics.event("exit", reason="ValueError during coder creation")
        return 1

    if return_coder:
        analytics.event("exit", reason="Returning coder object")
        return coder

    ignores = []
    if git_root:
        ignores.append(str(Path(git_root) / ".gitignore"))
    if args.loracodeignore:
        ignores.append(args.loracodeignore)

    if args.watch_files:
        file_watcher = FileWatcher(
            coder,
            gitignores=ignores,
            verbose=args.verbose,
            analytics=analytics,
            root=str(Path.cwd()) if args.subtree_only else None,
        )
        coder.file_watcher = file_watcher

    if args.copy_paste:
        analytics.event("copy-paste mode")
        ClipboardWatcher(coder.io, verbose=args.verbose)


    if coder.hook_manager:
        context = coder.get_hook_context(HookEvent.SESSION_START)
        results = coder.hook_manager.trigger(HookEvent.SESSION_START, context)
        for result in results:
            if result.stdout:
                io.tool_output(result.stdout.strip())

    coder.show_announcements()

    if args.show_prompts:
        coder.cur_messages += [
            dict(role="user", content="Hello!"),
        ]
        messages = coder.format_messages().all_messages()
        utils.show_messages(messages)
        analytics.event("exit", reason="Showed prompts")
        return

    if args.lint:
        coder.commands.cmd_lint(fnames=fnames)

    if args.test:
        if not args.test_cmd:
            io.tool_error(t("test.no_command"))
            analytics.event("exit", reason="No test command provided")
            return 1
        coder.commands.cmd_test(args.test_cmd)
        if io.placeholder:
            coder.run(io.placeholder)

    if args.commit:
        if args.dry_run:
            io.tool_output(t("dry_run.skip_commit"))
        else:
            coder.commands.cmd_commit()

    if args.lint or args.test or args.commit:
        analytics.event("exit", reason="Completed lint/test/commit")
        return

    if args.show_repo_map:
        repo_map = coder.get_repo_map()
        if repo_map:
            io.tool_output(repo_map)
        analytics.event("exit", reason="Showed repo map")
        return

    if args.apply:
        content = io.read_text(args.apply)
        if content is None:
            analytics.event("exit", reason="Failed to read apply content")
            return
        coder.partial_response_content = content
        coder.apply_updates()
        analytics.event("exit", reason="Applied updates")
        return

    if args.apply_clipboard_edits:
        args.edit_format = main_model.editor_edit_format
        args.message = "/paste"

    if args.show_release_notes is True:
        io.tool_output(t("release.opening", url=urls.release_notes))
        io.tool_output()
        webbrowser.open(urls.release_notes)
    elif args.show_release_notes is None and is_first_run:
        io.tool_output()
        io.offer_url(
            urls.release_notes,
            t("release.ask_view"),
            allow_never=False,
        )

    if git_root and Path.cwd().resolve() != Path(git_root).resolve():
        io.tool_warning(t("directory.relative_warning"))

        io.tool_output(t("directory.cur_working", path=Path.cwd()))
        io.tool_output(t("directory.git_working", path=git_root))

    if args.stream and args.cache_prompts:
        io.tool_warning(t("cache.cost_warning"))

    if args.load:
        commands.cmd_load(args.load)

    if args.load_checkpoint:
        commands.cmd_checkpoint_load(args.load_checkpoint)

    if args.message:
        io.add_to_input_history(args.message)
        io.tool_output()
        try:
            coder.run(with_message=args.message)
        except SwitchCoder:
            pass
        if coder.hook_manager:
            context = coder.get_hook_context(HookEvent.SESSION_END)
            coder.hook_manager.trigger(HookEvent.SESSION_END, context)
        analytics.event("exit", reason="Completed --message")
        return

    if args.message_file:
        try:
            message_from_file = io.read_text(args.message_file)
            io.tool_output()
            coder.run(with_message=message_from_file)
        except FileNotFoundError:
            io.tool_error(t("main.message_file_not_found", filename=args.message_file))
            analytics.event("exit", reason="Message file not found")
            return 1
        except IOError as e:
            io.tool_error(t("main.message_file_error", error=e))
            analytics.event("exit", reason="Message file IO error")
            return 1
        if coder.hook_manager:
            context = coder.get_hook_context(HookEvent.SESSION_END)
            coder.hook_manager.trigger(HookEvent.SESSION_END, context)
        analytics.event("exit", reason="Completed --message-file")
        return

    if args.exit:
        analytics.event("exit", reason="Exit flag set")
        return

    analytics.event("cli session", main_model=main_model, edit_format=main_model.edit_format)

    def trigger_session_end():
        if args.save_on_exit:
            checkpoint_name = args.save_on_exit if args.save_on_exit != "auto" else None
            commands.cmd_checkpoint_save(checkpoint_name or "")
        
        if coder.hook_manager:
            context = coder.get_hook_context(HookEvent.SESSION_END)
            results = coder.hook_manager.trigger(HookEvent.SESSION_END, context)
            for result in results:
                if result.stdout:
                    io.tool_output(result.stdout.strip())

    while True:
        try:
            coder.ok_to_warm_cache = bool(args.cache_keepalive_pings)
            coder.run()
            trigger_session_end()
            analytics.event("exit", reason="Completed main CLI coder.run")
            return
        except SwitchCoder as switch:
            coder.ok_to_warm_cache = False

            if hasattr(switch, "placeholder") and switch.placeholder is not None:
                io.placeholder = switch.placeholder

            kwargs = dict(io=io, from_coder=coder)
            kwargs.update(switch.kwargs)
            if "show_announcements" in kwargs:
                del kwargs["show_announcements"]

            coder = Coder.create(**kwargs)

            if switch.kwargs.get("show_announcements") is not False:
                coder.show_announcements()


def is_first_run_of_new_version(io, verbose=False):
    installs_file = Path.home() / ".loracode" / "installs.json"
    key = (__version__, sys.executable)

    if ".dev" in __version__:
        return False

    if verbose:
        io.tool_output(
            f"Checking imports for version {__version__} and executable {sys.executable}"
        )
        io.tool_output(f"Installs file: {installs_file}")

    try:
        if installs_file.exists():
            with open(installs_file, "r") as f:
                installs = json.load(f)
            if verbose:
                io.tool_output(t("imports.file_exists"))
        else:
            installs = {}
            if verbose:
                io.tool_output(t("imports.file_new"))

        is_first_run = str(key) not in installs

        if is_first_run:
            installs[str(key)] = True
            installs_file.parent.mkdir(parents=True, exist_ok=True)
            with open(installs_file, "w") as f:
                json.dump(installs, f, indent=4)

        return is_first_run

    except Exception as e:
        io.tool_warning(t("main.version_check_error", error=e))
        if verbose:
            io.tool_output(f"Full exception details: {traceback.format_exc()}")
        return True


def check_and_load_imports(io, is_first_run, verbose=False):
    try:
        if is_first_run:
            if verbose:
                io.tool_output(t("main.first_run_loading"))
            try:
                load_slow_imports(swallow=False)
            except Exception as err:
                io.tool_error(str(err))
                io.tool_output(t("imports.error"))
                io.offer_url(urls.install_properly, t("imports.open_docs"))
                sys.exit(1)

            if verbose:
                io.tool_output(t("imports.loaded"))
        else:
            if verbose:
                io.tool_output(t("imports.background"))
            thread = threading.Thread(target=load_slow_imports)
            thread.daemon = True
            thread.start()

    except Exception as e:
        io.tool_warning(t("main.imports_loading_error", error=e))
        if verbose:
            io.tool_output(f"Full exception details: {traceback.format_exc()}")


def load_slow_imports(swallow=True):

    try:
        import httpx  
        import networkx
        import numpy
        import requests
    except Exception as e:
        if not swallow:
            raise e


if __name__ == "__main__":
    status = main()
    sys.exit(status)
