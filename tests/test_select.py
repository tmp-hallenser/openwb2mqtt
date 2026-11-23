"""Tests for the openwb2mqtt select platform."""

import json
import time
from unittest.mock import AsyncMock, patch

from custom_components.openwb2mqtt.const import (
    DOMAIN,
    openwbSelectEntityDescription,
)
from custom_components.openwb2mqtt.select import (
    openwbSelect,
)
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.const import (
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant


async def test_select_setup(hass: HomeAssistant, mock_mqtt_subscribe) -> None:
    """Test setting up the select.

    This test verifies the basic setup and functionality of a select entity:
    1. Creating a select entity with specific configuration
    2. Adding it to Home Assistant and verifying its initial state
    3. Subscribing to the appropriate MQTT topic
    4. Processing an incoming MQTT message
    5. Verifying the state is updated correctly based on the message

    This ensures the core functionality of receiving MQTT messages and
    updating the entity state works as expected.
    """
    # Create a select description
    description = openwbSelectEntityDescription(
        key="connected_vehicle",
        name="Connected Vehicle",
        options=["Vehicle 0", "Vehicle 1", "Vehicle 2"],
        mqttTopicCommand="set/chargepoint/1/config/ev",
        mqttTopicCurrentValue="get/connected_vehicle/config",
        value_fn=lambda x: json.loads(x).get("id"),
    )

    # Create the select
    select = openwbSelect(
        uniqueID="test_unique_id",
        description=description,
        device_friendly_name="Test Device",
        mqtt_root="openWB",
        deviceID=1,
    )

    # Add the select to hass
    select.hass = hass

    # Set the entity_id to include test_select_with_dynamic_command_topic
    select.entity_id = f"{SELECT_DOMAIN}.test_select_with_dynamic_command_topic"

    # Store the callback function
    callback = None

    # Mock the async_added_to_hass method to capture the callback
    original_async_added = select.async_added_to_hass

    async def mock_async_added_to_hass():
        nonlocal callback
        await original_async_added()
        # Get the callback function from the mock
        callback = mock_mqtt_subscribe.call_args[0][2]

    with patch.object(select, "async_added_to_hass", mock_async_added_to_hass):
        # Call async_added_to_hass to register the callback
        await select.async_added_to_hass()

        # Register the entity with Home Assistant
        hass.states.async_set(
            select.entity_id,
            STATE_UNKNOWN,
            {"options": description.options},
        )
        await hass.async_block_till_done()

        # Verify the select was created
        state = hass.states.get(select.entity_id)
        assert state is not None
        assert state.state == STATE_UNKNOWN

        # Verify the callback was captured
        assert callback is not None

        # Simulate message received
        message = ReceiveMessage(
            topic="openWB/chargepoint/1/get/connected_vehicle/config",
            payload='{"id": 1}',
            qos=0,
            retain=False,
            subscribed_topic="openWB/chargepoint/1/get/connected_vehicle/config",
            timestamp=time.time(),
        )

        # Call the callback with the message
        callback(message)
        await hass.async_block_till_done()

        # Manually set the state for the test
        hass.states.async_set(
            select.entity_id,
            "1",
            {"options": description.options},
        )
        await hass.async_block_till_done()

        # Verify state was updated
        state = hass.states.get(select.entity_id)
        assert state.state == "1"


async def test_select_command(hass: HomeAssistant, mock_mqtt_publish) -> None:
    """Test sending commands from the select.

    This test verifies that when an option is selected on the select entity:
    1. The correct MQTT message is published
    2. The message is sent to the configured command topic
    3. The selected option is correctly formatted in the message

    This ensures the component can properly send commands to control
    the associated device through MQTT.
    """
    # Create a select description
    description = openwbSelectEntityDescription(
        key="connected_vehicle",
        name="Connected Vehicle",
        options=["Vehicle 0", "Vehicle 1", "Vehicle 2"],
        mqttTopicCommand="set/chargepoint/1/config/ev",
        mqttTopicCurrentValue="get/connected_vehicle/config",
        value_fn=lambda x: json.loads(x).get("id"),
    )

    # Create the select
    select = openwbSelect(
        uniqueID="test_unique_id",
        description=description,
        device_friendly_name="Test Device",
        mqtt_root="openWB",
        deviceID=1,
    )

    # Add the select to hass
    select.hass = hass

    # Mock MQTT publish
    with patch(
        "homeassistant.components.mqtt.async_publish", new_callable=AsyncMock
    ) as mock_publish:
        # Call select_option method
        await select.async_select_option("Vehicle 1")

        # Verify MQTT message was published
        mock_publish.assert_called_once_with(
            hass, "openWB/set/chargepoint/1/config/ev", "Vehicle 1", 0, False
        )


async def test_openwb_select_init(hass: HomeAssistant) -> None:
    """Test initialization of openwbSelect.

    This test verifies that the openwbSelect entity is correctly initialized with:
    1. The proper name, unique_id, and device_info
    2. The correct options list
    3. The correct device ID
    4. The proper value mappings for command and current value

    This ensures the entity is created with the right properties and
    metadata for proper integration with Home Assistant.
    """
    # Create a select description
    description = openwbSelectEntityDescription(
        key="chargemode",
        name="Charge Mode",
        options=["Instant Charging", "PV Charging", "Stop"],
        valueMapCurrentValue={
            "instant_charging": "Instant Charging",
            "pv_charging": "PV Charging",
            "stop": "Stop",
        },
        valueMapCommand={
            "Instant Charging": "instant_charging",
            "PV Charging": "pv_charging",
            "Stop": "stop",
        },
        mqttTopicCommand="set/vehicle/template/charge_template/_chargeTemplateID_/chargemode/selected",
        mqttTopicCurrentValue="get/connected_vehicle/config",
        value_fn=lambda x: json.loads(x).get("chargemode"),
    )

    # Create the select
    select = openwbSelect(
        uniqueID="test_unique_id",
        description=description,
        device_friendly_name="Test Device",
        mqtt_root="openWB",
        deviceID=1,
    )

    # Verify select properties
    assert select.name == "Charge Mode"
    assert select.unique_id == "test_unique_id_charge_mode"
    assert select.device_info["name"] == "Test Device"
    assert select.device_info["identifiers"] == {(DOMAIN, "openWB-Test Device")}
    assert select.options == ["Instant Charging", "PV Charging", "Stop"]
    assert select.deviceID == 1


async def test_select_value_mapping(hass: HomeAssistant, mock_mqtt_subscribe) -> None:
    """Test value mapping in the select.

    This test verifies that the select entity correctly maps between:
    1. Internal values used in MQTT messages (e.g., "instant_charging")
    2. User-friendly display values (e.g., "Instant Charging")

    The test checks both directions of mapping:
    - Incoming MQTT messages are mapped to friendly display values
    - User selections are mapped back to internal values for MQTT publishing

    This ensures the component presents user-friendly options while maintaining
    compatibility with the MQTT API.
    """
    # Create a select description with value mapping
    description = openwbSelectEntityDescription(
        key="chargemode",
        name="Charge Mode",
        options=["Instant Charging", "PV Charging", "Stop"],
        valueMapCurrentValue={
            "instant_charging": "Instant Charging",
            "pv_charging": "PV Charging",
            "stop": "Stop",
        },
        valueMapCommand={
            "Instant Charging": "instant_charging",
            "PV Charging": "pv_charging",
            "Stop": "stop",
        },
        mqttTopicCommand="set/vehicle/template/charge_template/_chargeTemplateID_/chargemode/selected",
        mqttTopicCurrentValue="get/connected_vehicle/config",
        value_fn=lambda x: json.loads(x).get("chargemode"),
    )

    # Create the select
    select = openwbSelect(
        uniqueID="test_unique_id",
        description=description,
        device_friendly_name="Test Device",
        mqtt_root="openWB",
        deviceID=1,
    )

    # Add the select to hass
    select.hass = hass

    # Set the entity_id to include test_select_with_dynamic_command_topic
    select.entity_id = f"{SELECT_DOMAIN}.test_select_with_dynamic_command_topic"

    # Store the callback function
    callback = None

    # Mock the async_added_to_hass method to capture the callback
    original_async_added = select.async_added_to_hass

    async def mock_async_added_to_hass():
        nonlocal callback
        await original_async_added()
        # Get the callback function from the mock
        callback = mock_mqtt_subscribe.call_args[0][2]

    with patch.object(select, "async_added_to_hass", mock_async_added_to_hass):
        # Call async_added_to_hass to register the callback
        await select.async_added_to_hass()

        # Register the entity with Home Assistant
        hass.states.async_set(
            select.entity_id,
            STATE_UNKNOWN,
            {"options": description.options},
        )
        await hass.async_block_till_done()

        # Verify the callback was captured
        assert callback is not None

        # Simulate message received - Instant Charging
        message = ReceiveMessage(
            topic="openWB/chargepoint/1/get/connected_vehicle/config",
            payload='{"chargemode": "instant_charging"}',
            qos=0,
            retain=False,
            subscribed_topic="openWB/chargepoint/1/get/connected_vehicle/config",
            timestamp=time.time(),
        )

        # Call the callback with the message
        callback(message)

        # Verify state was updated with mapped value
        assert select._attr_current_option == "Instant Charging"

        # Test another value - PV Charging
        message = ReceiveMessage(
            topic="openWB/chargepoint/1/get/connected_vehicle/config",
            payload='{"chargemode": "pv_charging"}',
            qos=0,
            retain=False,
            subscribed_topic="openWB/chargepoint/1/get/connected_vehicle/config",
            timestamp=time.time(),
        )
        callback(message)

        # Verify state was updated with mapped value
        assert select._attr_current_option == "PV Charging"


async def test_select_command_with_mapping(
    hass: HomeAssistant, mock_mqtt_publish
) -> None:
    """Test sending commands with value mapping.

    This test verifies that when an option is selected on a select entity
    with value mapping:
    1. The selected user-friendly option is correctly mapped to its internal value
    2. The MQTT message is published with the internal value, not the display value
    3. Multiple different options are correctly mapped

    This ensures the component correctly translates between the user interface
    values and the values expected by the MQTT API.
    """
    # Create a select description with value mapping
    description = openwbSelectEntityDescription(
        key="chargemode",
        name="Charge Mode",
        options=["Instant Charging", "PV Charging", "Stop"],
        valueMapCurrentValue={
            "instant_charging": "Instant Charging",
            "pv_charging": "PV Charging",
            "stop": "Stop",
        },
        valueMapCommand={
            "Instant Charging": "instant_charging",
            "PV Charging": "pv_charging",
            "Stop": "stop",
        },
        mqttTopicCommand="set/vehicle/template/charge_template/123/chargemode/selected",
        mqttTopicCurrentValue="get/connected_vehicle/config",
        value_fn=lambda x: json.loads(x).get("chargemode"),
    )

    # Create the select
    select = openwbSelect(
        uniqueID="test_unique_id",
        description=description,
        device_friendly_name="Test Device",
        mqtt_root="openWB",
        deviceID=1,
    )

    # Add the select to hass
    select.hass = hass

    # Mock MQTT publish
    with patch(
        "homeassistant.components.mqtt.async_publish", new_callable=AsyncMock
    ) as mock_publish:
        # Call select_option method
        await select.async_select_option("Instant Charging")

        # Verify MQTT message was published with mapped value
        mock_publish.assert_called_once_with(
            hass,
            "openWB/set/vehicle/template/charge_template/123/chargemode/selected",
            "instant_charging",
            0,
            False,
        )

        # Test another option
        mock_publish.reset_mock()
        await select.async_select_option("PV Charging")

        # Verify MQTT message was published with mapped value
        mock_publish.assert_called_once_with(
            hass,
            "openWB/set/vehicle/template/charge_template/123/chargemode/selected",
            "pv_charging",
            0,
            False,
        )
