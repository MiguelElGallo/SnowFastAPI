import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / ".python_packages"))

if __name__ == "__main__":
    import uvicorn
    from snowapi.api import create_app
    from snowapi.catalog import Catalog

    catalog = Catalog.model_validate_json((ROOT / "catalog.json").read_bytes())
    uvicorn.run(
        create_app(catalog),
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        access_log=False,
        proxy_headers=False,
    )
