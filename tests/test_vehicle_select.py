"""Tests for the connected vehicle select of a chargepoint (MQTT)."""

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
from homeassistant.components.select import (
    ATTR_OPTION,
    ATTR_OPTIONS,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

# HA's MQTT client keeps a periodic timer running after the test.
pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

VEHICLE = "select.openwb_chargepoint_1_angeschlossenes_fahrzeug"


@pytest.fixture
async def chargepoint(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    entity_registry: er.EntityRegistry,
) -> None:
    """Set up chargepoint 1 with the (disabled by default) vehicle select enabled."""
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
    entity_registry.async_get_or_create(
        SELECT_DOMAIN,
        DOMAIN,
        "openwb_chargepoint_1_angeschlossenes_fahrzeug",
        config_entry=entry,
        suggested_object_id="openwb_chargepoint_1_angeschlossenes_fahrzeug",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _connected(hass: HomeAssistant, vehicle_id: int) -> None:
    async_fire_mqtt_message(
        hass,
        "openWB/chargepoint/1/get/connected_vehicle/info",
        json.dumps({"id": vehicle_id, "name": "ignored"}),
    )


def _name(hass: HomeAssistant, vehicle_id: int, name: str) -> None:
    async_fire_mqtt_message(hass, f"openWB/vehicle/{vehicle_id}/name", f'"{name}"')


@pytest.mark.usefixtures("chargepoint")
async def test_vehicle_known_before_names(hass: HomeAssistant) -> None:
    """The names arriving after the connected vehicle update the state.

    Seen in production: the select showed 'unknown' because its state kept
    the placeholder 'Vehicle 0' after the name replaced it in the options.
    """
    _connected(hass, 0)
    await hass.async_block_till_done()
    _name(hass, 0, "Standard-Fahrzeug")
    _name(hass, 2, "Fahrzeug 2")
    await hass.async_block_till_done()

    state = hass.states.get(VEHICLE)
    assert state.state == "Standard-Fahrzeug"
    assert state.attributes[ATTR_OPTIONS] == ["Standard-Fahrzeug", "Fahrzeug 2"]


@pytest.mark.usefixtures("chargepoint")
async def test_names_before_vehicle(hass: HomeAssistant) -> None:
    """The usual order also works."""
    _name(hass, 0, "Standard-Fahrzeug")
    _name(hass, 2, "Fahrzeug 2")
    _connected(hass, 2)
    await hass.async_block_till_done()

    assert hass.states.get(VEHICLE).state == "Fahrzeug 2"


@pytest.mark.usefixtures("chargepoint")
async def test_without_names_placeholders_are_used(hass: HomeAssistant) -> None:
    """If the bridge does not forward vehicle names, placeholders still work."""
    _connected(hass, 1)
    await hass.async_block_till_done()

    state = hass.states.get(VEHICLE)
    assert state.state == "Vehicle 1"
    assert state.attributes[ATTR_OPTIONS] == [f"Vehicle {i}" for i in range(11)]


@pytest.mark.usefixtures("chargepoint")
async def test_renamed_vehicle(hass: HomeAssistant) -> None:
    """Renaming a vehicle in openWB renames the option and the state."""
    _name(hass, 0, "Standard-Fahrzeug")
    _connected(hass, 0)
    await hass.async_block_till_done()
    _name(hass, 0, "Kombi")
    await hass.async_block_till_done()

    state = hass.states.get(VEHICLE)
    assert state.state == "Kombi"
    assert state.attributes[ATTR_OPTIONS] == ["Kombi"]


@pytest.mark.usefixtures("chargepoint")
async def test_select_vehicle_publishes_its_id(
    hass: HomeAssistant, mqtt_mock: MqttMockHAClient
) -> None:
    """Selecting a vehicle by name sends its ID to the chargepoint."""
    _name(hass, 0, "Standard-Fahrzeug")
    _name(hass, 2, "Fahrzeug 2")
    _connected(hass, 0)
    await hass.async_block_till_done()

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: VEHICLE, ATTR_OPTION: "Fahrzeug 2"},
        blocking=True,
    )
    mqtt_mock.async_publish.assert_called_once()
    topic, payload = mqtt_mock.async_publish.call_args.args[:2]
    assert topic == "openWB/set/chargepoint/1/config/ev"
    assert payload == "2"
