import asyncio
import json
import os

# Configure the orchestrator by setting these environment variables before running, or edit the defaults below.
# run_workflow(script_path="/absolute/path/to/workflow.py", workflow_name="mission-orchestrator")
MISSION_FILE = os.environ.get("MISSION_FILE", "/home/ubuntu/attachments/f2ea6938-ef83-45b7-850d-bf6897c7f944/MISSAO_IGREJA12")
REPO = os.environ.get("REPO", "haniellevi/PastorAI-LionClaw-V1")
MAX_TASKS = int(os.environ.get("MAX_TASKS", "7"))

META = {
    "name": "mission-orchestrator",
    "description": "Reads a mission context file, breaks it into tasks, dispatches child Devin sessions, and aggregates results.",
    "product": "Devin Mission Orchestrator",
    "phases": [
        {"title": "plan", "detail": "Parse mission context into a structured task list", "count": 1, "labels": ["planner"]},
        {"title": "execute", "detail": "Run independent tasks in parallel child Devin sessions", "count": 1, "labels": ["workers"]},
        {"title": "report", "detail": "Aggregate outputs into a human-readable final report", "count": 1, "labels": ["reporter"]},
    ],
}

TASK_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "expected_deliverables": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "title", "description"],
            },
        }
    },
    "required": ["tasks"],
}

TASK_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["done", "blocked", "failed", "skipped"]},
        "summary": {"type": "string"},
        "artifacts": {"type": "array", "items": {"type": "string"}},
        "blockers": {"type": "array", "items": {"type": "string"}},
        "next_steps": {"type": "array", "items": {"type": "string"}},
        "branch": {"type": "string"},
        "files_changed": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "summary"],
}

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "summary": {"type": "string"},
        "blockers": {"type": "array", "items": {"type": "string"}},
        "next_action": {"type": "string"},
        "risk_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "summary", "next_action"],
}


def load_mission(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


async def main():
    await register_workflow(META)

    if not os.path.exists(MISSION_FILE):
        log(f"Mission file not found: {MISSION_FILE}")
        raise FileNotFoundError(f"Mission file not found: {MISSION_FILE}")

    mission_content = load_mission(MISSION_FILE)
    log(f"Loaded mission file: {MISSION_FILE} ({len(mission_content)} chars)")

    # Phase 1: planner parses the mission into a structured task list.
    planner_prompt = (
        "You are a mission orchestrator for a Devin workflow. "
        "Read the following mission/project context file and break it down into a short list of concrete, "
        "actionable tasks that can each be executed by one Devin agent session.\n\n"
        "Rules:\n"
        f"- Produce at most {MAX_TASKS} tasks. Group related work.\n"
        "- Focus on next actions and open work, not historical narration.\n"
        "- Each task must be small enough for a single agent to complete in one session.\n"
        "- Include task id, title, detailed description, optional dependencies (depends_on), and expected deliverables.\n"
        "- If the mission already lists numbered steps or objectives, turn those into tasks directly.\n\n"
        "Return a JSON object matching the schema with a 'tasks' array.\n\n"
        "Mission context file:\n"
        "---\n"
        f"{mission_content[:300000]}\n"
        "---"
    )

    plan = await agent(
        prompt=planner_prompt,
        phase="plan",
        schema=TASK_LIST_SCHEMA,
        label="planner",
        vm_mode="shared",
    )

    tasks = plan.get("tasks", [])
    if not tasks:
        log("Planner produced no tasks.")
        return

    log(f"Planner produced {len(tasks)} tasks: {[t['id'] for t in tasks]}")

    # Phase 2: execute tasks respecting dependencies.
    results = {}
    pending = {t["id"]: t for t in tasks}
    completed = set()

    while pending:
        ready = [
            t for t in pending.values()
            if all(dep in completed for dep in t.get("depends_on", []))
        ]

        if not ready:
            remaining = list(pending.keys())
            log(f"Cannot schedule remaining tasks due to unresolved/circular dependencies: {remaining}")
            for tid in remaining:
                results[tid] = {
                    "status": "blocked",
                    "summary": "Could not schedule: unresolved or circular dependencies.",
                    "blockers": ["Unresolved or circular dependency"],
                    "artifacts": [],
                    "next_steps": ["Fix task dependencies in the mission context and re-run."],
                }
                completed.add(tid)
                del pending[tid]
            break

        async def run_task(task):
            prior = {
                dep: results[dep]
                for dep in task.get("depends_on", [])
                if dep in results
            }
            worker_prompt = (
                f"You are a Devin agent working on one task of the mission for repo {REPO}.\n\n"
                f"Task ID: {task['id']}\n"
                f"Title: {task['title']}\n"
                f"Description:\n{task['description']}\n\n"
                f"Expected deliverables: {json.dumps(task.get('expected_deliverables', []), ensure_ascii=False)}\n\n"
            )
            if prior:
                worker_prompt += (
                    "Results from tasks this one depends on:\n"
                    f"{json.dumps(prior, ensure_ascii=False, indent=2)}\n\n"
                )
            worker_prompt += (
                "Full mission context (for reference):\n"
                "---\n"
                f"{mission_content[:200000]}\n"
                "---\n\n"
                "Instructions:\n"
                "1. Execute this task in the repo above.\n"
                "2. If you create files or code changes, push them to a git branch named after this task id (e.g., 'devin/task-{id}').\n"
                "3. For research or validation, return concise findings.\n"
                "4. If blocked, explain why and what is needed.\n"
                "5. Return the structured result."
            )

            return await agent(
                prompt=worker_prompt,
                phase="execute",
                schema=TASK_RESULT_SCHEMA,
                label=f"task-{task['id']}",
                repos=[REPO],
            )

        batch_results = await asyncio.gather(*(run_task(t) for t in ready), return_exceptions=True)

        for task, res in zip(ready, batch_results):
            tid = task["id"]
            if isinstance(res, Exception):
                log(f"Task {tid} raised exception: {res}")
                results[tid] = {
                    "status": "failed",
                    "summary": f"Exception: {res}",
                    "blockers": [str(res)],
                    "artifacts": [],
                    "next_steps": ["Re-run the workflow to retry this task."],
                }
            else:
                results[tid] = res
                log(f"Task {tid}: {res['status']} - {res['summary'][:80]}")

            completed.add(tid)
            del pending[tid]

    # Phase 3: final report.
    counts = {"done": 0, "failed": 0, "blocked": 0, "skipped": 0}
    for r in results.values():
        counts[r.get("status", "failed")] += 1

    summary_payload = {
        "mission_file": MISSION_FILE,
        "repo": REPO,
        "task_count": len(tasks),
        "counts": counts,
        "results": results,
    }

    reporter_prompt = (
        "You are the orchestrator summarizer. Review the mission results below and produce a final report for the human operator.\n"
        "Be concise, highlight blockers, and state the single most important next action.\n\n"
        "Results:\n"
        f"{json.dumps(summary_payload, ensure_ascii=False, indent=2)[:250000]}\n"
    )

    final_report = await agent(
        prompt=reporter_prompt,
        phase="report",
        schema=REPORT_SCHEMA,
        label="reporter",
        vm_mode="shared",
    )

    log("Final report generated.")
    log(f"Status: {final_report['status']}")
    log(f"Summary: {final_report['summary']}")
    log(f"Next action: {final_report['next_action']}")

    # Persist a machine-readable summary for the parent session.
    report_path = "/home/ubuntu/mission_orchestrator_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "mission_file": MISSION_FILE,
            "repo": REPO,
            "counts": counts,
            "final_report": final_report,
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    log(f"Machine-readable report written to {report_path}")


asyncio.run(main())
