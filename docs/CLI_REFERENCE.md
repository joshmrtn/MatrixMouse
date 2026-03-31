# MatrixMouse CLI Reference

This document provides complete reference documentation for the MatrixMouse command-line interface.

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Basic Usage](#basic-usage)
- [Repository Management](#repository-management)
- [Task Management](#task-management)
- [Agent Control](#agent-control)
- [Communication](#communication)
- [Monitoring and Debugging](#monitoring-and-debugging)
- [Configuration](#configuration)
- [Decision Handling](#decision-handling)
- [Output Formats](#output-formats)
- [Non-Interactive Usage](#non-interactive-usage)

## Overview

The MatrixMouse CLI provides a non-interactive interface for managing the autonomous coding agent. All commands can be used in scripts and automation workflows.

The CLI communicates with the MatrixMouse service via its HTTP API. Most commands require the service to be running. Service management is handled by systemd:

```bash
sudo systemctl start matrixmouse
sudo systemctl stop matrixmouse
sudo systemctl status matrixmouse
sudo systemctl restart matrixmouse
```

## Installation

MatrixMouse is installed system-wide via uv:

```bash
./install.sh
```

This installs the `matrixmouse` command and sets up the systemd service.

## Basic Usage

Run `matrixmouse` without arguments to display help information:

```bash
matrixmouse
```

Run `matrixmouse --help` to see all available commands:

```bash
matrixmouse --help
```

Get help for a specific command:

```bash
matrixmouse tasks --help
matrixmouse tasks add --help
```

## Repository Management

### Add a Repository

Clone or register a repository into the workspace:

```bash
# Remote repository (HTTPS)
matrixmouse add-repo https://github.com/user/repo.git

# Remote repository (SSH)
matrixmouse add-repo git@github.com:user/repo.git

# Local repository (creates a mirror)
matrixmouse add-repo /path/to/local/repo

# With custom name
matrixmouse add-repo https://github.com/user/repo.git --name my-repo
```

For local repositories, the CLI creates a bare mirror and adds a `matrixmouse` remote to your working copy, enabling collaboration with the agent:

```bash
git push matrixmouse    # Share your work with the agent
git fetch matrixmouse   # Pull agent commits back
```

### List Repositories

```bash
matrixmouse repos list
```

Output in JSON format:

```bash
matrixmouse repos list --format json
```

### Remove a Repository

Remove a repository from the registry (does not delete the cloned directory):

```bash
# Interactive (asks for confirmation)
matrixmouse repos remove my-repo

# Non-interactive
matrixmouse repos remove my-repo --yes
```

## Task Management

### List Tasks

List all active tasks:

```bash
matrixmouse tasks list
```

Filter by status:

```bash
matrixmouse tasks list --status active
matrixmouse tasks list --status blocked_by_task
matrixmouse tasks list --status blocked_by_human
```

Filter by repo:

```bash
matrixmouse tasks list --repo my-repo
```

Include completed and cancelled tasks:

```bash
matrixmouse tasks list --all
```

Combine filters:

```bash
matrixmouse tasks list --status blocked --repo my-repo --all
```

Output in JSON format:

```bash
matrixmouse tasks list --format json
```

### Show Task Details

```bash
matrixmouse tasks show <task-id>
```

Task ID can be a full ID or unique prefix:

```bash
matrixmouse tasks show abc123
matrixmouse tasks show abc    # If abc uniquely identifies the task
```

Output in JSON format:

```bash
matrixmouse tasks show <task-id> --format json
```

### Add a Task

Create a task interactively (prompts for all fields):

```bash
matrixmouse tasks add
```

Create a task non-interactively:

```bash
matrixmouse tasks add --title "Fix authentication bug" \
  --description "The OAuth flow fails when the token expires." \
  --repo my-repo \
  --importance 0.8 \
  --urgency 0.6
```

Read description from a file:

```bash
matrixmouse tasks add --title "Implement feature" \
  --description @/path/to/description.txt \
  --repo my-repo
```

Read description from stdin:

```bash
cat description.txt | matrixmouse tasks add --title "Implement feature" \
  --description @- \
  --repo my-repo
```

Specify target files:

```bash
matrixmouse tasks add --title "Update API endpoints" \
  --description "Add new REST endpoints for user management" \
  --repo my-repo \
  --target-files src/api.py,src/handlers.py
```

Multiple repos (comma-separated):

```bash
matrixmouse tasks add --title "Update shared types" \
  --description "Sync types between frontend and backend" \
  --repo frontend,backend
```

### Edit a Task

Edit a task interactively (prompts for all editable fields):

```bash
matrixmouse tasks edit <task-id>
```

Edit specific fields non-interactively:

```bash
matrixmouse tasks edit <task-id> \
  --title "Updated title" \
  --importance 0.9
```

Update description from file:

```bash
matrixmouse tasks edit <task-id> --description @new-description.txt
```

Update from stdin:

```bash
echo "New description" | matrixmouse tasks edit <task-id> --description @-
```

Update multiple fields:

```bash
matrixmouse tasks edit <task-id> \
  --title "New title" \
  --description "Updated description" \
  --importance 0.7 \
  --urgency 0.8 \
  --notes "Priority increased per team discussion" \
  --repo repo1,repo2 \
  --target-files file1.py,file2.py
```

### Cancel a Task

Cancel with confirmation prompt:

```bash
matrixmouse tasks cancel <task-id>
```

Cancel without confirmation (for scripts):

```bash
matrixmouse tasks cancel <task-id> --yes
```

### Answer a Task Clarification

Answer a specific task's clarification question interactively:

```bash
matrixmouse tasks answer <task-id>
```

Answer non-interactively:

```bash
matrixmouse tasks answer <task-id> --message "Use the staging database for testing"
```

## Agent Control

### Show Agent Status

```bash
matrixmouse status
```

Shows current state: running, paused, stopped, or blocked, along with current task, role, and model.

### Soft Stop

Request the agent to stop after completing the current tool call:

```bash
matrixmouse stop
```

The agent will halt at the next safe boundary and can be resumed with `matrixmouse resume`.

### Emergency Stop (E-STOP)

Immediately shut down the agent without automatic restart:

```bash
# Interactive (requires typing "ESTOP" to confirm)
matrixmouse kill

# Non-interactive
matrixmouse kill --yes
```

After E-STOP, reset and restart:

```bash
matrixmouse estop reset
sudo systemctl start matrixmouse
```

### Check E-STOP Status

```bash
matrixmouse estop status
```

### Reset E-STOP

```bash
matrixmouse estop reset
```

### Pause Orchestration

Prevent the agent from starting new tasks (current task continues):

```bash
matrixmouse pause
```

### Resume Orchestration

Resume task scheduling after a pause:

```bash
matrixmouse resume
```

### Upgrade MatrixMouse

Upgrade to the latest version and rebuild the test runner image:

```bash
matrixmouse upgrade
```

The service is automatically restarted after upgrade.

## Communication

### Send Workspace Interjection

Send a workspace-scoped message to the Manager agent:

```bash
matrixmouse interject workspace "Please prioritize security fixes this week"
```

### Send Repo Interjection

Send a repo-scoped message to the Manager agent:

```bash
matrixmouse interject repo my-repo "Focus on the authentication module first"
```

### Send Task Interjection

Send a message to a specific task's agent:

```bash
matrixmouse interject task <task-id> "Consider using the cached response for better performance"
```

### Answer Pending Clarification (Legacy)

Answer a workspace-level pending clarification:

```bash
# Interactive
matrixmouse answer

# Non-interactive
matrixmouse answer --message "Proceed with the refactoring"
```

For task-specific clarifications, use `matrixmouse tasks answer <task-id>` instead.

## Monitoring and Debugging

### View Blocked Tasks

Show all blocked and waiting tasks with reasons:

```bash
matrixmouse blocked
```

Output in JSON format:

```bash
matrixmouse blocked --format json
```

### View Token Usage

Show token usage for remote providers (Anthropic, OpenAI):

```bash
matrixmouse token-usage
```

Output in JSON format:

```bash
matrixmouse token-usage --format json
```

### View Task Context

View the conversation history (context messages) for a specific task:

```bash
matrixmouse tasks context <task-id>
```

Show only the last N messages:

```bash
matrixmouse tasks context <task-id> --last 20
```

Show all messages (no default limit):

```bash
matrixmouse tasks context <task-id> --all
```

Output in JSON format:

```bash
matrixmouse tasks context <task-id> --format json
```

Each task maintains its own conversation history. The context includes system messages, user messages, assistant responses, thinking blocks, and tool call results.

By default, output is limited to 50 messages to prevent terminal flooding. Use `--last N` to specify a different limit, or `--all` to show the complete conversation.

To see which tasks are currently being processed by agents, use `matrixmouse tasks list --status running`.

### Health Check

Check if the API is reachable:

```bash
matrixmouse health
```

## Configuration

### Get Configuration

Show all workspace-level configuration values:

```bash
matrixmouse config get
```

Show a specific key:

```bash
matrixmouse config get coder_model
```

Show repo-level configuration:

```bash
matrixmouse config get --repo my-repo
```

### Set Configuration

Set a workspace-level config value:

```bash
matrixmouse config set coder_model ollama:qwen3.5:9b
```

Set a repo-level config value (untracked, local to workspace state dir):

```bash
matrixmouse config set coder_model ollama:qwen3.5:14b --repo my-repo
```

Set a repo-level config value (tracked, committed to repo tree):

```bash
matrixmouse config set coder_model ollama:qwen3.5:14b --repo my-repo --commit
```

Configuration changes require a service restart:

```bash
sudo systemctl restart matrixmouse
```

## Decision Handling

When tasks are blocked waiting for human decisions, use the `tasks decision` command.

### View Available Decision Types

```bash
matrixmouse decisions list
```

Output in JSON format:

```bash
matrixmouse decisions list --format json
```

### Submit a Decision

```bash
matrixmouse tasks decision <task-id> <decision-type> <choice> [--note "..."]
```

#### PR Approval Required

When the agent has created a PR and awaits approval:

```bash
# Approve the PR
matrixmouse tasks decision <task-id> pr_approval_required approve

# Reject the PR
matrixmouse tasks decision <task-id> pr_approval_required reject
```

#### PR Rejection Rework

When a PR was rejected and the agent asks how to proceed:

```bash
# Rework the code based on feedback
matrixmouse tasks decision <task-id> pr_rejection rework

# Handle manually (keep task blocked)
matrixmouse tasks decision <task-id> pr_rejection manual
```

#### Turn Limit Reached

When a task has exhausted its turn limit:

```bash
# Grant more turns
matrixmouse tasks decision <task-id> turn_limit_reached extend --extend-by 20

# Respec the task (reset turns with new direction)
matrixmouse tasks decision <task-id> turn_limit_reached respec --note "Try a different approach"

# Cancel the task
matrixmouse tasks decision <task-id> turn_limit_reached cancel
```

#### Critic Turn Limit Reached

When a Critic review task has exhausted turns:

```bash
# Approve the reviewed task directly
matrixmouse tasks decision <task-id> critic_turn_limit_reached approve_task

# Extend the Critic's turn limit
matrixmouse tasks decision <task-id> critic_turn_limit_reached extend_critic

# Block the reviewed task for manual review
matrixmouse tasks decision <task-id> critic_turn_limit_reached block_task
```

#### Merge Conflict Resolution Turn Limit

When merge conflict resolution has exhausted turns:

```bash
# Grant more turns
matrixmouse tasks decision <task-id> merge_conflict_resolution_turn_limit_reached extend

# Abort the merge
matrixmouse tasks decision <task-id> merge_conflict_resolution_turn_limit_reached abort
```

#### Planning Turn Limit Reached

When Manager planning has exhausted turns:

```bash
# Grant more planning turns
matrixmouse tasks decision <task-id> planning_turn_limit_reached extend

# Commit the partial plan as-is
matrixmouse tasks decision <task-id> planning_turn_limit_reached commit

# Cancel the planning task
matrixmouse tasks decision <task-id> planning_turn_limit_reached cancel
```

#### Decomposition Confirmation Required

When the Manager asks to decompose a task further:

```bash
# Allow further decomposition
matrixmouse tasks decision <task-id> decomposition_confirmation_required allow

# Deny decomposition (provide a reason)
matrixmouse tasks decision <task-id> decomposition_confirmation_required deny --note "Complete this task without further splitting"
```

## Output Formats

Most list and view commands support multiple output formats:

### Table Format (Default)

Human-readable table output:

```bash
matrixmouse tasks list
```

### JSON Format

Machine-readable JSON output:

```bash
matrixmouse tasks list --format json
```

JSON output is suitable for scripting and integration with other tools:

```bash
# Count active tasks
matrixmouse tasks list --format json | jq '.tasks | length'

# Get task titles
matrixmouse tasks list --format json | jq '.tasks[].title'

# Export to file
matrixmouse tasks list --format json > tasks.json
```

## Non-Interactive Usage

All CLI commands support non-interactive operation for use in scripts and automation.

### Key Patterns

1. **Use flags instead of prompts**: All commands that would prompt for input accept flags to provide values directly.

2. **Skip confirmations with `--yes`**: Commands that ask for confirmation accept `--yes` to proceed automatically.

3. **Read from stdin with `@-`**: Description fields can read from stdin using the `@-` syntax.

4. **Read from files with `@path`**: Description fields can read from files using the `@/path/to/file` syntax.

### Script Examples

#### Create a Task in a Script

```bash
#!/bin/bash

# Create a high-priority bug fix task
matrixmouse tasks add \
  --title "Fix critical authentication bug" \
  --description "OAuth tokens expire without refresh" \
  --repo backend \
  --importance 0.95 \
  --urgency 0.9
```

#### Batch Cancel Tasks

```bash
#!/bin/bash

# Cancel all tasks in a repo
matrixmouse tasks list --repo old-project --format json | \
  jq -r '.tasks[].id' | \
  while read task_id; do
    matrixmouse tasks cancel "$task_id" --yes
  done
```

#### Automated Decision Handling

```bash
#!/bin/bash

# Auto-approve all PRs from trusted repos
matrixmouse blocked --format json | \
  jq -r '.report[] | select(.reason | contains("PR approval")) | .task_id' | \
  while read task_id; do
    matrixmouse tasks decision "$task_id" pr_approval_required approve
  done
```

#### Monitor and Alert

```bash
#!/bin/bash

# Check for blocked tasks and send notification
blocked_count=$(matrixmouse blocked --format json | jq '.report | length')

if [ "$blocked_count" -gt 0 ]; then
  echo "MatrixMouse has $blocked_count blocked task(s) requiring attention" | \
    notify-send "MatrixMouse Alert"
fi
```

#### CI/CD Integration

```bash
#!/bin/bash

# In CI/CD: create a task for each failed test
for test in "${FAILED_TESTS[@]}"; do
  matrixmouse tasks add \
    --title "Fix failing test: $test" \
    --description "Test failed in CI build $BUILD_NUMBER" \
    --repo my-repo \
    --importance 0.7 \
    --urgency 0.8
done
```

## Environment Variables

The following environment variables can be used to configure CLI behavior:

| Variable | Description | Default |
|----------|-------------|---------|
| `WORKSPACE_PATH` | Path to the MatrixMouse workspace | `/var/lib/matrixmouse-workspace` |
| `MM_SERVER_PORT` | API server port | `8080` |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (invalid arguments, API error, service unreachable) |

## Troubleshooting

### Service Unreachable

If commands fail with "Could not reach the MatrixMouse service":

```bash
# Check service status
sudo systemctl status matrixmouse

# Start the service if stopped
sudo systemctl start matrixmouse

# Check logs for errors
journalctl -u matrixmouse -f
```

### Permission Denied on Config

If you see "Cannot read /etc/matrixmouse/config.toml":

```bash
# Log out and back in for group membership to take effect
# Or add yourself to the matrixmouse group
sudo usermod -aG matrixmouse $USER
```

### Ambiguous Task ID

If a task ID prefix matches multiple tasks:

```bash
# Use more characters to uniquely identify the task
matrixmouse tasks show abc123    # Instead of matrixmouse tasks show abc
```

### No Repos Registered

If commands fail due to no registered repos:

```bash
# Add a repository first
matrixmouse add-repo /path/to/repo
```
