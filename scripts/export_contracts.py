"""Export language-neutral JSON schemas. Decimal fields serialize as strings."""

import json
from pathlib import Path

from services.common.contracts import RawEnvelope
from services.ingestion.normalizers.base import CanonicalTrade


def main():
    directory = Path("contracts/events")
    directory.mkdir(parents=True, exist_ok=True)
    for name, model in (("raw.v1", RawEnvelope), ("trade.v1", CanonicalTrade)):
        schema = model.model_json_schema(mode="serialization")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        (directory / f"{name}.schema.json").write_text(
            json.dumps(schema, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
