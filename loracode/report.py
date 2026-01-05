import os
import platform
import subprocess
import sys
import traceback
import urllib.parse
import webbrowser

from loracode import __version__
from loracode.urls import github_issues
from loracode.versioncheck import VERSION_CHECK_FNAME

FENCE = "`" * 3


def get_python_info():
    implementation = platform.python_implementation()
    is_venv = sys.prefix != sys.base_prefix
    return (
        f"Python implementation: {implementation}\nVirtual environment:"
        f" {'Yes' if is_venv else 'No'}"
    )


def get_os_info():
    return f"OS: {platform.system()} {platform.release()} ({platform.architecture()[0]})"


def get_git_info():
    try:
        git_version = subprocess.check_output(["git", "--version"]).decode().strip()
        return f"Git version: {git_version}"
    except Exception:
        return "Git information unavailable"


def report_github_issue(issue_text, title=None, confirm=True):
    version_info = f"LoraCode version: {__version__}\n"
    python_version = f"Python version: {sys.version.split()[0]}\n"
    platform_info = f"Platform: {platform.platform()}\n"
    python_info = get_python_info() + "\n"
    os_info = get_os_info() + "\n"
    git_info = get_git_info() + "\n"

    system_info = (
        version_info + python_version + platform_info + python_info + os_info + git_info + "\n"
    )

    issue_text = system_info + issue_text
    params = {"body": issue_text}
    if title is None:
        title = "Bug report"
    params["title"] = title
    issue_url = f"{github_issues}?{urllib.parse.urlencode(params)}"

    if confirm:
        print(f"\n# {title}\n")
        print(issue_text.strip())
        print()
        print("Please consider reporting this bug to help improve LoraCode!")
        prompt = "Open a GitHub Issue pre-filled with the above error in your browser? (Y/n) "
        confirmation = input(prompt).strip().lower()

        yes = not confirmation or confirmation.startswith("y")
        if not yes:
            return

    print("Attempting to open the issue URL in your default web browser...")
    try:
        if webbrowser.open(issue_url):
            print("Browser window should be opened.")
    except Exception:
        pass

    if confirm:
        print()
        print()
        print("You can also use this URL to file the GitHub Issue:")
        print()
        print(issue_url)
        print()
        print()


def exception_handler(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        return sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = None

    try:
        if VERSION_CHECK_FNAME.exists():
            VERSION_CHECK_FNAME.unlink()
    except Exception:
        pass

    tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)

    tb_lines_with_basenames = []
    for line in tb_lines:
        try:
            if "File " in line:
                parts = line.split('"')
                if len(parts) > 1:
                    full_path = parts[1]
                    basename = os.path.basename(full_path)
                    line = line.replace(full_path, basename)
        except Exception:
            pass
        tb_lines_with_basenames.append(line)

    tb_text = "".join(tb_lines_with_basenames)

    innermost_tb = exc_traceback
    while innermost_tb.tb_next:
        innermost_tb = innermost_tb.tb_next

    filename = innermost_tb.tb_frame.f_code.co_filename
    line_number = innermost_tb.tb_lineno
    try:
        basename = os.path.basename(filename)
    except Exception:
        basename = filename

    exception_type = exc_type.__name__

    issue_text = f"An uncaught exception occurred:\n\n{FENCE}\n{tb_text}\n{FENCE}"

    title = f"Uncaught {exception_type} in {basename} line {line_number}"

    report_github_issue(issue_text, title=title)

    sys.__excepthook__(exc_type, exc_value, exc_traceback)


def report_uncaught_exceptions():
    sys.excepthook = exception_handler


def dummy_function1():
    def dummy_function2():
        def dummy_function3():
            raise ValueError("boo")

        dummy_function3()

    dummy_function2()


def main():
    report_uncaught_exceptions()

    dummy_function1()

    title = None
    if len(sys.argv) > 2:
        title = sys.argv[1]
        issue_text = sys.argv[2]
    elif len(sys.argv) > 1:
        issue_text = sys.argv[1]
    else:
        print("Enter the issue title (optional, press Enter to skip):")
        title = input().strip()
        if not title:
            title = None
        print("Enter the issue text (Ctrl+D to finish):")
        issue_text = sys.stdin.read().strip()

    report_github_issue(issue_text, title)


if __name__ == "__main__":
    main()
