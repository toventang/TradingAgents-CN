from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs" / "jules" / "task-manifest.json"


def main() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise SystemExit("task-manifest.json must contain a non-empty tasks list")

    by_id: dict[str, dict] = {}
    for task in tasks:
        task_id = task.get("id")
        if not isinstance(task_id, str) or not re.fullmatch(r"J[0-9][0-9A-Z]", task_id):
            raise SystemExit(f"Invalid task id: {task_id!r}")
        if task_id in by_id:
            raise SystemExit(f"Duplicate task id: {task_id}")
        by_id[task_id] = task

    for task_id, task in by_id.items():
        dependencies = task.get("depends_on")
        if not isinstance(dependencies, list):
            raise SystemExit(f"{task_id}: depends_on must be a list")
        unknown = [dep for dep in dependencies if dep not in by_id]
        if unknown:
            raise SystemExit(f"{task_id}: unknown dependencies {unknown}")

        task_file = ROOT / task.get("task_file", "")
        if not task_file.is_file():
            raise SystemExit(f"{task_id}: missing task file {task_file}")
        content = task_file.read_text(encoding="utf-8")
        if f"## {task_id} " not in content:
            raise SystemExit(f"{task_id}: section not found in {task_file}")

        section_match = re.search(
            rf"^## {re.escape(task_id)} .*?(?=^## J[0-9][0-9A-Z] |\Z)",
            content,
            flags=re.MULTILINE | re.DOTALL,
        )
        if section_match is None:
            raise SystemExit(f"{task_id}: unable to parse task section")
        dependency_match = re.search(
            r"^- depends_on:\s*(.*)$",
            section_match.group(0),
            flags=re.MULTILINE,
        )
        if dependency_match is None:
            raise SystemExit(f"{task_id}: task packet is missing depends_on metadata")
        packet_value = dependency_match.group(1).strip()
        packet_dependencies = (
            []
            if packet_value == "none"
            else [item.strip() for item in packet_value.split(",") if item.strip()]
        )
        if packet_dependencies != dependencies:
            raise SystemExit(
                f"{task_id}: manifest dependencies {dependencies} do not match "
                f"task packet dependencies {packet_dependencies}"
            )

        prompt = task.get("prompt")
        if not isinstance(prompt, str) or task_id not in prompt:
            raise SystemExit(f"{task_id}: prompt must name its own task id")
        if task.get("risk") == "high" and task.get("require_plan_approval") is not True:
            raise SystemExit(f"{task_id}: high-risk task must require plan approval")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise SystemExit(f"Dependency cycle detected at {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in by_id[task_id]["depends_on"]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in by_id:
        visit(task_id)

    packet_ids: set[str] = set()
    for task_file in (ROOT / "docs" / "jules" / "tasks").glob("*.md"):
        packet_ids.update(
            re.findall(r"^## (J[0-9][0-9A-Z]) ", task_file.read_text(encoding="utf-8"), re.MULTILINE)
        )
    if packet_ids != set(by_id):
        missing_manifest = sorted(packet_ids - set(by_id))
        missing_packet = sorted(set(by_id) - packet_ids)
        raise SystemExit(
            f"Task packet/manifest mismatch: missing_manifest={missing_manifest}, "
            f"missing_packet={missing_packet}"
        )

    print(f"Jules manifest valid: {len(by_id)} tasks, no missing sections or dependency cycles")


if __name__ == "__main__":
    main()
