from __future__ import annotations

from backend.shared.errors import (
    ValidationError,
)


class CampaignError(ValidationError):
    default_code = "connectivity.campaign"


class GroupsArtifactError(ValidationError):
    default_code = "connectivity.groups.artifact"


class GroupsProvenanceError(GroupsArtifactError):
    default_code = "connectivity.groups.provenance"


__all__ = [
    "CampaignError",
    "GroupsArtifactError",
    "GroupsProvenanceError",
]
