"""Check frontend API types without overwriting the committed artifact."""

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix=".test-tmp-generated-", dir=ROOT) as directory:
        generated = Path(directory) / "schema.d.ts"
        subprocess.run(
            [
                "node",
                str(ROOT / "frontend/node_modules/openapi-typescript/bin/cli.js"),
                str(ROOT / "frontend/openapi.json"),
                "-o",
                str(generated),
            ],
            check=True,
        )
        if generated.read_text(encoding="utf-8") != (
            ROOT / "frontend/src/shared/api/schema.d.ts"
        ).read_text(encoding="utf-8"):
            raise SystemExit("Frontend API types are stale: run npm run gen:api in frontend")
    print("Frontend generated API types match OpenAPI")


if __name__ == "__main__":
    main()
