import json
import platform
import sys
import time
import uuid
from pathlib import Path

from mixpanel import MixpanelException
from posthog import Posthog

from loracode import __version__
from loracode.dump import dump  # noqa: F401
from loracode.models import model_info_manager

PERCENT = 10


def compute_hex_threshold(percent):
    return format(int(0xFFFFFF * percent / 100), "06x")


def is_uuid_in_percentage(uuid_str, percent):
    if not (0 <= percent <= 100):
        raise ValueError("Percentage must be between 0 and 100")

    if not uuid_str:
        return False

    if percent == 0:
        return False

    threshold = compute_hex_threshold(percent)
    return uuid_str[:6] <= threshold


mixpanel_project_token = "5c7e00a5d6bd2caf5fdae5fdcf9ecc7c"
posthog_project_api_key = "phc_Ym2rBWIguyx3LXOfuGYvUtPV6EKN38iklAl7CanAFAi"
posthog_host = "https://us.i.posthog.com"


class Analytics:
    mp = None
    ph = None

    user_id = None
    permanently_disable = None
    asked_opt_in = None

    logfile = None

    def __init__(
        self,
        logfile=None,
        permanently_disable=False,
        posthog_host=None,
        posthog_project_api_key=None,
    ):
        self.logfile = logfile
        self.get_or_create_uuid()
        self.custom_posthog_host = posthog_host
        self.custom_posthog_project_api_key = posthog_project_api_key

        if self.permanently_disable or permanently_disable or not self.asked_opt_in:
            self.disable(permanently_disable)

    def enable(self):
        if not self.user_id:
            self.disable(False)
            return

        if self.permanently_disable:
            self.disable(True)
            return

        if not self.asked_opt_in:
            self.disable(False)
            return

        self.ph = Posthog(
            project_api_key=self.custom_posthog_project_api_key or posthog_project_api_key,
            host=self.custom_posthog_host or posthog_host,
            on_error=self.posthog_error,
            enable_exception_autocapture=True,
            super_properties=self.get_system_info(),
        )

    def disable(self, permanently):
        self.mp = None
        self.ph = None

        if permanently:
            self.asked_opt_in = True
            self.permanently_disable = True
            self.save_data()

    def need_to_ask(self, args_analytics):
        if args_analytics is False:
            return False

        could_ask = not self.asked_opt_in and not self.permanently_disable
        if not could_ask:
            return False

        if args_analytics is True:
            return True

        assert args_analytics is None, args_analytics

        if not self.user_id:
            return False

        return is_uuid_in_percentage(self.user_id, PERCENT)

    def get_data_file_path(self):
        try:
            data_file = Path.home() / ".loracode" / "analytics.json"
            data_file.parent.mkdir(parents=True, exist_ok=True)
            return data_file
        except OSError:
            self.disable(permanently=False)
            return None

    def get_or_create_uuid(self):
        self.load_data()
        if self.user_id:
            return

        self.user_id = str(uuid.uuid4())
        self.save_data()

    def load_data(self):
        data_file = self.get_data_file_path()
        if not data_file:
            return

        if data_file.exists():
            try:
                data = json.loads(data_file.read_text())
                self.permanently_disable = data.get("permanently_disable")
                self.user_id = data.get("uuid")
                self.asked_opt_in = data.get("asked_opt_in", False)
            except (json.decoder.JSONDecodeError, OSError):
                self.disable(permanently=False)

    def save_data(self):
        data_file = self.get_data_file_path()
        if not data_file:
            return

        data = dict(
            uuid=self.user_id,
            permanently_disable=self.permanently_disable,
            asked_opt_in=self.asked_opt_in,
        )

        try:
            data_file.write_text(json.dumps(data, indent=4))
        except OSError:
            self.disable(permanently=False)

    def get_system_info(self):
        return {
            "python_version": sys.version.split()[0],
            "os_platform": platform.system(),
            "os_release": platform.release(),
            "machine": platform.machine(),
            "loracode_version": __version__,
        }

    def _redact_model_name(self, model):
        if not model:
            return None

        info = model_info_manager.get_model_from_cached_json_db(model.name)
        if info:
            return model.name
        elif "/" in model.name:
            return model.name.split("/")[0] + "/REDACTED"
        return None

    def posthog_error(self):
        """disable posthog if we get an error"""
        print("X" * 100)
        self.ph = None

    def event(self, event_name, main_model=None, **kwargs):
        if not self.mp and not self.ph and not self.logfile:
            return

        properties = {}

        if main_model:
            properties["main_model"] = self._redact_model_name(main_model)
            properties["weak_model"] = self._redact_model_name(main_model.weak_model)
            properties["editor_model"] = self._redact_model_name(main_model.editor_model)

        properties.update(kwargs)

        for key, value in properties.items():
            if isinstance(value, (int, float)):
                properties[key] = value
            else:
                properties[key] = str(value)

        if self.mp:
            try:
                self.mp.track(self.user_id, event_name, dict(properties))
            except MixpanelException:
                self.mp = None

        if self.ph:
            self.ph.capture(event_name, distinct_id=self.user_id, properties=dict(properties))

        if self.logfile:
            log_entry = {
                "event": event_name,
                "properties": properties,
                "user_id": self.user_id,
                "time": int(time.time()),
            }
            try:
                with open(self.logfile, "a") as f:
                    json.dump(log_entry, f)
                    f.write("\n")
            except OSError:
                pass


if __name__ == "__main__":
    dump(compute_hex_threshold(PERCENT))
