"""Tests for setting up and unloading the openwb2mqtt integration."""

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import MqttMockHAClient

from custom_components.openwb2mqtt import async_setup_entry, async_unload_entry
from custom_components.openwb2mqtt.const import (
    API_PREFIX,
    API_URL,
    COMM_METHOD_HTTP,
    COMM_METHOD_MQTT,
    COMMUNICATION_METHOD,
    DEVICEID,
    DEVICETYPE,
    DOMAIN,
    MQTT_ROOT_TOPIC,
    PLATFORMS,
)
from custom_components.openwb2mqtt.coordinator import (
    OpenWB2MqttDataUpdateCoordinator,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant


# HA's MQTT client keeps a periodic timer running after the test.
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_setup_and_unload_mqtt_entry(
    hass: HomeAssistant, mqtt_mock: MqttMockHAClient
) -> None:
    """An MQTT entry forwards all platforms and unloads them again."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            COMMUNICATION_METHOD: COMM_METHOD_MQTT,
            MQTT_ROOT_TOPIC: "openWB",
            DEVICETYPE: "pv",
            DEVICEID: 2,
        },
    )
    entry.add_to_hass(hass)

    with patch.object(
        hass.config_entries, "async_forward_entry_setups", return_value=True
    ) as mock_forward:
        assert await async_setup_entry(hass, entry) is True
    mock_forward.assert_called_once_with(entry, PLATFORMS)
    assert entry.runtime_data.coordinator is None
    assert entry.runtime_data.charge_template is None

    with patch.object(
        hass.config_entries, "async_unload_platforms", return_value=True
    ) as mock_unload:
        assert await async_unload_entry(hass, entry) is True
    mock_unload.assert_called_once_with(entry, PLATFORMS)


async def test_setup_and_unload_http_entry(hass: HomeAssistant) -> None:
    """An HTTP entry creates and stores a polling coordinator."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            COMMUNICATION_METHOD: COMM_METHOD_HTTP,
            API_PREFIX: "openWB",
            API_URL: "http://192.0.2.1/openWB/simpleAPI/simpleapi.php",
            DEVICETYPE: "chargepoint",
            DEVICEID: 1,
        },
    )
    entry.add_to_hass(hass)

    api_data = {"chargepoint_1": {"power": 1234}}
    with (
        patch(
            "custom_components.openwb2mqtt.OpenWB2MqttApiClient.async_get_data",
            AsyncMock(return_value=api_data),
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", return_value=True
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    assert isinstance(coordinator, OpenWB2MqttDataUpdateCoordinator)
    assert coordinator.data == {"power": 1234}

    with patch.object(hass.config_entries, "async_unload_platforms", return_value=True):
        assert await async_unload_entry(hass, entry) is True


async def test_mqtt_entry_waits_for_mqtt(hass: HomeAssistant) -> None:
    """Without the MQTT integration an MQTT entry is retried later."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            COMMUNICATION_METHOD: COMM_METHOD_MQTT,
            MQTT_ROOT_TOPIC: "openWB",
            DEVICETYPE: "pv",
            DEVICEID: 2,
        },
    )
    entry.add_to_hass(hass)
    with patch(
        "homeassistant.components.mqtt.async_wait_for_mqtt_client", return_value=False
    ):
        await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
