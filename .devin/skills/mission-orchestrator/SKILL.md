---
name: mission-orchestrator
description: Reads a mission/project context file, breaks it into tasks, dispatches child Devin sessions to execute them, and aggregates a final report.
---

# Mission Orchestrator

Use this skill when you have a large mission or project-context file (like `MISSAO_IGREJA12`) and want to split the work across multiple supervised Devin agents.

## What it does

1. **Planning** — one shared-VM agent reads the mission file and extracts a structured list of tasks (max 7).
2. **Execution** — each task runs in its own child Devin session (separate VM) with the full mission context and any dependency results.
3. **Reporting** — a shared-VM agent consolidates all outputs into a final status, blockers, and next action.

## How to run

### 1. Prepare the mission context file

Place the mission/context file on the Devin box and note its absolute path. The default path is the `MISSAO_IGREJA12` attachment path, but you can override it:

```bash
export MISSION_FILE=/home/ubuntu/missions/minha-missao.md
export REPO=haniellevi/PastorAI-LionClaw-V1
```

### 2. Run the workflow

```python
run_workflow(
    workflow_name="mission-orchestrator",
    script_path="/home/ubuntu/repos/PastorAI-LionClaw-V1/.devin/skills/mission-orchestrator/workflow.py",
)
```

### 3. Supervise

While it runs, poll progress with `get_workflow_output(run_id="wfr-...")`. The workflow logs each task start/finish and writes a machine-readable report to `/home/ubuntu/mission_orchestrator_report.json` when it completes.

## Configuration

You can set these environment variables before running:

| Variable | Description | Default |
|----------|-------------|---------|
| `MISSION_FILE` | Absolute path to the mission/context file | `/home/ubuntu/attachments/f2ea6938-ef83-45b7-850d-bf6897c7f944/MISSAO_IGREJA12` |
| `REPO` | Repository identifier in `owner/repo` format | `haniellevi/PastorAI-LionClaw-V1` |
| `MAX_TASKS` | Maximum number of tasks the planner may create | `7` |

## Output

- Console logs via `run_workflow` / `get_workflow_output`.
- Machine-readable report: `/home/ubuntu/mission_orchestrator_report.json`.
- Each task reports its own `artifacts`, `branch`, and `files_changed` in structured output.

## Course correction

If a task fails or produces the wrong result:

1. Edit the mission file (or the offending task description in it).
2. Re-run the workflow with the same `run_id` to retry failed/cached calls, or with a new `run_id` for a fresh start.
3. Failed tasks are recorded; you can dispatch a single follow-up child session using the same prompt with corrections.
