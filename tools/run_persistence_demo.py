# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
# Run from API: PYTHONPATH=src .venv/bin/python -m tools.run_persistence_demo DB ACTION
import sys
from enum import StrEnum
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from platform import python_version
from typing import Final, Literal, assert_never

from submission.document_contracts import DocumentSource, Sha256, ToolDescriptor
from submission.evidence_contracts import ArtifactBinding, EvidenceModel
from submission.page_rule_contracts import SubmissionCheckContext, SubmissionCheckResult
from submission.persistence import PersistenceStore
from submission.persistence_contracts import (
    ArtifactPayload,
    ExecutionSettings,
    OriginalPayload,
    PersistenceError,
    PersistenceRequest,
    RunSummary,
    StoredRun,
)
from submission.report_check_validation import criteria_fingerprint
from submission.review_contracts import CriteriaVersion
from tools.run_submission_check_demo import (
    DemoCase,
    authored_response,
    check_context,
    page_input,
    report_input,
)


class DemoAction(StrEnum):
    NORMAL = "normal"
    MISSING = "missing"
    OVER_LIMIT = "over-limit"
    INSPECT = "inspect"
    RETRY = "retry"
    RETRY_FAILURE = "retry-failure"


class OriginalReceipt(EvidenceModel):
    source: DocumentSource
    byte_sha256: Sha256
    byte_size: int


class ArtifactReceipt(EvidenceModel):
    binding: ArtifactBinding
    byte_sha256: Sha256
    byte_size: int


class DemoRun(RunSummary):
    schema_version: Literal["1"] = "1"
    durable: Literal[True] = True
    criteria: CriteriaVersion
    criteria_sha256: Sha256
    settings: ExecutionSettings
    originals: tuple[OriginalReceipt, ...]
    artifacts: tuple[ArtifactReceipt, ...]
    result: SubmissionCheckResult | None
    result_sha256: Sha256 | None
    failure_code: str | None


class DemoReceipt(EvidenceModel):
    action: DemoAction
    project_id: str
    runs: tuple[RunSummary, ...]
    selected: DemoRun | None
    latest_success: DemoRun | None


USAGE: Final = (
    "Usage: PYTHONPATH=src .venv/bin/python -m tools.run_persistence_demo "
    "DB {normal|missing|over-limit|inspect|retry|retry-failure} [PROJECT_ID]\n"
)


def demo_request(case: DemoCase) -> PersistenceRequest:
    report = report_input(case)
    context = check_context(case, report)
    guide_bytes = (Path(__file__).resolve().parents[1] / "samples/pdf/guide.pdf").read_bytes()
    originals = (
        OriginalPayload(source=context.guide.source, content=guide_bytes),
        OriginalPayload(source=context.report.source, content=report.content),
    )
    artifacts = tuple(
        ArtifactPayload(
            binding=ArtifactBinding(source=original.source, artifact=artifact),
            content=original.content,
        )
        for original, document in zip(originals, (context.guide, context.report), strict=True)
        for artifact in document.artifacts
    )
    return PersistenceRequest(
        context=SubmissionCheckContext(
            report_check=context, page_checks=(page_input(case, context, report),)
        ),
        originals=originals,
        artifacts=artifacts,
        response_json=authored_response(case, context),
        settings=ExecutionSettings(
            toolchain=(
                ToolDescriptor(name="python", version=python_version()),
                ToolDescriptor(name="pydantic", version=version("pydantic")),
                ToolDescriptor(name="pypdf", version=version("pypdf"), options=("strict=true",)),
                ToolDescriptor(name="offline-report-check", version="1"),
                ToolDescriptor(name="page-rule-grammar", version="pdf-all-upper-v1"),
            )
        ),
    )


def run_receipt(run: StoredRun) -> DemoRun:
    result_hash = (
        sha256(run.result.model_dump_json(exclude_computed_fields=True).encode("utf-8")).hexdigest()
        if run.result is not None
        else None
    )
    return DemoRun(
        run_id=run.run_id,
        project_id=run.project_id,
        sequence=run.sequence,
        created_at=run.created_at,
        status=run.status,
        predecessor_run_id=run.predecessor_run_id,
        elapsed_ms=run.elapsed_ms,
        criteria=run.request.context.report_check.criteria,
        criteria_sha256=criteria_fingerprint(run.request.context.report_check),
        settings=run.request.settings,
        originals=tuple(
            OriginalReceipt(
                source=value.source,
                byte_sha256=sha256(value.content).hexdigest(),
                byte_size=len(value.content),
            )
            for value in run.request.originals
        ),
        artifacts=tuple(
            ArtifactReceipt(
                binding=value.binding,
                byte_sha256=sha256(value.content).hexdigest(),
                byte_size=len(value.content),
            )
            for value in run.request.artifacts
        ),
        result=run.result,
        result_sha256=result_hash,
        failure_code=run.failure_code.value if run.failure_code is not None else None,
    )


def perform(store: PersistenceStore, action: DemoAction, project_id: str) -> StoredRun | None:
    match action:
        case DemoAction.NORMAL:
            return store.execute(project_id, demo_request(DemoCase.NORMAL))
        case DemoAction.MISSING:
            return store.execute(project_id, demo_request(DemoCase.MISSING))
        case DemoAction.OVER_LIMIT:
            return store.execute(project_id, demo_request(DemoCase.OVER_LIMIT))
        case DemoAction.RETRY | DemoAction.RETRY_FAILURE:
            previous = store.latest_success(project_id)
            if previous is None:
                return None
            match action:
                case DemoAction.RETRY:
                    request = previous.request
                case DemoAction.RETRY_FAILURE:
                    request = previous.request.model_copy(
                        update={"response_json": "invalid-offline-response"}
                    )
                case _:
                    assert_never(action)
            return store.execute(project_id, request)
        case DemoAction.INSPECT:
            runs = store.list_runs(project_id)
            return store.get_run(runs[-1].run_id) if runs else None
        case _:
            assert_never(action)


def main() -> int:
    arguments = sys.argv[1:]
    if len(arguments) not in {2, 3}:
        _ = sys.stderr.write(USAGE)
        return 2
    try:
        action = DemoAction(arguments[1])
    except ValueError:
        _ = sys.stderr.write(USAGE)
        return 2
    project_id = next(iter(arguments[2:]), "storage-demo")
    if (
        action in {DemoAction.INSPECT, DemoAction.RETRY, DemoAction.RETRY_FAILURE}
        and not Path(arguments[0]).is_file()
    ):
        _ = sys.stderr.write("not_found\n")
        return 1
    try:
        with PersistenceStore(Path(arguments[0])) as store:
            selected = perform(store, action, project_id)
            latest = store.latest_success(project_id)
            output = DemoReceipt(
                action=action,
                project_id=project_id,
                runs=store.list_runs(project_id),
                selected=run_receipt(selected) if selected else None,
                latest_success=run_receipt(latest) if latest else None,
            )
            _ = sys.stdout.write(output.model_dump_json(exclude_computed_fields=True) + "\n")
    except PersistenceError as error:
        _ = sys.stderr.write(error.code.value + "\n")
        return 1
    match action:
        case DemoAction.INSPECT:
            return 0
        case (
            DemoAction.NORMAL
            | DemoAction.MISSING
            | DemoAction.OVER_LIMIT
            | DemoAction.RETRY
            | DemoAction.RETRY_FAILURE
        ):
            return 0 if selected is not None and selected.result is not None else 1
        case _:
            assert_never(action)


if __name__ == "__main__":
    sys.exit(main())
