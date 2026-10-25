from sqlalchemy.orm import Session
from backend.database import Base, check_db_connection
from backend.models.user import Institution, User, UserRole
from backend.models.workflow import ApplicationType, WorkflowRoute, WorkflowStage
from backend.models.setting import SystemSetting


def test_database_table_metadata():
    """Verify all required domain tables are registered in SQLAlchemy metadata."""
    expected_tables = {
        "institutions",
        "users",
        "application_types",
        "workflow_routes",
        "workflow_stages",
        "stage_transitions",
        "applications",
        "application_stage_history",
        "evc_visits",
        "undertaking_documents",
        "notifications",
        "escalation_records",
        "audit_logs",
        "system_settings",
    }
    actual_tables = set(Base.metadata.tables.keys())
    assert expected_tables.issubset(actual_tables), f"Missing tables: {expected_tables - actual_tables}"


def test_database_connection_check():
    """Verify check_db_connection executes a valid test query."""
    assert check_db_connection() is True


def test_institution_persistence(db_session: Session):
    """Verify an institution can be created and persisted in the database."""
    inst = Institution(
        name="Delhi Technological University",
        code="DTU-DEL-001",
        region="Northern Region",
        address="Shahbad Daulatpur, Bawana Road, Delhi",
        contact_email="registrar@dtu.ac.in",
        contact_phone="+91-11-27871018",
        establishment_year=1941,
    )
    db_session.add(inst)
    db_session.commit()
    db_session.refresh(inst)

    assert inst.id is not None
    assert inst.created_at is not None

    # Query back
    fetched = db_session.query(Institution).filter_by(code="DTU-DEL-001").first()
    assert fetched is not None
    assert fetched.name == "Delhi Technological University"
    assert fetched.region == "Northern Region"


def test_user_persistence_with_institution_relation(db_session: Session):
    """Verify creating a user linked to an institution."""
    inst = Institution(
        name="College of Engineering Pune",
        code="COEP-MAH-002",
        region="Western Region",
        contact_email="admin@coep.ac.in",
    )
    db_session.add(inst)
    db_session.commit()
    db_session.refresh(inst)

    user = User(
        email="principal@coep.ac.in",
        hashed_password="mock_hashed_secret",
        full_name="Dr. S. K. Mahajan",
        role=UserRole.INSTITUTION,
        region="Western Region",
        institution_id=inst.id,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    assert user.id is not None
    assert user.institution_id == inst.id
    assert user.institution.name == "College of Engineering Pune"


def test_system_settings_persistence(db_session: Session):
    """Verify system setting storage for demo time offsets."""
    setting = SystemSetting(
        key="simulated_time_offset_seconds",
        value="0",
        description="Current demo time fast-forward offset in seconds",
    )
    db_session.add(setting)
    db_session.commit()
    db_session.refresh(setting)

    assert setting.id is not None
    fetched = db_session.query(SystemSetting).filter_by(key="simulated_time_offset_seconds").first()
    assert fetched is not None
    assert fetched.value == "0"
