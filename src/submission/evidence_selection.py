from typing import Annotated

from pydantic import Field

from submission.models import FrozenModel


class EvidenceSelection(FrozenModel):
    block_id: Annotated[str, Field(min_length=1, max_length=2000)]
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(gt=0)]
