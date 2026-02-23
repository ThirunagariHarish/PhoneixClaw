"""Discover all text channels accessible to a Discord account.

Connects with the provided token, enumerates guilds and their text channels,
then disconnects. Used by the API to auto-populate Channel records.
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
    auth_type: str = "user_token",
) -> list[dict]:
    """Connect to Discord, list all text channels, and return them.

    Returns list of dicts with keys:
        channel_id, channel_name, guild_id, guild_name, category
    """
    if discord is None:
        raise ImportError("discord.py or discord.py-self is required")

    channels: list[dict] = []
    ready_event = asyncio.Event()
    error_holder: list[Exception] = []

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

    client = DiscoveryClient()

    async def _run() -> None:
        try:
            await client.start(token)
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
