---
name: openclaw
description: OpenClaw Skill Manager - Search and install skills from the OpenClaw registry.
---

# OpenClaw Skill Manager

This skill provides capabilities to search and install new skills from the OpenClaw registry (clawhub).

## Usage

You can use the `execute_shell_command` tool to interact with the OpenClaw registry using the `clawhub` CLI.

### Searching for Skills

To search for available skills, use the following command:

```bash
npx -y clawhub search <query>
```

Example:
```bash
npx -y clawhub search "weather"
```

### Installing Skills

To install a skill, you must install it into the session's skill directory. The session's skill directory is mapped to `/workspace/skills` in the sandbox.

**Important**: You MUST specify the `--dir` parameter as `/workspace/skills`.

```bash
npx -y clawhub install <slug> --dir /workspace/skills
```

Example:
```bash
npx -y clawhub install "google-search" --dir /workspace/skills
```

### After Installation

After installing a new skill, the system will automatically add the skills when constructing the next system prompt. You can then throw a reload skill command to reload the skill and use the new skill immediately.
