from pathlib import Path

from run_report_check_demo import DemoReportName, demo_context

from submission.document_contracts import CharacterRange
from submission.evidence_artifacts import inspect_artifact
from submission.evidence_contracts import ArtifactBinding, PageSelection, PdfArtifactInput
from submission.models import DocumentRole, PdfInput
from submission.page_rule_contracts import PageRuleInput


def context():
    return demo_context(DemoReportName.NORMAL)


def page_input(ctx):
    path = Path(__file__).resolve().parents[1] / "samples/pdf/normal.pdf"
    target = PdfArtifactInput(
        binding=ArtifactBinding(source=ctx.report.source, artifact=ctx.report.artifacts[0]),
        pdf=PdfInput(path.name, path.read_bytes(), DocumentRole.REPORT),
    )
    snapshot = inspect_artifact(target)
    selection = PageSelection(
        binding_sha256=snapshot.binding_sha256,
        basis="original_pdf",
        included_pages=tuple(range(1, snapshot.physical_page_count + 1)),
        excluded_pages=(),
        scope_confirmed=True,
    )
    return PageRuleInput(requirement_id="R5", target=target, selection=selection)


def response():
    return (
        Path(__file__).resolve().parents[1] / "samples/checks/normal-offline-response.json"
    ).read_text(encoding="utf-8")


def changed_rule(ctx, text, prefix=""):
    original = ctx.original_draft.requirements[4]
    citation = original.citations[0]
    block = next(block for block in ctx.guide.blocks if block.block_id == citation.block_id)
    raw = block.raw_text.replace(citation.quote, prefix + text)
    start = raw.index(text)
    parent = citation.model_copy(
        update={"quote": text, "char_range": CharacterRange(start=start, end=start + len(text))}
    )
    child = original.subconditions[0]
    scope = child.citations[0]
    scope_start = raw.index(scope.quote)
    child = child.model_copy(
        update={
            "citations": (
                scope.model_copy(
                    update={
                        "char_range": CharacterRange(
                            start=scope_start, end=scope_start + len(scope.quote)
                        )
                    }
                ),
            )
        }
    )
    original = original.model_copy(update={"citations": (parent,), "subconditions": (child,)})
    guide = ctx.guide.model_copy(
        update={
            "blocks": tuple(
                item.model_copy(update={"raw_text": raw})
                if item.block_id == block.block_id
                else item
                for item in ctx.guide.blocks
            )
        }
    )
    draft = ctx.original_draft.model_copy(
        update={"requirements": (*ctx.original_draft.requirements[:4], original)}
    )
    return ctx.model_copy(update={"guide": guide, "original_draft": draft})
