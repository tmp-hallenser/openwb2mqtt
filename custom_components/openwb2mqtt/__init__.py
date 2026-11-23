"""The openwbmqtt component for controlling the openWB wallbox via home assistant / MQTT."""

import logging

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api_client import OpenWB2MqttApiClient
from .charge_template import ChargeTemplateManager
from .common import async_migrate_device_identifiers

# Import global values.
from .const import (
    API_TOKEN,
    API_URL,
    COMM_METHOD_HTTP,
    COMMUNICATION_METHOD,
    DEVICEID,
    DEVICETYPE,
    MQTT_ROOT_TOPIC,
    PLATFORMS,
)
from .coordinator import OpenWB2MqttDataUpdateCoordinator
from .data import OpenWBConfigEntry, OpenWBRuntimeData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: OpenWBConfigEntry) -> bool:
    """Set up the openWB2 MQTT integration from a config entry."""
    runtime_data = OpenWBRuntimeData()

    if entry.data.get(COMMUNICATION_METHOD) == COMM_METHOD_HTTP:
        api_client = OpenWB2MqttApiClient(
            api_url=entry.data[API_URL],
            token=entry.data.get(API_TOKEN),
            session=async_get_clientsession(hass),
        )
        coordinator = OpenWB2MqttDataUpdateCoordinator(
            hass,
            client=api_client,
            device_type=entry.data[DEVICETYPE],
            device_id=entry.data[DEVICEID],
            config_entry=entry,
        )
        await coordinator.async_config_entry_first_refresh()
        runtime_data.coordinator = coordinator
    else:
        # MQTT is an after_dependency so that HTTP users do not need it.
        if not await mqtt.async_wait_for_mqtt_client(hass):
            raise ConfigEntryNotReady("MQTT integration is not available")
        async_migrate_device_identifiers(hass, entry)
        if entry.data.get(DEVICETYPE) == "chargepoint":
            # Charge mode, limits and currents are read from and written to
            # the chargepoint's active charge template.
            manager = ChargeTemplateManager(
                hass, entry.data[MQTT_ROOT_TOPIC], entry.data[DEVICEID]
            )
            entry.async_on_unload(await manager.async_start())
            entry.async_on_unload(
                manager.async_report_missing_template(
                    f"missing_charge_template_{entry.entry_id}", entry.title
                )
            )
            runtime_data.charge_template = manager

    entry.runtime_data = runtime_data
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OpenWBConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
