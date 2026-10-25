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
    _: User = Depends(require_roles([UserRole.ADMIN])),
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
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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

    if payload.email is not None:
        normalized_email = payload.email.lower().strip()
        if normalized_email != target_user.email:
            existing = db.query(User).filter(User.email == normalized_email).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Email '{payload.email}' is already in use",
                )
            target_user.email = normalized_email

    if payload.full_name is not None:
        target_user.full_name = payload.full_name.strip()

    if payload.password is not None:
        target_user.hashed_password = hash_password(payload.password)

    if is_admin:
        if payload.role is not None:
            target_user.role = payload.role
        if payload.region is not None:
            target_user.region = payload.region
        if payload.institution_id is not None:
            target_user.institution_id = payload.institution_id
        if payload.is_active is not None:
            target_user.is_active = payload.is_active

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
    _: User = Depends(require_roles([UserRole.ADMIN])),
) -> MessageResponse:
    """Admin-only endpoint to soft-delete / deactivate a user."""
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    target_user.is_active = False
    db.commit()

    return MessageResponse(message=f"User '{target_user.email}' has been deactivated successfully.")
