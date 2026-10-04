"""Supplier-neutral async contracts used by the operations workflow."""

from datetime import date, datetime
from typing import Any, Literal, Protocol, Self, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class ContractModel(BaseModel):
    """Strict immutable values at every external-service boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelMessage(ContractModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class ModelRequest(ContractModel):
    purpose: str = Field(min_length=1, max_length=100)
    messages: tuple[ModelMessage, ...] = Field(min_length=1)
    max_output_tokens: int = Field(default=4_000, ge=1, le=250_000)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


class ModelUsage(ContractModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class StructuredModelResult[OutputT: BaseModel](ContractModel):
    output: OutputT
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    request_id: str | None = None
    usage: ModelUsage


class SearchRequest(ContractModel):
    query: str = Field(min_length=1, max_length=1_000)
    max_results: int = Field(default=8, ge=1, le=20)
    offset: int = Field(default=0, ge=0, le=19)
    language: str = Field(default="zh-CN", min_length=2, max_length=20)

    @model_validator(mode="after")
    def validate_bounded_result_window(self) -> Self:
        if self.offset + self.max_results > 20:
            raise ValueError("offset plus max_results cannot exceed 20")
        return self


class SearchResult(ContractModel):
    title: str = Field(min_length=1, max_length=500)
    url: HttpUrl
    snippet: str = Field(default="", max_length=2_000)
    rank: int = Field(ge=1)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(ContractModel):
    query: str
    results: tuple[SearchResult, ...]
    provider: str = Field(min_length=1)
    request_id: str | None = None


class FetchedPage(ContractModel):
    requested_url: HttpUrl
    final_url: HttpUrl
    status_code: int = Field(ge=100, le=599)
    content_type: str = Field(min_length=1, max_length=200)
    body: bytes
    fetched_at: datetime
    redirect_chain: tuple[HttpUrl, ...] = ()
    response_headers: dict[str, str] = Field(default_factory=dict)


class ExtractedContent(ContractModel):
    canonical_url: HttpUrl
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    publication_date: date | None = None
    publisher: str | None = Field(default=None, max_length=300)
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class ModelProvider(Protocol):
    async def generate_structured[OutputT: BaseModel](
        self,
        request: ModelRequest,
        output_schema: type[OutputT],
    ) -> StructuredModelResult[OutputT]: ...


@runtime_checkable
class SearchProvider(Protocol):
    async def search(self, request: SearchRequest) -> SearchResponse: ...


@runtime_checkable
class PageFetcher(Protocol):
    async def fetch(self, url: HttpUrl) -> FetchedPage: ...


@runtime_checkable
class ContentExtractor(Protocol):
    async def extract(self, page: FetchedPage) -> ExtractedContent: ...
