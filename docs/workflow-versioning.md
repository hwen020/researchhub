# Workflow versioning and schedules

Create a template under `/projects/{project_id}/workflow-templates` and append versions under its `/versions` endpoint. Each version has a checksum over its unbound template and defaults. In node parameters, `{"$parameter":"name"}` inserts a declared binding. The resolved plugin inputs are validated. A run stores the concrete definition and its own digest.

Under `/workflow-versions/{version_id}`, submit a run or schedule. Start times are ISO 8601 with offsets matching an IANA zone. Recurring schedules use fixed elapsed seconds. A delayed scheduler coalesces missed occurrences into the latest due occurrence. The trigger and schedule advance commit together. Dataset-backed nodes snapshot validated inputs from the chosen dataset version.

Migration 0008 backfills checksums on existing runs. Downgrade removes version and schedule metadata. Preserve a PostgreSQL backup before production changes and use it to recover that metadata when needed.
