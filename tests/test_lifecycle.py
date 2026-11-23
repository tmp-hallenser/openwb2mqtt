"""Tests for MQTT subscription lifecycle across config entry reloads."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import MqttMockHAClient

from custom_components.openwb2mqtt.const import (
    COMM_METHOD_MQTT,
    COMMUNICATION_METHOD,
    CONF_WALLBOX_POWER,
    DEVICEID,
    DEVICETYPE,
    DOMAIN,
    MQTT_ROOT_TOPIC,
)
from homeassistant.components.mqtt import DATA_MQTT
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant


def _openwb_subscriptions(hass: HomeAssistant) -> list[str]:
    """Return the topics of all active subscriptions below openWB/."""
    # The mqtt_mock fixture wraps the real MQTT client in a MagicMock.
    client = hass.data[DATA_MQTT].client._mock_wraps
    return sorted(
        sub.topic for sub in client.subscriptions if sub.topic.startswith("openWB/")
    )


# HA's MQTT client keeps a periodic timer running after the test.
@pytest.mark.parametrize("expected_lingering_timers", [True])
@pytest.mark.parametrize(
    ("device_type", "device_id"),
    [
        ("controller", 1),
        ("chargepoint", 1),
        ("vehicle", 1),
        ("counter", 0),
        ("pv", 2),
        ("bat", 3),
    ],
)
async def test_reload_does_not_leak_subscriptions(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    device_type: str,
    device_id: int,
) -> None:
    """Reloading an entry (e.g. after an options change) keeps one subscription per topic."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"openWB-{device_type}-{device_id}",
        title=f"openWB-{device_type}-{device_id}",
        data={
            COMMUNICATION_METHOD: COMM_METHOD_MQTT,
            MQTT_ROOT_TOPIC: "openWB",
            DEVICETYPE: device_type,
            DEVICEID: device_id,
            CONF_WALLBOX_POWER: "11",
        },
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    after_setup = _openwb_subscriptions(hass)
    assert after_setup

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _openwb_subscriptions(hass) == after_setup

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert _openwb_subscriptions(hass) == []
