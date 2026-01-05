<h1 align="center">Lora Code</h1>

<p align="center">
  <strong>Enterprise-Grade AI Coding Assistant for Your Terminal</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/loracode/"><img src="https://img.shields.io/pypi/v/loracode.svg" alt="PyPI Version"></a>
  <a href="https://pypi.org/project/loracode/"><img src="https://img.shields.io/pypi/pyversions/loracode.svg" alt="Python Versions"></a>
  <a href="https://github.com/Lora-Technologies/loracode/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"></a>
  <a href="https://github.com/Lora-Technologies/loracode/actions"><img src="https://img.shields.io/github/actions/workflow/status/Lora-Technologies/loracode/ci.yml" alt="Build Status"></a>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#installation">Installation</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#usage">Usage</a> •
  <a href="#configuration">Configuration</a> •
  <a href="#documentation">Documentation</a>
</p>

---

## Overview

Lora Code is a powerful AI-driven command-line coding assistant that seamlessly integrates into your development workflow. Built for professional developers and teams, it provides intelligent code suggestions, automated refactoring, and comprehensive project understanding directly from your terminal.

## Features

### Core Capabilities

| Feature | Description |
|---------|-------------|
| 🤖 **AI-Powered Coding** | Intelligent code generation, refactoring, and explanations |
| 🏗️ **Architect Mode** | Design-first approach with separate architect and editor models |
| 📊 **Context Mode** | Automatic identification of relevant files for your task |
| 💬 **Ask Mode** | Query your codebase without making changes |
| 🗺️ **Repository Mapping** | Intelligent codebase understanding with customizable token limits |
| 🔄 **Git Integration** | Automatic commits, diffs, and version control management |

### Advanced Features

| Feature | Description |
|---------|-------------|
| 🎤 **Voice Input** | Record and transcribe voice commands (WAV, MP3, WebM) |
| 💾 **Checkpoints** | Save and restore session states |
| 🪝 **Hooks System** | Custom automation triggers for various events |
| ✅ **Auto-Approve** | Configurable automatic approval for different action categories |
| 🌐 **Web Scraping** | Fetch and analyze web content with Playwright support |
| 🔐 **Authentication** | Secure device-flow authentication with credential caching |
| 🌍 **Multi-Language UI** | Interface available in English and Turkish |
| 📋 **Clipboard Integration** | Paste images and text directly into chat |

### Developer Experience

| Feature | Description |
|---------|-------------|
| 🎨 **Syntax Highlighting** | Customizable code themes (One Dark, Monokai, Solarized, etc.) |
| ⌨️ **VI Mode** | Optional VI editing mode in terminal |
| 📝 **Multi-line Input** | Extended input mode with Meta-Enter submission |
| 🔔 **Notifications** | Terminal bell or custom command notifications |
| 🧪 **Auto-Testing** | Automatic test execution after changes |
| 🔍 **Auto-Linting** | Automatic linting with configurable commands |

## Installation

### Requirements

- Python 3.10 or higher
- Git (recommended)
- FFmpeg (optional, for MP3/WebM voice recording)

### Install via pip

```bash
pip install loracode
```

### Install from Source

```bash
git clone https://github.com/Lora-Technologies/loracode.git
cd loracode
pip install -e .
```

### Upgrade

```bash
# Upgrade to latest stable version
loracode --upgrade

# Install from main branch (development)
loracode --install-main-branch
```

## Quick Start

### 1. Authentication

```bash
# Interactive login with device flow
loracode
# Then use: /auth login

# Or set API key directly
export LORA_CODE_API_KEY="your-api-key"
```

### 2. Start a Session

```bash
# Start interactive session
loracode

# Work with specific files
loracode src/main.py src/utils.py

# Use a specific model
loracode --model gpt-4

# Single message mode (non-interactive)
loracode -m "Add error handling to main.py"
```

## Usage

### Chat Modes

| Mode | Command | Description |
|------|---------|-------------|
| **Code** | `/code` | Make code changes (default) |
| **Architect** | `/architect` | Design changes with architect model, implement with editor |
| **Ask** | `/ask` | Ask questions without making changes |
| **Context** | `/context` | Auto-identify files needed for a task |
| **Help** | `/help` | Get help about Lora Code usage |

### In-Session Commands

#### File Management
| Command | Description |
|---------|-------------|
| `/add <file>` | Add file(s) to the editable session |
| `/drop [file]` | Remove file(s) from session (all if no argument) |
| `/read-only <file>` | Add file(s) as read-only reference |
| `/ls` | List all files in session and repository |

#### Git Operations
| Command | Description |
|---------|-------------|
| `/commit [message]` | Commit pending changes |
| `/diff` | Show changes since last commit |
| `/undo` | Undo the last Lora Code commit |
| `/git <command>` | Run any git command |

#### Session Management
| Command | Description |
|---------|-------------|
| `/clear` | Clear conversation history |
| `/reset` | Clear history and drop all files |
| `/tokens` | Show token usage breakdown |
| `/settings` | Display current configuration |

#### Model Configuration
| Command | Description |
|---------|-------------|
| `/model [name]` | Switch or display current model |
| `/editor-model <name>` | Set the editor model |
| `/weak-model <name>` | Set the weak model (for summaries) |
| `/think-tokens [value]` | Set thinking token budget |
| `/chat-mode <mode>` | Switch chat mode |

#### Checkpoints
| Command | Description |
|---------|-------------|
| `/checkpoint-save [name]` | Save current session state |
| `/checkpoint-load <name>` | Restore a saved session |
| `/checkpoints` | List all saved checkpoints |
| `/checkpoint delete <name>` | Delete a checkpoint |

#### Automation
| Command | Description |
|---------|-------------|
| `/auto-approve <categories>` | Auto-approve specific action categories |
| `/auto-reject <categories>` | Auto-reject specific action categories |
| `/auto-ask <categories>` | Reset categories to ask mode |
| `/auto-status` | Show current auto-approval settings |
| `/hooks` | List and manage automation hooks |

#### Utilities
| Command | Description |
|---------|-------------|
| `/web <url>` | Fetch and add web content to chat |
| `/voice` | Record voice input (requires OpenAI API key) |
| `/paste` | Paste clipboard content (text or image) |
| `/copy` | Copy last assistant message to clipboard |
| `/copy-context` | Copy current context for external use |
| `/editor` | Open external editor for input |
| `/run <command>` | Execute shell command |
| `/test [command]` | Run tests |
| `/lint` | Lint and fix files |
| `/map` | Show repository map |
| `/report` | Report an issue on GitHub |
| `/language [code]` | Change UI language (en/tr) |
| `/auth <login\|logout\|status>` | Manage authentication |
| `/help [topic]` | Get help on specific topics |
| `/quit` | Exit Lora Code |


## Configuration

### Configuration Files

Lora Code searches for configuration in the following order:

1. Command line arguments (highest priority)
2. Environment variables (prefixed with `LORACODE_`)
3. `.loracode.conf.yml` in current directory
4. `.loracode.conf.yml` in git root
5. `.loracode.conf.yml` in home directory

### Configuration File Example

```yaml
# .loracode.conf.yml

# Model Configuration
model: gpt-4
weak-model: gpt-3.5-turbo
editor-model: gpt-4
edit-format: architect
thinking-tokens: 8096

# API Settings
api-base: https://api.loratech.dev

# Git Settings
auto-commits: true
dirty-commits: true
attribute-co-authored-by: true
git-commit-verify: false

# UI Settings
dark-mode: true
pretty: true
stream: true
code-theme: one-dark
vim: false
multiline: false
notifications: false

# Repository Map
map-tokens: 2048
map-refresh: auto

# Automation
auto-lint: true
auto-test: false
suggest-shell-commands: true

# Language
language: en
chat-language: null
commit-language: null

# Voice Settings
voice-format: wav
voice-language: en
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `LORA_CODE_API_KEY` | API key for Lora Code services |
| `LORA_CODE_API_BASE` | Custom API base URL |
| `LORACODE_MODEL` | Default model to use |
| `LORACODE_DARK_MODE` | Enable dark mode (true/false) |
| `LORACODE_AUTO_COMMITS` | Enable auto-commits (true/false) |

### CLI Arguments Reference

#### Main Model Settings
```bash
--model MODEL              # Main chat model
--weak-model MODEL         # Model for summaries and commits
--editor-model MODEL       # Model for editor tasks
--edit-format FORMAT       # Edit format (diff, whole, architect, etc.)
--architect                # Use architect edit format
--thinking-tokens VALUE    # Thinking token budget (0 to disable)
```

#### API Settings
```bash
--api-key KEY              # Lora Code API key
--api-base URL             # API base URL
--timeout SECONDS          # API call timeout
--verify-ssl / --no-verify-ssl  # SSL verification
```

#### Cache Settings
```bash
--cache-prompts / --no-cache-prompts  # Enable prompt caching
--cache-keepalive-pings N             # Keep cache warm (ping count)
```

#### Repository Map
```bash
--map-tokens N             # Token limit for repo map (0 to disable)
--map-refresh MODE         # Refresh mode: auto, always, files, manual
--map-multiplier-no-files N  # Multiplier when no files specified
```

#### Git Settings
```bash
--git / --no-git           # Enable/disable git integration
--auto-commits / --no-auto-commits  # Auto-commit changes
--dirty-commits / --no-dirty-commits  # Commit with dirty repo
--attribute-co-authored-by / --no-attribute-co-authored-by  # Co-author attribution
--commit-prompt PROMPT     # Custom commit message prompt
--dry-run                  # Preview changes without applying
```

#### Output Settings
```bash
--dark-mode / --light-mode  # Color scheme
--pretty / --no-pretty      # Colorized output
--stream / --no-stream      # Streaming responses
--code-theme THEME          # Syntax highlighting theme
--show-diffs                # Show diffs when committing
```

#### Voice Settings
```bash
--voice-format FORMAT      # Audio format: wav, mp3, webm
--voice-language LANG      # ISO 639-1 language code
--voice-input-device NAME  # Input device name
```

#### Checkpoint Settings
```bash
--load-checkpoint NAME     # Load checkpoint at startup
--save-on-exit [NAME]      # Save checkpoint on exit
--checkpoint-dir DIR       # Custom checkpoint directory
```

#### Automation
```bash
--auto-approve CATEGORIES  # Auto-approve categories (comma-separated)
--auto-reject CATEGORIES   # Auto-reject categories
--yes-always               # Always confirm prompts
--lint-cmd "LANG: CMD"     # Custom lint command per language
--test-cmd CMD             # Test command
--auto-lint / --no-auto-lint  # Auto-lint after changes
--auto-test / --no-auto-test  # Auto-test after changes
```

#### Modes
```bash
-m, --message MSG          # Single message mode
-f, --message-file FILE    # Message from file
--gui                      # Browser-based interface
--copy-paste               # Auto copy/paste with web UI
--watch-files              # Watch for AI coding comments
```

#### Other Options
```bash
--vim                      # VI editing mode
--multiline                # Multi-line input mode
--fancy-input / --no-fancy-input  # Input with history/completion
--notifications            # Enable notifications
--detect-urls              # Auto-detect URLs in input
--language LANG            # UI language (en, tr)
--encoding ENCODING        # I/O encoding (default: utf-8)
--verbose                  # Verbose output
--version                  # Show version
--help                     # Show help
```

## Hooks System

Hooks allow you to run custom commands at specific events during your Lora Code session.

### Configuration

Create `.loracode/settings.json` in your project root:

```json
{
  "hooks": {
    "BeforeTool": [
      {
        "name": "pre-edit-check",
        "command": "python scripts/validate.py",
        "description": "Validate before making changes",
        "timeout": 5000
      }
    ],
    "AfterTool": [
      {
        "name": "post-edit-format",
        "command": "black .",
        "description": "Format code after changes"
      }
    ]
  }
}
```

### Hook Events

| Event | Trigger |
|-------|---------|
| `BeforeTool` | Before any tool execution |
| `AfterTool` | After tool execution |

### Managing Hooks

```bash
/hooks                    # List all hooks
/hooks enable <name>      # Enable a hook
/hooks disable <name>     # Disable a hook
/hooks test <name>        # Test a hook
```

## Auto-Approval System

Control which actions require confirmation:

### Categories

| Category | Description |
|----------|-------------|
| `file_create` | Creating new files |
| `file_edit` | Editing existing files |
| `shell_command` | Running shell commands |
| `url_add` | Adding URLs to chat |
| `lint_fix` | Applying lint fixes |
| `test_fix` | Applying test fixes |
| `git_repo` | Git operations |
| `analytics` | Analytics collection |

### Usage

```bash
# Auto-approve specific categories
/auto-approve file_edit,lint_fix

# Auto-approve everything
/auto-approve all

# Auto-reject categories
/auto-reject shell_command

# Reset to ask mode
/auto-ask all

# View current settings
/auto-status
```

## Authentication

Lora Code uses secure device-flow authentication:

```bash
# Start login process
/auth login

# Check authentication status
/auth status

# Logout
/auth logout
```

Credentials are securely cached locally. Use `--no-cache-credentials` to disable caching.

## Project Structure

```
loracode/
├── loracode/           # Main package
│   ├── coders/         # Edit format implementations
│   ├── locales/        # i18n translations
│   ├── resources/      # Model settings and assets
│   ├── main.py         # Entry point
│   ├── commands.py     # In-session commands
│   ├── args.py         # CLI argument parsing
│   └── ...
├── tests/              # Test suite
├── requirements/       # Dependency specifications
├── scripts/            # Utility scripts
└── docs/               # Documentation
```

## Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Setup

```bash
# Clone the repository
git clone https://github.com/Lora-Technologies/loracode.git
cd loracode

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linting
flake8 loracode tests
```

## Security

For security concerns, please see our [Security Policy](SECURITY.md) or contact security@loratech.dev.

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Support

| Channel | Link |
|---------|------|
| 📧 Email | support@loratech.dev |
| 🐛 Issues | [GitHub Issues](https://github.com/Lora-Technologies/loracode/issues) |
| 💬 Discussions | [GitHub Discussions](https://github.com/Lora-Technologies/loracode/discussions) |
| 📖 Documentation | [docs.loratech.dev](https://docs.loratech.dev) |

---

<p align="center">
  <sub>Built with ❤️ by <a href="https://loratech.dev">Lora Technologies</a></sub>
</p>
