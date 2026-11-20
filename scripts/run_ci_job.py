"""Run one job of .github/workflows/compose.yml on this machine, in a temporary copy of the checkout.

    uv run --with pyyaml python scripts/run_ci_job.py compose-smoke

Only `run` steps are executed. A checkout step that names another repository is cloned from a
sibling directory of this checkout when one exists, else with `gh repo clone`.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


def copy_checkout(target: Path) -> None:
    listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=REPO, capture_output=True, text=True, check=True).stdout.split("\n")
    for name in filter(None, listed):
        source = REPO / name
        if source.is_file():
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target / name)


def clone_other_repository(step: dict, root: Path) -> None:
    options = step.get("with", {})
    name = options["repository"].split("/")[-1]
    sibling = REPO.parent / name
    source = ["git", "clone", "-q", str(sibling)] if sibling.is_dir() else ["gh", "repo", "clone", options["repository"], "--", "-q"]
    subprocess.run([*source, str(root / options["path"])], check=True)
    subprocess.run(["git", "checkout", "-q", options["ref"]], cwd=root / options["path"], check=True)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    job = yaml.safe_load((REPO / ".github/workflows/compose.yml").read_text())["jobs"][sys.argv[1]]
    default_dir = job.get("defaults", {}).get("run", {}).get("working-directory", ".")
    with tempfile.TemporaryDirectory(prefix="crucible-ci-") as work:
        root, temp = Path(work) / "repo", Path(work) / "temp"
        root.mkdir()
        temp.mkdir()
        copy_checkout(root)
        env_file = temp / "github_env"
        env_file.write_text("")
        env = {**os.environ, **{key: str(value) for key, value in job.get("env", {}).items()}, "RUNNER_TEMP": str(temp), "GITHUB_ENV": str(env_file)}
        failed = False
        for step in job["steps"]:
            if "run" not in step:
                if step.get("with", {}).get("repository"):
                    clone_other_repository(step, root)
                continue
            condition = step.get("if", "success()")
            if (condition == "failure()" and not failed) or (condition == "success()" and failed):
                continue
            name = step.get("name", "step")
            print(f"=== {name}", flush=True)
            step_env = {**env, **{key: str(value) for key, value in step.get("env", {}).items()}}
            result = subprocess.run(["bash", "-eo", "pipefail", "-c", step["run"]], cwd=root / step.get("working-directory", default_dir), env=step_env)
            for line in env_file.read_text().splitlines():
                key, _, value = line.partition("=")
                env[key] = value
            if result.returncode:
                failed = True
                print(f"!!! FAILED ({result.returncode}): {name}", flush=True)
        print("JOB", "FAILED" if failed else "PASSED", flush=True)
        return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
