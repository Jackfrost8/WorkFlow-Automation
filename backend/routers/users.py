from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user, require_roles
from backend.core.security import hash_password
from backend.database import get_db
from backend.models.user import Institution, User, UserRole
from backend.schemas.auth import UserUpdate
from backend.schemas.common import MessageResponse
from backend.schemas.user import UserCreate, UserResponse
from backend.services.audit_service import log_audit_event

router = APIRouter(prefix="/users", tags=["User Management"])


@router.get(
    "",
    response_model=List[UserResponse],
    summary="List platform users (Admin only)",
)
def list_users(
    role: Optional[UserRole] = Query(default=None, description="Filter by user role"),
    region: Optional[str] = Query(default=None, description="Filter by assigned region"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles([UserRole.ADMIN])),
) -> List[UserResponse]:
    """Admin-only endpoint to list registered platform users."""
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)
    if region:
        query = query.filter(User.region == region)

    users = query.offset(skip).limit(limit).all()
    return [UserResponse.model_validate(u) for u in users]


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user (Admin only)",
)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.ADMIN])),
) -> UserResponse:
    """Admin-only endpoint to provision a new user account."""
    existing = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User with email '{payload.email}' already exists",
        )

    # Validate institution link for INSTITUTION role
    if payload.role == UserRole.INSTITUTION:
        if not payload.institution_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="institution_id is mandatory for users with INSTITUTION role",
            )
        institution = db.query(Institution).filter(Institution.id == payload.institution_id).first()
        if not institution:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Institution with id {payload.institution_id} not found",
            )

    new_user = User(
        email=payload.email.lower().strip(),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        role=payload.role,
        region=payload.region,
        institution_id=payload.institution_id if payload.role == UserRole.INSTITUTION else None,
        is_active=True,
    )
    db.add(new_user)
    db.flush()

    log_audit_event(
        db=db,
        action="USER_CREATED",
        resource_type="USER",
        resource_id=str(new_user.id),
        user_id=current_user.id,
        details={
            "email": new_user.email,
            "role": new_user.role.value,
            "region": new_user.region if new_user.region else None,
            "institution_id": new_user.institution_id,
        },
    )
    db.commit()
    db.refresh(new_user)

    return UserResponse.model_validate(new_user)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get user details by ID",
)
def get_user_by_id(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """Retrieve details for a specific user (Admin or self)."""
    if current_user.role != UserRole.ADMIN and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to view another user's profile",
        )

    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return UserResponse.model_validate(target_user)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="Update user details",
)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """
    Update user profile.
    - Admins can update roles, status, and assignments.
    - Non-admins can only update their own profile and CANNOT change their role or active status.
    """
    is_admin = current_user.role == UserRole.ADMIN

    if not is_admin and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to edit another user's profile",
        )

    # Security check: Non-admins cannot alter role or active status
    if not is_admin:
        if payload.role is not None and payload.role != current_user.role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Non-administrators are not permitted to change user roles",
            )
        if payload.is_active is not None and payload.is_active != current_user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Non-administrators are not permitted to deactivate or activate accounts",
            )

    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    changes = {}
    if payload.email is not None:
        normalized_email = payload.email.lower().strip()
        if normalized_email != target_user.email:
            existing = db.query(User).filter(User.email == normalized_email).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Email '{payload.email}' is already in use",
                )
            changes["email"] = {"old": target_user.email, "new": normalized_email}
            target_user.email = normalized_email

    if payload.full_name is not None and payload.full_name.strip() != target_user.full_name:
        changes["full_name"] = {"old": target_user.full_name, "new": payload.full_name.strip()}
        target_user.full_name = payload.full_name.strip()

    if payload.password is not None:
        target_user.hashed_password = hash_password(payload.password)
        changes["password"] = "[UPDATED]"

    role_changed = False
    if is_admin:
        if payload.role is not None and payload.role != target_user.role:
            changes["role"] = {"old": target_user.role.value, "new": payload.role.value}
            target_user.role = payload.role
            role_changed = True
        if payload.region is not None and payload.region != target_user.region:
            changes["region"] = {
                "old": target_user.region.value if target_user.region else None,
                "new": payload.region.value if payload.region else None,
            }
            target_user.region = payload.region
        if payload.institution_id is not None and payload.institution_id != target_user.institution_id:
            changes["institution_id"] = {"old": target_user.institution_id, "new": payload.institution_id}
            target_user.institution_id = payload.institution_id
        if payload.is_active is not None and payload.is_active != target_user.is_active:
            changes["is_active"] = {"old": target_user.is_active, "new": payload.is_active}
            target_user.is_active = payload.is_active

    if changes:
        action_name = "USER_ROLE_CHANGED" if role_changed else "USER_UPDATED"
        log_audit_event(
            db=db,
            action=action_name,
            resource_type="USER",
            resource_id=str(target_user.id),
            user_id=current_user.id,
            details={"changes": changes},
        )

    db.commit()
    db.refresh(target_user)

    return UserResponse.model_validate(target_user)


@router.delete(
    "/{user_id}",
    response_model=MessageResponse,
    summary="Deactivate user account (Admin only)",
)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.ADMIN])),
) -> MessageResponse:
    """Admin-only endpoint to soft-delete / deactivate a user."""
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    target_user.is_active = False
    log_audit_event(
        db=db,
        action="USER_DEACTIVATED",
        resource_type="USER",
        resource_id=str(target_user.id),
        user_id=current_user.id,
        details={"email": target_user.email},
    )
    db.commit()

    return MessageResponse(message=f"User '{target_user.email}' has been deactivated successfully.")
