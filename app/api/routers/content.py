from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_content_service
from app.schemas.content import AboutOut, FaqItemOut
from app.services.content_service import ContentService

router = APIRouter(prefix="/content", tags=["content"])


@router.get("/about", response_model=AboutOut)
def about(service: Annotated[ContentService, Depends(get_content_service)]) -> AboutOut:
    return service.about()


@router.get("/faq", response_model=list[FaqItemOut])
def faq(service: Annotated[ContentService, Depends(get_content_service)]) -> list[FaqItemOut]:
    return service.faq()
