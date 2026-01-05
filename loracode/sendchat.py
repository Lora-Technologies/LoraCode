from loracode.dump import dump  # noqa: F401
from loracode.utils import format_messages


def sanity_check_messages(messages):
    last_role = None
    last_non_system_role = None

    for msg in messages:
        role = msg.get("role")
        if role == "system":
            continue

        if last_role and role == last_role:
            turns = format_messages(messages)
            raise ValueError("Messages don't properly alternate user/assistant:\n\n" + turns)

        last_role = role
        last_non_system_role = role

    return last_non_system_role == "user"


def ensure_alternating_roles(messages):
    if not messages:
        return messages

    fixed_messages = []
    prev_role = None

    for msg in messages:
        current_role = msg.get("role")

        if current_role == prev_role:
            if current_role == "user":
                fixed_messages.append({"role": "assistant", "content": ""})
            else:
                fixed_messages.append({"role": "user", "content": ""})

        fixed_messages.append(msg)
        prev_role = current_role

    return fixed_messages
