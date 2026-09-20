from pathlib import Path

from blackboard_sync.storage import Manifest, safe_name, sha256_file, unique_path


def test_safe_name_strips_invalid_chars():
    assert safe_name('Week 1: Intro / Overview?') == "Week 1_ Intro _ Overview_"


def test_safe_name_empty_falls_back():
    assert safe_name("   ") == "untitled"


def test_safe_name_truncates_long_names():
    long_name = "a" * 300
    assert len(safe_name(long_name, max_len=150)) == 150


def test_unique_path_avoids_clobbering(tmp_path: Path):
    d = tmp_path / "content"
    d.mkdir()
    first = unique_path(d, "notes.pdf")
    first.write_text("v1")

    second = unique_path(d, "notes.pdf")
    assert second != first
    assert second.name == "notes (2).pdf"


def test_sha256_file_is_stable(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_text("hello world")
    assert sha256_file(f) == sha256_file(f)


def test_manifest_round_trip(tmp_path: Path):
    manifest_path = tmp_path / ".manifest.json"
    m = Manifest(manifest_path)
    assert not m.is_unchanged("item-1", "fp-a")

    m.record("item-1", "content/foo.pdf", "fp-a")
    assert m.is_unchanged("item-1", "fp-a")
    assert not m.is_unchanged("item-1", "fp-b")

    m.save()
    assert manifest_path.exists()

    reloaded = Manifest(manifest_path)
    assert reloaded.is_unchanged("item-1", "fp-a")
    assert len(reloaded) == 1


def test_manifest_updates_fingerprint_keeps_first_seen(tmp_path: Path):
    manifest_path = tmp_path / ".manifest.json"
    m = Manifest(manifest_path)
    m.record("item-1", "content/foo.pdf", "fp-a")
    first_seen = m.get("item-1")["first_seen"]

    m.record("item-1", "content/foo.pdf", "fp-b")
    entry = m.get("item-1")
    assert entry["fingerprint"] == "fp-b"
    assert entry["first_seen"] == first_seen
