import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable
import requests


@dataclass
class Credentials:
    api_key: str
    jwt_token: str
    token_expires_at: str
    user_id: str
    email: str
    plan: str


@dataclass
class AuthResult:
    success: bool
    credentials: Optional[Credentials]
    error_message: Optional[str]


def _get_encryption_key() -> bytes:
    machine_id = ""
    try:
        if os.name == 'nt':
            import subprocess
            result = subprocess.run(
                ['wmic', 'csproduct', 'get', 'uuid'],
                capture_output=True, text=True
            )
            machine_id = result.stdout.strip().split('\n')[-1].strip()
        else:
            for path in ['/etc/machine-id', '/var/lib/dbus/machine-id']:
                if os.path.exists(path):
                    with open(path, 'r') as f:
                        machine_id = f.read().strip()
                    break
    except Exception:
        pass
    
    if not machine_id:
        machine_id = "loracode-default-key"
    
    salt = b"lora-code"
    key = hashlib.pbkdf2_hmac('sha256', machine_id.encode(), salt, 100000)
    return key[:32]


def _xor_encrypt(data: bytes, key: bytes) -> bytes:
    return bytes(d ^ key[i % len(key)] for i, d in enumerate(data))


def encrypt_value(value: str) -> str:
    key = _get_encryption_key()
    encrypted = _xor_encrypt(value.encode('utf-8'), key)
    return base64.b64encode(encrypted).decode('ascii')


def decrypt_value(encrypted_value: str) -> str:
    key = _get_encryption_key()
    encrypted = base64.b64decode(encrypted_value.encode('ascii'))
    decrypted = _xor_encrypt(encrypted, key)
    return decrypted.decode('utf-8')


class LoraCodeAuth:
    
    CREDENTIALS_FILE = os.path.expanduser("~/.loracode/lora-code-credentials.json")
    DEFAULT_API_BASE = "https://api.loratech.dev"
    
    def __init__(self, api_base: str = None):
        self.api_base = api_base or os.environ.get(
            "LORA_CODE_API_BASE", 
            self.DEFAULT_API_BASE
        )
        self._session = requests.Session()
    
    def login_with_api_key(self, api_key: str) -> AuthResult:
        try:
            response = self._session.post(
                f"{self.api_base}/auth/token",
                json={"api_key": api_key},
                timeout=30
            )
            
            if response.status_code == 401:
                return AuthResult(
                    success=False,
                    credentials=None,
                    error_message="Invalid API key"
                )
            
            response.raise_for_status()
            data = response.json()
            
            expires_in = data.get("expires_in", 86400)
            expires_at = datetime.now(timezone.utc).timestamp() + expires_in
            expires_at_iso = datetime.fromtimestamp(
                expires_at, timezone.utc
            ).isoformat()
            
            user_info = self._fetch_user_info(data["access_token"])
            
            credentials = Credentials(
                api_key=api_key,
                jwt_token=data["access_token"],
                token_expires_at=expires_at_iso,
                user_id=user_info.get("id", ""),
                email=user_info.get("email", ""),
                plan=user_info.get("plan", "free")
            )
            
            return AuthResult(
                success=True,
                credentials=credentials,
                error_message=None
            )
            
        except requests.exceptions.ConnectionError:
            return AuthResult(
                success=False,
                credentials=None,
                error_message=f"Cannot connect to Lora Code API at {self.api_base}"
            )
        except requests.exceptions.Timeout:
            return AuthResult(
                success=False,
                credentials=None,
                error_message="Connection to Lora Code API timed out"
            )
        except requests.exceptions.RequestException as e:
            return AuthResult(
                success=False,
                credentials=None,
                error_message=f"Authentication failed: {str(e)}"
            )
        except (KeyError, ValueError) as e:
            return AuthResult(
                success=False,
                credentials=None,
                error_message=f"Invalid response from API: {str(e)}"
            )
    
    def _fetch_user_info(self, token: str) -> dict:
        try:
            response = self._session.get(
                f"{self.api_base}/v1/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            return {}

    
    def save_credentials(self, credentials: Credentials) -> None:
        creds_path = Path(self.CREDENTIALS_FILE)
        creds_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "version": 1,
            "api_key_encrypted": encrypt_value(credentials.api_key),
            "jwt_token_encrypted": encrypt_value(credentials.jwt_token),
            "token_expires_at": credentials.token_expires_at,
            "user": {
                "id": credentials.user_id,
                "email": credentials.email,
                "plan": credentials.plan
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        with open(creds_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def get_credentials(self) -> Optional[Credentials]:
        creds_path = Path(self.CREDENTIALS_FILE)
        
        if not creds_path.exists():
            return None
        
        try:
            with open(creds_path, 'r') as f:
                data = json.load(f)
            
            if data.get("version") != 1:
                return None
            
            api_key = decrypt_value(data["api_key_encrypted"])
            jwt_token = decrypt_value(data["jwt_token_encrypted"])
            
            user = data.get("user", {})
            
            return Credentials(
                api_key=api_key,
                jwt_token=jwt_token,
                token_expires_at=data["token_expires_at"],
                user_id=user.get("id", ""),
                email=user.get("email", ""),
                plan=user.get("plan", "free")
            )
            
        except (json.JSONDecodeError, KeyError, ValueError):
            return None
    
    def get_credentials_with_validation(self, auto_refresh: bool = True) -> tuple[Optional[Credentials], bool]:
        credentials = self.get_credentials()
        
        if credentials is None:
            return None, False
        
        if not self.is_token_expired(credentials):
            return credentials, False
        
        if not auto_refresh:
            return None, False
        
        if credentials.api_key:
            refresh_result = self.refresh_token(credentials)
            
            if refresh_result.success and refresh_result.credentials:
                self.save_credentials(refresh_result.credentials)
                return refresh_result.credentials, True
        
        return None, False
    
    def delete_credentials(self) -> None:
        creds_path = Path(self.CREDENTIALS_FILE)
        if creds_path.exists():
            creds_path.unlink()
    
    def is_authenticated(self) -> bool:
        credentials = self.get_credentials()
        if credentials is None:
            return False
        return not self.is_token_expired(credentials)
    
    def is_token_expired(self, credentials: Credentials) -> bool:
        try:
            expires_at = datetime.fromisoformat(
                credentials.token_expires_at.replace('Z', '+00:00')
            )
            now = datetime.now(timezone.utc)
            return now >= expires_at
        except (ValueError, AttributeError):
            return True

    
    def login_with_device_flow(
        self, 
        display_callback: Callable[[str, str], None] = None,
        poll_callback: Callable[[], bool] = None
    ) -> AuthResult:
        try:
            response = self._session.post(
                f"{self.api_base}/auth/github/device",
                timeout=30
            )
            response.raise_for_status()
            device_data = response.json()
            
            device_code = device_data["device_code"]
            user_code = device_data["user_code"]
            verification_uri = device_data["verification_uri"]
            expires_in = device_data.get("expires_in", 900)
            server_interval = device_data.get("interval", 5)
            interval = max(server_interval, 8)
            
            if display_callback:
                display_callback(user_code, verification_uri)
            
            start_time = time.time()
            
            while time.time() - start_time < expires_in:
                if poll_callback and not poll_callback():
                    return AuthResult(
                        success=False,
                        credentials=None,
                        error_message="Authentication cancelled by user"
                    )
                
                time.sleep(interval)
                
                poll_response = self._session.post(
                    f"{self.api_base}/auth/github/device/poll",
                    json={"device_code": device_code},
                    timeout=30
                )
                
                if poll_response.status_code == 200:
                    token_data = poll_response.json()
                    
                    expires_in_token = token_data.get("expires_in", 86400)
                    expires_at = datetime.now(timezone.utc).timestamp() + expires_in_token
                    expires_at_iso = datetime.fromtimestamp(
                        expires_at, timezone.utc
                    ).isoformat()
                    
                    customer = token_data.get("customer", {})
                    if customer:
                        user_info = customer
                    else:
                        user_info = self._fetch_user_info(token_data["access_token"])
                    
                    credentials = Credentials(
                        api_key=token_data.get("api_key", ""),
                        jwt_token=token_data["access_token"],
                        token_expires_at=expires_at_iso,
                        user_id=user_info.get("id", ""),
                        email=user_info.get("email", ""),
                        plan=user_info.get("plan", "free")
                    )
                    
                    return AuthResult(
                        success=True,
                        credentials=credentials,
                        error_message=None
                    )
                
                elif poll_response.status_code == 428:
                    continue
                
                elif poll_response.status_code == 400:
                    error_data = poll_response.json()
                    error = error_data.get("error", "")
                    
                    if error == "slow_down":
                        interval += 10
                        continue
                    elif error == "expired_token":
                        return AuthResult(
                            success=False,
                            credentials=None,
                            error_message="Device code expired. Please try again."
                        )
                    elif error == "access_denied":
                        return AuthResult(
                            success=False,
                            credentials=None,
                            error_message="Access denied by user"
                        )
                    else:
                        return AuthResult(
                            success=False,
                            credentials=None,
                            error_message=f"Authentication failed: {error}"
                        )
                else:
                    continue
            
            return AuthResult(
                success=False,
                credentials=None,
                error_message="Authentication timed out. Please try again."
            )
            
        except requests.exceptions.ConnectionError:
            return AuthResult(
                success=False,
                credentials=None,
                error_message=f"Cannot connect to Lora Code API at {self.api_base}"
            )
        except requests.exceptions.Timeout:
            return AuthResult(
                success=False,
                credentials=None,
                error_message="Connection to Lora Code API timed out"
            )
        except requests.exceptions.RequestException as e:
            return AuthResult(
                success=False,
                credentials=None,
                error_message=f"Authentication failed: {str(e)}"
            )
        except (KeyError, ValueError) as e:
            return AuthResult(
                success=False,
                credentials=None,
                error_message=f"Invalid response from API: {str(e)}"
            )

    
    def refresh_token(self, credentials: Credentials = None) -> AuthResult:
        if credentials is None:
            credentials = self.get_credentials()
        
        if credentials is None:
            return AuthResult(
                success=False,
                credentials=None,
                error_message="No credentials found to refresh"
            )
        
        if not credentials.api_key:
            return AuthResult(
                success=False,
                credentials=None,
                error_message="No API key available for token refresh"
            )
        
        return self.login_with_api_key(credentials.api_key)
    
    def get_valid_token(self) -> Optional[str]:
        credentials, was_refreshed = self.get_credentials_with_validation(auto_refresh=True)
        
        if credentials is None:
            return None
        
        return credentials.jwt_token
    
    def ensure_authenticated(self) -> AuthResult:
        credentials, was_refreshed = self.get_credentials_with_validation(auto_refresh=True)
        
        if credentials is None:
            raw_credentials = self.get_credentials()
            if raw_credentials is None:
                return AuthResult(
                    success=False,
                    credentials=None,
                    error_message="Not authenticated. Please run 'loracode auth login'"
                )
            else:
                return AuthResult(
                    success=False,
                    credentials=None,
                    error_message="Token expired and refresh failed. Please run 'loracode auth login'"
                )
        
        return AuthResult(
            success=True,
            credentials=credentials,
            error_message=None
        )
