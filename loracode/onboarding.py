import os

from loracode import urls
from loracode.io import InputOutput
from loracode.i18n import t


def try_to_select_default_model():
    if os.environ.get("LORA_CODE_API_KEY"):
        return "lora-code-v1"

    try:
        from loracode.lora_code_auth import LoraCodeAuth
        auth = LoraCodeAuth()
        if auth.is_authenticated():
            return "lora-code-v1"
    except Exception:
        pass

    return None


def offer_lora_code_auth(io, analytics):
    io.tool_output(t("auth.intro"))
    
    if io.confirm_ask(
        t("onboarding.login_prompt"),
        default="y",
    ):
        analytics.event("oauth_flow_initiated", provider="lora_code")
        
        try:
            from loracode.lora_code_auth import LoraCodeAuth
            auth = LoraCodeAuth()
            result = auth.login_with_device_flow(io)
            
            if result.success:
                analytics.event("oauth_flow_success", provider="lora_code")
                io.tool_output(t("auth.success"))
                return True
            else:
                analytics.event("oauth_flow_failure", provider="lora_code")
                io.tool_error(t("auth.failed", error=result.error_message))
                return False
        except Exception as e:
            analytics.event("oauth_flow_failure", provider="lora_code", reason=str(e))
            io.tool_error(t("auth.error", error=str(e)))
            return False

    return False


def select_default_model(args, io, analytics):
    if args.model:
        return args.model

    model = try_to_select_default_model()
    if model:
        io.tool_warning(t("onboarding.using_model", model=model))
        analytics.event("auto_model_selection", model=model)
        return model

    no_model_msg = t("onboarding.no_model")
    io.tool_warning(no_model_msg)

    offer_lora_code_auth(io, analytics)

    model = try_to_select_default_model()
    if model:
        return model

    io.offer_url(urls.models_and_keys, "Open documentation URL for more info?")
    return None


class DummyAnalytics:
    def event(self, *args, **kwargs):
        pass


def main():
    print(t("onboarding.test_starting"))

    io = InputOutput(
        pretty=True,
        yes=False,
        input_history_file=None,
        chat_history_file=None,
        tool_output_color="BLUE",
        tool_error_color="RED",
    )
    analytics = DummyAnalytics()

    model = try_to_select_default_model()
    if model:
        print(t("onboarding.already_authenticated", model=model))
    else:
        print(t("onboarding.no_credentials"))
        if offer_lora_code_auth(io, analytics):
            print(t("onboarding.auth_successful"))
        else:
            print(t("onboarding.auth_failed"))

    print("\n" + t("onboarding.test_finished"))


if __name__ == "__main__":
    main()
