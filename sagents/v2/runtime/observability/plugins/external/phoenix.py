"""Phoenix adapter for normalized trace queries; independent of HTTP routes."""

from __future__ import annotations

import json
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sagents.v2.runtime.observability.plugins._shared.query import request

from .evidence import ExternalEvidenceSink


class CostTotal(BaseModel):
    cost: float | None = None


class SpanCost(BaseModel):
    total: CostTotal


class SessionReference(BaseModel):
    session_id: str


class TraceReference(BaseModel):
    trace_id: str = Field(pattern="^[a-fA-F0-9]{32}$")
    num_spans: int
    error_count: int
    cost_summary: SpanCost | None = None
    session: SessionReference | None = None


class SpanRow(BaseModel):
    span_id: str
    name: str
    span_kind: str
    status_code: str
    parent_id: str | None = None
    start_time: str
    end_time: str | None = None
    latency_ms: float | None = None
    token_count_total: int | None = None
    token_count_prompt: int | None = None
    token_count_completion: int | None = None
    cumulative_tokens: float | None = None
    cost_summary: SpanCost | None = None
    trace: TraceReference


class RawContext(BaseModel):
    model_config = ConfigDict(extra="allow")
    span_id: str
    trace_id: str


class RawSpan(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    context: RawContext
    attributes: dict = Field(default_factory=dict)
    events: list[dict] = Field(default_factory=list)


class SpanEdge(BaseModel):
    node: SpanRow


class PageInfo(BaseModel):
    hasNextPage: bool
    endCursor: str | None = None


class SpanPage(BaseModel):
    edges: list[SpanEdge]
    pageInfo: PageInfo


FIELDS = """
span_id:spanId name span_kind:spanKind status_code:statusCode parent_id:parentId
start_time:startTime end_time:endTime latency_ms:latencyMs
token_count_total:tokenCountTotal token_count_prompt:tokenCountPrompt
token_count_completion:tokenCountCompletion cost_summary:costSummary {total {cost}}
cumulative_tokens:cumulativeTokenCountTotal
trace {trace_id:traceId num_spans:numSpans error_count:errorCount cost_summary:costSummary {total {cost}}
       session {session_id:sessionId}}
"""
PAGE = "pageInfo {hasNextPage endCursor} edges {node {" + FIELDS + "}}"


class PhoenixTraceQuery:
    def __init__(self, diagnostics: ExternalEvidenceSink):
        self.source = diagnostics

    async def _graphql(self, client, query, variables):
        content, _ = await request(
            self.source,
            client,
            "/graphql",
            [],
            method="POST",
            body={"query": query, "variables": variables},
        )
        result = json.loads(content)
        if result.get("errors"):
            # Never expose upstream errors or connection credentials to the browser.
            raise ValueError("Phoenix query failed")
        return result["data"]

    async def _project(self, client):
        payload = json.loads(
            await self.source._request(
                client, f"/v1/projects/{quote(self.source.project, safe='')}", []
            )
        )
        identifier = payload["data"]["id"]
        if not isinstance(identifier, str):
            raise ValueError("Invalid Phoenix project")
        return identifier

    def _filter(self, agent_id="", session_id=""):
        conditions = [
            f'attributes["deployment"]["environment"]["name"] == {json.dumps(self.source.environment)}'
        ]
        if agent_id:
            conditions.append(f'attributes["agent_id"] == {json.dumps(agent_id)}')
        if session_id:
            conditions.append(
                f'attributes["session"]["id"] == {json.dumps(session_id)}'
            )
        return " and ".join(conditions)

    async def summary(self, *, start, end, agent_id="", session_id="", client=None):
        if client is None:
            async with httpx.AsyncClient() as owned:
                return await self.summary(
                    start=start,
                    end=end,
                    agent_id=agent_id,
                    session_id=session_id,
                    client=owned,
                )
        base = self._filter(agent_id, session_id)
        roots = base + ' and name == "agent.run" and parent_span is None'
        variables = dict(
            id=await self._project(client),
            range={"start": start, "end": end},
            roots=roots,
            errors=roots + ' and status_code == "ERROR"',
            models=base + ' and span_kind == "LLM"',
        )
        query = """query($id:ID!,$range:TimeRange!,$roots:String!,$errors:String!,$models:String!) {
          node(id:$id) {... on Project {
            requests:traceCount(timeRange:$range,filterCondition:$roots)
            errors:traceCount(timeRange:$range,filterCondition:$errors)
            tokens:tokenCountTotal(timeRange:$range,filterCondition:$models)
            input_tokens:tokenCountPrompt(timeRange:$range,filterCondition:$models)
            output_tokens:tokenCountCompletion(timeRange:$range,filterCondition:$models)
            cost:costSummary(timeRange:$range,filterCondition:$models) {total {cost}}
          }} }"""
        data = (await self._graphql(client, query, variables))["node"]
        # Explicit numeric parsing rejects unexpected upstream response shapes.
        return dict(
            requests=int(data["requests"]),
            errors=int(data["errors"]),
            tokens=float(data["tokens"]),
            input_tokens=float(data["input_tokens"]),
            output_tokens=float(data["output_tokens"]),
            cost=float(data["cost"]["total"]["cost"])
            if data["cost"]["total"]["cost"] is not None
            else None,
        )

    async def spans(
        self,
        *,
        start=None,
        end=None,
        agent_id="",
        session_id="",
        kind="AGENT",
        status="",
        cursor=None,
        trace_id=None,
        client=None,
    ):
        if client is None:
            async with httpx.AsyncClient() as owned:
                return await self.spans(
                    start=start,
                    end=end,
                    agent_id=agent_id,
                    kind=kind,
                    status=status,
                    cursor=cursor,
                    trace_id=trace_id,
                    session_id=session_id,
                    client=owned,
                )
        variables = dict(id=await self._project(client), cursor=cursor)
        if trace_id:
            variables["trace"] = trace_id
            query = """query($id:ID!,$trace:ID!,$cursor:String) {
              node(id:$id) {... on Project {trace(traceId:$trace) {
              spans(first:100,after:$cursor) {PAGE}
              }}}}""".replace("PAGE", PAGE)
            trace = (await self._graphql(client, query, variables))["node"]["trace"]
            connection = (
                trace["spans"]
                if trace
                else {"edges": [], "pageInfo": {"hasNextPage": False}}
            )
        else:
            condition = self._filter(agent_id, session_id)
            condition += ' and name in ["agent.run", "model.request", "tool.call"]'
            if kind != "ALL":
                condition += f" and span_kind == {json.dumps(kind)}"
            if kind == "AGENT":
                condition += " and parent_span is None"
            if status:
                condition += f" and status_code == {json.dumps(status)}"
            variables.update(range={"start": start, "end": end}, condition=condition)
            query = """query($id:ID!,$range:TimeRange!,$condition:String!,$cursor:String) {
              node(id:$id) {... on Project {
              spans(first:50,after:$cursor,timeRange:$range,filterCondition:$condition,
                    sort:{col:startTime,dir:desc}) {PAGE}
              }}}""".replace("PAGE", PAGE)
            connection = (await self._graphql(client, query, variables))["node"][
                "spans"
            ]
        page = SpanPage.model_validate(connection)
        return {
            "items": [
                {
                    **e.node.model_dump(),
                    "session_id": e.node.trace.session.session_id
                    if e.node.trace.session
                    else None,
                }
                for e in page.edges
                if not e.node.name.startswith("sage.diagnostic.")
            ],
            "next_cursor": page.pageInfo.endCursor
            if page.pageInfo.hasNextPage
            else None,
        }

    async def span(self, span_id, *, client=None):
        if client is None:
            async with httpx.AsyncClient() as owned:
                return await self.span(span_id, client=owned)
        payload = json.loads(
            await self.source._request(
                client,
                f"/v1/projects/{quote(self.source.project, safe='')}/spans",
                [("span_id", span_id), ("limit", "1")],
            )
        )
        rows = payload["data"]
        if not isinstance(rows, list):
            raise ValueError("Invalid Phoenix span response")
        if not rows:
            return None
        span = RawSpan.model_validate(rows[0])
        if span.context.span_id != span_id:
            raise ValueError("Unexpected Phoenix span")
        return span.model_dump()
