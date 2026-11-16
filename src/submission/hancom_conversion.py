import os
import re
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from submission.conversion_contracts import ConversionError, ConversionErrorCode, ConversionResult
from submission.conversion_fonts import collect_fonts
from submission.conversion_process import run_process
from submission.document_contracts import DocumentSource, ToolDescriptor
from submission.docx_conversion import (
    PDF_OPTIONS,
    RENDER_OPTIONS,
    build_conversion_result,
    conversion_slot,
    read_preview,
)
from submission.formats import inspect_document
from submission.hancom_content import reject_hwpx_active_content
from submission.hancom_contracts import HancomConversionConfig
from submission.hancom_profile import check_deadline, copy_profile, validate_runtime
from submission.hwp_content import reject_hwp_active_content
from submission.input_contracts import DocumentInput


def render_hancom(
    source: DocumentInput,
    identity: DocumentSource,
    config: HancomConversionConfig,
    directory: Path,
    deadline: float,
) -> ConversionResult:
    validate_runtime(config.provision, config.soffice, deadline)
    profile = copy_profile(config.provision, directory, deadline)
    java_home = directory / "java-home"
    java_tmp = directory / "java-tmp"
    java_home.mkdir(mode=0o700)
    java_tmp.mkdir(mode=0o700)
    base = (
        "/usr/bin/env",
        "-i",
        "PATH=/usr/bin:/bin",
        "LANG=en_US.UTF-8",
        f"TMPDIR={java_tmp}",
        str(config.soffice.absolute()),
        *RENDER_OPTIONS,
        f"-env:UserInstallation={profile.as_uri()}",
        f"-env:UNO_JAVA_JFW_JREHOME={config.provision.java_home.as_uri()}",
        f"-env:UNO_JAVA_JFW_PARAMETER_1=-Duser.home={java_home}",
        f"-env:UNO_JAVA_JFW_PARAMETER_2=-Djava.io.tmpdir={java_tmp}",
    )
    version = (
        run_process((*base, "--version"), directory, deadline, config.terminate_grace_seconds)
        .decode("utf-8", errors="replace")
        .strip()
    )
    if re.fullmatch(r"LibreOffice [0-9]+(?:\.[0-9]+){1,4}(?: [0-9a-f]+)?", version) is None:
        raise ConversionError(ConversionErrorCode.RENDERER_UNAVAILABLE)
    input_path = directory / f"source.{identity.detected_format}"
    _ = input_path.write_bytes(source.content)
    output = directory / "output"
    output.mkdir(mode=0o700)
    _ = run_process(
        (*base, "--infilter=Hwp2002_File", *PDF_OPTIONS, "--outdir", str(output), str(input_path)),
        directory,
        deadline,
        config.terminate_grace_seconds,
    )
    content, pages, fonts = read_preview(output / "source.pdf", config)
    manifest = collect_fonts(fonts, deadline)
    check_deadline(deadline)
    renderer = ToolDescriptor(
        name="LibreOffice",
        version=version,
        options=(
            *RENDER_OPTIONS,
            *PDF_OPTIONS,
            "--infilter=Hwp2002_File",
            "isolated_user_profile",
            "macros_disabled",
            "active_content_disabled",
            "link_updates_never",
            "field_updates_disabled",
            "private_java_home",
            f"template_sha256={config.provision.template_sha256}",
            f"executable_sha256={config.provision.soffice.sha256}",
        ),
    )
    extension = ToolDescriptor(
        name="H2Orestart",
        version=config.provision.extension_version,
        options=(f"jar_sha256={config.provision.extension_sha256}",),
    )
    java = ToolDescriptor(
        name="Java runtime files",
        version="sha256-pinned",
        options=tuple(
            f"{item.path.relative_to(config.provision.java_home)}={item.sha256}"
            for item in config.provision.java_files
        ),
    )
    return build_conversion_result(
        identity, (content, pages), manifest, renderer, (renderer, extension, java)
    )


def convert_hancom(source: DocumentInput, config: HancomConversionConfig) -> ConversionResult:
    """Render a bounded preview using a trusted, preinstalled H2Orestart profile."""
    deadline = time.monotonic() + config.timeout_seconds
    if os.name != "posix":
        raise ConversionError(ConversionErrorCode.UNSUPPORTED_PLATFORM)
    with conversion_slot():
        identity = inspect_document(source, config.input_limits).source
        if identity.detected_format not in {"hwp", "hwpx"}:
            raise ConversionError(ConversionErrorCode.UNSUPPORTED_FORMAT)
        if identity.detected_format == "hwpx":
            reject_hwpx_active_content(source.content)
        else:
            reject_hwp_active_content(source.content, config.input_limits)
        try:
            config.work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            with TemporaryDirectory(prefix="hancom-", dir=config.work_root) as job:
                return render_hancom(source, identity, config, Path(job).resolve(), deadline)
        except OSError as error:
            raise ConversionError(ConversionErrorCode.IO_ERROR) from error
