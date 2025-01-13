from __future__ import annotations

import asyncio
import logging
import struct
from collections.abc import Callable
from typing import Any, TypeVar

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakDBusError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    BleakError,
    establish_connection,
    retry_bluetooth_connection_error,
)

from .const import BLE_DATA_RECEIVE
from .models import ProbeState, RelayState

__version__ = "0.0.0"

WrapFuncType = TypeVar("WrapFuncType", bound=Callable[..., Any])

_LOGGER = logging.getLogger(__name__)

class ProbePlusBLE:
    """A Probe Plus probe and relay."""

    def __init__(self, ble_device: BLEDevice, advertisement_data: AdvertisementData | None = None):
        self._ble_device = ble_device
        self._advertisement_data = advertisement_data
        self._relay_state = RelayState()
        self._probe_state = ProbeState()
        self._callbacks: list[Callable[[RelayState|ProbeState]], None] = []
        self._connect_lock: asyncio.Lock = asyncio.Lock()
        self._disconnect_timer: asyncio.TimerHandle | None = None
        self.loop = asyncio.get_running_loop()
        self._expected_disconnect = True
        self._client: BleakClientWithServiceCache | None = None

    def set_ble_device_and_advertisement_data(
            self, ble_device: BLEDevice, advertisement_data: AdvertisementData
    ):
        """Set the ble device."""
        self._ble_device = ble_device
        self._advertisement_data = advertisement_data

    @property
    def address(self) -> str:
        """Return the address."""
        return self._ble_device.address

    @property
    def name(self) -> str:
        """Get the name of the device."""
        return self._ble_device.name or self._ble_device.address

    @property
    def rssi(self) -> int | None:
        """Get the rssi of the device."""
        if self._advertisement_data:
            return self._advertisement_data.rssi
        return None

    @property
    def probe_battery(self) -> float | None:
        """Get the battery level of the probe."""
        return self._probe_state.battery_level

    @property
    def relay_battery(self) -> float | None:
        """Get the battery level of the relay."""
        return self._relay_state.battery_level

    @property
    def relay_voltage(self) -> float | None:
        """Get the voltage of the relay."""
        return self._relay_state.volage

    @property
    def probe_state(self) -> int | None:
        """Get the current connection state of the probe."""
        return self._relay_state.status

    @property
    def probe_temperature(self) -> int | None:
        """Get the current temperature state of the probe."""
        return self._probe_state.temperature

    def _disconnected(self, client: BleakClientWithServiceCache) -> None:
        """Disconnected callback."""
        if self._expected_disconnect:
            _LOGGER.debug(
                "%s: Disconnected from device; RSSI: %s", self.name, self.rssi
            )
            return
        _LOGGER.warning(
            "%s: Device unexpectedly disconnected; RSSI: %s",
            self.name,
            self.rssi,
        )

    def _disconnect(self) -> None:
        """Disconnect from device."""
        self._disconnect_timer = None
        asyncio.create_task(self._execute_disconnect())

    async def _execute_disconnect(self) -> None:
        """Execute disconnection."""
        async with self._connect_lock:
            client = self._client
            self._expected_disconnect = True
            self._client = None
            if client and client.is_connected:
                try:
                    await client.stop_notify(BLE_DATA_RECEIVE)
                except BleakError:
                    _LOGGER.debug(
                        "%s: Failed to stop notifications", self.name, exc_info=True
                    )
                await client.disconnect()

    @retry_bluetooth_connection_error(10)
    async def _retry_ble_connection(self) -> None:
        """Send command to device and read response."""
        try:
            await self._ensure_connected()
        except BleakDBusError as ex:
            # Disconnect so we can reset state and try again
            await asyncio.sleep(60)
            _LOGGER.debug(
                "%s: RSSI: %s; Backing off %ss; Disconnecting due to error: %s",
                self.name,
                self.rssi,
                60,
                ex,
            )
            await self._execute_disconnect()
            raise
        except BleakError as ex:
            # Disconnect so we can reset state and try again
            _LOGGER.debug(
                "%s: RSSI: %s; Disconnecting due to error: %s", self.name, self.rssi, ex
            )
            await self._execute_disconnect()
            raise


    def register_callback(
        self, callback: Callable[[RelayState|ProbeState], None]
    ) -> Callable[[], None]:
        """Register a callback to be called when the state changes."""

        def unregister_callback() -> None:
            self._callbacks.remove(callback)

        self._callbacks.append(callback)
        return unregister_callback

    async def _ensure_connected(self) -> None:
        """Ensure connection to device is established."""
        if self._connect_lock.locked():
            _LOGGER.debug(
                "%s: Connection already in progress, waiting for it to complete; RSSI: %s",
                self.name,
                self.rssi,
            )
        if self._client and self._client.is_connected:
            return
        async with self._connect_lock:
            # Check again while holding the lock
            if self._client and self._client.is_connected:
                return
            _LOGGER.debug("%s: Connecting; RSSI: %s", self.name, self.rssi)
            client = await establish_connection(
                BleakClientWithServiceCache,
                self._ble_device,
                self.name,
                self._disconnected,
                use_services_cache=True,
                ble_device_callback=lambda: self._ble_device,
            )
            _LOGGER.debug("%s: Connected; RSSI: %s", self.name, self.rssi)

            self._client = client

            _LOGGER.debug(
                "%s: Subscribe to notifications; RSSI: %s", self.name, self.rssi
            )
            await client.start_notify(BLE_DATA_RECEIVE, self._notification_handler)

    def _fire_callbacks(self) -> None:
        """Fire the callbacks."""
        for callback in self._callbacks:
            callback(self._relay_state)
            callback(self._probe_state)

    def _notification_handler(self, _sender: int, data: bytearray):
        """Notification handler."""
        _LOGGER.debug("%s: Notification received: %s", self.name, data.hex())
        probe_channels = [0]  # Hardcoded probe channels

        if len(data) == 9 and data[0] == 0x00 and data[1] == 0x00:
            # probe state
            d = data[3] * 0.03125
            if d >= 2.0:
                self._probe_state.battery_level = 100
            elif d >= 1.7:
                self._probe_state.battery_level = 51
            elif d >= 1.5:
                self._probe_state.battery_level = 26
            else:
                self._probe_state.battery_level = 20
            temp_bytes = data[4:6]
            self._probe_state.temperature = ((struct.unpack(">H", temp_bytes)[0] * 0.0625) - 50.0625) / 100
            self._probe_state.rssi = data[8]

        elif len(data) == 8 and data[0] == 0x00 and data[1] == 0x01:
            # relay state
            voltage_bytes = data[2:4]
            self._relay_state.volage = struct.unpack(">H", voltage_bytes)[0] / 1000.0
            if self._relay_state.volage > 3.87:
                self._relay_state.battery_level = 100
            elif self._relay_state.volage >= 3.7:
                self._relay_state.battery_level = 74
            elif self._relay_state.volage >= 3.6:
                self._relay_state.battery_level = 49
            else:
                self._relay_state.battery_level = 0

            for channel in probe_channels:
                if len(data) > 4: # check to avoid index out of range errors
                    status_byte = data[4] # Directly access the 5th byte (index 4)
                    self._relay_state.status = int(status_byte)

        self._fire_callbacks()
