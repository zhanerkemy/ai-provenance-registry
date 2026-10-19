
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hash_file import fingerprint, hash_directory, hash_file  # noqa: E402


def test_matches_known_sha256_value(tmp_path):
    # Standard reference value: SHA-256 of the three bytes "abc".
    f = tmp_path / "abc.txt"
    f.write_bytes(b"abc")
    assert hash_file(f) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_matches_hashlib_on_file_larger_than_one_chunk(tmp_path):
    data = bytes(range(256)) * 10_000  # about 2.5 MB, so it is read in several chunks
    f = tmp_path / "big.bin"
    f.write_bytes(data)
    assert hash_file(f) == hashlib.sha256(data).hexdigest()


def test_changing_one_byte_changes_the_hash(tmp_path):
    f = tmp_path / "weights.bin"
    f.write_bytes(b"\x00" * 1000)
    before = hash_file(f)
    f.write_bytes(b"\x00" * 999 + b"\x01")
    assert hash_file(f) != before


def test_directory_hash_ignores_file_creation_order(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "config.json").write_text("{}")
    (a / "model.bin").write_bytes(b"weights")
    (b / "model.bin").write_bytes(b"weights")  # same files, created in the other order
    (b / "config.json").write_text("{}")
    assert hash_directory(a) == hash_directory(b)


def test_directory_hash_detects_renamed_file(tmp_path):
    folder = tmp_path / "m"
    folder.mkdir()
    (folder / "model.bin").write_bytes(b"weights")
    before = hash_directory(folder)
    (folder / "model.bin").rename(folder / "model_v2.bin")
    assert hash_directory(folder) != before


def test_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        fingerprint(tmp_path / "does_not_exist")


def test_empty_folder_raises(tmp_path):
    with pytest.raises(ValueError):
        hash_directory(tmp_path)
