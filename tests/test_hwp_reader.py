import json
import sys
from io import BytesIO
from pathlib import Path
from struct import pack

import pytest
from olefile import OleFileIO

from submission.conversion_contracts import ConversionError, ConversionErrorCode
from submission.hwp_reader import read_hwp
from submission.hwp_reader_contracts import HwpTree
from submission.hwp_reading import provision_hwp_reader
from submission.hwp_reading_contracts import HwpReadConfig
from submission.input_contracts import DocumentInput, InputErrorCode, InputValidationError
from submission.models import DocumentRole


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


def payload() -> bytes:
    path = "BodyText/Section0/paragraph[0]"
    return json.dumps(
        {
            "parts": ["BodyText/Section0"],
            "nodes": [
                {
                    "path": path,
                    "kind": "paragraph",
                    "text": "앞😀",
                    "parent": None,
                    "fragment": 1,
                    "start": 0,
                },
                {
                    "path": path + "/control[0]/row[0]/cell[0]",
                    "kind": "table_cell",
                    "text": "",
                    "parent": None,
                    "fragment": None,
                    "start": 0,
                },
                {
                    "path": path + "/control[0]/row[0]/cell[0]/paragraph[0]",
                    "kind": "paragraph",
                    "text": "셀 내용",
                    "parent": path + "/control[0]/row[0]/cell[0]",
                    "fragment": 1,
                    "start": 0,
                },
                {
                    "path": path,
                    "kind": "paragraph",
                    "text": "뒤",
                    "parent": None,
                    "fragment": 2,
                    "start": 2,
                },
            ],
            "omitted": [path + "/control[1]"],
            "references": [],
        }
    ).encode()


def result_body(raw: bytes) -> str:
    return f"import pathlib, sys\npathlib.Path(sys.argv[-1]).write_bytes({raw!r})\nprint('ok')"


def test_nested_projection_preserves_unicode_order_and_parent(tmp_path: Path):
    config = config_for(tmp_path, result_body(payload()))
    result = read_hwp(source_input(), config)
    assert [block.raw_text for block in result.blocks] == ["앞😀", "", "셀 내용", "뒤"]
    assert result.blocks[2].parent_block_id == result.blocks[1].block_id
    assert result.blocks[3].raw_char_range.start == 2
    assert result.coverage.scope == "hwp5_structure"
    assert result.extraction_status == "partial"
    assert result.page_count.status == "deferred"
    assert tuple(config.work_root.iterdir()) == ()


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("print('ok')", ConversionErrorCode.OUTPUT_MISSING),
        (
            "import pathlib,sys\npathlib.Path(sys.argv[-1]).symlink_to(sys.argv[-2])\nprint('ok')",
            ConversionErrorCode.OUTPUT_INVALID,
        ),
        (result_body(b"{}"), ConversionErrorCode.OUTPUT_INVALID),
        ("print('output_limit')", ConversionErrorCode.OUTPUT_LIMIT),
        ("print('wrong')", ConversionErrorCode.OUTPUT_INVALID),
        ("import sys\nsys.exit(1)", ConversionErrorCode.RENDERER_FAILED),
        ("import os,sys\nos.mkfifo(sys.argv[-1])\nprint('ok')", ConversionErrorCode.OUTPUT_INVALID),
        (
            (
                "import pathlib,sys\npathlib.Path(sys.argv[-1]).write_bytes(b'x' * (4194304+1))\n"
                "print('ok')"
            ),
            ConversionErrorCode.OUTPUT_LIMIT,
        ),
    ],
)
def test_invalid_result_file_is_typed_and_removed(
    tmp_path: Path,
    body: str,
    code: ConversionErrorCode,
):
    config = config_for(tmp_path, body)
    with pytest.raises(ConversionError) as failure:
        _ = read_hwp(source_input(), config)
    assert failure.value.code == code
    assert tuple(config.work_root.iterdir()) == ()


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (b"Section0", b"Section1"),
        (b'"fragment": 2', b'"fragment": 1'),
        (b'"fragment": 2', b'"fragment": 3'),
        (b'"start": 2', b'"start": 3'),
        (b'"kind": "table_cell"', b'"kind": "paragraph"'),
        (b'"fragment": null', b'"fragment": 1'),
        (b'"text": ""', b'"text": "invalid"'),
        (
            b'"parent": "BodyText/Section0/paragraph[0]/control[0]/row[0]/cell[0]"',
            b'"parent": "BodyText/Section0/paragraph[0]/control[0]/row[0]/cell[8]"',
        ),
    ],
)
def test_inconsistent_worker_contract_is_rejected(tmp_path: Path, before: bytes, after: bytes):
    config = config_for(tmp_path, result_body(payload().replace(before, after)))
    with pytest.raises(ConversionError) as failure:
        _ = read_hwp(source_input(), config)
    assert failure.value.code == ConversionErrorCode.OUTPUT_INVALID


@pytest.mark.parametrize("readable", [True, False])
def test_complete_and_empty_status_do_not_claim_layout(tmp_path: Path, *, readable: bool):
    tree = HwpTree.model_validate_json(payload())
    node = tree.nodes[0].model_copy(update={"text": "readable" if readable else ""})
    raw = tree.model_copy(update={"nodes": (node,), "omitted": ()}).model_dump_json().encode()
    config = config_for(tmp_path, result_body(raw))
    result = read_hwp(source_input(), config)
    assert result.extraction_status == ("complete" if readable else "failed")
    assert bool(result.typed_errors) is not readable
    assert result.page_count.count is None


@pytest.mark.parametrize("name", ["worker", "java"])
def test_changed_pinned_runtime_prevents_execution(tmp_path: Path, name: str):
    config = config_for(tmp_path, "raise RuntimeError()")
    path = config.provision.worker.path if name == "worker" else config.provision.java_files[0].path
    _ = path.write_text("changed")
    with pytest.raises(ConversionError) as failure:
        _ = read_hwp(source_input(), config)
    assert failure.value.code == ConversionErrorCode.INVALID_CONFIG
    assert not config.work_root.exists()


def test_missing_runtime_is_typed_io_failure(tmp_path: Path):
    config = config_for(tmp_path, "raise RuntimeError()")
    config.provision.worker.path.unlink()
    with pytest.raises(ConversionError) as failure:
        _ = read_hwp(source_input(), config)
    assert failure.value.code == ConversionErrorCode.IO_ERROR


def test_wrong_format_is_rejected_before_worker(tmp_path: Path):
    config = config_for(tmp_path, "raise RuntimeError()")
    source = DocumentInput(
        "sample.hwpx", Path("samples/formats/spine-order.hwpx").read_bytes(), DocumentRole.REPORT
    )
    with pytest.raises(ConversionError) as failure:
        _ = read_hwp(source, config)
    assert failure.value.code == ConversionErrorCode.UNSUPPORTED_FORMAT


def test_worker_timeout_cleans_and_retry_works(tmp_path: Path):
    config = config_for(tmp_path, "import signal\nsignal.pause()")
    limited = config.model_copy(update={"timeout_seconds": 0.2})
    with pytest.raises(ConversionError) as failure:
        _ = read_hwp(source_input(), limited)
    assert failure.value.code == ConversionErrorCode.TIMEOUT
    assert tuple(config.work_root.iterdir()) == ()
    executable = config.provision.java_files[0].path
    _ = executable.write_text(f"#!{sys.executable}\n{result_body(payload())}\n")
    retry = HwpReadConfig(
        provision=provision_hwp_reader(
            config.provision.java_home, config.provision.jar.path, config.provision.worker.path
        ),
        work_root=config.work_root,
    )
    assert read_hwp(source_input(), retry).content_review_available


@pytest.mark.parametrize(
    ("flags", "expected"),
    [(2, InputErrorCode.ENCRYPTED_DOCUMENT), (4, InputErrorCode.PROTECTED_DOCUMENT)],
)
def test_protection_refused_before_nested_worker(
    tmp_path: Path, flags: int, expected: InputErrorCode
):
    config = config_for(tmp_path, "raise RuntimeError()")
    buffer = BytesIO(source_input().content)
    container: OleFileIO[str] = OleFileIO(buffer, write_mode=True)
    with container as document:
        with document.openstream("FileHeader") as stream:
            header = stream.read()
        document.write_stream("FileHeader", header[:36] + pack("<I", flags) + header[40:])
    with pytest.raises(InputValidationError) as failure:
        _ = read_hwp(DocumentInput("test.hwp", buffer.getvalue(), DocumentRole.REPORT), config)
    assert failure.value.code == expected
    assert not config.work_root.exists()
