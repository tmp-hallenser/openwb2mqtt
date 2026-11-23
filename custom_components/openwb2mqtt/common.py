"""The openwbmqtt component for controlling the openWB wallbox via home assistant / MQTT."""

from __future__ import annotations

from collections.abc import Callable
import copy
import logging
from typing import Any, TypeVar

from homeassistant.components import mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICEID, DEVICETYPE, DOMAIN, MANUFACTURER, MODEL, MQTT_ROOT_TOPIC

_LOGGER = logging.getLogger(__name__)

# Type variable for entity classes
T = TypeVar("T", bound=Entity)


def device_identifier(mqtt_root: str, device_friendly_name: str) -> tuple[str, str]:
    """Return the device registry identifier of an MQTT device."""
    return (DOMAIN, f"{mqtt_root}-{device_friendly_name}")


@callback
def async_migrate_device_identifiers(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Convert (domain, name, mqtt_root) identifiers to device_identifier().

    Device registry identifiers are (domain, id) pairs. Earlier versions used a
    three-element tuple. Updating the existing devices keeps their IDs, names
    set by the user, areas and the entities attached to them.
    """
    device_registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if not any(
            ident[0] == DOMAIN and len(ident) == 3 for ident in device.identifiers
        ):
            continue
        new_identifiers = {
            device_identifier(ident[2], ident[1])
            if ident[0] == DOMAIN and len(ident) == 3
            else ident
            for ident in device.identifiers
        }
        _LOGGER.debug(
            "Migrating device %s identifiers %s -> %s",
            device.id,
            device.identifiers,
            new_identifiers,
        )
        device_registry.async_update_device(device.id, new_identifiers=new_identifiers)


class OpenWBBaseEntity:
    """Openwallbox entity base class."""

    deviceID: int | None = None

    def __init__(
        self,
        device_friendly_name: str,
        mqtt_root: str,
    ) -> None:
        """Init device info class."""
        self.device_friendly_name = device_friendly_name
        self.mqtt_root = mqtt_root

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device information."""
        return DeviceInfo(
            name=self.device_friendly_name,
            identifiers={device_identifier(self.mqtt_root, self.device_friendly_name)},
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    async def async_subscribe_topic(
        self,
        topic: str,
        msg_callback: Callable[[ReceiveMessage], None],
        qos: int = 1,
    ) -> None:
        """Subscribe to an MQTT topic for the lifetime of this entity.

        The subscription is removed automatically when the entity is removed,
        for example when the config entry is reloaded after an options change.
        """
        self.async_on_remove(
            await mqtt.async_subscribe(self.hass, topic, msg_callback, qos)
        )


async def async_setup_entities(
    hass: HomeAssistant,
    config: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    entity_descriptions: list[Any],
    entity_class: type[T],
    topic_template: str,
    device_type_name: str = None,
    additional_processing: Callable[[Any, str, int, str], None] = None,
) -> None:
    """Set up entities for a specific platform and device type.

    Args:
        hass: The Home Assistant instance
        config: The config entry
        async_add_entities: Callback to add entities
        entity_descriptions: List of entity descriptions
        entity_class: The entity class to instantiate
        topic_template: Template for MQTT topic with placeholders
        device_type_name: Optional friendly name for the device type (defaults to devicetype)
        additional_processing: Optional callback for additional entity description processing
    """
    integration_unique_id = config.unique_id
    mqtt_root = config.data[MQTT_ROOT_TOPIC]
    device_type = config.data[DEVICETYPE]
    device_id = config.data[DEVICEID]

    # Use provided device type name or capitalize the device type
    if device_type_name is None:
        device_type_name = device_type.capitalize()

    entities = []
    descriptions_copy = copy.deepcopy(entity_descriptions)

    for description in descriptions_copy:
        # Format the MQTT topic using the template
        description.mqttTopicCurrentValue = topic_template.format(
            mqtt_root=mqtt_root,
            device_type=device_type,
            device_id=device_id,
            key=description.key,
        )

        # Call additional processing if provided
        if additional_processing:
            additional_processing(description, device_type, device_id, mqtt_root)

        # Create the entity
        entities.append(
            entity_class(
                uniqueID=integration_unique_id,
                description=description,
                device_friendly_name=f"{device_type_name} {device_id}",
                mqtt_root=mqtt_root,
            )
        )

    async_add_entities(entities)


async def async_setup_sensors(
    hass: HomeAssistant,
    config: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    sensor_descriptions: list[Any],
    topic_template: str,
    device_type_name: str = None,
    additional_processing: Callable[[Any, str, int, str], None] = None,
) -> None:
    """Set up sensor entities."""
    from .sensor import openwbSensor  # noqa: PLC0415

    await async_setup_entities(
        hass,
        config,
        async_add_entities,
        sensor_descriptions,
        openwbSensor,
        topic_template,
        device_type_name,
        additional_processing,
    )


async def async_setup_binary_sensors(
    hass: HomeAssistant,
    config: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    binary_sensor_descriptions: list[Any],
    topic_template: str,
    device_type_name: str = None,
) -> None:
    """Set up binary sensor entities."""
    from .binary_sensor import openwbBinarySensor  # noqa: PLC0415

    await async_setup_entities(
        hass,
        config,
        async_add_entities,
        binary_sensor_descriptions,
        openwbBinarySensor,
        topic_template,
        device_type_name,
    )


async def async_setup_selects(
    hass: HomeAssistant,
    config: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    select_descriptions: list[Any],
    topic_template: str,
    device_type_name: str = None,
    additional_processing: Callable[[Any, str, int, str], None] = None,
) -> None:
    """Set up select entities."""
    from .select import openwbSelect  # noqa: PLC0415

    integration_unique_id = config.unique_id
    mqtt_root = config.data[MQTT_ROOT_TOPIC]
    device_type = config.data[DEVICETYPE]
    device_id = config.data[DEVICEID]

    # Use provided device type name or capitalize the device type
    if device_type_name is None:
        device_type_name = device_type.capitalize()

    entities = []
    descriptions_copy = copy.deepcopy(select_descriptions)

    for description in descriptions_copy:
        # Call additional processing if provided
        if additional_processing:
            additional_processing(description, device_type, device_id, mqtt_root)

        # Create the entity
        entities.append(
            openwbSelect(
                uniqueID=integration_unique_id,
                description=description,
                device_friendly_name=f"{device_type_name} {device_id}",
                mqtt_root=mqtt_root,
                deviceID=device_id,
            )
        )

    async_add_entities(entities)


async def async_setup_numbers(
    hass: HomeAssistant,
    config: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    number_descriptions: list[Any],
    topic_template: str,
    device_type_name: str = None,
    additional_processing: Callable[[Any, str, int, str], None] = None,
) -> None:
    """Set up number entities."""
    from .number import openWBNumber  # noqa: PLC0415

    integration_unique_id = config.unique_id
    mqtt_root = config.data[MQTT_ROOT_TOPIC]
    device_type = config.data[DEVICETYPE]
    device_id = config.data[DEVICEID]

    # Use provided device type name or capitalize the device type
    if device_type_name is None:
        device_type_name = device_type.capitalize()

    entities = []
    descriptions_copy = copy.deepcopy(number_descriptions)

    for description in descriptions_copy:
        # Call additional processing if provided
        if additional_processing:
            additional_processing(description, device_type, device_id, mqtt_root)

        # Create the entity
        entities.append(
            openWBNumber(
                uniqueID=integration_unique_id,
                description=description,
                device_friendly_name=f"{device_type_name} {device_id}",
                mqtt_root=mqtt_root,
                deviceID=device_id,
            )
        )

    async_add_entities(entities)
