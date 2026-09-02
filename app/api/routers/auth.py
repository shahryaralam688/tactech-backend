from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import enforce_auth_rate_limit, get_auth_service, get_principal
from app.api.deps import Principal
from app.schemas.requests import LoginRequest, LogoutRequest, RefreshRequest, SignupRequest
from app.schemas.responses import AuthResponse, MeResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(
    payload: SignupRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
    _: Annotated[None, Depends(enforce_auth_rate_limit)],
) -> AuthResponse:
    return service.signup(
        name=payload.name,
        email=str(payload.email),
        password=payload.password,
        role=payload.role,
        invite_code=payload.invite_code,
    )


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
    _: Annotated[None, Depends(enforce_auth_rate_limit)],
) -> AuthResponse:
    return service.login(str(payload.email), payload.password)


@router.post("/refresh", response_model=AuthResponse)
def refresh(
    payload: RefreshRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthResponse:
    return service.refresh(payload.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    payload: LogoutRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    service.logout(payload.refresh_token)


@router.get("/me", response_model=MeResponse)
def me(
    principal: Annotated[Principal, Depends(get_principal)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> MeResponse:
    return service.me(principal.user_id)
