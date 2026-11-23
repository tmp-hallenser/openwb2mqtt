"""OpenWB Number Entity."""

from __future__ import annotations

import json
import logging

from homeassistant.components import mqtt
from homeassistant.components.number import (
    DOMAIN as NUMBER_DOMAIN,
    NumberEntity,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .charge_template import ChargeTemplateManager
from .common import OpenWBBaseEntity, async_setup_numbers
from .const import (
    COMM_METHOD_HTTP,
    COMMUNICATION_METHOD,
    CONF_WALLBOX_POWER,
    DEVICEID,
    DEVICETYPE,
    DOMAIN,
    MANUFACTURER,
    MQTT_ROOT_TOPIC,
    NUMBERS_PER_CHARGEPOINT,
    openwbChargeTemplateNumberEntityDescription,
    openWBNumberEntityDescription,
)
from .coordinator import OpenWB2MqttDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, config: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up number entities for openWB."""
    device_type = config.data[DEVICETYPE]
    entities_to_add = []

    if config.data.get(COMMUNICATION_METHOD) == COMM_METHOD_HTTP:
        coordinator = config.runtime_data.coordinator
        if device_type == "chargepoint":
            for description in NUMBERS_PER_CHARGEPOINT:
                if description.api_key is None:
                    continue
                entities_to_add.append(
                    OpenWB2MqttApiNumber(coordinator, description, config)
                )
        async_add_entities(entities_to_add)
    else:
        if device_type == "chargepoint":
            regular_numbers = [
                desc
                for desc in NUMBERS_PER_CHARGEPOINT
                if not isinstance(desc, openwbChargeTemplateNumberEntityDescription)
            ]
            template_numbers = [
                desc
                for desc in NUMBERS_PER_CHARGEPOINT
                if isinstance(desc, openwbChargeTemplateNumberEntityDescription)
            ]

            def process_chargepoint_numbers(
                description, device_type, device_id, mqtt_root
            ):
                description.mqttTopicCommand = (
                    f"{mqtt_root}/{description.mqttTopicCommand}"
                )
                description.mqttTopicCurrentValue = f"{mqtt_root}/{device_type}/{device_id}/{description.mqttTopicCurrentValue}"

            await async_setup_numbers(
                hass,
                config,
                async_add_entities,
                regular_numbers,
                "{mqtt_root}/{device_type}/{device_id}/{key}",
                "Chargepoint",
                process_chargepoint_numbers,
            )

            manager = config.runtime_data.charge_template
            async_add_entities(
                openwbChargeTemplateNumber(
                    config_entry=config,
                    uniqueID=config.unique_id,
                    description=desc,
                    device_friendly_name=f"Chargepoint {config.data[DEVICEID]}",
                    mqtt_root=config.data[MQTT_ROOT_TOPIC],
                    manager=manager,
                )
                for desc in template_numbers
            )


class OpenWB2MqttApiNumber(CoordinatorEntity, NumberEntity):
    """Entity representing openWB numbers that are updated via API."""

    entity_description: openWBNumberEntityDescription

    def __init__(
        self,
        coordinator: OpenWB2MqttDataUpdateCoordinator,
        description: openWBNumberEntityDescription,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self.config_entry = config_entry
        self._attr_unique_id = slugify(f"{config_entry.title}_{description.name}")
        self.entity_id = (
            f"{NUMBER_DOMAIN}.{slugify(f'{config_entry.title}_{description.name}')}"
        )

    @property
    def native_max_value(self) -> float:
        """Return the maximum value."""
        if self.entity_description.key in {
            "instant_charging_current_control",
            "pv_charging_min_current_control",
        }:
            power = self.config_entry.options.get(
                CONF_WALLBOX_POWER, self.config_entry.data.get(CONF_WALLBOX_POWER)
            )
            if power == "11":
                return 16
            return 32
        return self.entity_description.native_max_value

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None
        if self.entity_description.api_key:
            key = self.entity_description.api_key
        value = self.coordinator.data.get(key)
        if self.entity_description.api_value_fn:
            return self.entity_description.api_value_fn(value)
        return value

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        command_key = self.entity_description.api_key_command
        state_key = self.entity_description.api_key
        chargepoint_nr = self.config_entry.data[DEVICEID]

        if not command_key or not state_key:
            return

        payload = f"{command_key}={value}&chargepoint_nr={chargepoint_nr}"

        response = await self.coordinator.client.async_set_data(payload)
        if (
            response
            and response.get("success")
            and "data" in response
            and command_key in response["data"]
        ):
            new_data = self.coordinator.data.copy()
            if command_key == "instant_charging_amount":
                try:
                    new_data[state_key] = 1000 * float(response["data"][command_key])
                except (ValueError, TypeError):
                    new_data[state_key] = None
            else:
                new_data[state_key] = response["data"][command_key]
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


class openWBNumber(OpenWBBaseEntity, NumberEntity):
    """Entity representing openWB numbers."""

    entity_description: openWBNumberEntityDescription

    def __init__(
        self,
        uniqueID: str,
        device_friendly_name: str,
        mqtt_root: str,
        description: openWBNumberEntityDescription,
        deviceID: int | None = None,
        state: float | None = None,
        native_min_value: float | None = None,
        native_max_value: float | None = None,
        native_step: float | None = None,
        mode: NumberMode = NumberMode.AUTO,
    ) -> None:
        """Initialize the sensor and the openWB device."""
        super().__init__(
            device_friendly_name=device_friendly_name,
            mqtt_root=mqtt_root,
        )

        self.entity_description = description
        self._attr_unique_id = slugify(f"{uniqueID}-{description.name}")
        self.entity_id = f"{NUMBER_DOMAIN}.{slugify(f'{uniqueID}_{description.name}')}"
        self._attr_name = description.name

        self._attr_native_value = state
        self._attr_mode = mode

        self.deviceID = deviceID
        self.mqtt_root = mqtt_root
        # Vehicle connected to the chargepoint, for commands addressed to it.
        self._vehicle_id: int | None = None

        if native_min_value is not None:
            self._attr_native_min_value = native_min_value
        if native_max_value is not None:
            self._attr_native_max_value = native_max_value
        if native_step is not None:
            self._attr_native_step = native_step

    async def async_added_to_hass(self):
        """Subscribe to MQTT events."""

        @callback
        def message_received(message):
            """Handle new MQTT messages.

            If defined, convert values.
            """
            if self.entity_description.value_fn is not None:
                self._attr_native_value = self.entity_description.value_fn(
                    message.payload
                )
            else:
                self._attr_native_value = message.payload
            self.async_write_ha_state()

        # Subscribe to MQTT topic and connect callack message
        _LOGGER.debug(
            "Subscribed to MQTT topic: %s",
            self.entity_description.mqttTopicCurrentValue,
        )
        await self.async_subscribe_topic(
            self.entity_description.mqttTopicCurrentValue, message_received
        )

        if "_vehicleID_" in (self.entity_description.mqttTopicCommand or ""):

            @callback
            def vehicle_info_received(message):
                """Remember which vehicle is connected to the chargepoint."""
                try:
                    self._vehicle_id = int(json.loads(message.payload)["id"])
                except (ValueError, TypeError, KeyError) as err:
                    _LOGGER.debug("No vehicle ID in %s: %s", message.topic, err)
                    self._vehicle_id = None

            await self.async_subscribe_topic(
                f"{self.mqtt_root}/chargepoint/{self.deviceID}/get/connected_vehicle/info",
                vehicle_info_received,
            )

    async def async_set_native_value(self, value):
        """Update the current value.

        After set_vative_value --> the result is published to MQTT.
        But the HA sensor shall only change when the MQTT message on the /get/ topic is received.
        Only then, openWB has changed the setting as well.
        """
        if slugify("Ladestromvorgabe (PV Laden)") in self.entity_id:
            success = await self.publishToMQTT(int(value))
            if success:
                self._attr_native_value = value
                self.async_write_ha_state()
        else:
            success = await self.publishToMQTT(value)
        if success:
            return
        _LOGGER.error("Error publishing MQTT message")

    async def publishToMQTT(self, valueToPublish: float) -> bool:
        """Publish message to MQTT.

        If necessary, placeholders in MQTT topic are replaced.
        """
        publish_mqtt_message = False
        topic = self.entity_description.mqttTopicCommand

        # For the special SoC topic, we need to replace the _vehicleID_ placeholder
        # with the actual vehicle ID associated with this charge point
        if "_vehicleID_" in topic:
            if self._vehicle_id is None:
                raise HomeAssistantError(
                    f"No vehicle connected to chargepoint {self.deviceID}"
                )
            topic = topic.replace("_vehicleID_", str(self._vehicle_id))
            publish_mqtt_message = True
        else:
            publish_mqtt_message = True

        _LOGGER.debug("MQTT topic: %s", topic)

        payload = str(valueToPublish)
        _LOGGER.debug("MQTT payload: %s", payload)

        if publish_mqtt_message:
            # Use the modified topic with replaced placeholders
            await mqtt.async_publish(self.hass, topic, payload)

        return publish_mqtt_message


class openwbChargeTemplateNumber(OpenWBBaseEntity, NumberEntity):
    """Number for a value in the chargepoint's active charge template."""

    entity_description: openwbChargeTemplateNumberEntityDescription

    def __init__(
        self,
        config_entry: ConfigEntry,
        uniqueID: str,
        device_friendly_name: str,
        mqtt_root: str,
        description: openwbChargeTemplateNumberEntityDescription,
        manager: ChargeTemplateManager,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(
            device_friendly_name=device_friendly_name,
            mqtt_root=mqtt_root,
        )
        self.config_entry = config_entry
        self.entity_description = description
        self._attr_unique_id = slugify(f"{uniqueID}-{description.name}")
        self.entity_id = f"{NUMBER_DOMAIN}.{slugify(f'{uniqueID}_{description.name}')}"
        self._attr_name = description.name
        self._manager = manager

        if description.max_from_wallbox_power or description.key in {
            "instant_charging_current_control",
            "pv_charging_min_current_control",
        }:
            power = config_entry.options.get(
                CONF_WALLBOX_POWER, config_entry.data.get(CONF_WALLBOX_POWER)
            )
            self._attr_native_max_value = 16 if power == "11" else 32

    @property
    def available(self) -> bool:
        """Unavailable while the template lacks the entity's required part."""
        path = self.entity_description.available_path
        return path is None or self._manager.get(path) is not None

    @property
    def native_value(self) -> float | None:
        """Return the value from the charge template in the entity's unit."""
        value = self._manager.get(self.entity_description.template_path)
        if value is None:
            return None
        if self.entity_description.from_template is not None:
            return self.entity_description.from_template(value)
        return value

    async def async_added_to_hass(self) -> None:
        """Update the state whenever openWB publishes the charge template."""
        self.async_on_remove(
            self._manager.async_add_listener(self.async_write_ha_state)
        )

    async def async_set_native_value(self, value: float) -> None:
        """Write the value into the charge template.

        The state changes once openWB publishes the updated template.
        Values in ``extra_changes`` are written in the same message, e.g. the
        target SoC also switches the plan's limit to "soc".
        """
        await self._manager.async_set_many(
            [
                (
                    self.entity_description.template_path,
                    self.entity_description.to_template(value),
                ),
                *self.entity_description.extra_changes,
            ]
        )
