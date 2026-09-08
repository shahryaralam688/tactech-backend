from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import Principal, get_principal, get_support_service
from app.schemas.support import SupportConversationOut, SupportMessageCreate, SupportMessageOut
from app.services.support_service import SupportService

router = APIRouter(prefix="/support", tags=["support"])


@router.get("/conversations", response_model=SupportConversationOut)
def get_conversation(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[SupportService, Depends(get_support_service)],
) -> SupportConversationOut:
    return service.get_or_create_open(principal.user_id)


@router.post("/conversations", response_model=SupportConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[SupportService, Depends(get_support_service)],
) -> SupportConversationOut:
    return service.create_conversation(principal.user_id)


@router.get("/conversations/{conversation_id}/messages", response_model=list[SupportMessageOut])
def list_messages(
    conversation_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[SupportService, Depends(get_support_service)],
    after: str | None = Query(default=None),
) -> list[SupportMessageOut]:
    return service.list_messages(principal.user_id, conversation_id, after, request)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=SupportMessageOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_message(
    conversation_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[SupportService, Depends(get_support_service)],
) -> SupportMessageOut:
    content_type = request.headers.get("content-type", "")
    text = None
    upload = None
    if "multipart/form-data" in content_type:
        form = await request.form()
        raw = form.get("text")
        if raw is not None:
            text = str(raw)
        maybe_file = form.get("file")
        if maybe_file is not None and hasattr(maybe_file, "filename"):
            upload = maybe_file
    else:
        try:
            data = await request.json()
        except Exception:
            data = {}
        if data:
            text = SupportMessageCreate.model_validate(data).text
    return await service.add_message(principal.user_id, conversation_id, text, upload, request)
