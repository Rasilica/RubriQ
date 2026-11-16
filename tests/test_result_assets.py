import json
import shutil
from hashlib import sha256

import pytest

from submission.result_assets import SAMPLES, bounded_read, load_raster
from submission.result_contracts import ResultError


@pytest.fixture
def samples(tmp_path):
    shutil.copytree(SAMPLES / "result-demos", tmp_path / "result-demos")
    shutil.copytree(SAMPLES / "pdf", tmp_path / "pdf")
    return tmp_path


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("image_sha256", "0" * 64),
        ("image_path", "../private-sentinel.png"),
        ("page_number", 2),
        ("width", 1),
        ("height", 1),
        ("page_number", True),
        ("private-sentinel", "bad"),
    ],
)
def test_assets_when_page_manifest_is_invalid_rejects_safely(samples, key, value):
    # Given
    manifest_path = samples / "result-demos/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    document = manifest["documents"][1]
    page = document["pages"][0]
    page[key] = value
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ResultError) as error:
        load_raster("normal", samples=samples)
    assert error.value.code == "result_demo_unavailable"
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "change",
    [
        "pdf_hash",
        "pdf_path",
        "page_count",
        "duplicate_document",
        "renderer",
        "png_header",
        "invalid_pdf",
    ],
)
def test_assets_when_document_manifest_is_invalid_rejects_safely(samples, change):
    manifest_path = samples / "result-demos/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    document = manifest["documents"][1]
    page = document["pages"][0]
    if change == "pdf_hash":
        document["pdf_sha256"] = "0" * 64
    elif change == "pdf_path":
        document["pdf_path"] = "../private-sentinel.pdf"
    elif change == "page_count":
        document["pages"] = document["pages"][:1]
    elif change == "duplicate_document":
        manifest["documents"][0] = document
    elif change == "renderer":
        manifest["renderer"]["dpi"] = 120
    elif change == "png_header":
        image = samples / page["image_path"]
        image.write_bytes(b"not-a-png")
        page["image_sha256"] = sha256(image.read_bytes()).hexdigest()
    else:
        pdf = samples / document["pdf_path"]
        pdf.write_bytes(b"not-a-pdf")
        document["pdf_sha256"] = sha256(pdf.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    # When
    with pytest.raises(ResultError) as error:
        load_raster("normal", samples=samples)
    # Then
    assert error.value.code == "result_demo_unavailable"
    assert "private" not in str(error.value)


def test_assets_when_corrupt_file_restored_recovers_without_cache(samples):
    # Given
    path = samples / "pdf/normal.pdf"
    original = path.read_bytes()
    path.write_bytes(b"corrupt")
    with pytest.raises(ResultError):
        load_raster("normal", samples=samples)
    path.write_bytes(original)
    # When
    loaded = load_raster("normal", samples=samples)
    # Then
    assert loaded.pdf_bytes == original
    assert len(loaded.images) == 2


@pytest.mark.parametrize("missing", [True, False])
def test_bounded_read_when_missing_or_oversized_returns_safe_error(tmp_path, missing):
    # Given
    path = tmp_path / "private-sentinel"
    if not missing:
        path.write_bytes(b"123")
    # When
    with pytest.raises(ResultError) as error:
        bounded_read(path, 2)
    # Then
    assert error.value.code == "result_demo_unavailable"
    assert "private" not in str(error.value)


def test_assets_when_unknown_document_does_not_read_path(tmp_path):
    # Given / When
    with pytest.raises(ResultError) as error:
        load_raster("../private", samples=tmp_path)
    # Then
    assert error.value.code == "result_not_found"
