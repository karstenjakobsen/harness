from fastapi import HTTPException, Request

from ..models import WorkspaceModel


def owner_service[Service: WorkspaceModel](
    request: Request, service: Service
) -> Service:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    bearer = value.encode("latin-1") if scheme.lower() == "bearer" else b""
    if not service.permits_owner_http(bearer):
        raise HTTPException(
            401,
            "Owner HTTP credential required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return service
