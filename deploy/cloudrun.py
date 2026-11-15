"""Deploy FIRMS Harmonizer to Google Cloud Run (pay-as-you-go with a monthly free tier).

    python deploy/cloudrun.py setup  --project <id> [--billing-account <id>] [--budget-eur 1]
    python deploy/cloudrun.py deploy --project <id> [--region europe-west1]
    python deploy/cloudrun.py status --project <id>

Requires the gcloud CLI logged in (`gcloud auth login`) and Docker. The image is built
locally from the repository Dockerfile, pushed to Artifact Registry and deployed with
scale-to-zero, a capped instance count and request-based CPU billing, which keeps hackathon
traffic inside the free tier. Runtime data is downloaded from the public Hugging Face
dataset named by --data-repo at container start-up.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE = "firms-harmonizer"
REGISTRY = "firms-harmonizer"
APIS = ["run.googleapis.com", "artifactregistry.googleapis.com", "billingbudgets.googleapis.com",
        "cloudresourcemanager.googleapis.com"]
WINDOWS_GCLOUD = Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd"


def gcloud_binary() -> str:
    found = shutil.which("gcloud") or (str(WINDOWS_GCLOUD) if WINDOWS_GCLOUD.is_file() else None)
    if not found:
        raise SystemExit("gcloud CLI not found. Install the Google Cloud CLI and run `gcloud auth login`.")
    bin_dir = str(Path(found).parent)
    if bin_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
    return found


def run(*args: str, capture: bool = False, check: bool = True) -> str:
    command = [gcloud_binary(), *args[1:]] if args[0] == "gcloud" else list(args)
    result = subprocess.run(command, cwd=REPO_ROOT, text=True, check=False,
                            capture_output=capture, encoding="utf-8")
    if check and result.returncode:
        detail = (result.stderr or "").strip().splitlines()[-3:] if capture else []
        raise SystemExit(f"Command failed ({result.returncode}): {' '.join(args[:4])} ...\n" + "\n".join(detail))
    return (result.stdout or "").strip()


def active_account() -> str:
    account = run("gcloud", "config", "get-value", "account", capture=True)
    if not account or account == "(unset)":
        raise SystemExit("gcloud is not logged in. Run `gcloud auth login` first.")
    return account


def project_exists(project: str) -> bool:
    return bool(run("gcloud", "projects", "list", f"--filter=projectId={project}", "--format=value(projectId)",
                    capture=True))


def setup(args) -> None:
    print(f"Account: {active_account()}")
    if not project_exists(args.project):
        print(f"Creating project {args.project}.")
        run("gcloud", "projects", "create", args.project, "--name=FIRMS-Harmonizer")
    accounts = json.loads(run("gcloud", "billing", "accounts", "list", "--filter=open=true", "--format=json",
                              capture=True) or "[]")
    billing = args.billing_account or (accounts[0]["name"].split("/")[-1] if len(accounts) == 1 else None)
    if not billing:
        names = ", ".join(f"{a['displayName']} ({a['name'].split('/')[-1]})" for a in accounts) or "none"
        raise SystemExit("Choose a billing account with --billing-account. Open billing accounts: " + names +
                         ". Create one at https://console.cloud.google.com/billing if the list is empty.")
    run("gcloud", "billing", "projects", "link", args.project, f"--billing-account={billing}")
    print(f"Billing account {billing} linked.")
    run("gcloud", "services", "enable", *APIS, f"--project={args.project}")
    print("APIs enabled: " + ", ".join(APIS))
    repositories = run("gcloud", "artifacts", "repositories", "list", f"--project={args.project}",
                       f"--location={args.region}", "--format=value(name)", capture=True)
    if REGISTRY not in repositories:
        run("gcloud", "artifacts", "repositories", "create", REGISTRY, "--repository-format=docker",
            f"--location={args.region}", f"--project={args.project}", "--description=FIRMS-Harmonizer-images")
    # Keep only the latest images so storage stays inside the 0.5 GB free tier.
    policy = REPO_ROOT / "deploy" / "artifact_cleanup_policy.json"
    run("gcloud", "artifacts", "repositories", "set-cleanup-policies", REGISTRY, f"--policy={policy}",
        f"--location={args.region}", f"--project={args.project}", "--no-dry-run", "--quiet")
    budgets = run("gcloud", "billing", "budgets", "list", f"--billing-account={billing}", f"--billing-project={args.project}",
                  "--format=value(displayName)", capture=True, check=False)
    if "FIRMS-Harmonizer" not in budgets:
        number = run("gcloud", "projects", "describe", args.project, "--format=value(projectNumber)", capture=True)
        run("gcloud", "billing", "budgets", "create", f"--billing-account={billing}", f"--billing-project={args.project}",
            "--display-name=FIRMS-Harmonizer", f"--budget-amount={args.budget_eur}EUR",
            f"--filter-projects=projects/{number}", "--threshold-rule=percent=0.5",
            "--threshold-rule=percent=0.9", "--threshold-rule=percent=1.0")
        print(f"Budget alert created at {args.budget_eur} EUR (email to billing administrators).")
    print("Setup complete.")


def deploy(args) -> None:
    print(f"Account: {active_account()}")
    revision = run("git", "rev-parse", "--short", "HEAD", capture=True)
    image = f"{args.region}-docker.pkg.dev/{args.project}/{REGISTRY}/{SERVICE}:{revision}"
    run("gcloud", "auth", "configure-docker", f"{args.region}-docker.pkg.dev", "--quiet")
    print(f"Building {image}.")
    run("docker", "build", "--platform=linux/amd64", "-t", image, ".")
    run("docker", "push", image)
    flags = [f"--image={image}", f"--project={args.project}", f"--region={args.region}", "--platform=managed",
             "--allow-unauthenticated", "--memory=2Gi", "--cpu=1", "--min-instances=0",
             f"--max-instances={args.max_instances}", "--concurrency=8", "--timeout=300", "--cpu-boost",
             "--execution-environment=gen2", "--port=7860",
             f"--update-env-vars=DATA_REPO={args.data_repo},NRT_POLLING=0,USE_SYNTHETIC_CUBE=0"]
    run("gcloud", "run", "deploy", SERVICE, *flags, "--quiet")
    url = run("gcloud", "run", "services", "describe", SERVICE, f"--project={args.project}",
              f"--region={args.region}", "--format=value(status.url)", capture=True)
    check_health(url)


def check_health(url: str) -> None:
    for _ in range(30):
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=60) as response:
                health = json.loads(response.read())
            print(f"Live: {url} | health={health.get('status')} data_source={health.get('data_source')} "
                  f"rows={health.get('row_count')}")
            return
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(10)
    raise SystemExit(f"Deployed, but {url}/api/health did not answer. Check the Cloud Run logs.")


def status(args) -> None:
    url = run("gcloud", "run", "services", "describe", SERVICE, f"--project={args.project}",
              f"--region={args.region}", "--format=value(status.url)", capture=True)
    check_health(url)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="europe-west1")
    commands = parser.add_subparsers(dest="command", required=True)
    first = commands.add_parser("setup", help="Create the project, link billing, enable APIs and add a budget alert.")
    first.add_argument("--billing-account")
    first.add_argument("--budget-eur", type=int, default=1)
    first.set_defaults(func=setup)
    release = commands.add_parser("deploy", help="Build, push and deploy the container.")
    release.add_argument("--data-repo", default="andearlla/firms-harmonizer-data")
    release.add_argument("--max-instances", type=int, default=1)
    release.set_defaults(func=deploy)
    check = commands.add_parser("status", help="Print the service URL and its health.")
    check.set_defaults(func=status)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
