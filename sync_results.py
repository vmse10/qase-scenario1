import os
import sys
import argparse
import logging
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv


# --------------------------------------------------------------------
# Environment & logging setup
# --------------------------------------------------------------------

load_dotenv()

API_TOKEN = os.getenv("QASE_API_TOKEN")
BASE_URL = os.getenv("QASE_BASE_URL", "https://api.qase.io/v1").rstrip("/")

if not API_TOKEN:
    print("ERROR: QASE_API_TOKEN not found in .env")
    sys.exit(1)

# Logging:
# - Console: we keep using print() for normal info.
# - File: only ERROR level is written, with timestamp and function name.
LOG_FILE = os.getenv("QASE_SYNC_LOG_FILE", "sync_results_errors.log")

logger = logging.getLogger("qase_sync")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.ERROR)
formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(funcName)s - %(message)s"
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

HEADERS = {
    "Token": API_TOKEN,
    "Accept": "application/json",
    "Content-Type": "application/json",
}

AUTOMATION_CF_TITLE_DEFAULT = "Automation Key"


# --------------------------------------------------------------------
# Generic API helpers
# --------------------------------------------------------------------

def api_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Wrapper for GET requests to Qase API with basic error handling."""
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.get(url, headers=HEADERS, params=params or {})
    except Exception as exc:
        logger.error(f"GET {url} failed with exception: {exc}", exc_info=True)
        raise

    if not resp.ok:
        logger.error(f"GET {url} failed: {resp.status_code} {resp.text}")
        raise RuntimeError(f"GET {url} failed: {resp.status_code} {resp.text}")

    data = resp.json()
    if not data.get("status", True):
        logger.error(f"GET {url} returned status=false: {data}")
        raise RuntimeError(f"GET {url} returned status=false: {data}")

    return data["result"]


def api_post(path: str, payload: Dict[str, Any]) -> Any:
    """Wrapper for POST requests to Qase API with basic error handling."""
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.post(url, headers=HEADERS, json=payload)
    except Exception as exc:
        logger.error(f"POST {url} failed with exception: {exc}", exc_info=True)
        raise

    if not resp.ok:
        logger.error(f"POST {url} failed: {resp.status_code} {resp.text}")
        raise RuntimeError(f"POST {url} failed: {resp.status_code} {resp.text}")

    data = resp.json()
    if not data.get("status", True):
        logger.error(f"POST {url} returned status=false: {data}")
        raise RuntimeError(f"POST {url} returned status=false: {data}")

    return data["result"]


# --------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------

def get_run_by_id(project_code: str, run_id: int) -> Dict[str, Any]:
    """Return a single run by its ID in a given project."""
    result = api_get(f"/run/{project_code}/{run_id}")
    return result


def find_run_by_title(project_code: str, title: str) -> Optional[Dict[str, Any]]:
    """Search for a run by its title in the given project."""
    offset = 0
    limit = 50

    while True:
        result = api_get(f"/run/{project_code}", params={"limit": limit, "offset": offset})
        entities = result.get("entities", [])
        if not entities:
            break

        for run in entities:
            run_title = run.get("title") or run.get("name")
            if run_title == title:
                return run

        if len(entities) < limit:
            break
        offset += limit

    return None


def get_latest_run(project_code: str) -> Dict[str, Any]:
    """
    Return the most recent run in a project.

    For simplicity in this assignment, we consider the run with the highest ID
    to be the newest one.
    """
    offset = 0
    limit = 50
    latest_run: Optional[Dict[str, Any]] = None

    while True:
        result = api_get(f"/run/{project_code}", params={"limit": limit, "offset": offset})
        entities = result.get("entities", [])
        if not entities:
            break

        for run in entities:
            if latest_run is None or run["id"] > latest_run["id"]:
                latest_run = run

        if len(entities) < limit:
            break
        offset += limit

    if latest_run is None:
        logger.error(f"No runs found in project {project_code}")
        raise RuntimeError(f"No runs found in project {project_code}")

    title = latest_run.get("title") or latest_run.get("name")
    print(f"[INFO] Latest run in {project_code}: id={latest_run['id']} title='{title}'")
    return latest_run


# --------------------------------------------------------------------
# Results
# --------------------------------------------------------------------

def get_results_for_run(project_code: str, run_id: int) -> List[Dict[str, Any]]:
    """
    Fetch all results for a specific run in a project.

    Uses the 'run' query parameter, which worked correctly in your previous tests.
    """
    all_results: List[Dict[str, Any]] = []
    offset = 0
    limit = 50

    while True:
        result = api_get(
            f"/result/{project_code}",
            params={"limit": limit, "offset": offset, "run": run_id},
        )
        entities = result.get("entities", [])
        all_results.extend(entities)

        if len(entities) < limit:
            break
        offset += limit

    print(f"[INFO] Fetched {len(all_results)} results for run {run_id} in {project_code}")
    return all_results


# --------------------------------------------------------------------
# Custom fields / Cases
# --------------------------------------------------------------------

def get_custom_field_id_by_name(field_title: str) -> int:
    """Return the ID of a custom field (for cases) based on its title."""
    result = api_get("/custom_field", params={"limit": 100, "offset": 0})
    for cf in result.get("entities", []):
        if cf.get("title") == field_title and cf.get("entity") == "case":
            print(f"[INFO] Found custom field '{field_title}' with id={cf['id']}")
            return cf["id"]

    logger.error(f"Custom field '{field_title}' (entity=case) not found.")
    raise RuntimeError(f"Custom field '{field_title}' (entity=case) not found.")


def get_cases_with_automation_key(
    project_code: str,
    automation_cf_id: int,
) -> Dict[str, Dict[str, Any]]:
    """
    Return a mapping:
        automation_key (str) -> case_entity (dict)
    Only for cases that have the Automation Key custom field filled.
    """
    by_key: Dict[str, Dict[str, Any]] = {}
    offset = 0
    limit = 50

    while True:
        result = api_get(f"/case/{project_code}", params={"limit": limit, "offset": offset})
        entities = result.get("entities", [])
        if not entities:
            break

        for case in entities:
            cf_list = case.get("custom_fields", [])
            auto_val = None
            for cf in cf_list:
                if cf.get("id") == automation_cf_id:
                    auto_val = cf.get("value")
                    break

            if auto_val:
                by_key[auto_val] = case

        if len(entities) < limit:
            break
        offset += limit

    print(f"[INFO] Project {project_code}: found {len(by_key)} cases with Automation Key")
    return by_key


def create_case_in_target(
    target_project: str,
    source_case: Dict[str, Any],
    automation_cf_id: int,
    automation_key: str,
) -> Dict[str, Any]:
    """
    Create a test case in the target project, cloning basic information from the
    source case and applying the same Automation Key.
    """
    payload = {
        "title": source_case.get("title") or f"Auto-created {automation_key}",
        "description": source_case.get("description", ""),
        "custom_fields": [
            {"id": automation_cf_id, "value": automation_key}
        ],
    }

    result = api_post(f"/case/{target_project}", payload)
    new_id = result["id"]
    print(f"[INFO] Created case in {target_project}: id={new_id} key={automation_key}")
    return {
        "id": new_id,
        "title": payload["title"],
        "custom_fields": payload["custom_fields"],
    }


# --------------------------------------------------------------------
# Target run handling
# --------------------------------------------------------------------

def get_or_create_target_run(
    target_project: str,
    target_run_title: str,
    source_run: Dict[str, Any],
    source_project: str,
    case_ids_for_run: List[int],
) -> int:
    """
    Find or create a run in the target project.

    If a run with the given title already exists, reuse it.
    Otherwise, create a new run including the given list of case IDs.
    """
    existing = find_run_by_title(target_project, target_run_title)
    if existing:
        print(
            f"[INFO] Found existing run in {target_project}: "
            f"id={existing['id']} title='{target_run_title}'"
        )
        return existing["id"]

    payload = {
        "title": target_run_title,
        "description": (
            f"Auto-created mirror of run {source_run['id']} from project {source_project}"
        ),
        "cases": sorted(set(case_ids_for_run)),
    }
    created = api_post(f"/run/{target_project}", payload)
    run_id = created["id"]
    print(f"[INFO] Created new run in {target_project}: id={run_id} title='{target_run_title}'")
    return run_id


# --------------------------------------------------------------------
# Target results
# --------------------------------------------------------------------

def create_result_in_target(
    target_project: str,
    target_run_id: int,
    target_case_id: int,
    source_result: Dict[str, Any],
    source_project: str,
):
    """
    Create a result in the target run for a given case, cloning information from
    the source result.
    """
    status = source_result.get("status", "passed")
    comment = source_result.get("comment") or ""
    time_spent = source_result.get("time")

    payload: Dict[str, Any] = {
        "status": status,
        "case_id": target_case_id,
    }
    if comment:
        payload["comment"] = f"[Mirrored from {source_project}] {comment}"
    if time_spent is not None:
        payload["time"] = time_spent

    api_post(f"/result/{target_project}/{target_run_id}", payload)
    print(f"    [OK] Result for case_id={target_case_id} status={status}")


# --------------------------------------------------------------------
# Core sync logic
# --------------------------------------------------------------------

def sync_run(
    source_project: str,
    target_project: str,
    source_run: Dict[str, Any],
    target_run_title: str,
    automation_cf_title: str,
):
    """
    Sync a single run from source_project to target_project based on Automation Key.

    Steps:
    1. Fetch results from the source run.
    2. Build a mapping from source cases to Automation Keys.
    3. Ensure all relevant cases exist in the target project (create if needed).
    4. Find or create the target run.
    5. Create corresponding results in the target run.
    """
    run_id = source_run["id"]
    source_run_title = source_run.get("title") or source_run.get("name")
    print(
        f"[INFO] Syncing run id={run_id} title='{source_run_title}' "
        f"from {source_project} -> {target_project} "
        f"(target run title='{target_run_title}')"
    )

    # 1) Fetch results from the source run
    results = get_results_for_run(source_project, run_id)
    if not results:
        print("[WARN] No results found for this run. Nothing to sync.")
        return

    # 2) Find Automation Key custom field ID
    automation_cf_id = get_custom_field_id_by_name(automation_cf_title)

    # 3) Source cases by Automation Key
    source_cases_by_key = get_cases_with_automation_key(source_project, automation_cf_id)
    source_caseid_to_key: Dict[int, str] = {}
    for key, case in source_cases_by_key.items():
        source_caseid_to_key[case["id"]] = key

    # 4) Target cases by Automation Key
    target_cases_by_key = get_cases_with_automation_key(target_project, automation_cf_id)

    # 5) Ensure all cases referenced in the source run exist in the target project
    target_case_ids_for_run: List[int] = []

    for r in results:
        src_case_id = r.get("case_id")
        if not src_case_id:
            print("[WARN] Result without case_id found, skipping.")
            continue

        auto_key = source_caseid_to_key.get(src_case_id)
        if not auto_key:
            print(f"[WARN] Source case_id={src_case_id} has no Automation Key, skipping.")
            continue

        target_case = target_cases_by_key.get(auto_key)
        if not target_case:
            source_case = source_cases_by_key[auto_key]
            target_case = create_case_in_target(
                target_project,
                source_case,
                automation_cf_id,
                auto_key,
            )
            target_cases_by_key[auto_key] = target_case

        target_case_ids_for_run.append(target_case["id"])

    if not target_case_ids_for_run:
        print("[WARN] No cases with Automation Key to mirror. Stopping.")
        return

    # 6) Find or create the target run
    target_run_id = get_or_create_target_run(
        target_project,
        target_run_title,
        source_run,
        source_project,
        target_case_ids_for_run,
    )

    # 7) Create mirrored results in the target run
    print(f"[INFO] Creating results in {target_project} run_id={target_run_id} ...")
    for r in results:
        src_case_id = r.get("case_id")
        if not src_case_id:
            continue

        auto_key = source_caseid_to_key.get(src_case_id)
        if not auto_key:
            continue

        target_case = target_cases_by_key.get(auto_key)
        if not target_case:
            continue

        create_result_in_target(
            target_project,
            target_run_id,
            target_case["id"],
            r,
            source_project,
        )

    print("[INFO] Sync completed.")


# --------------------------------------------------------------------
# CLI entrypoint
# --------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Sync Qase test run results from one project to another using a shared "
            "Automation Key custom field."
        )
    )

    parser.add_argument(
        "--source-project",
        required=True,
        help="Source project code (e.g. DEMO)",
    )
    parser.add_argument(
        "--target-project",
        required=True,
        help="Target project code (e.g. AO)",
    )

    # Source run selector: ID OR title OR latest (mutually exclusive)
    source_run_group = parser.add_mutually_exclusive_group(required=True)
    source_run_group.add_argument(
        "--source-run-id",
        type=int,
        help="ID of the run in the source project.",
    )
    source_run_group.add_argument(
        "--source-run-title",
        help="Title of the run in the source project.",
    )
    source_run_group.add_argument(
        "--use-latest-source-run",
        action="store_true",
        help="Use the latest run in the source project.",
    )

    # Target run: either reuse an existing ID, or specify a title (or fall back to source title)
    parser.add_argument(
        "--target-run-id",
        type=int,
        help=(
            "ID of the run in the target project. "
            "If not provided, --target-run-title is used (or the source run title)."
        ),
    )
    parser.add_argument(
        "--target-run-title",
        help=(
            "Title of the run in the target project. "
            "If omitted and --target-run-id is not set, the source run title is used."
        ),
    )

    parser.add_argument(
        "--automation-field-title",
        default=AUTOMATION_CF_TITLE_DEFAULT,
        help="Title of the custom field used as Automation Key (default: 'Automation Key').",
    )

    args = parser.parse_args()

    source_project = args.source_project
    target_project = args.target_project

    # 1) Resolve source run
    if args.source_run_id is not None:
        source_run = get_run_by_id(source_project, args.source_run_id)
    elif args.source_run_title:
        run = find_run_by_title(source_project, args.source_run_title)
        if not run:
            msg = (
                f"Run with title '{args.source_run_title}' not found "
                f"in project {source_project}"
            )
            logger.error(msg)
            raise RuntimeError(msg)
        source_run = run
    elif args.use_latest_source_run:
        source_run = get_latest_run(source_project)
    else:
        # argparse enforces that one option is chosen, so we should never get here
        raise RuntimeError("No source run selector provided.")

    # 2) Resolve target run title
    if args.target_run_id is not None:
        target_run = get_run_by_id(target_project, args.target_run_id)
        target_run_title = target_run.get("title") or target_run.get("name")
        print(
            f"[INFO] Target run already exists: project={target_project} "
            f"id={target_run['id']} title='{target_run_title}'"
        )
    else:
        # If no explicit target run, use provided title or fallback to source title
        target_run_title = args.target_run_title or (
            source_run.get("title") or source_run.get("name")
        )

    # 3) Perform synchronization
    sync_run(
        source_project=source_project,
        target_project=target_project,
        source_run=source_run,
        target_run_title=target_run_title,
        automation_cf_title=args.automation_field_title,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Any unhandled exception will be logged to the error log file
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        print(f"[ERROR] {exc}")
        sys.exit(1)
