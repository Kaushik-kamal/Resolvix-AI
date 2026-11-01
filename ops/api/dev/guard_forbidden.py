"""Guard forbidden paths - ensure no modifications to contracts, prompts, etc.

Run with: python -X utf8 dev/guard_forbidden.py [--init]
"""
import hashlib
import json
import sys
from pathlib import Path


FORBIDDEN_PATHS = [
    "contracts/python",
    "contracts/openapi",
    "contracts/fixtures",
    "contracts/tests",
    "contracts/config/departments.yaml",
    "contracts/config/urgency_rules.yaml",
    "prompts",
    "voice-runtime",
    "brain",
]

EXCLUDE_PATTERNS = [
    "*.egg-info",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
]


def should_exclude(path: Path) -> bool:
    """Check if path matches exclude patterns."""
    path_str = str(path)
    for pattern in EXCLUDE_PATTERNS:
        if pattern.startswith("*"):
            if path_str.endswith(pattern[1:]):
                return True
        elif pattern in path_str:
            return True
    return False


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def scan_paths(base_dir: Path) -> dict[str, str]:
    """Scan forbidden paths and compute hashes."""
    manifest = {}
    
    for forbidden_path in FORBIDDEN_PATHS:
        full_path = base_dir / forbidden_path
        
        if not full_path.exists():
            continue  # Path doesn't exist yet (e.g., voice-runtime, brain)
        
        if full_path.is_file():
            if not should_exclude(full_path):
                relative = str(full_path.relative_to(base_dir))
                manifest[relative] = compute_file_hash(full_path)
        else:
            # Directory - walk all files
            for file_path in full_path.rglob("*"):
                if file_path.is_file() and not should_exclude(file_path):
                    relative = str(file_path.relative_to(base_dir))
                    manifest[relative] = compute_file_hash(file_path)
    
    return manifest


def main():
    """Main entry point."""
    ops_api_dir = Path(__file__).parent.parent
    base_dir = ops_api_dir.parent.parent  # resolvix-team-package/resolvix
    manifest_path = ops_api_dir / "docs" / "forbidden_manifest.json"
    
    mode = "--init" if len(sys.argv) > 1 and sys.argv[1] == "--init" else "compare"
    
    current_manifest = scan_paths(base_dir)
    
    if mode == "--init":
        # Write baseline
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(current_manifest, f, indent=2, sort_keys=True)
        print(f"Initialized baseline with {len(current_manifest)} files")
        print(f"Manifest written to {manifest_path}")
        return 0
    
    # Compare mode
    if not manifest_path.exists():
        print(f"ERROR: Baseline manifest not found at {manifest_path}")
        print("Run with --init to create baseline")
        return 1
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        baseline_manifest = json.load(f)
    
    # Compare
    added = set(current_manifest.keys()) - set(baseline_manifest.keys())
    removed = set(baseline_manifest.keys()) - set(current_manifest.keys())
    changed = {
        path for path in current_manifest
        if path in baseline_manifest and current_manifest[path] != baseline_manifest[path]
    }
    
    if not (added or removed or changed):
        print("OK - No changes detected in forbidden paths")
        return 0
    
    # Report differences
    print("ERROR: Changes detected in forbidden paths!")
    
    if added:
        print(f"\nADDED ({len(added)}):")
        for path in sorted(added):
            print(f"  + {path}")
    
    if removed:
        print(f"\nREMOVED ({len(removed)}):")
        for path in sorted(removed):
            print(f"  - {path}")
    
    if changed:
        print(f"\nCHANGED ({len(changed)}):")
        for path in sorted(changed):
            print(f"  M {path}")
    
    return 1


if __name__ == "__main__":
    sys.exit(main())
