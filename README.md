# Lora Code

<p align="center">
  <strong>AI-powered coding assistant in your terminal</strong>
</p>

<p align="center">
  <a href="#installation">Installation</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#features">Features</a> •
  <a href="#documentation">Documentation</a> •
  <a href="#contributing">Contributing</a>
</p>

---

Lora Code is an AI-powered command-line coding assistant that helps you write, edit, and understand code directly from your terminal. It integrates seamlessly with your development workflow and supports multiple AI models through the Lora Technologies API.

## Features

- 🤖 **AI-Powered Coding** - Get intelligent code suggestions, refactoring help, and explanations
- 💻 **Terminal-First** - Works entirely in your terminal, no IDE required
- 🔄 **Git Integration** - Automatically tracks changes and creates meaningful commits
- 📁 **Multi-File Support** - Edit multiple files in a single session
- 🌐 **Multiple Languages** - Supports Python, JavaScript, TypeScript, and many more
- 🎨 **Syntax Highlighting** - Beautiful code display with customizable themes
- 🔒 **Secure** - Your code stays local, only prompts are sent to the API

## Installation

### Prerequisites

- Python 3.10 or higher
- Git (optional, but recommended)

### Install via pip

```bash
pip install loracode
```

### Install from source

```bash
git clone https://github.com/Lora-Technologies/loracode.git
cd loracode
pip install -e .
```

## Quick Start

1. **Set your API key:**

```bash
export LORA_CODE_API_KEY="your-api-key"
```

Or create a `.env` file in your project directory:

```
LORA_CODE_API_KEY=your-api-key
```

2. **Start Lora Code:**

```bash
loracode
```

3. **Add files to work with:**

```bash
loracode myfile.py another_file.js
```

## Usage

### Basic Commands

```bash
# Start a new session
loracode

# Work with specific files
loracode src/main.py src/utils.py

# Use a specific model
loracode --model gpt-4

# Enable dark mode
loracode --dark-mode

# Get help
loracode --help
```

### In-Session Commands

Once inside Lora Code, you can use these commands:

| Command | Description |
|---------|-------------|
| `/add <file>` | Add a file to the session |
| `/drop <file>` | Remove a file from the session |
| `/clear` | Clear the conversation history |
| `/diff` | Show pending changes |
| `/commit` | Commit changes to git |
| `/help` | Show all available commands |
| `/quit` | Exit Lora Code |

## Configuration

Lora Code can be configured via:

1. **Command line arguments**
2. **Environment variables**
3. **Configuration file** (`.loracode.conf.yml`)

### Configuration File Example

Create `.loracode.conf.yml` in your project root or home directory:

```yaml
# Model settings
model: gpt-4

# UI settings
dark-mode: true
pretty: true

# Git settings
auto-commits: true
dirty-commits: false

# Editor settings
vim: false
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `LORA_CODE_API_KEY` | Your Lora Code API key |
| `LORA_CODE_API_BASE` | Custom API base URL (optional) |

## Requirements

Core dependencies:
- Python >= 3.10
- GitPython
- rich
- prompt_toolkit
- litellm

See [requirements](requirements/) for the full list.

## Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Setup

```bash
# Clone the repository
git clone https://github.com/Lora-Technologies/loracode.git
cd loracode

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest
```

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Support

- 📧 Email: support@loratech.dev
- 🐛 Issues: [GitHub Issues](https://github.com/Lora-Technologies/loracode/issues)
- 💬 Discussions: [GitHub Discussions](https://github.com/Lora-Technologies/loracode/discussions)

---

<p align="center">
  Made with ❤️ by <a href="https://loratech.dev">Lora Technologies</a>
</p>
