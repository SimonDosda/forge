"""Notion skill — search, read, and write pages and database rows.

Auth: each golem configures its own integration token via the forge UI
(Skills tab). Create an integration at https://www.notion.so/my-integrations
and share each target page/database with that integration so it can see them.
NOTION_TOKEN in the environment is used as a fallback if no per-golem key is
configured.
"""
import os
from typing import Any

import requests

from golem.core import ToolSpec


_API_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"


class NotionSkill:
    name = "notion"
    config_schema = [
        {
            "key": "api_key",
            "label": "Notion API key",
            "secret": True,
            "description": (
                "Internal integration token from notion.so/my-integrations. "
                "Share each page or database you want the golem to access with this integration."
            ),
        },
    ]

    def __init__(
        self,
        api_key: str = "",
        http: requests.Session | None = None,
        timeout_s: float = 15.0,
    ):
        self._api_key = api_key
        self._http = http or requests.Session()
        self._timeout = timeout_s

    @property
    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="notion_search",
                description=(
                    "Search the workspace for pages and databases the integration "
                    "has access to. Returns {id, type, title, url, parent} items. "
                    "Use the returned id with the other notion_* tools."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Free-text title query. Empty matches everything shared with the integration.",
                        },
                        "filter_type": {
                            "type": "string",
                            "enum": ["page", "database"],
                            "description": "Optional: restrict to pages or databases only.",
                        },
                    },
                },
            ),
            ToolSpec(
                name="notion_get_page",
                description=(
                    "Retrieve a page's properties and rendered text content. "
                    "Returns {id, title, url, properties, text} where text concatenates "
                    "simple block content (paragraphs, headings, lists, to-dos, quotes)."
                ),
                input_schema={
                    "type": "object",
                    "properties": {"page_id": {"type": "string"}},
                    "required": ["page_id"],
                },
            ),
            ToolSpec(
                name="notion_create_page",
                description=(
                    "Create a new page. Parent is either a page (sub-page) or a "
                    "database (new row). For a database parent, `properties` must "
                    "match the schema — call notion_get_database first to learn it. "
                    "For a page parent, only `title` is needed. `content` is an "
                    "optional list of strings (each becomes a paragraph block) or "
                    "full Notion block dicts."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "parent_id": {"type": "string", "description": "Page id or database id."},
                        "parent_type": {
                            "type": "string",
                            "enum": ["page", "database"],
                        },
                        "title": {
                            "type": "string",
                            "description": "Page title. Folded into the title property if not already provided.",
                        },
                        "properties": {
                            "type": "object",
                            "description": (
                                "Full Notion property schema for database rows, e.g. "
                                "{\"Status\": {\"select\": {\"name\": \"Done\"}}}."
                            ),
                        },
                        "content": {
                            "type": "array",
                            "description": "List of paragraph strings, or full Notion block objects.",
                        },
                    },
                    "required": ["parent_id", "parent_type"],
                },
            ),
            ToolSpec(
                name="notion_update_page",
                description=(
                    "Update properties on an existing page (typically a database row). "
                    "Pass the Notion property schema for each field to set. Set "
                    "`archived` true/false to archive or restore."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "page_id": {"type": "string"},
                        "properties": {"type": "object"},
                        "archived": {"type": "boolean"},
                    },
                    "required": ["page_id"],
                },
            ),
            ToolSpec(
                name="notion_append_blocks",
                description=(
                    "Append blocks to a page or block. `content` items can be plain "
                    "strings (each becomes a paragraph) or full Notion block dicts."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "block_id": {
                            "type": "string",
                            "description": "Target page id or block id.",
                        },
                        "content": {"type": "array"},
                    },
                    "required": ["block_id", "content"],
                },
            ),
            ToolSpec(
                name="notion_query_database",
                description=(
                    "Query rows in a database. Returns a list of pages with id, "
                    "title, url, and full Notion properties. Call notion_get_database "
                    "first to learn property names and types for filters/sorts."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "database_id": {"type": "string"},
                        "filter": {"type": "object", "description": "Notion filter object."},
                        "sorts": {"type": "array", "description": "List of Notion sort objects."},
                        "page_size": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 25,
                        },
                    },
                    "required": ["database_id"],
                },
            ),
            ToolSpec(
                name="notion_get_database",
                description=(
                    "Retrieve a database's title and property schema (column names "
                    "and types). Use before creating rows or building filters."
                ),
                input_schema={
                    "type": "object",
                    "properties": {"database_id": {"type": "string"}},
                    "required": ["database_id"],
                },
            ),
        ]

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "notion_search":
            return self._search(arguments.get("query", ""), arguments.get("filter_type"))
        if name == "notion_get_page":
            return self._get_page(arguments["page_id"])
        if name == "notion_create_page":
            return self._create_page(
                parent_id=arguments["parent_id"],
                parent_type=arguments["parent_type"],
                title=arguments.get("title"),
                properties=arguments.get("properties"),
                content=arguments.get("content"),
            )
        if name == "notion_update_page":
            return self._update_page(
                arguments["page_id"],
                arguments.get("properties"),
                arguments.get("archived"),
            )
        if name == "notion_append_blocks":
            return self._append_blocks(arguments["block_id"], arguments["content"])
        if name == "notion_query_database":
            return self._query_database(
                arguments["database_id"],
                arguments.get("filter"),
                arguments.get("sorts"),
                int(arguments.get("page_size", 25)),
            )
        if name == "notion_get_database":
            return self._get_database(arguments["database_id"])
        raise ValueError(f"unknown tool: {name}")

    # ---- HTTP ----

    def _headers(self) -> dict[str, str]:
        token = self._api_key or os.getenv("NOTION_TOKEN") or os.getenv("NOTION_API_KEY")
        if not token:
            raise RuntimeError(
                "Notion API key not set. Open the golem's Skills tab in the "
                "forge, enable Notion, and paste an integration token from "
                "https://www.notion.so/my-integrations."
            )
        return {
            "Authorization": f"Bearer {token}",
            "Notion-Version": _NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        r = self._http.request(
            method,
            f"{_API_BASE}{path}",
            headers=self._headers(),
            timeout=self._timeout,
            **kwargs,
        )
        if not r.ok:
            try:
                detail = r.json()
                msg = detail.get("message") or detail
            except Exception:
                msg = r.text
            raise RuntimeError(f"Notion API {r.status_code}: {msg}")
        return r.json() if r.text else {}

    # ---- Operations ----

    def _search(self, query: str, filter_type: str | None) -> list[dict[str, Any]]:
        body: dict[str, Any] = {}
        if query:
            body["query"] = query
        if filter_type in ("page", "database"):
            body["filter"] = {"property": "object", "value": filter_type}
        data = self._request("POST", "/search", json=body)
        return [_summarize(obj) for obj in data.get("results", [])]

    def _get_page(self, page_id: str) -> dict[str, Any]:
        page = self._request("GET", f"/pages/{page_id}")
        blocks = self._request("GET", f"/blocks/{page_id}/children?page_size=100")
        lines = [_block_text(b) for b in blocks.get("results", [])]
        text = "\n".join(line for line in lines if line)
        return {
            "id": page.get("id"),
            "title": _extract_title(page.get("properties") or {}),
            "url": page.get("url"),
            "properties": page.get("properties"),
            "text": text,
        }

    def _create_page(
        self,
        *,
        parent_id: str,
        parent_type: str,
        title: str | None,
        properties: dict[str, Any] | None,
        content: list[Any] | None,
    ) -> dict[str, Any]:
        props = dict(properties or {})
        if parent_type == "page":
            parent = {"page_id": parent_id}
            if title:
                props["title"] = {"title": [{"text": {"content": title}}]}
        elif parent_type == "database":
            parent = {"database_id": parent_id}
            if title and not _has_title_prop(props):
                # Common default; if the title column has a different name, the
                # caller should put it in `properties` directly.
                props["Name"] = {"title": [{"text": {"content": title}}]}
        else:
            raise ValueError(f"invalid parent_type: {parent_type!r}")

        body: dict[str, Any] = {"parent": parent, "properties": props}
        if content:
            body["children"] = _normalize_blocks(content)
        data = self._request("POST", "/pages", json=body)
        return {"id": data.get("id"), "url": data.get("url")}

    def _update_page(
        self,
        page_id: str,
        properties: dict[str, Any] | None,
        archived: bool | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if properties is not None:
            body["properties"] = properties
        if archived is not None:
            body["archived"] = archived
        if not body:
            raise ValueError("nothing to update — provide properties or archived")
        data = self._request("PATCH", f"/pages/{page_id}", json=body)
        return {"id": data.get("id"), "url": data.get("url")}

    def _append_blocks(self, block_id: str, content: list[Any]) -> dict[str, Any]:
        data = self._request(
            "PATCH",
            f"/blocks/{block_id}/children",
            json={"children": _normalize_blocks(content)},
        )
        return {"appended": len(data.get("results", []))}

    def _query_database(
        self,
        database_id: str,
        filter_: dict[str, Any] | None,
        sorts: list | None,
        page_size: int,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"page_size": max(1, min(100, page_size))}
        if filter_:
            body["filter"] = filter_
        if sorts:
            body["sorts"] = sorts
        data = self._request("POST", f"/databases/{database_id}/query", json=body)
        return [
            {
                "id": row.get("id"),
                "url": row.get("url"),
                "title": _extract_title(row.get("properties") or {}),
                "properties": row.get("properties"),
            }
            for row in data.get("results", [])
        ]

    def _get_database(self, database_id: str) -> dict[str, Any]:
        data = self._request("GET", f"/databases/{database_id}")
        return {
            "id": data.get("id"),
            "title": _plain_rich_text(data.get("title") or []),
            "url": data.get("url"),
            "properties": {
                name: {"type": prop.get("type"), "id": prop.get("id")}
                for name, prop in (data.get("properties") or {}).items()
            },
        }


# ---- Helpers ----

def _summarize(obj: dict[str, Any]) -> dict[str, Any]:
    kind = obj.get("object", "")
    title = ""
    if kind == "page":
        title = _extract_title(obj.get("properties") or {})
    elif kind == "database":
        title = _plain_rich_text(obj.get("title") or [])
    return {
        "id": obj.get("id"),
        "type": kind,
        "title": title,
        "url": obj.get("url"),
        "parent": obj.get("parent") or {},
    }


def _extract_title(properties: dict[str, Any]) -> str:
    for value in properties.values():
        if isinstance(value, dict) and value.get("type") == "title":
            return _plain_rich_text(value.get("title") or [])
    return ""


def _plain_rich_text(items: list[dict[str, Any]]) -> str:
    return "".join((i.get("plain_text") or "") for i in items)


def _has_title_prop(props: dict[str, Any]) -> bool:
    return any(
        isinstance(v, dict) and ("title" in v or v.get("type") == "title")
        for v in props.values()
    )


def _normalize_blocks(items: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            out.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": item}}],
                },
            })
        elif isinstance(item, dict):
            out.append(item)
        else:
            raise ValueError(f"unsupported block: {item!r}")
    return out


def _block_text(block: dict[str, Any]) -> str:
    btype = block.get("type", "")
    body = block.get(btype) or {}
    text = _plain_rich_text(body.get("rich_text") or [])
    prefix = {
        "bulleted_list_item": "- ",
        "numbered_list_item": "1. ",
        "to_do": "[x] " if body.get("checked") else "[ ] ",
        "heading_1": "# ",
        "heading_2": "## ",
        "heading_3": "### ",
        "quote": "> ",
    }.get(btype, "")
    return prefix + text if text else ""
