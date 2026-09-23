import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Service
from app.schemas import ServiceInput


class ServiceConflict(Exception):
    pass


class ServiceNotFound(Exception):
    pass


def list_services(db: Session, workspace_id: uuid.UUID, limit: int, offset: int) -> list[Service]:
    return list(
        db.scalars(
            select(Service)
            .where(Service.workspace_id == workspace_id)
            .order_by(Service.created_at.desc(), Service.id)
            .limit(limit)
            .offset(offset)
        )
    )


def create_service(db: Session, workspace_id: uuid.UUID, data: ServiceInput) -> Service:
    service = Service(workspace_id=workspace_id, **data.model_dump())
    db.add(service)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise ServiceConflict("A service with that name already exists") from error
    db.refresh(service)
    return service


def get_service(db: Session, workspace_id: uuid.UUID, service_id: uuid.UUID) -> Service:
    service = db.scalar(
        select(Service).where(Service.id == service_id, Service.workspace_id == workspace_id)
    )
    if service is None:
        raise ServiceNotFound("Service not found")
    return service
