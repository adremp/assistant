"""Notion API service for saving summaries."""

import logging
from datetime import datetime

from notion_client import AsyncClient

logger = logging.getLogger(__name__)

SUMMARY_PAGE_TITLE = "📊 Сводки"


class NotionService:
    """Service for interacting with Notion API (per-user tokens)."""

    def __init__(self, notion_token: str, parent_page_id: str | None = None):
        """
        Initialize Notion service with user's token.

        Args:
            notion_token: User's Notion API token
            parent_page_id: Parent page ID for creating new pages
        """
        self._token = notion_token
        self._parent_page_id = parent_page_id
        self._client: AsyncClient | None = None

    def _get_client(self) -> AsyncClient:
        """Get or create Notion client."""
        if self._client is None:
            self._client = AsyncClient(auth=self._token)
        return self._client

    async def find_or_create_summary_page(self, parent_page_id: str) -> dict:
        """
        Find existing '📊 Сводки' page or create new one.

        Args:
            parent_page_id: Parent page ID to search in and create under

        Returns:
            Page dict with id and url
        """
        client = self._get_client()

        # Search for existing page with title "📊 Сводки"
        try:
            # Get children of parent page
            children = await client.blocks.children.list(block_id=parent_page_id)
            
            for block in children.get("results", []):
                if block.get("type") == "child_page":
                    title = block.get("child_page", {}).get("title", "")
                    if title == SUMMARY_PAGE_TITLE:
                        page_id = block["id"]
                        # Get full page info for URL
                        page = await client.pages.retrieve(page_id=page_id)
                        logger.info(f"Found existing summary page: {page_id}")
                        return {"id": page_id, "url": page.get("url", "")}

            # Not found, create new page
            logger.info(f"Creating new summary page under {parent_page_id}")
            return await self._create_summary_page(parent_page_id)

        except Exception as e:
            logger.error(f"Failed to find/create summary page: {e}")
            raise

    async def _create_summary_page(self, parent_page_id: str) -> dict:
        """Create new summary page."""
        client = self._get_client()

        page = await client.pages.create(
            parent={"page_id": parent_page_id},
            properties={
                "title": {"title": [{"text": {"content": SUMMARY_PAGE_TITLE}}]}
            },
            children=[
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": "Сводки по выполненным задачам"}}]
                    },
                }
            ],
        )

        logger.info(f"Created summary page: {page['id']}")
        return {"id": page["id"], "url": page["url"]}

    async def append_summary(
        self,
        page_id: str,
        content: str,
        summary_type: str = "Выполненные задачи",
    ) -> bool:
        """
        Append summary to the unified summary page.

        Args:
            page_id: Summary page ID
            content: Summary content
            summary_type: Type header for the summary

        Returns:
            True if successful
        """
        client = self._get_client()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        blocks = [
            {"object": "block", "type": "divider", "divider": {}},
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": f"{summary_type} — {now}"}}]
                },
            },
        ]
        blocks.extend(self._text_to_blocks(content))

        try:
            await client.blocks.children.append(block_id=page_id, children=blocks)
            logger.info(f"Appended summary to page: {page_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to append summary: {e}")
            raise

    def _text_to_blocks(self, text: str) -> list[dict]:
        """Convert text to Notion blocks."""
        blocks = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            if line.startswith("### "):
                blocks.append({
                    "object": "block", "type": "heading_3",
                    "heading_3": {"rich_text": [{"type": "text", "text": {"content": line[4:]}}]},
                })
            elif line.startswith("## "):
                blocks.append({
                    "object": "block", "type": "heading_2",
                    "heading_2": {"rich_text": [{"type": "text", "text": {"content": line[3:]}}]},
                })
            elif line.startswith("# "):
                blocks.append({
                    "object": "block", "type": "heading_1",
                    "heading_1": {"rich_text": [{"type": "text", "text": {"content": line[2:]}}]},
                })
            elif line.startswith("- ") or line.startswith("* "):
                blocks.append({
                    "object": "block", "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": line[2:]}}]},
                })
            elif len(line) > 2 and line[0].isdigit() and line[1] in ".)":
                blocks.append({
                    "object": "block", "type": "numbered_list_item",
                    "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": line[2:].strip()}}]},
                })
            else:
                blocks.append({
                    "object": "block", "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": line}}]},
                })

        return blocks

    async def close(self) -> None:
        """Close the Notion client."""
        if self._client:
            await self._client.aclose()
            self._client = None
