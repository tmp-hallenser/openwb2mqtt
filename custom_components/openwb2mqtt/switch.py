"""Switches for openWB charge template values (MQTT)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .charge_template import ChargeTemplateManager
from .common import OpenWBBaseEntity
from .const import (
    COMM_METHOD_HTTP,
    COMMUNICATION_METHOD,
    DEVICEID,
    DEVICETYPE,
    MQTT_ROOT_TOPIC,
    SWITCHES_PER_CHARGEPOINT,
    openwbChargeTemplateSwitchEntityDescription,
)
from .data import OpenWBConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OpenWBConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switches of an MQTT chargepoint."""
    if (
        config_entry.data.get(COMMUNICATION_METHOD) == COMM_METHOD_HTTP
        or config_entry.data[DEVICETYPE] != "chargepoint"
    ):
        return
    manager = config_entry.runtime_data.charge_template
    async_add_entities(
        openwbChargeTemplateSwitch(
            uniqueID=config_entry.unique_id,
            description=description,
            device_friendly_name=f"Chargepoint {config_entry.data[DEVICEID]}",
            mqtt_root=config_entry.data[MQTT_ROOT_TOPIC],
            manager=manager,
        )
        for description in SWITCHES_PER_CHARGEPOINT
    )


class openwbChargeTemplateSwitch(OpenWBBaseEntity, SwitchEntity):
    """Switch for a boolean in the chargepoint's active charge template.

    The state changes once openWB publishes the updated template.
    """

    entity_description: openwbChargeTemplateSwitchEntityDescription

    def __init__(
        self,
        uniqueID: str | None,
        device_friendly_name: str,
        mqtt_root: str,
        description: openwbChargeTemplateSwitchEntityDescription,
        manager: ChargeTemplateManager,
    ) -> None:
        """Initialize the switch."""
        super().__init__(
            device_friendly_name=device_friendly_name,
            mqtt_root=mqtt_root,
        )
        self.entity_description = description
        self._attr_unique_id = slugify(f"{uniqueID}-{description.name}")
        self.entity_id = f"{SWITCH_DOMAIN}.{slugify(f'{uniqueID}_{description.name}')}"
        self._attr_name = description.name
        self._manager = manager

    @property
    def available(self) -> bool:
        """Unavailable while the template lacks the entity's required part."""
        path = self.entity_description.available_path
        return path is None or self._manager.get(path) is not None

    @property
    def is_on(self) -> bool | None:
        """Return the value from the charge template."""
        value = self._manager.get(self.entity_description.template_path)
        return value if isinstance(value, bool) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Show which part of the template is controlled (e.g. the plan name)."""
        paths = self.entity_description.attribute_paths
        if not paths:
            return None
        return {name: self._manager.get(path) for name, path in paths.items()}

    async def async_added_to_hass(self) -> None:
        """Update the state whenever openWB publishes the charge template."""
        self.async_on_remove(
            self._manager.async_add_listener(self.async_write_ha_state)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Write True into the charge template."""
        await self._manager.async_set(self.entity_description.template_path, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Write False into the charge template."""
        await self._manager.async_set(self.entity_description.template_path, False)
