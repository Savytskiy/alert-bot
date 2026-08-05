from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "warning", "info"]


class AlertPayload(BaseModel):
    severity: Severity
    title: str = Field(min_length=1, max_length=256)
    message: str = Field(default="", max_length=4000)
    fingerprint: str = Field(min_length=1, max_length=256)
