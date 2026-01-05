import os
import sys
import time
from pathlib import Path

import packaging.version

import loracode
from loracode import utils
from loracode.dump import dump  # noqa: F401
from loracode.i18n import t

VERSION_CHECK_FNAME = Path.home() / ".loracode" / "caches" / "versioncheck"


def install_from_main_branch(io):
    return utils.check_pip_install_extra(
        io,
        None,
        "Install the development version of LoraCode from the main branch?",
        ["git+https://github.com/loracode/loracode.git"],
        self_update=True,
    )


def install_upgrade(io, latest_version=None):
    if latest_version:
        new_ver_text = t("version.newer_available", version=latest_version)
    else:
        new_ver_text = t("version.install_latest")

    docker_image = os.environ.get("LORACODE_DOCKER_IMAGE")
    if docker_image:
        text = t("version.docker_upgrade", message=new_ver_text, image=docker_image)
        io.tool_warning(text)
        return True

    success = utils.check_pip_install_extra(
        io,
        None,
        new_ver_text,
        ["loracode"],
        self_update=True,
    )

    if success:
        io.tool_output(t("version.rerun"))
        sys.exit()

    return


def check_version(io, just_check=False, verbose=False):
    if not just_check and VERSION_CHECK_FNAME.exists():
        day = 60 * 60 * 24
        since = time.time() - os.path.getmtime(VERSION_CHECK_FNAME)
        if 0 < since < day:
            if verbose:
                hours = since / 60 / 60
                io.tool_output(t("version.too_soon", hours=hours))
            return

    import requests

    try:
        response = requests.get("https://pypi.org/pypi/loracode/json", timeout=5)
        
        if response.status_code == 404:
            if verbose:
                io.tool_output(t("version.not_on_pypi"))
            return False
        
        response.raise_for_status()
        data = response.json()
        
        if "info" not in data or "version" not in data.get("info", {}):
            if verbose:
                io.tool_output(t("version.invalid_response"))
            return False
            
        latest_version = data["info"]["version"]
        current_version = loracode.__version__

        if just_check or verbose:
            io.tool_output(t("version.current", version=current_version))
            io.tool_output(t("version.latest", version=latest_version))

        is_update_available = packaging.version.parse(latest_version) > packaging.version.parse(
            current_version
        )
    except requests.exceptions.RequestException:
        return False
    except Exception as err:
        io.tool_error(t("version.check_error", error=err))
        return False
    finally:
        VERSION_CHECK_FNAME.parent.mkdir(parents=True, exist_ok=True)
        VERSION_CHECK_FNAME.touch()


    if just_check or verbose:
        if is_update_available:
            io.tool_output(t("version.update_available"))
        else:
            io.tool_output(t("version.no_update"))

    if just_check:
        return is_update_available

    if not is_update_available:
        return False

    install_upgrade(io, latest_version)
    return True
