"""Test connectivity to PROBE PLUS."""

import asyncio
import logging
from bleak import BleakScanner

from src.pyprobeplus_ble import ProbePlusBLE

_LOGGER = logging.getLogger(__name__)

async def main():
    """Main test func."""
    event_lock = asyncio.Event()

    def updated_callback(*kwargs):
        _LOGGER.debug("Got updated data")

    while True:
        print("Scanning")
        devices = await BleakScanner.discover(
            return_adv=True
        )
        device = None
        adv = None
        session = None

        for d, a in devices.values():
            if a.local_name is not None and a.local_name.startswith("FM2"):
                device = d
                adv = a
                break
        if device:
            break

    session = ProbePlusBLE(
        ble_device=device,
        advertisement_data=adv
    )
    await session.start()
    session.register_callback(updated_callback)
    await event_lock.wait()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
