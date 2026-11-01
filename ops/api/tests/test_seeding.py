"""Test user seeding."""
import shutil
from pathlib import Path

import yaml
from resolvix_ops.app import create_app
from resolvix_ops.config import Settings
from resolvix_ops.orm import User
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_users_seeded_on_startup(tmp_path):
    """Users should be seeded from seed_users.yaml on startup."""
    # Create config files
    contracts_base = Path(__file__).parent.parent.parent.parent / "contracts" / "config"
    departments_file = tmp_path / "departments.yaml"
    urgency_rules_file = tmp_path / "urgency_rules.yaml"
    sms_templates_file = tmp_path / "sms_templates.yaml"
    
    shutil.copy(contracts_base / "departments.yaml", departments_file)
    shutil.copy(contracts_base / "urgency_rules.yaml", urgency_rules_file)
    shutil.copy(contracts_base / "sms_templates.yaml", sms_templates_file)
    
    # Create seed users file in tmp
    seed_file = tmp_path / "seed_users.yaml"
    seed_content = """users:
  - email: admin@demo
    role: admin
    department: null
  - email: exam@demo
    role: staff
    department: exam_cell
  - email: accounts@demo
    role: staff
    department: accounts
  - email: hostel@demo
    role: staff
    department: hostel
"""
    seed_file.write_text(seed_content, encoding="utf-8")
    
    # Create DB file
    db_file = tmp_path / "test.db"
    temp_db = f"sqlite:///{db_file}"
    
    # Create settings with temp seed file
    settings = Settings(
        database_url=temp_db,
        service_key="test-key",
        session_secret="test-secret-needs-32-chars-minimum",
        seed_password="TestPass123!",
        departments_file=str(departments_file),
        urgency_rules_file=str(urgency_rules_file),
        sms_templates_file=str(sms_templates_file),
        seed_users_file=str(seed_file),
        seed_users_on_startup=True
    )
    
    # Create app (should seed users)
    app = create_app(settings)
    
    # Verify users exist
    engine = create_engine(temp_db)
    Session = sessionmaker(bind=engine)
    db = Session()
    
    users = db.query(User).all()
    assert len(users) == 4
    
    emails = {u.email for u in users}
    assert emails == {"admin@demo", "exam@demo", "accounts@demo", "hostel@demo"}
    
    admin = db.query(User).filter(User.email == "admin@demo").first()
    assert admin.role == "admin"
    assert admin.department is None
    
    exam_staff = db.query(User).filter(User.email == "exam@demo").first()
    assert exam_staff.role == "staff"
    assert exam_staff.department == "exam_cell"
    
    db.close()
    engine.dispose()
    app.state.engine.dispose()


def test_seeding_idempotent(tmp_path):
    """Running seed twice should not create duplicates."""
    contracts_base = Path(__file__).parent.parent.parent.parent / "contracts" / "config"
    departments_file = tmp_path / "departments.yaml"
    urgency_rules_file = tmp_path / "urgency_rules.yaml"
    sms_templates_file = tmp_path / "sms_templates.yaml"
    
    shutil.copy(contracts_base / "departments.yaml", departments_file)
    shutil.copy(contracts_base / "urgency_rules.yaml", urgency_rules_file)
    shutil.copy(contracts_base / "sms_templates.yaml", sms_templates_file)
    
    # Create seed file in tmp
    seed_file = tmp_path / "seed_users.yaml"
    seed_content = """users:
  - email: admin@demo
    role: admin
    department: null
"""
    seed_file.write_text(seed_content, encoding="utf-8")
    
    db_file = tmp_path / "test2.db"
    temp_db = f"sqlite:///{db_file}"
    
    settings = Settings(
        database_url=temp_db,
        service_key="test-key",
        session_secret="test-secret-needs-32-chars-minimum",
        seed_password="TestPass123!",
        departments_file=str(departments_file),
        urgency_rules_file=str(urgency_rules_file),
        sms_templates_file=str(sms_templates_file),
        seed_users_file=str(seed_file),
        seed_users_on_startup=True
    )
    
    # Create app twice
    app1 = create_app(settings)
    app1.state.engine.dispose()
    
    app2 = create_app(settings)
    
    # Verify only one admin user
    engine = create_engine(temp_db)
    Session = sessionmaker(bind=engine)
    db = Session()
    
    users = db.query(User).all()
    assert len(users) == 1  # Still only 1 user
    
    db.close()
    engine.dispose()
    app2.state.engine.dispose()




def test_seed_fails_with_invalid_department(tmp_path):
    """Seeding should fail fast if staff department not in departments.yaml."""
    contracts_base = Path(__file__).parent.parent.parent.parent / "contracts" / "config"
    departments_file = tmp_path / "departments.yaml"
    urgency_rules_file = tmp_path / "urgency_rules.yaml"
    sms_templates_file = tmp_path / "sms_templates.yaml"
    
    shutil.copy(contracts_base / "departments.yaml", departments_file)
    shutil.copy(contracts_base / "urgency_rules.yaml", urgency_rules_file)
    shutil.copy(contracts_base / "sms_templates.yaml", sms_templates_file)
    
    # Create seed file with invalid department in tmp
    seed_file = tmp_path / "seed_users_invalid.yaml"
    seed_content = """users:
  - email: invalid@demo
    role: staff
    department: invalid_dept
"""
    seed_file.write_text(seed_content, encoding="utf-8")
    
    db_file = tmp_path / "test3.db"
    temp_db = f"sqlite:///{db_file}"
    
    settings = Settings(
        database_url=temp_db,
        service_key="test-key",
        session_secret="test-secret-needs-32-chars-minimum",
        seed_password="TestPass123!",
        departments_file=str(departments_file),
        urgency_rules_file=str(urgency_rules_file),
        sms_templates_file=str(sms_templates_file),
        seed_users_file=str(seed_file),
        seed_users_on_startup=True
    )
    
    # Should raise ValueError
    try:
        app = create_app(settings)
        app.state.engine.dispose()
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "invalid_dept" in str(e)
        assert "not in departments.yaml" in str(e)


