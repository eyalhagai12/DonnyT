"""Confluence Cloud REST client.

Pages are read and written through the v2 API; search uses v1 CQL because v2
has no search endpoint. Bodies travel as ``storage`` XHTML and are converted to
Markdown on the way out so the model reads a template the way a person does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._html2md import markdown_to_storage, storage_to_markdown
from ._http import JSONClient
from .config import Config, load_config


@dataclass
class Page:
    id: str
    title: str
    space_id: str
    version: int
    storage: str
    url: str

    @property
    def markdown(self) -> str:
        return storage_to_markdown(self.storage)

    def summary(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "version": self.version, "url": self.url}


class ConfluenceClient:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.site = self.config.atlassian_site
        email, token = self.config.atlassian_auth
        self.http = JSONClient(
            f"{self.site}/wiki",
            headers=JSONClient.basic_auth(email, token),
        )

    # -- reads -------------------------------------------------------------
    def get_page(self, page_id: str) -> Page:
        data = self.http.get(f"/api/v2/pages/{page_id}", params={"body-format": "storage"})
        return self._to_page(data)

    def search(self, cql: str, limit: int = 25) -> list[dict[str, Any]]:
        """Run a raw CQL query, returning content stubs (id, title, type, _links)."""
        data = self.http.get("/rest/api/content/search", params={"cql": cql, "limit": limit})
        results = []
        for item in data.get("results", []):
            webui = (item.get("_links") or {}).get("webui", "")
            results.append(
                {
                    "id": str(item.get("id", "")),
                    "title": item.get("title", ""),
                    "type": item.get("type", ""),
                    "url": f"{self.site}/wiki{webui}" if webui else "",
                }
            )
        return results

    def find_page(self, title: str, space_key: str | None = None) -> Page | None:
        """Find a page by exact title, scoped to a space when one is configured."""
        space = space_key if space_key is not None else self.config.confluence_space
        cql = 'type=page AND title="{}"'.format(title.replace('"', '\\"'))
        if space:
            cql += f' AND space="{space}"'
        results = self.search(cql, limit=1)
        return self.get_page(results[0]["id"]) if results else None

    def get_template(self) -> Page:
        """The configured MR template page -- by id when set, otherwise by title."""
        page_id = self.config.mr_template_page_id
        if page_id:
            return self.get_page(page_id)

        title = self.config.mr_template_title
        page = self.find_page(title)
        if page is None:
            raise LookupError(
                f"No Confluence page titled {title!r} in space "
                f"{self.config.confluence_space or '(any)'!r}.\n"
                "Set confluence.mr_template_page_id in config.toml to pin it by id."
            )
        return page

    def child_pages(self, page_id: str, limit: int = 100) -> list[dict[str, Any]]:
        data = self.http.get(f"/api/v2/pages/{page_id}/children", params={"limit": limit})
        return [
            {"id": str(c.get("id", "")), "title": c.get("title", "")}
            for c in data.get("results", [])
        ]

    # -- writes ------------------------------------------------------------
    def create_page(
        self,
        title: str,
        markdown: str,
        space_id: str | None = None,
        parent_id: str | None = None,
    ) -> Page:
        payload: dict[str, Any] = {
            "spaceId": space_id or self.space_id(),
            "status": "current",
            "title": title,
            "body": {"representation": "storage", "value": markdown_to_storage(markdown)},
        }
        if parent_id:
            payload["parentId"] = str(parent_id)
        return self._to_page(self.http.post("/api/v2/pages", json_body=payload))

    def update_page(self, page_id: str, title: str, markdown: str) -> Page:
        current = self.get_page(page_id)
        payload = {
            "id": str(page_id),
            "status": "current",
            "title": title,
            "body": {"representation": "storage", "value": markdown_to_storage(markdown)},
            "version": {"number": current.version + 1},
        }
        return self._to_page(self.http.put(f"/api/v2/pages/{page_id}", json_body=payload))

    # -- internals ---------------------------------------------------------
    def space_id(self, key: str | None = None) -> str:
        space_key = key or self.config.confluence_space
        if not space_key:
            raise ValueError("confluence.space is not set in config.toml")
        data = self.http.get("/api/v2/spaces", params={"keys": space_key, "limit": 1})
        results = data.get("results", [])
        if not results:
            raise LookupError(f"No Confluence space with key {space_key!r}")
        return str(results[0]["id"])

    def _to_page(self, data: dict[str, Any]) -> Page:
        body = (data.get("body") or {}).get("storage") or {}
        webui = (data.get("_links") or {}).get("webui", "")
        return Page(
            id=str(data.get("id", "")),
            title=data.get("title", ""),
            space_id=str(data.get("spaceId", "")),
            version=int((data.get("version") or {}).get("number", 0)),
            storage=body.get("value", ""),
            url=f"{self.site}/wiki{webui}" if webui else "",
        )
