from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from conversion_helpers import fake_renderer, pdf_bytes, source_docx

from submission.conversion_contracts import ConversionError, ConversionErrorCode
from submission.docx_conversion import conversion_slot
from submission.hancom_content import reject_hwpx_active_content
from submission.hancom_contracts import HancomConversionConfig
from submission.hancom_conversion import convert_hancom
from submission.hancom_profile import seal_profile
from submission.input_contracts import DocumentInput, InputErrorCode, InputValidationError
from submission.models import DocumentRole
from tests.test_hancom_profile import profile_fixture


def hwpx_source() -> DocumentInput:
    return DocumentInput(
        "sample.hwpx", Path("samples/formats/spine-order.hwpx").read_bytes(), DocumentRole.REPORT
    )


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("failure", ConversionErrorCode.RENDERER_FAILED),
        ("missing", ConversionErrorCode.OUTPUT_MISSING),
        ("timeout", ConversionErrorCode.TIMEOUT),
    ],
)
def test_failed_hancom_job_is_removed(tmp_path: Path, mode: str, code: ConversionErrorCode) -> None:
    template, _, java = profile_fixture(tmp_path)
    renderer = fake_renderer(tmp_path, mode=mode)
    config = HancomConversionConfig(
        soffice=renderer,
        work_root=tmp_path / "jobs",
        provision=seal_profile(template, renderer, java),
        timeout_seconds=0.5 if mode == "timeout" else 5.0,
        terminate_grace_seconds=0.1,
    )

    with pytest.raises(ConversionError) as caught:
        _ = convert_hancom(hwpx_source(), config)

    assert caught.value.code == code
    assert not tuple(config.work_root.iterdir())


def test_output_page_limit_removes_job(tmp_path: Path) -> None:
    template, _, java = profile_fixture(tmp_path)
    renderer = fake_renderer(tmp_path, pdf_bytes(2))
    config = HancomConversionConfig(
        soffice=renderer,
        work_root=tmp_path / "jobs",
        provision=seal_profile(template, renderer, java),
        max_output_pages=1,
    )

    with pytest.raises(ConversionError, match="output_limit"):
        _ = convert_hancom(hwpx_source(), config)

    assert not tuple(config.work_root.iterdir())


def test_docx_and_hancom_share_admission_gate(tmp_path: Path) -> None:
    template, renderer, java = profile_fixture(tmp_path)
    config = HancomConversionConfig(
        soffice=renderer,
        work_root=tmp_path / "jobs",
        provision=seal_profile(template, renderer, java),
    )

    with conversion_slot(), pytest.raises(ConversionError, match="conversion_busy"):
        _ = convert_hancom(hwpx_source(), config)

    assert not config.work_root.exists()


def test_other_formats_fail_without_job(tmp_path: Path) -> None:
    template, renderer, java = profile_fixture(tmp_path)
    config = HancomConversionConfig(
        soffice=renderer,
        work_root=tmp_path / "jobs",
        provision=seal_profile(template, renderer, java),
    )

    with pytest.raises(ConversionError, match="unsupported_format"):
        _ = convert_hancom(source_docx(), config)

    assert not config.work_root.exists()


@pytest.mark.parametrize(
    ("name", "xml"),
    [
        ("Contents/content.hpf", '<root href="https://example.invalid/file"/>'),
        ("Contents/section0.xml", "<root><fieldBegin/></root>"),
        ("Contents/section0.xml", "<root><ole/></root>"),
        ("META-INF/extra.xml", '<root src="../outside"/>'),
        ("META-INF/extra.xml", '<root target="/outside"/>'),
        ("META-INF/extra.rels", '<root TargetMode="External"/>'),
        ("META-INF/extra.xml", '<root isEmbeded="0"/>'),
        ("META-INF/extra.xml", '<root href="%2e%2e/outside"/>'),
        ("META-INF/extra.xml", '<root src="https%3A//example.invalid/x"/>'),
        ("Scripts/DefaultJScript", "fixture"),
    ],
)
def test_active_content_is_rejected(name: str, xml: str) -> None:
    package = BytesIO()
    with ZipFile(package, "w") as archive:
        archive.writestr(name, xml)

    with pytest.raises(ConversionError, match="unsupported_active_content"):
        reject_hwpx_active_content(package.getvalue())


def test_nonembedded_font_declaration_is_allowed() -> None:
    package = BytesIO()
    with ZipFile(package, "w") as archive:
        archive.writestr(
            "Contents/header.xml", '<root><font isEmbedded="0" face="fixture"/></root>'
        )

    reject_hwpx_active_content(package.getvalue())


def test_external_extra_xml_stops_before_renderer(tmp_path: Path) -> None:
    template, renderer, java = profile_fixture(tmp_path)
    config = HancomConversionConfig(
        soffice=renderer,
        work_root=tmp_path / "jobs",
        provision=seal_profile(template, renderer, java),
    )
    package = BytesIO()
    with ZipFile(BytesIO(hwpx_source().content)) as original, ZipFile(package, "w") as archive:
        for item in original.infolist():
            archive.writestr(item, original.read(item))
        archive.writestr("META-INF/extra.xml", '<root src="https://example.invalid/x"/>')
    source = DocumentInput("sample.hwpx", package.getvalue(), DocumentRole.REPORT)

    with pytest.raises(ConversionError, match="unsupported_active_content"):
        _ = convert_hancom(source, config)

    assert not config.work_root.exists()


def test_inherited_java_options_cannot_override_private_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template, _, java = profile_fixture(tmp_path)
    renderer = fake_renderer(tmp_path)
    shebang, body = renderer.read_text().split("\n", 1)
    guard = "assert 'UNO_JAVA_JFW_PARAMETER_3' not in os.environ"
    script = f"{shebang}\nimport os\n{guard}\n{body}"
    _ = renderer.write_text(script)
    provision = seal_profile(template, renderer, java)
    config = HancomConversionConfig(
        soffice=renderer, work_root=tmp_path / "jobs", provision=provision
    )
    monkeypatch.setenv("UNO_JAVA_JFW_PARAMETER_3", "-Duser.home=/unused-test-path")

    result = convert_hancom(hwpx_source(), config)

    assert result.preview_page_count == 1


@pytest.mark.parametrize("suffix", ["XML", "HPF", "RELS"])
def test_malformed_uppercase_xml_is_a_typed_input_error(tmp_path: Path, suffix: str) -> None:
    template, renderer, java = profile_fixture(tmp_path)
    config = HancomConversionConfig(
        soffice=renderer,
        work_root=tmp_path / "jobs",
        provision=seal_profile(template, renderer, java),
    )
    package = BytesIO()
    with ZipFile(BytesIO(hwpx_source().content)) as original, ZipFile(package, "w") as archive:
        for item in original.infolist():
            archive.writestr(item, original.read(item))
        archive.writestr(f"META-INF/extra.{suffix}", "<broken")
    source = DocumentInput("sample.hwpx", package.getvalue(), DocumentRole.REPORT)

    with pytest.raises(InputValidationError) as caught:
        _ = convert_hancom(source, config)

    assert caught.value.code == InputErrorCode.CORRUPT_DOCUMENT
    assert not config.work_root.exists()


HANCOM_HEADER_SCRIPT = (
    "var Documents = XHwpDocuments;\r\nvar Document = Documents.Active_XHwpDocument;\r\n"
)
HANCOM_SOURCE_SCRIPT = (
    "function OnDocument_New()\r\n{\r\n\t//todo : \r\n}\r\n"
    "function OnCheckBox1_Click()\r\n{\r\n\t//todo : \r\n}\r\n"
)


def script_package(scripts: dict[str, str]) -> bytes:
    package = BytesIO()
    with ZipFile(package, "w") as archive:
        for name, text in scripts.items():
            archive.writestr(name, text.encode("utf-16-le"))
    return package.getvalue()


def test_hancom_default_empty_script_template_is_allowed() -> None:
    content = script_package(
        {
            "Scripts/headerScripts": HANCOM_HEADER_SCRIPT,
            "Scripts/sourceScripts": HANCOM_SOURCE_SCRIPT,
        }
    )

    reject_hwpx_active_content(content)


@pytest.mark.parametrize(
    "scripts",
    [
        {"Scripts/sourceScripts": "function OnDocument_New()\r\n{\r\n\tDocument.Run();\r\n}\r\n"},
        {"Scripts/headerScripts": HANCOM_HEADER_SCRIPT + "var x = 1;\r\n"},
        {"Scripts/sourceScripts": "function OnDocument_New()\r\n{\r\n\t/* x */ go();\r\n}\r\n"},
        {"Scripts/otherScripts": HANCOM_HEADER_SCRIPT},
        {"Scripts/sourceScripts": "// a\u2028 evil()\r\nfunction A()\r\n{\r\n}\r\n"},
    ],
)
def test_hancom_scripts_with_code_are_rejected(scripts: dict[str, str]) -> None:
    with pytest.raises(ConversionError, match="unsupported_active_content"):
        reject_hwpx_active_content(script_package(scripts))


def field_package(begin: str) -> bytes:
    section = (
        '<hs:sec xmlns:hs="urn:s" xmlns:hp="urn:p"><hp:p><hp:run><hp:ctrl>'
        f"{begin}</hp:ctrl></hp:run><hp:run><hp:t>text</hp:t></hp:run>"
        '<hp:run><hp:ctrl><hp:fieldEnd beginIDRef="1"/></hp:ctrl></hp:run></hp:p></hs:sec>'
    )
    package = BytesIO()
    with ZipFile(package, "w") as archive:
        archive.writestr("Contents/section0.xml", section)
    return package.getvalue()


def hyperlink(target: str) -> str:
    return (
        '<hp:fieldBegin id="1" type="HYPERLINK"><hp:parameters>'
        f'<hp:stringParam name="Command">{target};2;0;0</hp:stringParam>'
        f'<hp:stringParam name="Path">{target}</hp:stringParam>'
        "</hp:parameters></hp:fieldBegin>"
    )


@pytest.mark.parametrize(
    "begin",
    [
        (
            '<hp:fieldBegin id="1" type="CLICK_HERE"><hp:parameters>'
            '<hp:stringParam name="Direction">이름을 입력하세요</hp:stringParam>'
            "</hp:parameters></hp:fieldBegin>"
        ),
        (
            '<hp:fieldBegin id="1" type="FORMULA"><hp:parameters>'
            '<hp:stringParam name="Command">=SUM(ABOVE)</hp:stringParam>'
            "</hp:parameters></hp:fieldBegin>"
        ),
        hyperlink("mailto:someone@example.invalid"),
        hyperlink("https://example.invalid/page"),
        hyperlink("http://example.invalid/page"),
        hyperlink("bookmark_name"),
        hyperlink("www.daum.net|-"),
        hyperlink("http\\://example.invalid/page"),
    ],
)
def test_inert_hancom_fields_are_allowed(begin: str) -> None:
    reject_hwpx_active_content(field_package(begin))


@pytest.mark.parametrize(
    "begin",
    [
        '<hp:fieldBegin id="1" type="DDE"/>',
        '<hp:fieldBegin id="1"/>',
        hyperlink("file:///etc/passwd"),
        hyperlink("javascript:alert(1)"),
        hyperlink("C:\\Windows\\run.exe"),
        hyperlink("smb://host/share"),
        hyperlink("../../secret.pdf"),
        hyperlink("~/secret.pdf"),
        hyperlink("dir/../secret.pdf"),
        hyperlink("file%253A///etc/passwd"),
        hyperlink("file\\:///etc/passwd"),
        (
            '<hp:fieldBegin id="1" type="CLICK_HERE"><hp:parameters>'
            '<hp:stringParam name="Path">file:///etc/passwd</hp:stringParam>'
            "</hp:parameters></hp:fieldBegin>"
        ),
    ],
)
def test_other_fields_and_unsafe_links_are_rejected(begin: str) -> None:
    with pytest.raises(ConversionError, match="unsupported_active_content"):
        reject_hwpx_active_content(field_package(begin))
