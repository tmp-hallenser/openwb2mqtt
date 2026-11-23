"""Runtime data of an openwb2mqtt config entry."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .charge_template import ChargeTemplateManager
from .coordinator import OpenWB2MqttDataUpdateCoordinator


@dataclass
class OpenWBRuntimeData:
    """Objects shared by the platforms of one config entry."""

    # Set for entries using the HTTP API.
    coordinator: OpenWB2MqttDataUpdateCoordinator | None = None
    # Set for MQTT chargepoint entries.
    charge_template: ChargeTemplateManager | None = None


type OpenWBConfigEntry = ConfigEntry[OpenWBRuntimeData]
