
import argparse
import hashlib
from collections.abc import Iterable
from pathlib import Path

CHUNK_SIZE = 1024 * 1024  # read 1 MB at a time, so multi-GB files never fill memory

# File types that hold model weights. Config and tokenizer files are left out.
WEIGHT_EXTENSIONS = (
    ".safetensors",
    ".bin",
    ".gguf",
    ".pt",
    ".pth",
    ".ckpt",
    ".h5",
    ".msgpack",
    ".onnx",
)


def is_weight_file(path: str) -> bool:
    """True if the file name looks like a weights file (case-insensitive)."""
    return path.lower().endswith(WEIGHT_EXTENSIONS)


def hash_file(path: Path) -> str:
    """Return the SHA-256 of one file as 64 lowercase hex characters."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def manifest_hash(entries: Iterable[tuple[str, str]]) -> str:
    """Hash a list of (relative path, file SHA-256) pairs into one SHA-256.

    Paths use "/" and are sorted as plain strings, so the result is the same on every
    operating system and every Python version, and whether the file hashes were
    computed locally or read from the Hugging Face Hub.
    """
    lines = sorted(entries)
    if not lines:
        raise ValueError("cannot fingerprint an empty list of files")
    manifest = "".join(f"{path} {digest}\n" for path, digest in lines)
    return hashlib.sha256(manifest.encode("utf-8")).hexdigest()


def hash_directory(folder: Path, weights_only: bool = False) -> str:
    """Return one SHA-256 for a whole folder, built from a sorted manifest of its files."""
    files = [p for p in folder.rglob("*") if p.is_file()]
    if weights_only:
        files = [p for p in files if is_weight_file(p.name)]
    if not files:
        kind = "weight files" if weights_only else "files"
        raise ValueError(f"{folder} contains no {kind}")
    return manifest_hash((p.relative_to(folder).as_posix(), hash_file(p)) for p in files)


def fingerprint(path: Path, weights_only: bool = False) -> str:
    """Hash a file or a folder, whichever the path points to."""
    if path.is_file():
        return hash_file(path)
    if path.is_dir():
        return hash_directory(path, weights_only)
    raise FileNotFoundError(f"No such file or folder: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="SHA-256 fingerprint for ModelRegistry.")
    parser.add_argument("path", type=Path, help="file or folder to hash")
    parser.add_argument(
        "--weights-only",
        action="store_true",
        help="for a folder, hash only weight files (matches the Hub-derived fingerprint)",
    )
    args = parser.parse_args()
    print("0x" + fingerprint(args.path, args.weights_only))


if __name__ == "__main__":
    main()
