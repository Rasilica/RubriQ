from hashlib import sha256

import pytest
from evidence_helpers import document, synthetic_context
from pydantic import ValidationError

from submission.document_contracts import ToolDescriptor
from submission.evidence_artifacts import inspect_artifact, make_synthetic_artifact
from submission.evidence_contracts import (
    ArtifactBinding,
    ArtifactPage,
    EvidenceError,
    EvidenceLimits,
    PdfArtifactInput,
)
from submission.models import DocumentRole, PdfInput


@pytest.mark.parametrize("number", [True, "1", 1.0])
def test_artifact_page_when_scalar_coercion_requested_rejects(number):
    # Given / When
    with pytest.raises(ValidationError):
        ArtifactPage(number=number, text="x")
    # Then: strict constructor cannot launder bool into integer.


@pytest.mark.parametrize(
    "change", ["version", "source_id", "artifact_id", "renderer", "font", "options", "pages"]
)
def test_binding_when_metadata_changes_invalidates_digest(text_pdf, change):
    # Given
    target = synthetic_context(text_pdf, ("text",)).target
    original = inspect_artifact(target).binding_sha256
    binding = target.binding
    if change == "version":
        binding = binding.model_copy(
            update={
                "source": binding.source.model_copy(update={"document_version_id": "new-version"})
            }
        )
    elif change == "source_id":
        binding = binding.model_copy(
            update={
                "source": binding.source.model_copy(update={"source_id": "new-source"}),
                "artifact": binding.artifact.model_copy(update={"parent_source_id": "new-source"}),
            }
        )
    elif change == "artifact_id":
        binding = binding.model_copy(
            update={"artifact": binding.artifact.model_copy(update={"artifact_id": "new-artifact"})}
        )
    elif change == "font":
        binding = binding.model_copy(
            update={
                "artifact": binding.artifact.model_copy(update={"font_manifest_hash": "0" * 64})
            }
        )
    elif change in {"renderer", "options"}:
        renderer = ToolDescriptor(
            name="fixture", version="1", options=("changed",) if change == "options" else ()
        )
        binding = binding.model_copy(
            update={"artifact": binding.artifact.model_copy(update={"renderer": renderer})}
        )
    else:
        target = target.model_copy(update={"pages": (ArtifactPage(number=1, text="other"),)})
    target = target.model_copy(update={"binding": binding})
    # When
    digest = inspect_artifact(target).binding_sha256
    # Then
    assert digest != original


@pytest.mark.parametrize(
    "change",
    [
        "parent",
        "blank_version",
        "blank_tool",
        "bool_page",
        "page_order",
        "empty",
        "status_text",
        "chars",
        "pages",
    ],
)
def test_synthetic_when_boundary_is_invalid_rejects(text_pdf, change):
    # Given
    target = synthetic_context(text_pdf, ("text",)).target
    limits = EvidenceLimits()
    if change == "parent":
        target = target.model_copy(
            update={
                "binding": target.binding.model_copy(
                    update={
                        "artifact": target.binding.artifact.model_copy(
                            update={"parent_source_id": "wrong"}
                        )
                    }
                )
            }
        )
    elif change == "blank_version":
        target = target.model_copy(
            update={
                "binding": target.binding.model_copy(
                    update={
                        "source": target.binding.source.model_copy(
                            update={"document_version_id": " "}
                        )
                    }
                )
            }
        )
    elif change == "blank_tool":
        target = target.model_copy(
            update={
                "binding": target.binding.model_copy(
                    update={
                        "artifact": target.binding.artifact.model_copy(
                            update={"renderer": ToolDescriptor(name=" ", version="1")}
                        )
                    }
                )
            }
        )
    elif change == "bool_page":
        target = target.model_copy(
            update={"pages": (target.pages[0].model_copy(update={"number": True}),)}
        )
    elif change == "page_order":
        target = target.model_copy(update={"pages": (ArtifactPage(number=2, text="x"),)})
    elif change == "empty":
        target = target.model_copy(update={"pages": ()})
    elif change == "status_text":
        target = target.model_copy(
            update={"pages": (ArtifactPage(number=1, text="x", status="text_unavailable"),)}
        )
    elif change == "chars":
        limits = EvidenceLimits(max_characters=1)
    else:
        target = target.model_copy(
            update={"pages": (ArtifactPage(number=1, text="a"), ArtifactPage(number=2, text="b"))}
        )
        limits = EvidenceLimits(max_pages=1)
    # When
    with pytest.raises(EvidenceError):
        inspect_artifact(target, limits=limits)
    # Then: no snapshot was emitted.


@pytest.mark.parametrize(
    "change", ["bytes", "origin", "role", "size", "invalid_pdf", "bytes_limit", "pages_limit"]
)
def test_actual_pdf_when_binding_or_limits_invalid_rejects(text_pdf, change):
    # Given
    source = document(text_pdf)
    binding = ArtifactBinding(source=source.source, artifact=source.artifacts[0])
    pdf = PdfInput("source.pdf", text_pdf, DocumentRole.REPORT)
    target = PdfArtifactInput(binding=binding, pdf=pdf)
    limits = EvidenceLimits()
    if change == "bytes":
        target = target.model_copy(
            update={"pdf": PdfInput("source.pdf", text_pdf + b"changed", DocumentRole.REPORT)}
        )
    elif change == "origin":
        target = target.model_copy(update={"origin": "synthetic"})
    elif change == "role":
        target = target.model_copy(
            update={"pdf": PdfInput("source.pdf", text_pdf, DocumentRole.GUIDE)}
        )
    elif change == "size":
        target = target.model_copy(
            update={
                "binding": binding.model_copy(
                    update={"source": binding.source.model_copy(update={"byte_size": 1})}
                )
            }
        )
    elif change == "invalid_pdf":
        content = b"private invalid pdf"
        digest = sha256(content).hexdigest()
        target = PdfArtifactInput(
            binding=ArtifactBinding(
                source=source.source.model_copy(
                    update={"content_sha256": digest, "byte_size": len(content)}
                ),
                artifact=source.artifacts[0].model_copy(update={"artifact_sha256": digest}),
            ),
            pdf=PdfInput("source.pdf", content, DocumentRole.REPORT),
        )
    elif change == "bytes_limit":
        limits = EvidenceLimits(max_bytes=1)
    else:
        limits = EvidenceLimits(max_pages=1)
    # When
    with pytest.raises(EvidenceError) as error:
        inspect_artifact(target, limits=limits)
    # Then
    assert "private" not in str(error.value)
    if change in {"bytes_limit", "pages_limit"}:
        assert error.value.code == "input_limit"


@pytest.mark.parametrize("location", ["target", "page", "source", "artifact"])
def test_inspection_when_model_copy_hides_unknown_field_rejects(text_pdf, location):
    # Given
    target = synthetic_context(text_pdf, ("x",)).target
    extra = {"unknown_private_field": "private-input"}
    if location == "target":
        target = target.model_copy(update=extra)
    elif location == "page":
        target = target.model_copy(update={"pages": (target.pages[0].model_copy(update=extra),)})
    else:
        child = getattr(target.binding, location).model_copy(update=extra)
        target = target.model_copy(
            update={"binding": target.binding.model_copy(update={location: child})}
        )
    # When
    with pytest.raises(EvidenceError) as error:
        inspect_artifact(target)
    # Then
    assert str(error.value) == "invalid_input"


def test_synthetic_factory_when_nested_extra_exists_preserves_rejection(text_pdf):
    # Given
    target = synthetic_context(text_pdf, ("x",)).target
    binding = target.binding.model_copy(
        update={"source": target.binding.source.model_copy(update={"private_extra": "private"})}
    )
    # When / Then
    with pytest.raises(EvidenceError):
        make_synthetic_artifact(binding, target.pages)


@pytest.mark.parametrize("change", ["binding", "renderer"])
def test_inspection_when_nested_shape_is_forged_returns_typed_error(text_pdf, change):
    # Given
    target = synthetic_context(text_pdf, ("x",)).target
    if change == "binding":
        target = target.model_copy(update={"binding": None})
    else:
        target = target.model_copy(
            update={
                "binding": target.binding.model_copy(
                    update={
                        "artifact": target.binding.artifact.model_copy(
                            update={"renderer": "sentinel-private"}
                        )
                    }
                )
            }
        )
    # When
    with pytest.raises(EvidenceError) as error:
        inspect_artifact(target)
    # Then
    assert str(error.value) == "invalid_input"
