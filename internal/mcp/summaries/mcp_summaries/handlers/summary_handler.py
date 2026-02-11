"""MCP tools for summary generation."""

from mcp.server.fastmcp import FastMCP

from mcp_summaries.container import create_user_telethon_repo, get_summary_service
from mcp_summaries.handlers import _err, _ok


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def generate_summary(
        user_id: int,
        channel_ids: list[str],
        prompt: str,
        last_message_ids: dict[str, int] | None = None,
    ) -> str:
        """Generate a summary for given channels. If last_message_ids provided, fetches only new messages (incremental)."""
        repo = await create_user_telethon_repo(user_id)
        if repo is None:
            return _err("Telethon not authenticated.")

        last_message_ids = last_message_ids or {}
        try:
            channels_data = []
            new_last_ids = dict(last_message_ids)

            for channel_id in channel_ids:
                cid = str(channel_id)
                info = await repo.get_channel_info(cid)
                name = info.get("title", cid) if info else cid

                min_id = last_message_ids.get(cid, 0)
                if min_id > 0:
                    messages = await repo.get_messages_since(cid, min_id=min_id)
                    if messages:
                        new_last_ids[cid] = max(m["id"] for m in messages)
                        lines = []
                        for m in messages:
                            sender = m.get("sender", "?")
                            text = m.get("text", "").replace("\n", " ")
                            lines.append(f"{sender}: {text}")
                        text_block = "\n".join(lines)
                        channels_data.append(
                            {"channel_name": name, "messages_text": text_block}
                        )
                else:
                    text_block = await repo.get_channel_messages_formatted(
                        cid, limit=500
                    )
                    if text_block:
                        channels_data.append(
                            {"channel_name": name, "messages_text": text_block}
                        )
                    latest = await repo.get_messages_since(cid, min_id=0, limit=1)
                    if latest:
                        new_last_ids[cid] = max(m["id"] for m in latest)

            if not channels_data:
                return _ok(
                    {
                        "summary": "",
                        "channels_processed": 0,
                        "last_message_ids": new_last_ids,
                    }
                )

            svc = await get_summary_service()
            summary = await svc.generate_multi_channel_summary(channels_data, prompt)
            return _ok(
                {
                    "summary": summary,
                    "channels_processed": len(channels_data),
                    "last_message_ids": new_last_ids,
                }
            )
        except Exception as e:
            return _err(f"Summary generation failed: {e}")
        finally:
            await repo.disconnect()
