"""Gap persistence: store one gap and assign it to a cluster inside the caller's transaction.

The caller commits. SQLite runs every transaction as BEGIN IMMEDIATE (see db.py), so the
lookup-or-create of the cluster and the increment cannot interleave with another writer; the
increment itself is still a single atomic `count = count + 1` UPDATE so it also holds on
databases without that guarantee. A unique-key race there is retried once.
"""
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..orm import Gap, GapCluster
from ..timeutil import iso_utc
from .cluster import ClusterStrategy, redact_phone_numbers

MAX_EXAMPLES = 5


def cluster_to_dict(cluster: GapCluster) -> dict:
    """GapCluster model shape (contracts/python/resolvix_contracts/models.py)."""
    return {
        "cluster_id": cluster.cluster_id,
        "label": cluster.label,
        "department": cluster.department,
        "count": cluster.count,
        "examples": list(cluster.examples or []),
        "last_seen": iso_utc(cluster.last_seen),
        "status": cluster.status,
    }


def _next_cluster_id(db: Session) -> str:
    n = (db.query(func.count(GapCluster.cluster_id)).scalar() or 0) + 1
    while db.get(GapCluster, f"gc-{n}") is not None:
        n += 1
    return f"gc-{n}"


def merge_examples(existing: list[str] | None, question: str) -> list[str]:
    """Last MAX_EXAMPLES distinct questions, newest last. A repeated text moves to the end."""
    examples = [e for e in (existing or []) if e != question]
    examples.append(question)
    return examples[-MAX_EXAMPLES:]


def _assign(db: Session, key: str, label: str, department: str | None, question: str, now: datetime) -> GapCluster:
    cluster = db.query(GapCluster).filter(GapCluster.cluster_key == key).first()
    if cluster is None:
        cluster = GapCluster(
            cluster_id=_next_cluster_id(db),
            cluster_key=key,
            label=label,
            department=department,
            count=1,
            examples=[question],
            last_seen=now,
            status="new",
        )
        db.add(cluster)
        db.flush()
        return cluster

    # Atomic increment; status is never touched (ignored/answered clusters are not reopened).
    db.query(GapCluster).filter(GapCluster.cluster_id == cluster.cluster_id).update(
        {GapCluster.count: GapCluster.count + 1, GapCluster.last_seen: now},
        synchronize_session=False,
    )
    db.refresh(cluster)
    cluster.examples = merge_examples(cluster.examples, question)
    db.flush()
    return cluster


def record_gap(
    db: Session,
    strategy: ClusterStrategy,
    *,
    question: str,
    lang: str,
    department_guess: str | None,
    call_id: str | None,
    ticket_id: str | None,
    now: datetime,
) -> tuple[Gap, GapCluster]:
    """Insert the gap and update/create its cluster. Flushes only; the caller commits."""
    text = redact_phone_numbers(question).strip()  # phone numbers never reach labels, examples or events
    department = (department_guess or "").strip() or None
    key, label = strategy.assign(text, department)

    for attempt in (1, 2):
        try:
            cluster = _assign(db, key, label, department, text, now)
            gap = Gap(
                question=text,
                lang=lang,
                department_guess=department_guess,
                call_id=call_id,
                ticket_id=ticket_id,
                cluster_id=cluster.cluster_id,
                created_at=now,
            )
            db.add(gap)
            db.flush()
            return gap, cluster
        except IntegrityError:
            db.rollback()  # lost a unique-key race on cluster_key; the winner's row now exists
            if attempt == 2:
                raise
    raise AssertionError("unreachable")  # pragma: no cover
