# Contributing to Lora Code

First off, thank you for considering contributing to Lora Code! It's people like you that make Lora Code such a great tool.

## Code of Conduct

By participating in this project, you are expected to uphold our Code of Conduct:

- Be respectful and inclusive
- Be patient and welcoming
- Be thoughtful in your communication
- Focus on what is best for the community

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check the existing issues to avoid duplicates. When you create a bug report, include as many details as possible:

- **Use a clear and descriptive title**
- **Describe the exact steps to reproduce the problem**
- **Provide specific examples** (code snippets, configuration files)
- **Describe the behavior you observed and what you expected**
- **Include your environment details** (OS, Python version, Lora Code version)

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion:

- **Use a clear and descriptive title**
- **Provide a detailed description of the proposed enhancement**
- **Explain why this enhancement would be useful**
- **List any alternatives you've considered**

### Pull Requests

1. **Fork the repository** and create your branch from `main`
2. **Install development dependencies:**
   ```bash
   pip install -e ".[dev]"
   ```
3. **Make your changes** and ensure they follow our coding standards
4. **Write or update tests** as needed
5. **Run the test suite:**
   ```bash
   pytest
   ```
6. **Update documentation** if needed
7. **Submit your pull request**

## Development Setup

```bash
# Clone your fork
git clone https://github.com/Lora-Technologies/loracode.git
cd loracode

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

## Coding Standards

### Python Style Guide

- Follow [PEP 8](https://pep8.org/) style guidelines
- Use meaningful variable and function names
- Add docstrings to all public functions and classes
- Keep functions focused and concise

### Code Formatting

We use the following tools to maintain code quality:

- **flake8** for linting
- **black** for code formatting (if configured)
- **isort** for import sorting

Run before committing:
```bash
flake8 loracode/
```

### Commit Messages

- Use the present tense ("Add feature" not "Added feature")
- Use the imperative mood ("Move cursor to..." not "Moves cursor to...")
- Limit the first line to 72 characters or less
- Reference issues and pull requests when relevant

Example:
```
Add support for custom model configurations

- Allow users to specify model parameters in config file
- Add validation for model settings
- Update documentation with new options

Fixes #123
```

## Testing

- Write tests for new features and bug fixes
- Ensure all tests pass before submitting a PR
- Aim for good test coverage

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=loracode

# Run specific test file
pytest tests/test_specific.py
```

## Documentation

- Update the README.md if you change functionality
- Add docstrings to new functions and classes
- Update configuration examples if needed

## Questions?

Feel free to open an issue with your question or reach out to the maintainers.

Thank you for contributing! 🎉
