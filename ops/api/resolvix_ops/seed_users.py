"""Seed users at startup."""
from pathlib import Path
from typing import List

import yaml
from sqlalchemy.orm import Session

from .auth import hash_password
from .config import Settings
from .orm import User


def seed_users_if_needed(db: Session, settings: Settings, departments_keys: set[str]):
    """Seed users from seed_users.yaml if the users table is empty."""
    # Check if users exist
    existing_count = db.query(User).count()
    if existing_count > 0:
        return  # Already seeded
    
    # Load seed file
    seed_file = settings.resolve_path(settings.seed_users_file)
    if not seed_file.exists():
        print(f"Warning: seed_users.yaml not found at {seed_file}")
        return
    
    with open(seed_file, "r", encoding="utf-8") as f:
        seed_data = yaml.safe_load(f)
    
    users_data = seed_data.get("users", [])
    password_hash = hash_password(settings.seed_password)
    
    for user_data in users_data:
        email = user_data["email"]
        role = user_data["role"]
        department = user_data.get("department")
        
        # Validate staff department exists
        if role == "staff" and department:
            if department not in departments_keys:
                raise ValueError(
                    f"Seed user {email} has department '{department}' which is not in departments.yaml. "
                    f"Valid departments: {sorted(departments_keys)}"
                )
        
        user = User(
            email=email,
            password_hash=password_hash,
            role=role,
            department=department
        )
        db.add(user)
    
    db.commit()
    print(f"Seeded {len(users_data)} users")
