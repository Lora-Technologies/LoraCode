"""
LoraCode CLI entry point with automatic authentication flow.

Run with: python -m loracode
"""

import sys
import os
import time
from pathlib import Path

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        pass
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except:
        pass

CYAN = "\033[38;2;86;156;214m"
GRAY = "\033[38;2;150;150;150m"
DIM = "\033[38;2;100;100;100m"
GREEN = "\033[38;2;78;201;176m"
YELLOW = "\033[38;2;204;167;0m"
RED = "\033[38;2;244;71;71m"
WHITE = "\033[38;2;212;212;212m"
ORANGE = "\033[38;2;232;145;45m"
ORANGE2 = "\033[38;2;200;120;40m"
RESET = "\033[0m"
BOLD = "\033[1m"

BANNER = f"""
{ORANGE}  _                     {ORANGE2}____          _      {RESET}
{ORANGE} | |    ___  _ __ __ _ {ORANGE2}/ ___|___   __| | ___ {RESET}
{ORANGE} | |   / _ \\| '__/ _` |{ORANGE2}| |   / _ \\ / _` |/ _ \\{RESET}
{ORANGE} | |__| (_) | | | (_| |{ORANGE2}| |__| (_) | (_| |  __/{RESET}
{ORANGE} |_____\\___/|_|  \\__,_|{ORANGE2}\\____\\___/ \\__,_|\\___|{RESET}
                                              
{DIM}  AI-powered coding assistant{RESET}
"""

BANNER_COMPACT = f"""
{ORANGE}*{RESET} {WHITE}LoraCode{RESET} {DIM}· AI coding assistant{RESET}
"""


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def get_terminal_width():
    try:
        return os.get_terminal_size().columns
    except:
        return 80


def show_banner():
    width = get_terminal_width()
    if width >= 55:
        print(BANNER)
    else:
        print(BANNER_COMPACT)


def spinner_frames():
    return ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def show_status(message, status="info"):
    icons = {
        "info": f"{CYAN}*{RESET}",
        "success": f"{GREEN}+{RESET}",
        "warning": f"{YELLOW}!{RESET}",
        "error": f"{RED}x{RESET}",
        "loading": f"{CYAN}~{RESET}",
    }
    icon = icons.get(status, icons["info"])
    print(f"  {icon} {message}")


_failed_login_attempts = 0
_last_failed_attempt_time = 0
_MAX_FAILED_ATTEMPTS = 3
_LOCKOUT_DURATION = 30


def _check_login_rate_limit():
    global _failed_login_attempts, _last_failed_attempt_time
    
    if _failed_login_attempts >= _MAX_FAILED_ATTEMPTS:
        elapsed = time.time() - _last_failed_attempt_time
        remaining = _LOCKOUT_DURATION - elapsed
        
        if remaining > 0:
            return True, int(remaining)
        else:
            _failed_login_attempts = 0
            _last_failed_attempt_time = 0
    
    return False, 0


def _record_failed_login():
    global _failed_login_attempts, _last_failed_attempt_time
    _failed_login_attempts += 1
    _last_failed_attempt_time = time.time()


def _reset_login_attempts():
    global _failed_login_attempts, _last_failed_attempt_time
    _failed_login_attempts = 0
    _last_failed_attempt_time = 0


def check_authentication():
    try:
        from loracode.lora_code_auth import LoraCodeAuth
        
        auth = LoraCodeAuth()
        
        api_key = os.environ.get("LORA_CODE_API_KEY")
        if api_key:
            is_locked, remaining = _check_login_rate_limit()
            if is_locked:
                return False, None, f"Cok fazla basarisiz deneme. {remaining} saniye bekleyin."
            
            result = auth.login_with_api_key(api_key)
            if result.success:
                _reset_login_attempts()
                auth.save_credentials(result.credentials)
                return True, result.credentials, None
            else:
                _record_failed_login()
                return False, None, result.error_message
        
        if auth.is_authenticated():
            creds = auth.get_credentials()
            return True, creds, None
        
        return False, None, None
        
    except Exception as e:
        return False, None, str(e)


def prompt_for_login():
    is_locked, remaining = _check_login_rate_limit()
    if is_locked:
        print()
        show_status(f"Cok fazla basarisiz deneme. {remaining} saniye bekleyin.", "warning")
        print(f"  {DIM}GitHub ile giris yapmak icin 2'yi secebilirsiniz.{RESET}")
        print()
    
    print()
    print(f"  {WHITE}Giris Yontemi Secin:{RESET}")
    print()
    print(f"  {ORANGE}1{RESET} {DIM}>{RESET} API Key ile giris")
    print(f"  {ORANGE}2{RESET} {DIM}>{RESET} GitHub ile giris")
    print()
    
    try:
        choice = input(f"  {ORANGE}>{RESET} Seciminiz [1/2]: ").strip()
        
        if choice == "1":
            return login_with_api_key()
        elif choice == "2":
            return login_with_github()
        else:
            show_status("Gecersiz secim", "error")
            return False
            
    except KeyboardInterrupt:
        print(f"\n  {DIM}Iptal edildi{RESET}")
        return False
    except Exception as e:
        show_status(f"Hata: {e}", "error")
        return False


def login_with_api_key():
    from loracode.lora_code_auth import LoraCodeAuth
    
    is_locked, remaining = _check_login_rate_limit()
    if is_locked:
        show_status(f"Cok fazla basarisiz deneme. {remaining} saniye bekleyin.", "warning")
        return False
    
    print()
    print(f"  {DIM}API anahtarinizi girin{RESET}")
    print(f"  {DIM}https://loratech.dev adresinden alabilirsiniz{RESET}")
    print()
    
    try:
        api_key = input(f"  {ORANGE}>{RESET} API Key: ").strip()
        
        if not api_key:
            show_status("API anahtari bos olamaz", "error")
            return False
        
        print(f"\n  {DIM}Dogrulaniyor...{RESET}", end="", flush=True)
        
        auth = LoraCodeAuth()
        result = auth.login_with_api_key(api_key)
        
        print("\r" + " " * 40 + "\r", end="")
        
        if result.success:
            _reset_login_attempts()
            auth.save_credentials(result.credentials)
            show_status("Giris basarili!", "success")
            if result.credentials and result.credentials.email:
                print(f"      {DIM}Hos geldiniz: {result.credentials.email}{RESET}")
            return True
        else:
            _record_failed_login()
            
            is_locked, remaining = _check_login_rate_limit()
            if is_locked:
                show_status(f"Giris basarisiz: {result.error_message}", "error")
                show_status(f"Cok fazla basarisiz deneme. {remaining} saniye bekleyin.", "warning")
            else:
                attempts_left = _MAX_FAILED_ATTEMPTS - _failed_login_attempts
                show_status(f"Giris basarisiz: {result.error_message}", "error")
                if attempts_left > 0:
                    print(f"      {DIM}Kalan deneme hakki: {attempts_left}{RESET}")
            return False
            
    except KeyboardInterrupt:
        print(f"\n  {DIM}Iptal edildi{RESET}")
        return False
    except Exception as e:
        show_status(f"Hata: {e}", "error")
        return False


def login_with_github():
    """Login with GitHub Device Flow."""
    from loracode.lora_code_auth import LoraCodeAuth
    import webbrowser
    
    print()
    print(f"  {DIM}GitHub ile giris yapiliyor...{RESET}")
    print()
    
    auth = LoraCodeAuth()
    polling_active = True
    
    def display_code(user_code, verification_uri):
        print(f"  {WHITE}Tarayicinizda asagidaki adresi acin:{RESET}")
        print()
        print(f"  {ORANGE}>{RESET} {CYAN}{verification_uri}{RESET}")
        print()
        print(f"  {WHITE}Kodu girin:{RESET}")
        print()
        print(f"  {ORANGE}  [ {WHITE}{user_code}{RESET}{ORANGE} ]{RESET}")
        print()
        print(f"  {DIM}Tarayici otomatik aciliyor...{RESET}")
        
        try:
            webbrowser.open(verification_uri)
        except:
            pass
        
        print()
        print(f"  {DIM}Yetkilendirme bekleniyor... (Ctrl+C ile iptal){RESET}")
    
    def poll_callback():
        return polling_active
    
    try:
        result = auth.login_with_device_flow(
            display_callback=display_code,
            poll_callback=poll_callback
        )
        
        if result.success:
            auth.save_credentials(result.credentials)
            print()
            show_status("GitHub ile giris basarili!", "success")
            if result.credentials:
                if result.credentials.email:
                    print(f"      {DIM}Hos geldiniz: {result.credentials.email}{RESET}")
                if result.credentials.plan:
                    print(f"      {DIM}Plan: {result.credentials.plan}{RESET}")
            return True
        else:
            print()
            show_status(f"Giris basarisiz: {result.error_message}", "error")
            return False
            
    except KeyboardInterrupt:
        polling_active = False
        print(f"\n  {DIM}Iptal edildi{RESET}")
        return False
    except Exception as e:
        show_status(f"Hata: {e}", "error")
        return False


def show_user_info(credentials):
    if not credentials:
        return False
        
    try:
        from loracode.lora_code_client import LoraCodeClient
        from loracode.lora_code_auth import LoraCodeAuth
        
        auth = LoraCodeAuth()
        client = LoraCodeClient(auth=auth)
        
        user_info = client.get_user_info()
        
        if not user_info or not user_info.get("email"):
            return False
        
        email = user_info.get("email", "")
        plan = user_info.get("plan", "free")
        usage = user_info.get("usage", {})
        limits = user_info.get("limits", {})
        
        parts = []
        
        if email:
            parts.append(f"{WHITE}{email}{RESET}")
        
        if plan:
            plan_colors = {
                "free": YELLOW,
                "pro": CYAN,
                "team": GREEN,
                "enterprise": "\033[38;2;197;134;192m"
            }
            color = plan_colors.get(plan.lower(), WHITE)
            parts.append(f"{color}{plan.capitalize()}{RESET}")
        
        requests_used = usage.get("requests", usage.get("requests_used", 0))
        requests_limit = limits.get("requests", limits.get("requests_limit", 0))
        tokens_used = usage.get("tokens", usage.get("tokens_used", 0))
        
        if requests_limit > 0:
            remaining = requests_limit - requests_used
            pct = (remaining / requests_limit) * 100 if requests_limit > 0 else 100
            if pct > 50:
                color = GREEN
            elif pct > 20:
                color = YELLOW
            else:
                color = RED
            parts.append(f"{DIM}Requests:{RESET} {color}{requests_used}/{requests_limit}{RESET}")
        elif requests_used > 0:
            parts.append(f"{DIM}Requests:{RESET} {WHITE}{requests_used}{RESET}")
        
        if tokens_used > 0:
            parts.append(f"{DIM}Tokens:{RESET} {WHITE}{tokens_used:,}{RESET}")
        
        if parts:
            print(f"  {ORANGE}*{RESET} " + f" {DIM}|{RESET} ".join(parts))
            return True
        
        return False
            
    except Exception:
        return False


def main():
    if len(sys.argv) > 1:
        from loracode.main import main as loracode_main
        return loracode_main()
    
    try:
        clear_screen()
        show_banner()
        
        print(f"  {DIM}Kimlik dogrulaniyor...{RESET}", end="", flush=True)
        is_auth, credentials, error = check_authentication()
        print("\r" + " " * 40 + "\r", end="")
        
        if is_auth:
            session_valid = show_user_info(credentials)
            
            if session_valid:
                print()
                print(f"  {DIM}LoraCode baslatiliyor...{RESET}")
                print()
                
                from loracode.main import main as loracode_main
                return loracode_main()
            else:
                show_status("Oturum suresi dolmus, yeniden giris yapiniz", "warning")
                
                try:
                    from loracode.lora_code_auth import LoraCodeAuth
                    auth = LoraCodeAuth()
                    auth.clear_credentials()
                except:
                    pass
                
                if prompt_for_login():
                    print()
                    print(f"  {DIM}LoraCode baslatiliyor...{RESET}")
                    print()
                    
                    from loracode.main import main as loracode_main
                    return loracode_main()
                else:
                    return handle_login_failure()
        
        else:
            if error:
                show_status(f"Kimlik dogrulama hatasi: {error}", "warning")
            else:
                show_status("Oturum acik degil", "info")
            
            if prompt_for_login():
                print()
                print(f"  {DIM}LoraCode baslatiliyor...{RESET}")
                print()
                
                from loracode.main import main as loracode_main
                return loracode_main()
            else:
                return handle_login_failure()
    
    except KeyboardInterrupt:
        print(f"\n\n  {DIM}Gorusmek uzere!{RESET}\n")
        return 0
    except Exception as e:
        print(f"\n  {RED}x{RESET} Beklenmeyen hata: {e}")
        return 1


def handle_login_failure():
    print()
    try:
        choice = input(f"  {YELLOW}?{RESET} Giris yapmadan devam etmek ister misiniz? [e/H]: ").strip().lower()
        if choice in ('e', 'y', 'yes', 'evet'):
            print()
            print(f"  {DIM}LoraCode baslatiliyor...{RESET}")
            print()
            
            from loracode.main import main as loracode_main
            return loracode_main()
        else:
            print(f"\n  {DIM}Gorusmek uzere!{RESET}\n")
            return 0
    except (KeyboardInterrupt, EOFError):
        print(f"\n\n  {DIM}Gorusmek uzere!{RESET}\n")
        return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
