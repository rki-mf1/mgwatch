import asyncio
import time

from mgw.settings import LOGGER


async def provide_after(delay_sec: float, to_say: str):
    await asyncio.sleep(delay_sec)
    LOGGER.debug(to_say + f" said at {time.strftime('%X')}")
    return to_say


async def main():
    LOGGER.debug(f"started at {time.strftime('%X')}")
    await provide_after(10, "10st awaitable")
    await provide_after(5, "5nd awaitable")
    LOGGER.debug(f"finished at {time.strftime('%X')}")
    await asyncio.sleep(2)  # just to have some gap
    t1 = asyncio.create_task(provide_after(20.0, "20st task"))
    t2 = asyncio.create_task(provide_after(15.0, "15nd task"))
    LOGGER.debug(f"started at {time.strftime('%X')}")
    await t1
    await t2
    LOGGER.debug(f"finished at {time.strftime('%X')}")


asyncio.run(main())
