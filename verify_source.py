"""Verify the local Olist inputs against the recorded Kaggle snapshot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def verify_sources() -> None:
    manifest = json.loads((ROOT / "data/source_manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        path = ROOT / "data/raw" / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing Olist source file: {path}")
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != expected["sha256"]:
            raise ValueError(f"Olist source checksum mismatch: {path}")


if __name__ == "__main__":
    verify_sources()
    print("Olist source checksums match the recorded snapshot")
