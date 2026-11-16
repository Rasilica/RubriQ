import sys
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from struct import pack

import pytest
from olefile import OleFileIO

from submission.conversion_contracts import ConversionError, ConversionErrorCode
from submission.hwp_reading import decode_structure, provision_hwp_reader, read_hwp_structure
from submission.hwp_reading_contracts import HwpReadConfig
from submission.input_contracts import DocumentInput, InputErrorCode, InputValidationError
from submission.models import DocumentRole

RAW = (
    b'{"sections":[{"path":"BodyText/Section0","paragraphs":['
    b'{"path":"BodyText/Section0/paragraph[0]","text":"hello","controls":['
    b'{"path":"BodyText/Section0/paragraph[0]/control[0]","kind":"SectionDefine"}]}]}]}'
)


def test_decode_preserves_order_text_and_control_paths():
    result = decode_structure(RAW)
    assert result.sections[0].paragraphs[0].text == "hello"
    assert result.sections[0].paragraphs[0].controls[0].kind == "SectionDefine"


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b'{"sections":[]}',
        b'{"sections":[{"path":"other","paragraphs":[]}]}',
        RAW.replace(b"paragraph[0]", b"paragraph[2]", 1),
        RAW.replace(b"control[0]", b"control[2]"),
    ],
)
def test_decode_rejects_invalid_worker_output(raw: bytes):
    with pytest.raises(ConversionError) as failure:
        _ = decode_structure(raw)
    assert failure.value.code == ConversionErrorCode.RENDERER_FAILED


def config_for(tmp_path: Path, body: str) -> HwpReadConfig:
    java = tmp_path / "jdk"
    (java / "bin").mkdir(parents=True)
    (java / "lib/server").mkdir(parents=True)
    executable = java / "bin/java"
    _ = executable.write_text(f"#!{sys.executable}\n{body}\n")
    executable.chmod(0o700)
    _ = (java / "release").write_text("test")
    _ = (java / "lib/server/libjvm.dylib").write_bytes(b"test")
    worker = tmp_path / "Worker.java"
    _ = worker.write_text("test")
    provision = provision_hwp_reader(java, Path("vendor/hwplib/1.1.11/hwplib-1.1.11.jar"), worker)
    return HwpReadConfig(provision=provision, work_root=tmp_path / "jobs")


def source_input() -> DocumentInput:
    return DocumentInput(
        "sample.hwp",
        Path("samples/formats/minimal-5.1.1.0.hwp").read_bytes(),
        DocumentRole.REPORT,
    )


def test_process_result_preserves_source_and_cleans_jobs(tmp_path: Path):
    config = config_for(tmp_path, f"import sys\nsys.stdout.buffer.write({RAW!r})")
    source = source_input()
    result = read_hwp_structure(source, config)
    assert result.source.content_sha256 == sha256(source.content).hexdigest()
    assert result.structure.sections[0].paragraphs[0].text == "hello"
    assert tuple(config.work_root.iterdir()) == ()


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("import sys\nsys.exit(1)", ConversionErrorCode.RENDERER_FAILED),
        ("import sys\nsys.stdout.write('x'*70000)", ConversionErrorCode.PROCESS_OUTPUT_LIMIT),
        ("import sys\nsys.stdout.write('bad')", ConversionErrorCode.RENDERER_FAILED),
    ],
)
def test_worker_failure_cleans_jobs(tmp_path: Path, body: str, code: ConversionErrorCode):
    config = config_for(tmp_path, body)
    with pytest.raises(ConversionError) as failure:
        _ = read_hwp_structure(source_input(), config)
    assert failure.value.code == code
    assert tuple(config.work_root.iterdir()) == ()


def test_runtime_change_rejected_before_launch(tmp_path: Path):
    config = config_for(tmp_path, "raise RuntimeError()")
    _ = config.provision.worker.path.write_text("changed")
    with pytest.raises(ConversionError) as failure:
        _ = read_hwp_structure(source_input(), config)
    assert failure.value.code == ConversionErrorCode.INVALID_CONFIG
    assert not config.work_root.exists()


def test_bad_jar_refused_during_provision(tmp_path: Path):
    jar = tmp_path / "bad.jar"
    _ = jar.write_bytes(b"bad")
    with pytest.raises(ConversionError) as failure:
        _ = provision_hwp_reader(tmp_path, jar, tmp_path)
    assert failure.value.code == ConversionErrorCode.INVALID_CONFIG


def test_missing_jar_refused_during_provision(tmp_path: Path):
    with pytest.raises(ConversionError) as failure:
        _ = provision_hwp_reader(tmp_path, tmp_path / "absent", tmp_path)
    assert failure.value.code == ConversionErrorCode.INVALID_CONFIG


def test_corrupt_input_refused_before_worker(tmp_path: Path):
    config = config_for(tmp_path, "raise RuntimeError()")
    with pytest.raises(InputValidationError):
        _ = read_hwp_structure(DocumentInput("bad.hwp", b"broken", DocumentRole.REPORT), config)
    assert not config.work_root.exists()


def test_process_timeout_cleans_job(tmp_path: Path):
    config = config_for(tmp_path, "import signal\nsignal.pause()")
    limited = HwpReadConfig(
        provision=config.provision,
        work_root=config.work_root,
        timeout_seconds=0.2,
    )
    with pytest.raises(ConversionError) as failure:
        _ = read_hwp_structure(source_input(), limited)
    assert failure.value.code == ConversionErrorCode.TIMEOUT
    assert tuple(config.work_root.iterdir()) == ()


def test_missing_worker_is_typed_io_failure(tmp_path: Path):
    config = config_for(tmp_path, "raise RuntimeError()")
    config.provision.worker.path.unlink()
    with pytest.raises(ConversionError) as failure:
        _ = read_hwp_structure(source_input(), config)
    assert failure.value.code == ConversionErrorCode.IO_ERROR


def test_non_hwp_refused_before_worker(tmp_path: Path):
    config = config_for(tmp_path, "raise RuntimeError()")
    source = DocumentInput(
        "report.hwpx",
        Path("samples/formats/spine-order.hwpx").read_bytes(),
        DocumentRole.REPORT,
    )
    with pytest.raises(ConversionError) as failure:
        _ = read_hwp_structure(source, config)
    assert failure.value.code == ConversionErrorCode.UNSUPPORTED_FORMAT


@pytest.mark.parametrize(
    ("flags", "expected"),
    [(2, InputErrorCode.ENCRYPTED_DOCUMENT), (4, InputErrorCode.PROTECTED_DOCUMENT)],
)
def test_protection_refused_before_launch(tmp_path: Path, flags: int, expected: InputErrorCode):
    config = config_for(tmp_path, "raise RuntimeError()")
    buffer = BytesIO(source_input().content)
    container: OleFileIO[str] = OleFileIO(buffer, write_mode=True)
    with container as document:
        with document.openstream("FileHeader") as stream:
            header = stream.read()
        document.write_stream("FileHeader", header[:36] + pack("<I", flags) + header[40:])
    with pytest.raises(InputValidationError) as failure:
        _ = read_hwp_structure(
            DocumentInput("test.hwp", buffer.getvalue(), DocumentRole.REPORT), config
        )
    assert failure.value.code == expected
    assert not config.work_root.exists()
