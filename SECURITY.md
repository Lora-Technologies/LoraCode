# Security Policy

## Supported Versions

We release patches for security vulnerabilities for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

We take the security of Lora Code seriously. If you believe you have found a security vulnerability, please report it to us as described below.

### Please do NOT:

- Open a public GitHub issue for security vulnerabilities
- Disclose the vulnerability publicly before we've had a chance to address it

### Please DO:

1. **Email us directly** at security@loratech.dev with:
   - A description of the vulnerability
   - Steps to reproduce the issue
   - Potential impact of the vulnerability
   - Any possible mitigations you've identified

2. **Allow us time to respond** - We will acknowledge your email within 48 hours and provide a more detailed response within 7 days.

3. **Work with us** - We may ask for additional information or guidance to help us understand and resolve the issue.

## What to Expect

After you submit a vulnerability report:

1. **Acknowledgment**: We will acknowledge receipt of your report within 48 hours.

2. **Assessment**: Our security team will assess the vulnerability and determine its severity and impact.

3. **Resolution**: We will work on a fix and coordinate with you on the disclosure timeline.

4. **Disclosure**: Once the vulnerability is fixed, we will:
   - Release a security update
   - Publish a security advisory
   - Credit you for the discovery (unless you prefer to remain anonymous)

## Security Best Practices for Users

When using Lora Code:

1. **Keep your API keys secure** - Never commit API keys to version control
2. **Use environment variables** - Store sensitive configuration in environment variables or `.env` files
3. **Keep Lora Code updated** - Always use the latest version to benefit from security patches
4. **Review code changes** - Always review AI-suggested code changes before accepting them
5. **Use in trusted environments** - Be cautious when using Lora Code with sensitive codebases

## Security Features

Lora Code includes several security features:

- **Local code processing** - Your code stays on your machine; only prompts are sent to the API
- **Secure API communication** - All API communication uses HTTPS
- **No telemetry by default** - Analytics are opt-in and can be permanently disabled
- **Git integration** - Changes are tracked and can be easily reverted

## Contact

For security-related inquiries, please contact: security@loratech.dev

For general support, please use: support@loratech.dev
