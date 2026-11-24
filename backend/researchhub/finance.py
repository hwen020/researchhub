from uuid import uuid4

from sqlalchemy import select

from .models import budgets, funding_requests
from .queue import now_ms


def request_funds(connection, project_id, user_id, key, amount, purpose):
    connection.execute(select(budgets).where(budgets.c.project_id == project_id).with_for_update()).one()
    existing = connection.execute(select(funding_requests).where(
        funding_requests.c.project_id == project_id, funding_requests.c.key == key,
    )).mappings().one_or_none()
    if existing is not None:
        if (existing["amount"], existing["purpose"], existing["requester"]) != (amount, purpose, user_id):
            raise ValueError("Funding request key already used")
        return existing["id"]
    request_id = str(uuid4())
    connection.execute(funding_requests.insert().values(
        id=request_id, project_id=project_id, requester=user_id, key=key,
        amount=amount, purpose=purpose, state="PENDING",
    ))
    return request_id


def decide(connection, project_id, request_id, reviewer, approve):
    budget = connection.execute(select(budgets).where(
        budgets.c.project_id == project_id,
    ).with_for_update()).mappings().one()
    request = connection.execute(select(funding_requests).where(
        funding_requests.c.project_id == project_id, funding_requests.c.id == request_id,
    ).with_for_update()).mappings().one_or_none()
    if request is None:
        raise LookupError("Funding request not found")
    if request["requester"] == reviewer:
        raise PermissionError("A requester cannot review their own funding request")
    state = "APPROVED" if approve else "REJECTED"
    if request["state"] == state:
        return state
    if request["state"] != "PENDING":
        raise ValueError("Funding request already decided")
    if approve:
        spent = budget["spent"] + request["amount"]
        if spent > budget["limit"]:
            raise ValueError("Insufficient project budget")
        connection.execute(budgets.update().where(budgets.c.project_id == project_id).values(spent=spent))
    connection.execute(funding_requests.update().where(funding_requests.c.id == request_id).values(
        state=state, reviewer=reviewer, reviewed_at=now_ms(connection),
    ))
    return state

