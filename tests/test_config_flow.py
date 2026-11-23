"""Tests for the openwb2mqtt config and options flow."""

from collections.abc import Generator
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.openwb2mqtt.const import (
    API_PREFIX,
    API_URL,
    COMM_METHOD_HTTP,
    COMM_METHOD_MQTT,
    COMMUNICATION_METHOD,
    CONF_VEHICLES,
    CONF_WALLBOX_POWER,
    DEVICEID,
    DEVICETYPE,
    DOMAIN,
    MQTT_ROOT_TOPIC,
)
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType


@pytest.fixture(autouse=True)
def mock_setup_entry() -> Generator[AsyncMock]:
    """Prevent the created entry from actually being set up."""
    with patch(
        "custom_components.openwb2mqtt.async_setup_entry", return_value=True
    ) as mock:
        yield mock


@pytest.fixture
def mqtt_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Pretend the MQTT integration is configured."""
    entry = MockConfigEntry(domain="mqtt")
    entry.add_to_hass(hass)
    return entry


async def _start_flow(hass: HomeAssistant, method: str) -> dict:
    """Start the user flow and pick the communication method."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {COMMUNICATION_METHOD: method}
    )


@pytest.mark.parametrize(
    ("device_type", "device_id", "expected_title"),
    [
        ("controller", 1, "openWB-controller"),
        ("counter", 0, "openWB-counter-0"),
        ("pv", 2, "openWB-pv-2"),
        ("bat", 3, "openWB-bat-3"),
        ("vehicle", 1, "openWB-vehicle-1"),
    ],
)
@pytest.mark.usefixtures("mqtt_entry")
async def test_mqtt_flow_creates_entry(
    hass: HomeAssistant, device_type: str, device_id: int, expected_title: str
) -> None:
    """Non-chargepoint MQTT devices are created right after the details step."""
    result = await _start_flow(hass, COMM_METHOD_MQTT)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "details_mqtt"

    details = {MQTT_ROOT_TOPIC: "openWB", DEVICETYPE: device_type, DEVICEID: device_id}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], details)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == expected_title
    assert result["result"].unique_id == expected_title
    assert result["data"] == {COMMUNICATION_METHOD: COMM_METHOD_MQTT, **details}


@pytest.mark.usefixtures("mqtt_entry")
async def test_mqtt_flow_chargepoint(hass: HomeAssistant) -> None:
    """A chargepoint asks for the wallbox power in an extra step."""
    result = await _start_flow(hass, COMM_METHOD_MQTT)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {MQTT_ROOT_TOPIC: "openWB", DEVICETYPE: "chargepoint", DEVICEID: 1},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "chargepoint"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WALLBOX_POWER: "11"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "openWB-chargepoint-1"
    assert result["data"] == {
        COMMUNICATION_METHOD: COMM_METHOD_MQTT,
        MQTT_ROOT_TOPIC: "openWB",
        DEVICETYPE: "chargepoint",
        DEVICEID: 1,
        CONF_WALLBOX_POWER: "11",
        CONF_VEHICLES: {},
    }


async def test_http_flow_chargepoint_with_vehicles(hass: HomeAssistant) -> None:
    """The HTTP chargepoint step parses the vehicle list into a dict."""
    result = await _start_flow(hass, COMM_METHOD_HTTP)
    assert result["step_id"] == "details_api"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            API_PREFIX: "openWB",
            API_URL: "http://192.0.2.1/openWB/simpleAPI/simpleapi.php",
            DEVICETYPE: "chargepoint",
            DEVICEID: 1,
        },
    )
    assert result["step_id"] == "chargepoint"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_WALLBOX_POWER: "22", CONF_VEHICLES: "0=Standard, 1=Second car"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "openWB-chargepoint-1"
    assert result["data"][CONF_VEHICLES] == {"0": "Standard", "1": "Second car"}


async def test_mqtt_flow_requires_mqtt_integration(hass: HomeAssistant) -> None:
    """Choosing MQTT without a configured MQTT integration aborts."""
    result = await _start_flow(hass, COMM_METHOD_MQTT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "mqtt_not_configured"


@pytest.mark.usefixtures("mqtt_entry")
async def test_flow_aborts_if_already_configured(hass: HomeAssistant) -> None:
    """Setting up the same device twice aborts."""
    MockConfigEntry(domain=DOMAIN, unique_id="openWB-pv-2").add_to_hass(hass)

    result = await _start_flow(hass, COMM_METHOD_MQTT)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {MQTT_ROOT_TOPIC: "openWB", DEVICETYPE: "pv", DEVICEID: 2}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_not_supported_for_non_chargepoint(
    hass: HomeAssistant,
) -> None:
    """Only chargepoints have options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={COMMUNICATION_METHOD: COMM_METHOD_MQTT, DEVICETYPE: "pv", DEVICEID: 2},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_conf_options_supported"


async def test_options_flow_chargepoint_http(hass: HomeAssistant) -> None:
    """The chargepoint options flow stores power and parsed vehicles."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            COMMUNICATION_METHOD: COMM_METHOD_HTTP,
            DEVICETYPE: "chargepoint",
            DEVICEID: 1,
        },
        options={CONF_WALLBOX_POWER: "11", CONF_VEHICLES: {"0": "Standard"}},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_WALLBOX_POWER: "22", CONF_VEHICLES: "0=Standard, 2=Guest"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_WALLBOX_POWER: "22",
        CONF_VEHICLES: {"0": "Standard", "2": "Guest"},
    }


def test_translations_have_the_same_keys() -> None:
    """English and German translations cover the same strings."""
    folder = Path(__file__).parents[1] / "custom_components/openwb2mqtt/translations"

    def keys(node: dict, prefix: str = "") -> set[str]:
        result = set()
        for key, value in node.items():
            path = f"{prefix}/{key}"
            result |= keys(value, path) if isinstance(value, dict) else {path}
        return result

    de = json.loads((folder / "de.json").read_text(encoding="utf-8"))
    en = json.loads((folder / "en.json").read_text(encoding="utf-8"))
    assert keys(en) == keys(de)
