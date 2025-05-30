"""Device BLE Parser."""

import logging
import struct

from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

@dataclass
class ProbePlusData:
    """Represents data from PP."""
    relay_battery: float | None = None
    relay_voltage: float | None = None
    relay_status: int | None = None
    probe_battery: float | None = None
    probe_voltage: float | None = None
    probe_temperature: float | None = None
    probe_rssi: float | None = None

class ParserBase:
    """ParserBase"""

    state: ProbePlusData = ProbePlusData()

    def parse_data(self, data: bytearray):
        """Handle data notification updates from the device."""
        probe_channels = [0]  # Hardcoded probe channels

        _LOGGER.debug(">> Received data notification: %s", data.hex())

        if len(data) == 9 and data[0] == 0x00 and data[1] == 0x00:
            # probe state
            d = data[3] * 0.03125
            if d >= 2.0:
                self.state.probe_battery = 100
            elif d >= 1.7:
                self.state.probe_battery = 51
            elif d >= 1.5:
                self.state.probe_battery = 26
            else:
                self.state.probe_battery = 20
            temp_bytes = data[4:6]
            temp_bytes = bytearray([temp_bytes[1], temp_bytes[0]])
            _LOGGER.debug(">> Temperature state %s", temp_bytes.hex())
            _LOGGER.debug(">> Unpacked temperature %s", struct.unpack(">H", temp_bytes)[0])
            self.state.probe_temperature = (
                (struct.unpack(">H", temp_bytes)[0] * 0.0625) - 50.0625
            )
            _LOGGER.debug(">> Parsed temperature: %s", self.state.probe_temperature)
            self.state.probe_rssi = data[8]
            return self.state

        elif len(data) == 8 and data[0] == 0x00 and data[1] == 0x01:
            # relay state
            voltage_bytes = data[2:4]
            self.state.relay_voltage = struct.unpack(">H", voltage_bytes)[0] / 1000.0
            _LOGGER.debug(">> Voltage state %s", voltage_bytes.hex())
            if self.state.relay_voltage > 3.87:
                self.state.relay_battery = 100
            elif self.state.relay_voltage >= 3.7:
                self.state.relay_battery = 74
            elif self.state.relay_voltage >= 3.6:
                self.state.relay_battery = 49
            else:
                self.state.relay_battery = 0

            for channel in probe_channels:
                if len(data) > 4: # check to avoid index out of range errors
                    status_byte = data[4] # Directly access the 5th byte (index 4)
                    self.state.relay_status = int(status_byte)
                    break
                self.state.relay_status = None
            _LOGGER.debug(">> Relay state %s", self.state.relay_status)
            return self.state

        return self.state
