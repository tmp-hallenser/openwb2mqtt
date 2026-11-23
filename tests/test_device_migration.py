"""Tests for migrating old three-element device identifiers."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import MqttMockHAClient

from custom_components.openwb2mqtt.const import (
    COMM_METHOD_MQTT,
    COMMUNICATION_METHOD,
    DEVICEID,
    DEVICETYPE,
    DOMAIN,
    MQTT_ROOT_TOPIC,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er


# HA's MQTT client keeps a periodic timer running after the test.
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_old_device_identifier_is_migrated_in_place(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """An existing device keeps its ID, user name and entities."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="openWB-pv-2",
        title="openWB-pv-2",
        data={
            COMMUNICATION_METHOD: COMM_METHOD_MQTT,
            MQTT_ROOT_TOPIC: "openWB",
            DEVICETYPE: "pv",
            DEVICEID: 2,
        },
    )
    entry.add_to_hass(hass)
    old_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "PV 2", "openWB")},
        name="PV 2",
    )
    device_registry.async_update_device(old_device.id, name_by_user="Dach")
    old_entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "openwb_pv_2_leistung",
        config_entry=entry,
        device_id=old_device.id,
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert len(devices) == 1
    device = devices[0]
    assert device.id == old_device.id
    assert device.identifiers == {(DOMAIN, "openWB-PV 2")}
    assert device.name_by_user == "Dach"
    assert entity_registry.async_get(old_entity.entity_id).device_id == device.id
    assert all(
        entity.device_id == device.id
        for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    )
