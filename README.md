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
