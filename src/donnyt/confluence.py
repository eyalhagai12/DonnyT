"""Confluence REST client, for Cloud and Data Center.

The two differ in where pages live:

* **Cloud** reads and writes pages through the v2 API (``/api/v2/pages``).
* **Data Center** has no v2 API; pages go through v1 ``/rest/api/content``.

Search is v1 CQL on both, since v2 has no search endpoint. ``atlassian.deployment``
picks the flavour. Bodies travel as ``storage`` XHTML and are converted to
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
        self.base = self.config.confluence_url
        self.cloud = self.config.atlassian_deployment == "cloud"
        self.http = JSONClient(self.base, headers=self.config.atlassian_headers("confluence"))

    # -- reads -------------------------------------------------------------
    def get_page(self, page_id: str) -> Page:
        if self.cloud:
            data = self.http.get(f"/api/v2/pages/{page_id}", params={"body-format": "storage"})
        else:
            data = self.http.get(
                f"/rest/api/content/{page_id}", params={"expand": "body.storage,version,space"}
            )
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
                    "url": f"{self.base}{webui}" if webui else "",
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
        path = (
            f"/api/v2/pages/{page_id}/children"
            if self.cloud
            else f"/rest/api/content/{page_id}/child/page"
        )
        data = self.http.get(path, params={"limit": limit})
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
        storage = markdown_to_storage(markdown)
        payload: dict[str, Any]
        if self.cloud:
            payload = {
                "spaceId": space_id or self.space_id(),
                "status": "current",
                "title": title,
                "body": {"representation": "storage", "value": storage},
            }
            if parent_id:
                payload["parentId"] = str(parent_id)
            return self._to_page(self.http.post("/api/v2/pages", json_body=payload))

        payload = {
            "type": "page",
            "title": title,
            "space": {"key": space_id or self._space_key()},
            "body": {"storage": {"value": storage, "representation": "storage"}},
        }
        if parent_id:
            payload["ancestors"] = [{"id": str(parent_id)}]
        return self._to_page(self.http.post("/rest/api/content", json_body=payload))

    def update_page(self, page_id: str, title: str, markdown: str) -> Page:
        current = self.get_page(page_id)
        storage = markdown_to_storage(markdown)
        version = {"number": current.version + 1}
        if self.cloud:
            payload: dict[str, Any] = {
                "id": str(page_id),
                "status": "current",
                "title": title,
                "body": {"representation": "storage", "value": storage},
                "version": version,
            }
            return self._to_page(self.http.put(f"/api/v2/pages/{page_id}", json_body=payload))

        payload = {
            "id": str(page_id),
            "type": "page",
            "title": title,
            "space": {"key": current.space_id or self._space_key()},
            "body": {"storage": {"value": storage, "representation": "storage"}},
            "version": version,
        }
        return self._to_page(self.http.put(f"/rest/api/content/{page_id}", json_body=payload))

    # -- internals ---------------------------------------------------------
    def _space_key(self, key: str | None = None) -> str:
        space_key = key or self.config.confluence_space
        if not space_key:
            raise ValueError("confluence.space is not set in config.toml")
        return space_key

    def space_id(self, key: str | None = None) -> str:
        """Cloud's numeric space id. Data Center addresses spaces by key alone."""
        space_key = self._space_key(key)
        if not self.cloud:
            return space_key
        data = self.http.get("/api/v2/spaces", params={"keys": space_key, "limit": 1})
        results = data.get("results", [])
        if not results:
            raise LookupError(f"No Confluence space with key {space_key!r}")
        return str(results[0]["id"])

    def _to_page(self, data: dict[str, Any]) -> Page:
        # v2 (Cloud) carries spaceId; v1 (Data Center) carries an expanded space.
        body = (data.get("body") or {}).get("storage") or {}
        webui = (data.get("_links") or {}).get("webui", "")
        space = data.get("spaceId") or (data.get("space") or {}).get("key", "")
        return Page(
            id=str(data.get("id", "")),
            title=data.get("title", ""),
            space_id=str(space),
            version=int((data.get("version") or {}).get("number", 0)),
            storage=body.get("value", ""),
            url=f"{self.base}{webui}" if webui else "",
        )
