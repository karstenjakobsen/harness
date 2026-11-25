"""JSON request and response schemas."""

from typing import Annotated

from pydantic import Field

PositiveInteger = Annotated[int, Field(strict=True, gt=0, lt=2**63)]
