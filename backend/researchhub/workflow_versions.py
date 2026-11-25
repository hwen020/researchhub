"""Immutable templates and persistent workflow triggers."""
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select

from .models import workflow_definitions, workflow_schedules, workflow_versions
from .plugins import validate_parameters
from .queue import now_ms
from .workflows import definition_checksum, start, validate


def get_version(connection, project_id, version_id):
    version = connection.execute(select(workflow_versions).join(workflow_definitions).where(
        workflow_definitions.c.project_id == project_id, workflow_versions.c.id == version_id,
        workflow_definitions.c.system_kind.is_(None),
    )).mappings().one_or_none()
    if version is None:
        raise LookupError("Workflow version not found")
    return version


def substitute(value, bindings):
    if isinstance(value, dict):
        if set(value) == {"$parameter"}:
            name = value["$parameter"]
            if not isinstance(name, str) or name not in bindings:
                raise ValueError("Unknown workflow parameter")
            return bindings[name]
        return {key: substitute(item, bindings) for key, item in value.items()}
    if isinstance(value, list):
        return [substitute(item, bindings) for item in value]
    return value


def bind(template, defaults, overrides):
    if overrides.keys() - defaults.keys():
        raise ValueError("Unknown workflow parameter")
    bindings = dict(defaults, **overrides)
    definition = {
        name: dict(node, parameters=validate_parameters(
            node["plugin"], substitute(node["parameters"], bindings),
        )) for name, node in template.items()
    }
    validate(definition)
    definition_checksum(bindings)
    return definition, bindings


def publish(connection, project_id, definition, defaults, *, name=None, definition_id=None):
    bind(definition, defaults, {})
    digest = definition_checksum({"definition": definition, "defaults": defaults})
    if definition_id is None:
        definition_id = str(uuid4())
        connection.execute(workflow_definitions.insert().values(
            id=definition_id, project_id=project_id, name=name,
        ))
    else:
        existing = connection.execute(select(workflow_definitions.c.id).where(
            workflow_definitions.c.project_id == project_id, workflow_definitions.c.id == definition_id,
            workflow_definitions.c.system_kind.is_(None),
        ).with_for_update()).scalar_one_or_none()
        if existing is None:
            raise LookupError("Workflow definition not found")
    number = connection.execute(select(func.max(workflow_versions.c.version)).where(
        workflow_versions.c.definition_id == definition_id,
    )).scalar_one()
    version = dict(id=str(uuid4()), definition_id=definition_id, version=(number or 0) + 1,
                   definition=definition, defaults=defaults, checksum=digest)
    connection.execute(workflow_versions.insert().values(**version))
    return version


def start_version(connection, project_id, version_id, overrides):
    version = get_version(connection, project_id, version_id)
    definition, parameters = bind(version["definition"], version["defaults"], overrides)
    return start(connection, project_id, definition, version_id=version_id, parameters=parameters)


def create_schedule(connection, project_id, version_id, overrides, start_at, zone, interval_seconds):
    version = get_version(connection, project_id, version_id)
    _, parameters = bind(version["definition"], version["defaults"], overrides)
    try:
        local = datetime.fromisoformat(start_at)
        timezone = ZoneInfo(zone)
        if local.utcoffset() is None or local.astimezone(timezone).utcoffset() != local.utcoffset():
            raise ValueError("Start time must include the applicable offset for the selected timezone")
        timestamp = int(local.timestamp() * 1000)
    except (ValueError, ZoneInfoNotFoundError, OverflowError) as exc:
        raise ValueError("Invalid start time, UTC offset or timezone") from exc
    schedule = dict(id=str(uuid4()), project_id=project_id, version_id=version_id,
                    parameters=parameters, zone=zone, next_at=timestamp,
                    interval_ms=interval_seconds * 1000 if interval_seconds is not None else None)
    connection.execute(workflow_schedules.insert().values(**schedule))
    return schedule


def trigger_due(connection):
    now = now_ms(connection)
    due = connection.execute(select(workflow_schedules).where(
        workflow_schedules.c.next_at <= now,
    ).order_by(workflow_schedules.c.next_at, workflow_schedules.c.id)
        .limit(20).with_for_update(skip_locked=True)).mappings().all()
    for schedule in due:
        scheduled_at = schedule["next_at"]
        next_at = None
        if schedule["interval_ms"] is not None:
            interval = schedule["interval_ms"]
            scheduled_at += (now - scheduled_at) // interval * interval
            next_at = scheduled_at + interval
        run_id = start_version(connection, schedule["project_id"], schedule["version_id"], schedule["parameters"])
        connection.execute(workflow_schedules.update().where(workflow_schedules.c.id == schedule["id"]).values(
            next_at=next_at, last_run_id=run_id, last_scheduled_at=scheduled_at,
        ))
    return len(due)
