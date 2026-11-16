from pathlib import Path
from struct import pack

import pytest
from conversion_helpers import fake_renderer

from submission.compound_documents import inspect_hwp_header
from submission.conversion_contracts import ConversionError
from submission.hancom_contracts import HancomConversionConfig
from submission.hancom_conversion import convert_hancom
from submission.hancom_profile import seal_profile
from submission.input_contracts import DocumentInput, InputValidationError
from submission.models import DocumentRole
from tests.test_hancom_profile import profile_fixture


def test_hwp_5034_keeps_actual_version() -> None:
    header = b"HWP Document File".ljust(32, b"\0") + pack("<II", 0x05000304, 0) + bytes(216)

    version, compressed = inspect_hwp_header(header)

    assert version == "5.0.3.4"
    assert not compressed


@pytest.mark.parametrize(("raw", "expected"), [(0x05010001, "5.1.0.1"), (0x05000204, "5.0.2.4")])
def test_older_hangul_hwp_versions_are_accepted(raw: int, expected: str) -> None:
    header = b"HWP Document File".ljust(32, b"\0") + pack("<II", raw, 1) + bytes(216)

    version, compressed = inspect_hwp_header(header)

    assert version == expected
    assert compressed


def test_unlisted_hwp_version_is_still_rejected() -> None:
    header = b"HWP Document File".ljust(32, b"\0") + pack("<II", 0x05000105, 0) + bytes(216)

    with pytest.raises(InputValidationError):
        _ = inspect_hwp_header(header)


@pytest.mark.parametrize("filename", ["minimal-5.1.1.0.hwp", "spine-order.hwpx"])
def test_hancom_preview_keeps_source_identity(tmp_path: Path, filename: str) -> None:
    template, _, java = profile_fixture(tmp_path)
    renderer = fake_renderer(tmp_path)
    provision = seal_profile(template, renderer, java)
    source = DocumentInput(
        filename, Path("samples/formats", filename).read_bytes(), DocumentRole.REPORT
    )
    config = HancomConversionConfig(
        soffice=renderer, work_root=tmp_path / "jobs", provision=provision
    )

    result = convert_hancom(source, config)

    assert result.artifact.parent_source_id == result.source.source_id
    assert result.preview_page_count == 1
    assert result.artifact.conversion_chain[1].name == "H2Orestart"
    assert not tuple(config.work_root.iterdir())


def test_runtime_tampering_is_rejected(tmp_path: Path) -> None:
    template, _, java = profile_fixture(tmp_path)
    renderer = fake_renderer(tmp_path)
    provision = seal_profile(template, renderer, java)
    source = DocumentInput(
        "sample.hwpx", Path("samples/formats/spine-order.hwpx").read_bytes(), DocumentRole.REPORT
    )
    config = HancomConversionConfig(
        soffice=renderer, work_root=tmp_path / "jobs", provision=provision
    )
    _ = (java / "lib/server/libjvm.dylib").write_bytes(b"changed")

    with pytest.raises(ConversionError, match="invalid_config"):
        _ = convert_hancom(source, config)

    assert not tuple(config.work_root.iterdir())


def test_hwp_is_gated_before_rendering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    template, _, java = profile_fixture(tmp_path)
    renderer = fake_renderer(tmp_path)
    config = HancomConversionConfig(
        soffice=renderer,
        work_root=tmp_path / "jobs",
        provision=seal_profile(template, renderer, java),
    )
    source = DocumentInput(
        "minimal.hwp",
        Path("samples/formats/minimal-5.1.1.0.hwp").read_bytes(),
        DocumentRole.REPORT,
    )
    seen: list[bytes] = []
    monkeypatch.setattr(
        "submission.hancom_conversion.reject_hwp_active_content",
        lambda content, _limits: seen.append(content),
    )

    _ = convert_hancom(source, config)

    assert seen == [source.content]
