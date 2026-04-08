"""
Automation scheduler entrypoint — runs the scheduler loop.
"""
import asyncio
import logging

from .scheduler import AutomationScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    scheduler = AutomationScheduler(task_creator=None, delivery_router=None)
    await scheduler.start()


if __name__ == "__main__":
    asyncio.run(main())
