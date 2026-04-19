"""Discover all text channels accessible to a Discord Bot account.

Connects with the provided bot token, enumerates guilds and their text channels,
then disconnects. Used by the API to auto-populate Channel records.

NOTE: Only official Discord Bot tokens are supported. User tokens (self-bots)
are prohibited by Discord TOS and will trigger account restrictions.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

try:
    import discord
except ImportError:
    discord = None  # type: ignore[assignment]

DISCOVERY_TIMEOUT_SECONDS = 30


async def discover_channels(
    token: str,
    auth_type: str = "bot",
) -> list[dict]:
    """Connect to Discord, list all text channels, and return them.

    Returns list of dicts with keys:
        channel_id, channel_name, guild_id, guild_name, category
    """
    if discord is None:
        raise ImportError("discord.py is required")

    channels: list[dict] = []
    ready_event = asyncio.Event()
    error_holder: list[Exception] = []

    if auth_type == "bot":
        intents = discord.Intents.default()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
    else:
        intents = discord.Intents.default()

    class DiscoveryClient(discord.Client):
        async def on_ready(self) -> None:
            try:
                for guild in self.guilds:
                    for ch in guild.text_channels:
                        category_name = ch.category.name if ch.category else None
                        channels.append({
                            "channel_id": str(ch.id),
                            "channel_name": ch.name,
                            "guild_id": str(guild.id),
                            "guild_name": guild.name,
                            "category": category_name,
                        })
                logger.info(
                    "Discovered %d channels across %d guilds",
                    len(channels), len(self.guilds),
                )
            except Exception as exc:
                error_holder.append(exc)
                logger.exception("Error during channel discovery")
            finally:
                ready_event.set()
                await self.close()

    client = DiscoveryClient(intents=intents)

    async def _run() -> None:
        try:
            await client.start(token, bot=(auth_type == "bot"))
        except TypeError:
            await client.start(token)
        except Exception as exc:
            error_holder.append(exc)
            ready_event.set()

    task = asyncio.create_task(_run())

    try:
        await asyncio.wait_for(ready_event.wait(), timeout=DISCOVERY_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        task.cancel()
        raise TimeoutError(
            f"Discord channel discovery timed out after {DISCOVERY_TIMEOUT_SECONDS}s"
        )

    if not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    if error_holder:
        raise error_holder[0]

    return channels


async def discover_servers(
    token: str,
    auth_type: str = "bot",
) -> list[dict]:
    """Return deduplicated list of guilds the token has access to.

    Each dict: {guild_id, guild_name, channel_count}
    """
    all_channels = await discover_channels(token, auth_type=auth_type)
    guild_map: dict[str, dict] = {}
    for ch in all_channels:
        gid = ch["guild_id"]
        if gid not in guild_map:
            guild_map[gid] = {
                "guild_id": gid,
                "guild_name": ch["guild_name"],
                "channel_count": 0,
            }
        guild_map[gid]["channel_count"] += 1
    return sorted(guild_map.values(), key=lambda g: g["guild_name"])
