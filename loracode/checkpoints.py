from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime
from pathlib import Path
import json
import os

CHECKPOINT_VERSION = "1.0"

DEFAULT_AUTO_SAVE_ENABLED = False
DEFAULT_AUTO_SAVE_INTERVAL = 10
DEFAULT_MAX_AUTO_CHECKPOINTS = 5
AUTO_CHECKPOINT_PREFIX = "auto-"


@dataclass
class CheckpointMetadata:
    version: str = CHECKPOINT_VERSION
    created_at: str = ""
    model: str = ""
    edit_format: str = ""
    description: str = ""


@dataclass
class AutoSaveConfig:
    enabled: bool = DEFAULT_AUTO_SAVE_ENABLED
    interval: int = DEFAULT_AUTO_SAVE_INTERVAL
    max_checkpoints: int = DEFAULT_MAX_AUTO_CHECKPOINTS


@dataclass
class Checkpoint:
    metadata: CheckpointMetadata = field(default_factory=CheckpointMetadata)
    files: List[str] = field(default_factory=list)
    read_only_files: List[str] = field(default_factory=list)
    done_messages: List[Dict[str, Any]] = field(default_factory=list)
    cur_messages: List[Dict[str, Any]] = field(default_factory=list)


class CheckpointManager:
    def __init__(
        self,
        project_root: Path,
        checkpoint_dir: Optional[Path] = None,
        io=None,
        hook_manager=None
    ):
        self.project_root = Path(project_root)
        self.checkpoint_dir = checkpoint_dir or (self.project_root / ".loracode" / "checkpoints")
        self.io = io
        self.hook_manager = hook_manager
        self.auto_save_config = AutoSaveConfig()
        self.operation_count = 0
        self._load_auto_save_config()
    
    def _load_auto_save_config(self) -> None:
        global_settings_path = Path.home() / ".loracode" / "settings.json"
        project_settings_path = self.project_root / ".loracode" / "settings.json"
        self._load_auto_save_from_file(global_settings_path)
        self._load_auto_save_from_file(project_settings_path)
    def _load_auto_save_from_file(self, settings_path: Path) -> None:
        if not settings_path.exists():
            return
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except json.JSONDecodeError as e:
            if self.io:
                self.io.tool_error(f"Auto-save yapılandırma hatası ({settings_path}): {e}")
            return
        except OSError as e:
            if self.io:
                self.io.tool_error(f"Settings dosyası okunamadı ({settings_path}): {e}")
            return
        if not isinstance(settings, dict):
            return
        checkpointing_config = settings.get("checkpointing", {})
        if not isinstance(checkpointing_config, dict):
            return
        if "auto_save" in checkpointing_config:
            self.auto_save_config.enabled = bool(checkpointing_config["auto_save"])
        if "auto_save_interval" in checkpointing_config:
            interval = checkpointing_config["auto_save_interval"]
            if isinstance(interval, int) and interval > 0:
                self.auto_save_config.interval = interval
        
        if "max_auto_checkpoints" in checkpointing_config:
            max_cp = checkpointing_config["max_auto_checkpoints"]
            if isinstance(max_cp, int) and max_cp > 0:
                self.auto_save_config.max_checkpoints = max_cp
    
    def get_auto_save_config(self) -> AutoSaveConfig:
        return self.auto_save_config
    
    def set_auto_save_config(
        self,
        enabled: Optional[bool] = None,
        interval: Optional[int] = None,
        max_checkpoints: Optional[int] = None
    ) -> None:
        if enabled is not None:
            self.auto_save_config.enabled = enabled
        if interval is not None and interval > 0:
            self.auto_save_config.interval = interval
        if max_checkpoints is not None and max_checkpoints > 0:
            self.auto_save_config.max_checkpoints = max_checkpoints
    
    def should_auto_save(self) -> bool:
        if not self.auto_save_config.enabled:
            return False
        
        return self.operation_count > 0 and \
               self.operation_count % self.auto_save_config.interval == 0
    
    def increment_operation_count(self) -> None:
        self.operation_count += 1
    
    def auto_save(self, coder) -> Optional[str]:
        if not self.auto_save_config.enabled:
            return None
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        name = f"{AUTO_CHECKPOINT_PREFIX}{timestamp}"
        saved_name = self.save(name, coder)
        self._cleanup_old_auto_checkpoints()
        if self.io:
            self.io.tool_output(f"💾 Otomatik checkpoint: {saved_name}")
        
        return saved_name
    
    def _cleanup_old_auto_checkpoints(self) -> None:
        if not self.checkpoint_dir.exists():
            return
        auto_checkpoints = []
        for checkpoint_file in self.checkpoint_dir.glob(f"{AUTO_CHECKPOINT_PREFIX}*.json"):
            try:
                mtime = checkpoint_file.stat().st_mtime
                auto_checkpoints.append((checkpoint_file, mtime))
            except OSError:
                continue
        auto_checkpoints.sort(key=lambda x: x[1], reverse=True)
        if len(auto_checkpoints) > self.auto_save_config.max_checkpoints:
            checkpoints_to_delete = auto_checkpoints[self.auto_save_config.max_checkpoints:]
            for checkpoint_file, _ in checkpoints_to_delete:
                try:
                    checkpoint_file.unlink()
                    if self.io:
                        self.io.tool_output(f"🗑️ Eski otomatik checkpoint silindi: {checkpoint_file.stem}")
                except OSError:
                    pass
    
    def list_auto_checkpoints(self) -> List[Dict[str, Any]]:
        all_checkpoints = self.list_checkpoints()
        return [cp for cp in all_checkpoints if cp["name"].startswith(AUTO_CHECKPOINT_PREFIX)]
    
    def save(self, name: Optional[str], coder) -> str:
        if not name:
            name = self._generate_name()
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = self._create_checkpoint_from_coder(coder)
        checkpoint_json = self._serialize(checkpoint)
        checkpoint_path = self.checkpoint_dir / f"{name}.json"
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            f.write(checkpoint_json)
        self._trigger_checkpoint_save_hook(name, checkpoint)
        
        return name
    
    def load(self, name: str, coder) -> Checkpoint:
        checkpoint_path = self.checkpoint_dir / f"{name}.json"
        if not checkpoint_path.exists():
            raise FileNotFoundError(f"Checkpoint bulunamadı: {name}")
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            checkpoint_json = f.read()
        checkpoint = self._deserialize(checkpoint_json)
        missing_files = self._validate_files(checkpoint)
        self._apply_checkpoint_to_coder(checkpoint, coder, missing_files)
        self._trigger_checkpoint_load_hook(name, checkpoint)
        return checkpoint
    
    def list_checkpoints(self) -> List[Dict[str, Any]]:
        checkpoints = []
        if not self.checkpoint_dir.exists():
            return checkpoints
        for checkpoint_file in self.checkpoint_dir.glob("*.json"):
            try:
                with open(checkpoint_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                metadata = data.get("metadata", {})
                checkpoints.append({
                    "name": checkpoint_file.stem,
                    "created_at": metadata.get("created_at", ""),
                    "model": metadata.get("model", ""),
                    "description": metadata.get("description", ""),
                    "message_count": len(data.get("done_messages", [])) + len(data.get("cur_messages", [])),
                    "file_count": len(data.get("files", [])) + len(data.get("read_only_files", [])),
                })
            except (json.JSONDecodeError, OSError):
                continue
        
        checkpoints.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
        return checkpoints
    
    def delete(self, name: str) -> bool:
        checkpoint_path = self.checkpoint_dir / f"{name}.json"
        
        if not checkpoint_path.exists():
            return False
        
        try:
            checkpoint_path.unlink()
            return True
        except OSError:
            return False
    
    def get_info(self, name: str) -> Optional[Dict[str, Any]]:
        checkpoint_path = self.checkpoint_dir / f"{name}.json"
        
        if not checkpoint_path.exists():
            return None
        
        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            metadata = data.get("metadata", {})
            return {
                "name": name,
                "version": metadata.get("version", ""),
                "created_at": metadata.get("created_at", ""),
                "model": metadata.get("model", ""),
                "edit_format": metadata.get("edit_format", ""),
                "description": metadata.get("description", ""),
                "files": data.get("files", []),
                "read_only_files": data.get("read_only_files", []),
                "message_count": len(data.get("done_messages", [])) + len(data.get("cur_messages", [])),
                "done_message_count": len(data.get("done_messages", [])),
                "cur_message_count": len(data.get("cur_messages", [])),
            }
        except (json.JSONDecodeError, OSError):
            return None
    
    def _serialize(self, checkpoint: Checkpoint) -> str:
        files = self._ensure_relative_paths(checkpoint.files)
        read_only_files = self._ensure_relative_paths(checkpoint.read_only_files)
        version = checkpoint.metadata.version or CHECKPOINT_VERSION
        
        data = {
            "metadata": {
                "version": version,
                "created_at": checkpoint.metadata.created_at,
                "model": checkpoint.metadata.model,
                "edit_format": checkpoint.metadata.edit_format,
                "description": checkpoint.metadata.description,
            },
            "files": files,
            "read_only_files": read_only_files,
            "done_messages": checkpoint.done_messages,
            "cur_messages": checkpoint.cur_messages,
        }
        
        return json.dumps(data, ensure_ascii=False, indent=2)
    
    def _ensure_relative_paths(self, paths: List[str]) -> List[str]:
        relative_paths = []
        for path_str in paths:
            path = Path(path_str)
            if path.is_absolute():
                try:
                    rel_path = path.relative_to(self.project_root)
                    relative_paths.append(rel_path.as_posix())
                except ValueError:
                    relative_paths.append(path.as_posix())
            else:
                relative_paths.append(Path(path_str).as_posix())
        return relative_paths
    
    def _is_relative_path(self, path_str: str) -> bool:
        path = Path(path_str)
        return not path.is_absolute()
    
    def _deserialize(self, json_str: str) -> Checkpoint:
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Geçersiz checkpoint formatı: {e}")
        if not isinstance(data, dict):
            raise ValueError("Checkpoint verisi bir dictionary olmalı")
        metadata_data = data.get("metadata", {})
        if not isinstance(metadata_data, dict):
            metadata_data = {}
        version = metadata_data.get("version", "1.0")
        if not self._is_valid_version(version):
            raise ValueError(f"Geçersiz versiyon formatı: {version}")
        if version != CHECKPOINT_VERSION:
            data = self._migrate(data, version)
            metadata_data = data.get("metadata", {})
        
        metadata = CheckpointMetadata(
            version=metadata_data.get("version", CHECKPOINT_VERSION),
            created_at=metadata_data.get("created_at", ""),
            model=metadata_data.get("model", ""),
            edit_format=metadata_data.get("edit_format", ""),
            description=metadata_data.get("description", ""),
        )
        files = data.get("files", [])
        if not isinstance(files, list):
            files = []
        files = [str(f) for f in files if f]
        
        read_only_files = data.get("read_only_files", [])
        if not isinstance(read_only_files, list):
            read_only_files = []
        read_only_files = [str(f) for f in read_only_files if f]
        done_messages = data.get("done_messages", [])
        if not isinstance(done_messages, list):
            done_messages = []
        
        cur_messages = data.get("cur_messages", [])
        if not isinstance(cur_messages, list):
            cur_messages = []
        
        return Checkpoint(
            metadata=metadata,
            files=files,
            read_only_files=read_only_files,
            done_messages=done_messages,
            cur_messages=cur_messages,
        )
    
    def _is_valid_version(self, version: str) -> bool:
        import re
        return bool(re.match(r'^\d+\.\d+$', str(version)))
    
    def _migrate(self, data: Dict, from_version: str) -> Dict:
        try:
            from_major, from_minor = map(int, from_version.split('.'))
            current_major, current_minor = map(int, CHECKPOINT_VERSION.split('.'))
        except (ValueError, AttributeError):
            return data
        
        # Migrasyon adımları (ileride eklenecek)
        # Örnek: 1.0 -> 1.1 migrasyonu
        # if from_major == 1 and from_minor == 0:
        #     data = self._migrate_1_0_to_1_1(data)
        #     from_minor = 1
        
        if "metadata" not in data:
            data["metadata"] = {}
        data["metadata"]["version"] = CHECKPOINT_VERSION
        
        return data
    
    def _generate_name(self) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return f"checkpoint-{timestamp}"
    
    def _validate_files(self, checkpoint: Checkpoint) -> List[str]:
        missing_files = []
        
        all_files = checkpoint.files + checkpoint.read_only_files
        
        for rel_path in all_files:
            abs_path = self.project_root / rel_path
            if not abs_path.exists():
                missing_files.append(rel_path)
        
        return missing_files
    
    def _create_checkpoint_from_coder(self, coder) -> Checkpoint:
        files = []
        if hasattr(coder, 'abs_fnames') and coder.abs_fnames:
            for abs_path in coder.abs_fnames:
                try:
                    rel_path = Path(abs_path).relative_to(self.project_root)
                    files.append(str(rel_path))
                except ValueError:
                    files.append(str(abs_path))
        
        read_only_files = []
        if hasattr(coder, 'abs_read_only_fnames') and coder.abs_read_only_fnames:
            for abs_path in coder.abs_read_only_fnames:
                try:
                    rel_path = Path(abs_path).relative_to(self.project_root)
                    read_only_files.append(str(rel_path))
                except ValueError:
                    read_only_files.append(str(abs_path))
        
        done_messages = []
        if hasattr(coder, 'done_messages') and coder.done_messages:
            done_messages = list(coder.done_messages)
        
        cur_messages = []
        if hasattr(coder, 'cur_messages') and coder.cur_messages:
            cur_messages = list(coder.cur_messages)
        
        model = ""
        if hasattr(coder, 'main_model') and coder.main_model:
            model = str(coder.main_model.name) if hasattr(coder.main_model, 'name') else str(coder.main_model)
        
        edit_format = ""
        if hasattr(coder, 'edit_format'):
            edit_format = str(coder.edit_format)
        
        metadata = CheckpointMetadata(
            version=CHECKPOINT_VERSION,
            created_at=datetime.now().isoformat(),
            model=model,
            edit_format=edit_format,
            description="",
        )
        
        return Checkpoint(
            metadata=metadata,
            files=files,
            read_only_files=read_only_files,
            done_messages=done_messages,
            cur_messages=cur_messages,
        )
    
    def _apply_checkpoint_to_coder(
        self,
        checkpoint: Checkpoint,
        coder,
        missing_files: List[str]
    ) -> None:
        if hasattr(coder, 'done_messages'):
            coder.done_messages = []
        if hasattr(coder, 'cur_messages'):
            coder.cur_messages = []
        if hasattr(coder, 'abs_fnames'):
            coder.abs_fnames = set()
        if hasattr(coder, 'abs_read_only_fnames'):
            coder.abs_read_only_fnames = set()
        if hasattr(coder, 'done_messages'):
            coder.done_messages = checkpoint.done_messages.copy()
        if hasattr(coder, 'cur_messages'):
            coder.cur_messages = checkpoint.cur_messages.copy()
        for rel_path in checkpoint.files:
            if rel_path not in missing_files:
                abs_path = self.project_root / rel_path
                if hasattr(coder, 'abs_fnames'):
                    coder.abs_fnames.add(str(abs_path))
        for rel_path in checkpoint.read_only_files:
            if rel_path not in missing_files:
                abs_path = self.project_root / rel_path
                if hasattr(coder, 'abs_read_only_fnames'):
                    coder.abs_read_only_fnames.add(str(abs_path))
        if missing_files and self.io:
            self.io.tool_warning(f"Eksik dosyalar: {', '.join(missing_files)}")
    
    def exists(self, name: str) -> bool:
        checkpoint_path = self.checkpoint_dir / f"{name}.json"
        return checkpoint_path.exists()

    def _trigger_checkpoint_save_hook(self, name: str, checkpoint: Checkpoint) -> None:
        if not self.hook_manager:
            return
        try:
            from loracode.hooks import HookEvent
        except ImportError:
            return
        context = {
            "checkpoint_name": name,
            "checkpoint_path": str(self.checkpoint_dir / f"{name}.json"),
            "cwd": str(self.project_root),
            "hook_event_name": HookEvent.CHECKPOINT_SAVE.value,
            "timestamp": checkpoint.metadata.created_at,
            "files": checkpoint.files,
            "read_only_files": checkpoint.read_only_files,
            "message_count": len(checkpoint.done_messages) + len(checkpoint.cur_messages),
            "model": checkpoint.metadata.model,
            "edit_format": checkpoint.metadata.edit_format,
        }
        self.hook_manager.trigger(HookEvent.CHECKPOINT_SAVE, context)
    
    def _trigger_checkpoint_load_hook(self, name: str, checkpoint: Checkpoint) -> None:
        if not self.hook_manager:
            return
        try:
            from loracode.hooks import HookEvent
        except ImportError:
            return
        context = {
            "checkpoint_name": name,
            "checkpoint_path": str(self.checkpoint_dir / f"{name}.json"),
            "cwd": str(self.project_root),
            "hook_event_name": HookEvent.CHECKPOINT_LOAD.value,
            "timestamp": datetime.now().isoformat(),
            "created_at": checkpoint.metadata.created_at,
            "files": checkpoint.files,
            "read_only_files": checkpoint.read_only_files,
            "message_count": len(checkpoint.done_messages) + len(checkpoint.cur_messages),
            "model": checkpoint.metadata.model,
            "edit_format": checkpoint.metadata.edit_format,
        }
        self.hook_manager.trigger(HookEvent.CHECKPOINT_LOAD, context)
