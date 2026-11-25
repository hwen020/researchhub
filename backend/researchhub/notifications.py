"""Write notification intents in source transactions and publish replay cursors in order."""
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .models import funding_requests, notification_receipts, notifications
from .observability import correlation_id, emit


def dialect_insert(connection):
    return pg_insert if connection.dialect.name == "postgresql" else sqlite_insert


def enqueue(connection, project_id, kind, subject_id, message, timestamp, trace_id=None):
    insert = dialect_insert(connection)
    connection.execute(insert(notifications).values(
        id=str(uuid4()), project_id=project_id, kind=kind, subject_id=subject_id,
        message=message, created_at=timestamp, correlation_id=correlation_id(trace_id),
    ).on_conflict_do_nothing(index_elements=[notifications.c.kind, notifications.c.subject_id]))


def publish(connection):
    if connection.dialect.name == "postgresql":
        if not connection.execute(text(
            "SELECT pg_try_advisory_xact_lock(1946983274, hashtext(current_schema()))"
        )).scalar_one():
            return 0
    pending = connection.execute(select(notifications).where(
        notifications.c.published_sequence.is_(None),
    ).order_by(notifications.c.created_at, notifications.c.id).limit(100)).mappings().all()
    if not pending:
        return 0
    last = connection.execute(select(func.coalesce(func.max(notifications.c.published_sequence), 0))).scalar_one()
    for sequence, item in enumerate(pending, last + 1):
        connection.execute(notifications.update().where(notifications.c.id == item["id"]).values(
            published_sequence=sequence,
        ))
        emit("notification_publication_attempt", notification_id=item["id"], correlation_id=item["correlation_id"],
             kind=item["kind"])
    return len(pending)


def visible_to(user_id, can_review):
    if can_review:
        return True
    requester = select(funding_requests.c.id).where(funding_requests.c.requester == user_id)
    return or_(notifications.c.kind.not_in(("APPROVAL_REQUESTED", "APPROVAL_DECIDED")),
               notifications.c.subject_id.in_(requester))


def feed(connection, project_id, user_id, after, limit, can_review):
    query = select(
        notifications.c.id, notifications.c.kind, notifications.c.subject_id, notifications.c.message,
        notifications.c.created_at, notifications.c.published_sequence.label("sequence"),
        notification_receipts.c.read_at.is_not(None).label("read"),
    ).select_from(notifications.outerjoin(notification_receipts, and_(
        notification_receipts.c.notification_id == notifications.c.id,
        notification_receipts.c.user_id == user_id,
    ))).where(notifications.c.project_id == project_id, notifications.c.published_sequence > after,
              visible_to(user_id, can_review))
    return [dict(row) for row in connection.execute(query.order_by(notifications.c.published_sequence)
                                                    .limit(limit)).mappings()]


def mark(connection, project_id, user_id, notification_id, read, timestamp, can_review):
    exists = connection.execute(select(notifications.c.id).where(
        notifications.c.project_id == project_id, notifications.c.id == notification_id,
        notifications.c.published_sequence.is_not(None), visible_to(user_id, can_review),
    )).scalar_one_or_none()
    if exists is None:
        raise LookupError("Notification not found")
    if read:
        insert = dialect_insert(connection)
        connection.execute(insert(notification_receipts).values(
            notification_id=notification_id, user_id=user_id, read_at=timestamp,
        ).on_conflict_do_nothing())
    else:
        connection.execute(notification_receipts.delete().where(
            notification_receipts.c.notification_id == notification_id,
            notification_receipts.c.user_id == user_id,
        ))
    return {"read": read}
