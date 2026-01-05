def scrub_sensitive_info(args, text):
    if text and hasattr(args, 'api_key') and args.api_key:
        last_4 = args.api_key[-4:]
        text = text.replace(args.api_key, f"...{last_4}")
    return text


def format_settings(parser, args):
    show = scrub_sensitive_info(args, parser.format_values())
    heading_env = "Environment Variables:"
    heading_defaults = "Defaults:"
    if heading_env in show:
        show = show.replace(heading_env, "\n" + heading_env)
        show = show.replace(heading_defaults, "\n" + heading_defaults)
    show += "\n"
    show += "Option settings:\n"
    for arg, val in sorted(vars(args).items()):
        if val:
            val = scrub_sensitive_info(args, str(val))
        show += f"  - {arg}: {val}\n" 
    return show
