from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user, require_roles
from backend.core.security import create_access_token, verify_password
from backend.database import get_db
from backend.models.user import User, UserRole
from backend.schemas.auth import LoginRequest, TokenResponse
from backend.schemas.user import UserResponse
from backend.services.audit_service import log_audit_event

router = APIRouter(prefix="", tags=["Authentication"])


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate user and obtain JWT token",
)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """
    Authenticate user via email and password.
    Returns signed JWT bearer token and user profile upon verification.
    """
    user = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        log_audit_event(
            db=db,
            action="LOGIN_FAILED",
            resource_type="AUTH",
            resource_id=str(user.id) if user else None,
            user_id=user.id if user else None,
            details={"email": payload.email.lower().strip(), "reason": "Invalid credentials"},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        log_audit_event(
            db=db,
            action="LOGIN_FAILED",
            resource_type="AUTH",
            resource_id=str(user.id),
            user_id=user.id,
            details={"email": user.email, "reason": "Account is inactive"},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is inactive. Contact the system administrator.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    log_audit_event(
        db=db,
        action="LOGIN_SUCCESS",
        resource_type="AUTH",
        resource_id=str(user.id),
        user_id=user.id,
        details={"email": user.email, "role": user.role.value},
    )
    db.commit()

    token = create_access_token(
        data={
            "sub": str(user.id),
            "email": user.email,
            "role": user.role.value,
        }
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve authenticated user profile",
)
def get_current_user_profile(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """Return the profile and permissions of the currently authenticated user."""
    return UserResponse.model_validate(current_user)


@router.get(
    "/officer-check",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Officer-only diagnostic route",
)
def officer_diagnostic_check(
    current_user: User = Depends(require_roles([UserRole.REGIONAL_OFFICER, UserRole.BUREAU_OFFICER])),
) -> UserResponse:
    """Restricted route accessible only to Regional and Bureau Officers."""
    return UserResponse.model_validate(current_user)
