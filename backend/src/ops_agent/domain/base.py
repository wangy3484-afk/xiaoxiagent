"""Common strict model behavior for business-domain contracts."""

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Reject undeclared fields and normalize surrounding string whitespace."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )
