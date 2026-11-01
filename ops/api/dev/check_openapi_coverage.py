"""Check OpenAPI coverage - compare ops-api.yaml to implemented routes.

Run with: python -X utf8 dev/check_openapi_coverage.py
"""
import sys
import tempfile
from pathlib import Path

import yaml
from resolvix_ops.app import create_app
from resolvix_ops.config import Settings


def parse_openapi_paths(yaml_path: Path) -> set[tuple[str, str]]:
    """Parse ops-api.yaml and return set of (method, path) tuples."""
    with open(yaml_path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    
    paths_set = set()
    for path, path_item in spec.get("paths", {}).items():
        for method in path_item.keys():
            if method in ["get", "post", "put", "patch", "delete", "options", "head"]:
                paths_set.add((method.upper(), path))
    
    return paths_set


def get_implemented_routes() -> set[tuple[str, str]]:
    """Get implemented routes from a FastAPI app built on a throwaway database (never the dev DB)."""
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=data_dir, ignore_cleanup_errors=True) as tmp:
        settings = Settings(
            _env_file=None,
            database_url=f"sqlite:///{Path(tmp, 'coverage.db').as_posix()}",
            service_key="coverage-check-service-key",
            session_secret="coverage-check-session-secret-0123456789",
            seed_users_on_startup=False,
            sms_poll_enabled=False,
        )
        app = create_app(settings)
        try:
            return _routes_of(app)
        finally:
            app.state.engine.dispose()


def _routes_of(app) -> set[tuple[str, str]]:
    routes_set = set()
    
    for route in app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            for method in route.methods:
                if method != "HEAD":  # Skip HEAD as it's auto-generated
                    routes_set.add((method, route.path))
    
    return routes_set


def main():
    """Compare OpenAPI spec to implemented routes."""
    ops_api_dir = Path(__file__).parent.parent
    yaml_path = ops_api_dir.parent.parent / "contracts" / "openapi" / "ops-api.yaml"
    
    if not yaml_path.exists():
        print(f"ERROR: {yaml_path} not found")
        return 1
    
    spec_routes = parse_openapi_paths(yaml_path)
    impl_routes = get_implemented_routes()
    
    # Normalize path templates for comparison
    def normalize_path(path: str) -> str:
        """Normalize {param} syntax."""
        return path
    
    spec_normalized = {(m, normalize_path(p)) for m, p in spec_routes}
    impl_normalized = {(m, normalize_path(p)) for m, p in impl_routes}
    
    # Compare
    implemented = spec_normalized & impl_normalized
    missing = spec_normalized - impl_normalized
    extra = impl_normalized - spec_normalized
    
    # Print table
    print("=" * 80)
    print("OpenAPI Coverage Report")
    print("=" * 80)
    print(f"Total in ops-api.yaml:    {len(spec_normalized)}")
    print(f"Implemented:              {len(implemented)}")
    print(f"Missing:                  {len(missing)}")
    print(f"Extra (not in spec):      {len(extra)}")
    print("=" * 80)
    
    if implemented:
        print("\nIMPLEMENTED:")
        for method, path in sorted(implemented):
            print(f"  {method:6s} {path}")
    
    if missing:
        print("\nMISSING FROM IMPLEMENTATION:")
        for method, path in sorted(missing):
            print(f"  {method:6s} {path}")
    
    if extra:
        print("\nEXTRA (not in ops-api.yaml):")
        for method, path in sorted(extra):
            print(f"  {method:6s} {path}")
    
    print("\n" + "=" * 80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
