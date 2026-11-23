"""OpenWB Selector."""

from __future__ import annotations

import logging

from homeassistant.components import mqtt
from homeassistant.components.select import DOMAIN as SELECT_DOMAIN, SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .charge_template import ChargeTemplateManager
from .common import OpenWBBaseEntity, async_setup_selects
from .const import (
    COMM_METHOD_HTTP,
    COMMUNICATION_METHOD,
    CONF_VEHICLES,
    DEVICEID,
    DEVICETYPE,
    DOMAIN,
    MANUFACTURER,
    MQTT_ROOT_TOPIC,
    SELECTS_PER_CHARGEPOINT,
    openwbChargeTemplateSelectEntityDescription,
    openwbSelectEntityDescription,
)
from .coordinator import OpenWB2MqttDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize the select and the openWB device."""
    device_type = config_entry.data[DEVICETYPE]
    entities_to_add = []

    if config_entry.data.get(COMMUNICATION_METHOD) == COMM_METHOD_HTTP:
        coordinator = config_entry.runtime_data.coordinator
        if device_type == "chargepoint":
            for description in SELECTS_PER_CHARGEPOINT:
                if description.api_key is None:
                    continue
                entities_to_add.append(
                    OpenWB2MqttApiSelect(coordinator, description, config_entry)
                )
        async_add_entities(entities_to_add)
    else:
        if device_type == "chargepoint":
            regular_selects = [
                desc
                for desc in SELECTS_PER_CHARGEPOINT
                if not isinstance(desc, openwbChargeTemplateSelectEntityDescription)
            ]
            template_selects = [
                desc
                for desc in SELECTS_PER_CHARGEPOINT
                if isinstance(desc, openwbChargeTemplateSelectEntityDescription)
            ]

            def process_chargepoint_selects(
                description, device_type, device_id, mqtt_root
            ):
                if "_chargePointID_" in description.mqttTopicCommand:
                    description.mqttTopicCommand = description.mqttTopicCommand.replace(
                        "_chargePointID_", str(device_id)
                    )
                description.mqttTopicCommand = (
                    f"{mqtt_root}/{description.mqttTopicCommand}"
                )
                description.mqttTopicCurrentValue = f"{mqtt_root}/{device_type}/{device_id}/{description.mqttTopicCurrentValue}"
                if description.mqttTopicOptions is not None:
                    description.mqttTopicOptions = [
                        f"{mqtt_root}/{option}"
                        for option in description.mqttTopicOptions
                    ]

            await async_setup_selects(
                hass,
                config_entry,
                async_add_entities,
                regular_selects,
                "{mqtt_root}/{device_type}/{device_id}/{key}",
                "Chargepoint",
                process_chargepoint_selects,
            )

            manager = config_entry.runtime_data.charge_template
            async_add_entities(
                openwbChargeTemplateSelect(
                    uniqueID=config_entry.unique_id,
                    description=desc,
                    device_friendly_name=f"Chargepoint {config_entry.data[DEVICEID]}",
                    mqtt_root=config_entry.data[MQTT_ROOT_TOPIC],
                    manager=manager,
                )
                for desc in template_selects
            )


class OpenWB2MqttApiSelect(CoordinatorEntity, SelectEntity):
    """Entity representing a select entity that is updated via API."""

    entity_description: openwbSelectEntityDescription

    def __init__(
        self,
        coordinator: OpenWB2MqttDataUpdateCoordinator,
        description: openwbSelectEntityDescription,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self.config_entry = config_entry
        self._attr_unique_id = slugify(f"{config_entry.title}_{description.name}")
        self.entity_id = (
            f"{SELECT_DOMAIN}.{slugify(f'{config_entry.title}_{description.name}')}"
        )

    @property
    def options(self) -> list[str]:
        """Return a set of selectable options."""
        if self.entity_description.key == "connected_vehicle":
            vehicles = self.config_entry.options.get(
                CONF_VEHICLES, self.config_entry.data.get(CONF_VEHICLES, {})
            )
            if len(vehicles) > 0:
                return list(vehicles.values())
            return []
        if self.entity_description.api_value_map_command:
            return list(self.entity_description.api_value_map_command.keys())
        return self.entity_description.options

    @property
    def current_option(self) -> str | None:
        """Return the selected option."""
        if self.coordinator.data is None:
            return None

        if self.entity_description.key == "connected_vehicle":
            return self.coordinator.data.get("connected_vehicle_name")

        key = self.entity_description.api_key
        value = self.coordinator.data.get(key)

        if self.entity_description.api_value_fn:
            value = self.entity_description.api_value_fn(value)
        elif self.entity_description.value_fn:
            value = self.entity_description.value_fn(value)

        if self.entity_description.valueMapCurrentValue:
            return self.entity_description.valueMapCurrentValue.get(value)
        return value

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self._attr_current_option = option
        self.async_write_ha_state()

        command_key: str | None
        payload: str
        chargepoint_nr = self.config_entry.data[DEVICEID]

        command_key = self.entity_description.api_key_command
        value = option
        if self.entity_description.key == "connected_vehicle":
            value = self.coordinator.vehicle_name_to_id_map.get(option, option)
        elif self.entity_description.api_value_map_command:
            value = self.entity_description.api_value_map_command.get(option, option)
        payload = f"{command_key}={value}&chargepoint_nr={chargepoint_nr}"

        state_key = self.entity_description.api_key
        if not command_key or not state_key:
            _LOGGER.error("Missing api_key or api_key_command for %s", self.entity_id)
            return

        response = await self.coordinator.client.async_set_data(payload)
        if (
            response
            and response.get("success")
            and "data" in response
            and command_key in response["data"]
        ):
            new_data = self.coordinator.data.copy()
            new_value = response["data"][command_key]
            if new_value == "eco":
                new_value = "eco_charging"
            new_data[state_key] = new_value
            self.coordinator.async_set_updated_data(new_data)
            return

        # Fallback to refresh if optimistic update fails
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self):
        """Return the device info."""
        return {
            "identifiers": {(DOMAIN, self.config_entry.title)},
            "name": self.config_entry.title,
            "manufacturer": MANUFACTURER,
        }


class openwbSelect(OpenWBBaseEntity, SelectEntity):
    """Entity representing the inverter operation mode."""

    entity_description: openwbSelectEntityDescription

    def __init__(
        self,
        uniqueID: str,
        device_friendly_name: str,
        description: openwbSelectEntityDescription,
        mqtt_root: str,
        deviceID: int | None = None,
    ) -> None:
        """Initialize the sensor and the openWB device."""
        super().__init__(
            device_friendly_name=device_friendly_name,
            mqtt_root=mqtt_root,
        )
        # Initialize the inverter operation mode setting entity.
        self.entity_description = description
        self._attr_unique_id = slugify(f"{uniqueID}-{description.name}")
        self.entity_id = f"{SELECT_DOMAIN}.{slugify(f'{uniqueID}_{description.name}')}"
        self._attr_name = description.name

        self._attr_current_option = None
        self.deviceID = deviceID
        self.mqtt_root = mqtt_root
        # For selects with option topics (connected vehicle): vehicle names
        # published by openWB, by vehicle ID, and the last received value.
        self._option_names: dict[int, str] = {}
        self._raw_value = None

    @property
    def options(self) -> list[str]:
        """Return a set of selectable options.

        Once openWB has published vehicle names, only those vehicles are
        offered instead of the fixed placeholder slots.
        """
        if self._option_names:
            options = [self._option_names[i] for i in sorted(self._option_names)]
            if self._attr_current_option not in (None, *options):
                options.append(self._attr_current_option)
            return options
        if self.entity_description.options is not None:
            return self.entity_description.options
        return []

    @callback
    def _update_current_option(self) -> None:
        """Map the last received value to an option."""
        payload = self._raw_value
        if payload is None:
            self._attr_current_option = None
            return
        try:
            key = int(payload)
        except (ValueError, TypeError):
            key = payload
        if key in self._option_names:
            self._attr_current_option = self._option_names[key]
        elif self.entity_description.valueMapCurrentValue is not None:
            self._attr_current_option = self.entity_description.valueMapCurrentValue.get(
                key, self.entity_description.valueMapCurrentValue.get(payload)
            )
        else:
            self._attr_current_option = payload

    async def async_added_to_hass(self):
        """Subscribe to MQTT events."""

        @callback
        def message_received(message):
            """Handle new MQTT messages.

            If defined, convert and map values.
            """
            payload = message.payload
            # Convert data if a conversion function is defined
            if self.entity_description.value_fn is not None:
                payload = self.entity_description.value_fn(payload)
            self._raw_value = payload
            self._update_current_option()
            self.async_write_ha_state()

        @callback
        def option_received(message):
            """Handle new MQTT messages for vehicle names."""
            try:
                vehicle_id = int(message.topic.split("/")[-2])
                name = str(message.payload).strip().strip('"')
                if name:
                    self._option_names[vehicle_id] = name
                else:
                    # Empty retained payload: vehicle deleted in openWB.
                    self._option_names.pop(vehicle_id, None)
                self._update_current_option()
                self.async_write_ha_state()
                _LOGGER.debug(
                    "Vehicle %s is named %r (from %s)", vehicle_id, name, message.topic
                )
            except (ValueError, TypeError, IndexError) as err:
                _LOGGER.warning(
                    "Unable to process vehicle name from MQTT topic %s: %s",
                    message.topic,
                    err,
                )

        # Subscribe to MQTT topic and connect callback message
        if self.entity_description.mqttTopicCurrentValue is not None:
            await self.async_subscribe_topic(
                self.entity_description.mqttTopicCurrentValue, message_received
            )

        # Subscribe to MQTT topic options and connect callback message
        if self.entity_description.mqttTopicOptions is not None:
            for option in self.entity_description.mqttTopicOptions:
                await self.async_subscribe_topic(option, option_received)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        success = await self.publishToMQTT(option)
        if success:
            # self._attr_current_option = option
            # self.async_write_ha_state()
            return
        _LOGGER.error("Error publishing MQTT message")

    async def publishToMQTT(self, commandValueToPublish) -> bool:
        """Publish message to MQTT.

        If defined, you can remap the value in HA to the value that is required by the integration.
        """
        publish_mqtt_message = False
        topic = self.entity_description.mqttTopicCommand

        if not topic.startswith(f"{self.mqtt_root}/"):
            topic = f"{self.mqtt_root}/{topic}"

        _LOGGER.debug("MQTT topic: %s", topic)

        # Vehicle names published by openWB map to their vehicle ID.
        names_to_ids = {name: str(i) for i, name in self._option_names.items()}
        if commandValueToPublish in names_to_ids:
            payload = names_to_ids[commandValueToPublish]
            publish_mqtt_message = True
        # Modify commandValueToPublish if mapping table is defined
        elif self.entity_description.valueMapCommand is not None:
            try:
                payload = self.entity_description.valueMapCommand.get(
                    commandValueToPublish
                )
                _LOGGER.debug("MQTT payload: %s", payload)
                publish_mqtt_message = True
            except ValueError:
                publish_mqtt_message = False
        else:
            payload = commandValueToPublish
            publish_mqtt_message = True

        if publish_mqtt_message:
            await mqtt.async_publish(self.hass, topic, payload, 0, False)

        return publish_mqtt_message


class openwbChargeTemplateSelect(OpenWBBaseEntity, SelectEntity):
    """Select for a value in the chargepoint's active charge template."""

    entity_description: openwbChargeTemplateSelectEntityDescription

    def __init__(
        self,
        uniqueID: str,
        device_friendly_name: str,
        description: openwbChargeTemplateSelectEntityDescription,
        mqtt_root: str,
        manager: ChargeTemplateManager,
    ) -> None:
        """Initialize the select."""
        super().__init__(
            device_friendly_name=device_friendly_name,
            mqtt_root=mqtt_root,
        )
        self.entity_description = description
        self._attr_unique_id = slugify(f"{uniqueID}-{description.name}")
        self.entity_id = f"{SELECT_DOMAIN}.{slugify(f'{uniqueID}_{description.name}')}"
        self._attr_name = description.name
        self._manager = manager

    @property
    def options(self) -> list[str]:
        """Return the options, plus the current one if openWB uses another value."""
        options = list(self.entity_description.options or [])
        current = self.current_option
        if current is not None and current not in options:
            options.append(current)
        return options

    @property
    def current_option(self) -> str | None:
        """Return the option matching the value in the charge template."""
        value = self._manager.get(self.entity_description.template_path)
        if value is None:
            return None
        value_map = self.entity_description.valueMapCurrentValue
        if value_map is None:
            return str(value)
        return value_map.get(value, str(value))

    async def async_added_to_hass(self) -> None:
        """Update the state whenever openWB publishes the charge template."""
        self.async_on_remove(
            self._manager.async_add_listener(self.async_write_ha_state)
        )

    async def async_select_option(self, option: str) -> None:
        """Write the selected option into the charge template."""
        value_map = self.entity_description.valueMapCommand
        if value_map is not None:
            if option not in value_map:
                raise ServiceValidationError(
                    f"{option} cannot be selected for {self.entity_id}"
                )
            value = value_map[option]
        else:
            value = option
        await self._manager.async_set(self.entity_description.template_path, value)
