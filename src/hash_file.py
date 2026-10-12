"""Compute the SHA-256 fingerprint of a model or dataset, ready for ModelRegistry.

Usage:
    python src/hash_file.py path/to/model.safetensors
    python src/hash_file.py path/to/model_folder/

For a single file, the result is the ordinary SHA-256 of its bytes, identical to
what `sha256sum` (Linux) or `shasum -a 256` (macOS) prints.

Many models are folders of several files (config.json, weight shards, ...).
For a folder we hash every file, write one line "<relative/path> <file hash>" per
file in sorted order, and hash that list. Any change to any file's content, a
renamed file, or an added or removed file therefore changes the result.

The output is printed with a "0x" prefix because that is how Solidity expects a
bytes32 value, e.g. registerModel(0x3f2a..., ...).
"""

import argparse
import hashlib
from pathlib import Path

CHUNK_SIZE = 1024 * 1024  # read 1 MB at a time, so multi-GB files never fill memory


def hash_file(path: Path) -> str:
    """Return the SHA-256 of one file as 64 lowercase hex characters."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def hash_directory(folder: Path) -> str:
    """Return one SHA-256 for a whole folder, built from a sorted manifest of its files."""
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    if not files:
        raise ValueError(f"{folder} contains no files")

    # Use "/" in paths on every OS, so Windows and macOS give the same result.
    manifest = "".join(
        f"{p.relative_to(folder).as_posix()} {hash_file(p)}\n" for p in files
    )
    return hashlib.sha256(manifest.encode("utf-8")).hexdigest()


def fingerprint(path: Path) -> str:
    """Hash a file or a folder, whichever the path points to."""
    if path.is_file():
        return hash_file(path)
    if path.is_dir():
        return hash_directory(path)
    raise FileNotFoundError(f"No such file or folder: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="SHA-256 fingerprint for ModelRegistry.")
    parser.add_argument("path", type=Path, help="file or folder to hash")
    args = parser.parse_args()
    print("0x" + fingerprint(args.path))


if __name__ == "__main__":
    main()
