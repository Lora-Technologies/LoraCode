from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from pathlib import Path
import subprocess
import json
import os


class HookEvent(Enum):
    SESSION_START = "SessionStart"      # Oturum başladığında
    SESSION_END = "SessionEnd"          # Oturum bittiğinde
    BEFORE_AGENT = "BeforeAgent"        # Kullanıcı mesajından sonra, işlemden önce
    AFTER_AGENT = "AfterAgent"          # Agent işlemi tamamlandığında
    BEFORE_TOOL = "BeforeTool"          # Araç çalışmadan önce
    AFTER_TOOL = "AfterTool"            # Araç çalıştıktan sonra
    CHECKPOINT_SAVE = "CheckpointSave"  # Checkpoint kaydedilirken
    CHECKPOINT_LOAD = "CheckpointLoad"  # Checkpoint yüklenirken


@dataclass
class HookConfig:
    name: str
    command: str
    description: str = ""
    timeout: int = 60000  # milliseconds (varsayılan: 60 saniye)
    enabled: bool = True
    matcher: Optional[str] = None  # BeforeTool/AfterTool için araç filtresi


@dataclass
class HookResult:
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    decision: str = "allow"  # allow, deny, ask, block
    timed_out: bool = False


class HookManager: 
    def __init__(self, project_root: Path, io=None):
        self.project_root = Path(project_root)
        self.io = io
        self.hooks: Dict[HookEvent, List[HookConfig]] = {event: [] for event in HookEvent}
        self.disabled_hooks: set = set()
    
    def load_hooks(self) -> None:
        global_settings_path = Path.home() / ".loracode" / "settings.json"
        project_settings_path = self.project_root / ".loracode" / "settings.json"
        self._load_hooks_from_file(global_settings_path)
        self._load_hooks_from_file(project_settings_path)
    
    def _load_hooks_from_file(self, settings_path: Path) -> None:
        if not settings_path.exists():
            return
        
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except json.JSONDecodeError as e:
            if self.io:
                self.io.tool_error(f"Hook yapılandırma hatası ({settings_path}): {e}")
            return
        except OSError as e:
            if self.io:
                self.io.tool_error(f"Settings dosyası okunamadı ({settings_path}): {e}")
            return
        if not isinstance(settings, dict):
            if self.io:
                self.io.tool_error(f"Geçersiz settings formatı ({settings_path}): dict bekleniyor")
            return
        
        hooks_config = settings.get("hooks", {})        
        if not isinstance(hooks_config, dict):
            if self.io:
                self.io.tool_error(f"Geçersiz hooks formatı ({settings_path}): dict bekleniyor")
            return
        disabled_list = hooks_config.get("disabled", [])
        self.disabled_hooks.update(disabled_list)
        for event in HookEvent:
            event_hooks = hooks_config.get(event.value, [])
            for hook_data in event_hooks:
                try:
                    hook = HookConfig(
                        name=hook_data["name"],
                        command=hook_data["command"],
                        description=hook_data.get("description", ""),
                        timeout=hook_data.get("timeout", 60000),
                        enabled=hook_data.get("enabled", True),
                        matcher=hook_data.get("matcher"),
                    )    
                    existing_idx = None
                    for idx, existing_hook in enumerate(self.hooks[event]):
                        if existing_hook.name == hook.name:
                            existing_idx = idx
                            break
                    
                    if existing_idx is not None:
                        self.hooks[event][existing_idx] = hook
                    else:
                        self.hooks[event].append(hook)
                        
                except KeyError as e:
                    if self.io:
                        self.io.tool_error(f"Hook yapılandırma eksik alan: {e}")
    
    def trigger(self, event: HookEvent, context: Dict[str, Any]) -> List[HookResult]:
        results = []
        
        for hook in self.hooks[event]:
            if not hook.enabled or hook.name in self.disabled_hooks:
                continue
            
            result = self.execute_hook(hook, context)
            results.append(result)
            if result.exit_code == 2 or result.decision == "deny":
                break
        
        return results
    
    def execute_hook(self, hook: HookConfig, context: Dict[str, Any]) -> HookResult:
        context_json = json.dumps(context, ensure_ascii=False, default=str)
        timeout_seconds = hook.timeout / 1000.0
        try:
            process = subprocess.Popen(
                hook.command,
                shell=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.project_root),
                env={**os.environ, "LORACODE_HOOK": hook.name},
            )
            stdout, stderr = process.communicate(
                input=context_json.encode("utf-8"),
                timeout=timeout_seconds
            )
            
            exit_code = process.returncode
            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")
            if exit_code == 0:
                decision = "allow"
                success = True
            elif exit_code == 2:
                decision = "deny"
                success = False
            else:
                decision = "allow" 
                success = False
            
            return HookResult(
                success=success,
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str,
                decision=decision,
                timed_out=False,
            )
            
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            
            if self.io:
                self.io.tool_warning(f"Hook timeout: {hook.name} ({timeout_seconds}s)")
            
            return HookResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"Hook timeout after {timeout_seconds} seconds",
                decision="allow",
                timed_out=True,
            )
            
        except Exception as e:
            if self.io:
                self.io.tool_error(f"Hook çalıştırma hatası ({hook.name}): {e}")
            
            return HookResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                decision="allow",
                timed_out=False,
            )
    
    def enable_hook(self, name: str) -> bool:
        if name in self.disabled_hooks:
            self.disabled_hooks.remove(name)
        for event_hooks in self.hooks.values():
            for hook in event_hooks:
                if hook.name == name:
                    hook.enabled = True
                    return True
        
        return False
    
    def disable_hook(self, name: str) -> bool:
        self.disabled_hooks.add(name)
        for event_hooks in self.hooks.values():
            for hook in event_hooks:
                if hook.name == name:
                    hook.enabled = False
                    return True
        
        return True
    
    def list_hooks(self) -> Dict[HookEvent, List[HookConfig]]:
        return self.hooks
    
    def test_hook(self, name: str) -> Optional[HookResult]:
        for event, event_hooks in self.hooks.items():
            for hook in event_hooks:
                if hook.name == name:
                    test_context = {
                        "session_id": "test-session",
                        "cwd": str(self.project_root),
                        "hook_event_name": event.value,
                        "timestamp": "2026-01-04T00:00:00Z",
                        "test_mode": True,
                    }
                    return self.execute_hook(hook, test_context)
        
        return None
    
    def get_hook_by_name(self, name: str) -> Optional[HookConfig]:
        for event_hooks in self.hooks.values():
            for hook in event_hooks:
                if hook.name == name:
                    return hook
        return None
    
    def is_hook_enabled(self, name: str) -> bool:
        if name in self.disabled_hooks:
            return False
        
        hook = self.get_hook_by_name(name)
        if hook:
            return hook.enabled
        
        return False
