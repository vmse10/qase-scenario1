# Qase Scenario 1 – Cross-Project Result Sync

This repository contains a small Python tool that synchronizes automated test results
between two Qase projects using a shared **Automation Key** custom field.

It is designed to solve **Scenario 1** from the Qase Solutions & Implementation Specialist
assignment:

> - Project A contains the full regression suite (manual + automated tests).  
> - Project B is automation-only; the CI pipeline posts automated results there.  
> - The user wants the results from a test run in Project B to be automatically
>   copied into the corresponding test run in Project A, with each result mapped
>   to the correct test case.

Instead of manually copying results between projects, this script:

- reads results from a **source project / run**,  
- maps each result to the corresponding test case in a **target project**,  
- and posts mirrored results into a **target run**.

Mapping is driven by a shared **Automation Key** custom field on test cases.

---

## High-Level Approach

### 1. Shared Automation Key

Both projects use a custom field on cases, for example:

- Title: `Automation Key`
- Entity: `case`

Each test case that has an automated counterpart is assigned a stable key, such as:

- `SIGN_001`
- `LOGIN_001`
- `CPROJECT_001`
- `EPROJECT_001`
- `DPROJECT_001`

The internal case IDs in the two projects can differ completely; the only requirement is:

> **Matching Automation Key values mean “these two cases are counterparts”.**

The script uses this Automation Key as the join between projects.

---

### 2. Data Flow & Architecture

The script performs the following steps:

1. **Discover the Automation Key custom field**

   - Calls `GET /custom_field` to retrieve all custom fields.
   - Filters by:
     - `entity == "case"`
     - `title == "Automation Key"` (configurable via CLI)
   - Extracts the `id` of this field for later use.

2. **Build case mappings in both projects**

   - Calls `GET /case/{project_code}` for:
     - **Source project** (e.g. automation-only project, “Project B”)
     - **Target project** (e.g. full regression project, “Project A”)
   - For each case, inspects `custom_fields` and builds:
     - `automation_key -> source_case`
     - `automation_key -> target_case`

   Only cases with a non-empty Automation Key are considered for synchronization.

3. **Select the source run**

   The source run (where results currently live) can be selected in three ways:

   - `--source-run-id` – use a known run ID, or
   - `--source-run-title` – search by the run title, or
   - `--use-latest-source-run` – automatically pick the run with the highest ID
     (treated as the most recent run).

   The script calls:
   - `GET /run/{project_code}` (list)
   - `GET /run/{project_code}/{id}` (single run)

4. **Fetch results from the source run**

   - Calls:

     ```text
     GET /result/{project_code}?run=<source_run_id>&limit=...&offset=...
     ```

   - Collects all entities for that run (handles pagination with `limit`/`offset`).
   - For each result, captures:
     - `case_id`
     - `status`
     - `time`
     - `comment`

5. **Ensure the target project has all needed cases**

   For each result in the source run:

   - Look up the corresponding **source case** by `case_id`.
   - Extract its **Automation Key**.
   - Use Automation Key to find the corresponding **target case**:
     - if it exists → reuse it,
     - if it does **not** exist → create it via:

       ```text
       POST /case/{target_project_code}
       ```

       The payload includes:
       - `title` – copied from the source case
       - `description` – copied from the source case (if present)
       - `custom_fields` – includes Automation Key with the same value

6. **Locate or create the target run**

   The target run (where we want to see the mirrored results) is determined using:

   - `--target-run-id` (optional) – reuse an existing run by ID, or
   - `--target-run-title` – search or create a run with that title, or
   - default: reuse **source run title** as the target run title.

   The script:

   - calls `GET /run/{target_project_code}` to search by title;
   - if no run is found with that title, issues:

     ```text
     POST /run/{target_project_code}
     ```

     with:
     - `title` – specified target run title (or source run title by default)
     - `description` – indicates that this run is a mirror of the source run
     - `cases` – list of target case IDs involved in the sync

7. **Create results in the target run**

   For each result in the source run:

   - Resolve the source `case_id` → Automation Key → target case (`case_id`).
   - For each mapped target case, issue:

     ```text
     POST /result/{target_project_code}/{target_run_id}
     ```

     with payload:

     - `status` – same as source
     - `case_id` – target case ID
     - `time` – copied from source if present
     - `comment` – source comment, prefixed with `[Mirrored from <source_project>]`

   The script **only creates new results** in the target run; it does not modify or
   delete existing results.

---

## Qase API Endpoints Used

The tool uses the following Qase API endpoints:

- **Custom Fields**
  - `GET /custom_field` – find the Automation Key field (entity: `case`)

- **Test Cases**
  - `GET /case/{project_code}` – list test cases in source and target projects
  - `POST /case/{project_code}` – create missing cases in the target project

- **Test Runs**
  - `GET /run/{project_code}` – list runs, filter by title or find latest by ID
  - `GET /run/{project_code}/{id}` – fetch a specific run by ID
  - `POST /run/{project_code}` – create a run in the target project

- **Results**
  - `GET /result/{project_code}` – fetch results for a given run (`run` query parameter)
  - `POST /result/{project_code}/{run_id}` – create results in the target run

---

## Local Setup

### Prerequisites

- **Python** 3.10+ (tested with Python 3.12)
- `pip` for installing dependencies

### Install dependencies

From the repository root:

```bash
pip install -r requirements.txt
```

`requirements.txt` contains:

```text
requests
python-dotenv
```

### Environment configuration

Create a `.env` file in the repository root (do **not** commit your real token)
based on `.env.example`:

```env
QASE_API_TOKEN=your_qase_api_token_here
QASE_BASE_URL=https://api.qase.io/v1
QASE_SYNC_LOG_FILE=sync_results_errors.log
```

- `QASE_API_TOKEN` – Qase personal API token (from your user profile).
- `QASE_BASE_URL` – API base URL (defaults to Qase cloud if not set).
- `QASE_SYNC_LOG_FILE` – optional log file name for error logs
  (defaults to `sync_results_errors.log`).

> **Logging behavior**  
> - **Console** – all informational messages (`[INFO]`, `[WARN]`).  
> - **Log file** – only `ERROR` level messages, with timestamp and function name.  
>   This is intended for debugging failures (bad token, network issues, API errors, etc.).

---

## Usage

The main entry point is `sync_results.py`.

General form:

```bash
python sync_results.py   --source-project <SOURCE_CODE>   [--source-run-id <ID> | --source-run-title "<TITLE>" | --use-latest-source-run]   --target-project <TARGET_CODE>   [--target-run-id <ID>]   [--target-run-title "<TITLE>"]   [--automation-field-title "Automation Key"]
```

- `--source-project` – project where results currently live (e.g. automation-only project).
- `--target-project` – project where you want the mirrored results.
- Exactly one of:
  - `--source-run-id` – numeric run ID in the source project
  - `--source-run-title` – run title in the source project
  - `--use-latest-source-run` – use the latest run (by highest ID) in the source project
- Target run:
  - `--target-run-id` – reuse an existing run in the target project; or
  - `--target-run-title` – run title in the target project;
  - if neither is provided, the script defaults to using the **source run title**.
- `--automation-field-title` – title of the custom field used as Automation Key
  (defaults to `"Automation Key"`).

---

## Example: Scenario 1 (Project B → Project A)

This matches the scenario described in the assignment:

- **Project B** – automation-only project (CI pipeline sends results here), e.g. `AO`.
- **Project A** – full regression suite (manual + automation), e.g. `DEMO`.

### Sync the latest run from AO into DEMO

```bash
python sync_results.py   --source-project AO   --use-latest-source-run   --target-project DEMO
```

### Sync a specific run by title from AO into DEMO

```bash
python sync_results.py   --source-project AO   --source-run-title "Regression Run October 31"   --target-project DEMO   --target-run-title "Regression Run October 31"
```

In both cases:

- The script uses the shared Automation Key to map cases between AO and DEMO.
- If a case with a given Automation Key does not exist in DEMO, it is created automatically.
- A run with the title `Regression Run October 31` is reused or created in DEMO.
- Results (status, time, comments) are mirrored from AO into DEMO.

---

## Example: DEMO → AO (Demo Workspace Setup)

In the demo workspace used during development, the script was also used in the
opposite direction, treating `DEMO` as the “master” and `AO` as an automation-only mirror:

```bash
python sync_results.py   --source-project DEMO   --use-latest-source-run   --target-project AO
```

This is useful to demonstrate that the approach is symmetric: all logic is driven
by Automation Key, not by hard-coded project codes.

---

## Integrating with CI (Run This Script After Each Test Run)

In a real-world setup, this script would not be run manually. Instead, it would be part
of the CI pipeline that already posts test results to Qase.

Typical pattern:

1. **Test runner** posts automated results to **Project B** (e.g. AO) using the official Qase reporter.  
2. The CI job knows which Qase `run_id` it used (either by configuration or from the reporter’s output).  
3. As the **final step in the pipeline**, the job invokes this script:

   ```bash
   python sync_results.py      --source-project AO      --source-run-id "$QASE_RUN_ID"      --target-project DEMO      --target-run-title "Regression Run ${RUN_DATE}"
   ```

   or, in a simpler demo environment:

   ```bash
   python sync_results.py      --source-project AO      --use-latest-source-run      --target-project DEMO
   ```

This ensures that every time the CI pipeline completes an automated run in Project B,
the corresponding results are **automatically mirrored** into Project A without any
manual copying.

> **Extension idea (not implemented here):**  
> Expose this script behind a small HTTP service and configure a Qase webhook for
> the `run.completed` event. The webhook payload contains the `run_id`, which can
> be passed directly to `sync_results.py` to trigger synchronization whenever
> a run is completed in the source project.

---

## Limitations & Possible Extensions

Current scope (for the assignment):

- Only test cases with a populated Automation Key are synchronized.
- Only status, time and comments are copied into the target run.
- Existing results in the target run are not modified or deleted.
- No dry-run mode (the script always writes to the target project).

Potential enhancements:

- Support for steps, parameters, attachments, or additional metadata.
- A `--dry-run` flag to show planned changes without calling `POST` endpoints.
- More advanced matching strategies (e.g. combination of Automation Key + title).
- Aggregated summaries (e.g. counts of synced, skipped and failed results).
- Webhook-driven automation (`run.completed`) for fully event-based syncing.

---

## License

(Choose and add a license here, e.g. MIT, if needed.)
