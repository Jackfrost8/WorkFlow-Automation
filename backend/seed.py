"""
Demo user and institution seeding script for AICTE Workflow Automation Platform.
Idempotent: Can be run repeatedly without duplicating records or throwing constraint errors.
"""
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from backend.core.security import hash_password
from backend.database import SessionLocal, init_db
from backend.models.user import Institution, User, UserRole

DEFAULT_DEMO_PASSWORD = "Demo@AICTE2026!"

DEMO_INSTITUTIONS = [
    {
        "name": "Delhi Technological University",
        "code": "DTU-DEL-001",
        "region": "Northern Region",
        "address": "Shahbad Daulatpur, Bawana Road, Delhi - 110042",
        "contact_email": "registrar@dtu.ac.in",
        "contact_phone": "+91-11-27871018",
        "establishment_year": 1941,
    },
    {
        "name": "College of Engineering Pune",
        "code": "COEP-MAH-002",
        "region": "Western Region",
        "address": "Wellesley Road, Shivajinagar, Pune, Maharashtra - 411005",
        "contact_email": "admin@coep.ac.in",
        "contact_phone": "+91-20-25507000",
        "establishment_year": 1854,
    },
]

DEMO_USERS = [
    {
        "email": "admin@aicte.gov.in",
        "full_name": "AICTE Platform Administrator",
        "role": UserRole.ADMIN,
        "region": None,
        "institution_code": None,
    },
    {
        "email": "bureau@aicte.gov.in",
        "full_name": "Bureau Officer - Approvals",
        "role": UserRole.BUREAU_OFFICER,
        "region": "HQ - New Delhi",
        "institution_code": None,
    },
    {
        "email": "ro.north@aicte.gov.in",
        "full_name": "Regional Officer (North)",
        "role": UserRole.REGIONAL_OFFICER,
        "region": "Northern Region",
        "institution_code": None,
    },
    {
        "email": "ro.west@aicte.gov.in",
        "full_name": "Regional Officer (West)",
        "role": UserRole.REGIONAL_OFFICER,
        "region": "Western Region",
        "institution_code": None,
    },
    {
        "email": "inst.dtu@aicte.gov.in",
        "full_name": "Principal / Dean - DTU",
        "role": UserRole.INSTITUTION,
        "region": "Northern Region",
        "institution_code": "DTU-DEL-001",
    },
    {
        "email": "inst.coep@aicte.gov.in",
        "full_name": "Principal / Dean - COEP",
        "role": UserRole.INSTITUTION,
        "region": "Western Region",
        "institution_code": "COEP-MAH-002",
    },
]


def seed_demo_data(
    session: Optional[Session] = None,
    verbose: bool = True,
) -> Dict[str, int]:
    """Execute idempotent seed operation."""
    close_session = False
    if session is None:
        init_db()
        session = SessionLocal()
        close_session = True

    inst_count = 0
    user_count = 0

    try:
        # 1. Seed Institutions
        inst_map: Dict[str, Institution] = {}
        for inst_data in DEMO_INSTITUTIONS:
            existing = session.query(Institution).filter(Institution.code == inst_data["code"]).first()
            if existing:
                for k, v in inst_data.items():
                    setattr(existing, k, v)
                inst_map[inst_data["code"]] = existing
            else:
                new_inst = Institution(**inst_data)
                session.add(new_inst)
                session.flush()
                inst_map[inst_data["code"]] = new_inst
                inst_count += 1

        session.commit()

        # 2. Seed Users
        hashed_pwd = hash_password(DEFAULT_DEMO_PASSWORD)
        for user_data in DEMO_USERS:
            email = user_data["email"].lower().strip()
            inst_code = user_data["institution_code"]
            inst_id = inst_map[inst_code].id if inst_code and inst_code in inst_map else None

            existing_user = session.query(User).filter(User.email == email).first()
            if existing_user:
                existing_user.full_name = user_data["full_name"]
                existing_user.role = user_data["role"]
                existing_user.region = user_data["region"]
                existing_user.institution_id = inst_id
                existing_user.hashed_password = hashed_pwd
                existing_user.is_active = True
            else:
                new_user = User(
                    email=email,
                    hashed_password=hashed_pwd,
                    full_name=user_data["full_name"],
                    role=user_data["role"],
                    region=user_data["region"],
                    institution_id=inst_id,
                    is_active=True,
                )
                session.add(new_user)
                user_count += 1

        session.commit()

        if verbose:
            print("\n=======================================================")
            print("  AICTE Workflow Platform - Demo Data Seed Summary")
            print("=======================================================")
            print(f"Institutions Seeded/Updated : {len(DEMO_INSTITUTIONS)}")
            print(f"Users Seeded/Updated        : {len(DEMO_USERS)}")
            print(f"Standard Demo Password      : {DEFAULT_DEMO_PASSWORD}")
            print("-------------------------------------------------------")
            print(f"{'Role':<18} {'Email':<25} {'Region / Link'}")
            print("-------------------------------------------------------")
            for u in DEMO_USERS:
                link = u["region"] or u["institution_code"] or "HQ"
                print(f"{u['role'].value:<18} {u['email']:<25} {link}")
            print("=======================================================\n")

        return {"institutions": len(DEMO_INSTITUTIONS), "users": len(DEMO_USERS)}

    finally:
        if close_session:
            session.close()


if __name__ == "__main__":
    seed_demo_data()
