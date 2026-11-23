"""Read and write the active charge template of an openWB chargepoint via MQTT.

openWB 2.x keeps the charge template that is currently in effect for a
chargepoint at ``<root>/chargepoint/<id>/set/charge_template`` (a complete JSON
document). openWB core only accepts changes to it as a complete document on
``<root>/set/chargepoint/<id>/set/charge_template``; it rejects topics that try
to set a single key (see packages/helpermodules/setdata.py in openWB/core).
Depending on the "temporary charge templates" setting, core then either keeps
the change on the chargepoint only or also stores it in the vehicle's template.

This module therefore keeps the last template received from openWB, applies a
single change to a copy and publishes the complete document.
"""

from __future__ import annotations

from collections.abc import Callable
import copy
import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)


class ChargeTemplateManager:
    """Keep track of one chargepoint's active charge template."""

    def __init__(self, hass: HomeAssistant, mqtt_root: str, chargepoint_id: int) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.state_topic = f"{mqtt_root}/chargepoint/{chargepoint_id}/set/charge_template"
        self.command_topic = (
            f"{mqtt_root}/set/chargepoint/{chargepoint_id}/set/charge_template"
        )
        # Last template published by openWB.
        self._template: dict[str, Any] | None = None
        # Base for the next change: the last template received or, if a change
        # was published since, that changed template. Without this, two changes
        # made before openWB echoes the first one would overwrite each other.
        self._working: dict[str, Any] | None = None
        self._listeners: list[Callable[[], None]] = []

    @property
    def template(self) -> dict[str, Any] | None:
        """Return the active charge template as last published by openWB."""
        return self._template

    def get(self, path: tuple[str, ...]) -> Any:
        """Return the value at ``path`` in the active template, or None."""
        value: Any = self._template
        for key in path:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return value

    @callback
    def async_add_listener(self, update_callback: Callable[[], None]) -> CALLBACK_TYPE:
        """Call ``update_callback`` whenever openWB publishes a new template."""
        self._listeners.append(update_callback)

        @callback
        def remove_listener() -> None:
            self._listeners.remove(update_callback)

        return remove_listener

    async def async_start(self) -> CALLBACK_TYPE:
        """Subscribe to the template topic. Returns the unsubscribe callback."""
        return await mqtt.async_subscribe(
            self.hass, self.state_topic, self._message_received, 1
        )

    @callback
    def _message_received(self, message: ReceiveMessage) -> None:
        """Store a template published by openWB and notify the entities."""
        if not message.payload:
            return
        try:
            template = json.loads(message.payload)
        except (json.JSONDecodeError, TypeError):
            _LOGGER.warning(
                "Ignoring invalid charge template on %s: %s",
                message.topic,
                message.payload,
            )
            return
        if not isinstance(template, dict):
            return
        self._template = template
        self._working = copy.deepcopy(template)
        for update_callback in list(self._listeners):
            update_callback()

    async def async_set(self, path: tuple[str, ...], value: Any) -> None:
        """Change one value of the template and publish the complete template."""
        if self._working is None:
            raise HomeAssistantError(
                f"No charge template received on {self.state_topic} yet"
            )
        template = copy.deepcopy(self._working)
        node = template
        for key in path[:-1]:
            node = node.get(key)
            if not isinstance(node, dict):
                raise HomeAssistantError(
                    f"Charge template has no '{'/'.join(path)}' entry"
                )
        if path[-1] not in node:
            raise HomeAssistantError(f"Charge template has no '{'/'.join(path)}' entry")
        node[path[-1]] = value
        self._working = template
        _LOGGER.debug("Publishing charge template %s=%s", "/".join(path), value)
        await mqtt.async_publish(
            self.hass, self.command_topic, json.dumps(template), qos=1, retain=False
        )
