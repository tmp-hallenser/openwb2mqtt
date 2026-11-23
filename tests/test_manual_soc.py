"""Tests for the manual SoC number of a chargepoint (MQTT)."""

import json

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)
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
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

# HA's MQTT client keeps a periodic timer running after the test.
pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

MANUAL_SOC = "number.openwb_chargepoint_1_aktueller_soc_manuelles_soc_modul"


@pytest.fixture
async def chargepoint(hass: HomeAssistant, mqtt_mock: MqttMockHAClient) -> None:
    """Set up chargepoint 1."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="openWB-chargepoint-1",
        title="openWB-chargepoint-1",
        data={
            COMMUNICATION_METHOD: COMM_METHOD_MQTT,
            MQTT_ROOT_TOPIC: "openWB",
            DEVICETYPE: "chargepoint",
            DEVICEID: 1,
            CONF_WALLBOX_POWER: "11",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_manual_soc_reads_connected_vehicle_soc(
    hass: HomeAssistant, chargepoint: None
) -> None:
    """The number shows the SoC of the vehicle connected to the chargepoint."""
    assert hass.states.get(MANUAL_SOC).state == STATE_UNKNOWN

    async_fire_mqtt_message(
        hass,
        "openWB/chargepoint/1/get/connected_vehicle/soc",
        json.dumps({"soc": 42, "range": 180.0, "fault_state": 0}),
    )
    await hass.async_block_till_done()
    assert float(hass.states.get(MANUAL_SOC).state) == 42


async def test_manual_soc_writes_to_connected_vehicle(
    hass: HomeAssistant, mqtt_mock: MqttMockHAClient, chargepoint: None
) -> None:
    """Setting the SoC addresses the vehicle reported on the chargepoint."""
    async_fire_mqtt_message(
        hass,
        "openWB/chargepoint/1/get/connected_vehicle/info",
        json.dumps({"id": 3, "name": "Testauto"}),
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: MANUAL_SOC, ATTR_VALUE: 55},
        blocking=True,
    )
    mqtt_mock.async_publish.assert_called_once()
    topic, payload = mqtt_mock.async_publish.call_args.args[:2]
    assert topic == "openWB/set/vehicle/3/soc_module/calculated_soc_state/manual_soc"
    assert payload == "55.0"


async def test_manual_soc_without_vehicle_raises(
    hass: HomeAssistant, mqtt_mock: MqttMockHAClient, chargepoint: None
) -> None:
    """Without a known vehicle nothing is published."""
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: MANUAL_SOC, ATTR_VALUE: 55},
            blocking=True,
        )
    mqtt_mock.async_publish.assert_not_called()
