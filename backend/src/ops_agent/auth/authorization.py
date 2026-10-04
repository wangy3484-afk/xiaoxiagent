"""Owner-scoped authorization policy for every user-visible resource type."""

from sqlalchemy.ext.asyncio import AsyncSession

from ops_agent.persistence.models import (
    EvidenceRecordRow,
    ExportFileRecord,
    OperationsBriefRecord,
    ReportJobRecord,
    ReportVersionRecord,
)
from ops_agent.persistence.repositories import (
    AuthorizationSubject,
    BriefRepository,
    EvidenceRepository,
    ExportFileRepository,
    ReportJobRepository,
    ReportVersionRepository,
    ResourceNotFound,
)


class ResourceAuthorizationPolicy:
    """Require ownership without revealing whether another user's row exists."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def require_brief(
        self, subject: AuthorizationSubject, resource_id: str
    ) -> OperationsBriefRecord:
        resource = await BriefRepository(self.session).get(subject, resource_id)
        if resource is None:
            raise ResourceNotFound("resource not found")
        return resource

    async def require_job(
        self, subject: AuthorizationSubject, resource_id: str
    ) -> ReportJobRecord:
        resource = await ReportJobRepository(self.session).get(subject, resource_id)
        if resource is None:
            raise ResourceNotFound("resource not found")
        return resource

    async def require_evidence(
        self, subject: AuthorizationSubject, resource_id: str
    ) -> EvidenceRecordRow:
        resource = await EvidenceRepository(self.session).get(subject, resource_id)
        if resource is None:
            raise ResourceNotFound("resource not found")
        return resource

    async def require_report(
        self, subject: AuthorizationSubject, resource_id: str
    ) -> ReportVersionRecord:
        resource = await ReportVersionRepository(self.session).get_version(subject, resource_id)
        if resource is None:
            raise ResourceNotFound("resource not found")
        return resource

    async def require_export(
        self, subject: AuthorizationSubject, resource_id: str
    ) -> ExportFileRecord:
        resource = await ExportFileRepository(self.session).get(subject, resource_id)
        if resource is None:
            raise ResourceNotFound("resource not found")
        return resource
