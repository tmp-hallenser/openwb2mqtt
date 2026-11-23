"""Departure time of the openWB target charging plan (MQTT)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
import logging
from typing import Any

from homeassistant.components.datetime import DOMAIN as DATETIME_DOMAIN, DateTimeEntity
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util, slugify

from .charge_template import ChargeTemplateManager
from .common import OpenWBBaseEntity
from .const import (
    COMM_METHOD_HTTP,
    COMMUNICATION_METHOD,
    DATETIMES_PER_CHARGEPOINT,
    DEVICEID,
    DEVICETYPE,
    MQTT_ROOT_TOPIC,
    openwbChargeTemplateDateTimeEntityDescription,
)
from .data import OpenWBConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OpenWBConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the datetime entities of an MQTT chargepoint."""
    if (
        config_entry.data.get(COMMUNICATION_METHOD) == COMM_METHOD_HTTP
        or config_entry.data[DEVICETYPE] != "chargepoint"
    ):
        return
    manager = config_entry.runtime_data.charge_template
    async_add_entities(
        openwbScheduledPlanDateTime(
            uniqueID=config_entry.unique_id,
            description=description,
            device_friendly_name=f"Chargepoint {config_entry.data[DEVICEID]}",
            mqtt_root=config_entry.data[MQTT_ROOT_TOPIC],
            manager=manager,
        )
        for description in DATETIMES_PER_CHARGEPOINT
    )


def next_departure(plan: Any, now: datetime) -> datetime | None:
    """Return the next target time of an openWB target charging plan.

    Mirrors openWB's own calculation (helpermodules/timecheck.py):
    - "once": the date in frequency.once at plan.time (may be in the past)
    - "daily": the next occurrence of plan.time
    - "weekly": the next day with frequency.weekly[weekday] (Monday = 0)
    Times are wall-clock times in ``now``'s time zone.
    """
    try:
        hour, minute = (int(part) for part in plan["time"].split(":"))
        frequency = plan["frequency"]
        selected = frequency["selected"]
        if selected == "once":
            return datetime.combine(
                date.fromisoformat(frequency["once"]),
                time(hour, minute),
                tzinfo=now.tzinfo,
            )
        if selected == "daily":
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return candidate if candidate > now else candidate + timedelta(days=1)
        if selected == "weekly":
            weekly = frequency["weekly"]
            for offset in range(8):
                day = now + timedelta(days=offset)
                if weekly[day.weekday()]:
                    candidate = day.replace(
                        hour=hour, minute=minute, second=0, microsecond=0
                    )
                    if candidate > now:
                        return candidate
            return None
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as err:
        _LOGGER.debug("Cannot read the departure from plan %s: %s", plan, err)
        return None
    _LOGGER.debug("Unknown plan frequency %s", selected)
    return None


class openwbScheduledPlanDateTime(OpenWBBaseEntity, DateTimeEntity):
    """Departure (target time) of the chargepoint's first target charging plan.

    openWB stores the time as wall-clock time of the wallbox; Home Assistant's
    time zone is assumed to be the same.
    """

    entity_description: openwbChargeTemplateDateTimeEntityDescription

    def __init__(
        self,
        uniqueID: str | None,
        device_friendly_name: str,
        mqtt_root: str,
        description: openwbChargeTemplateDateTimeEntityDescription,
        manager: ChargeTemplateManager,
    ) -> None:
        """Initialize the entity."""
        super().__init__(
            device_friendly_name=device_friendly_name,
            mqtt_root=mqtt_root,
        )
        self.entity_description = description
        self._attr_unique_id = slugify(f"{uniqueID}-{description.name}")
        self.entity_id = (
            f"{DATETIME_DOMAIN}.{slugify(f'{uniqueID}_{description.name}')}"
        )
        self._attr_name = description.name
        self._manager = manager
        self._unsub_refresh: CALLBACK_TYPE | None = None

    @property
    def _plan(self) -> Any:
        return self._manager.get(self.entity_description.plan_path)

    @property
    def available(self) -> bool:
        """Unavailable while the template has no target charging plan."""
        return isinstance(self._plan, dict)

    @property
    def native_value(self) -> datetime | None:
        """Return the plan's next target time."""
        plan = self._plan
        if not isinstance(plan, dict):
            return None
        return next_departure(plan, dt_util.now())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Show which openWB plan is controlled."""
        paths = self.entity_description.attribute_paths
        if not paths:
            return None
        return {
            name: self._manager.get((*self.entity_description.plan_path, *path))
            for name, path in paths.items()
        }

    async def async_added_to_hass(self) -> None:
        """Update the state whenever openWB publishes the charge template."""
        self.async_on_remove(self._manager.async_add_listener(self._handle_update))
        self.async_on_remove(self._cancel_refresh)
        self._schedule_refresh()

    @callback
    def _handle_update(self) -> None:
        self._schedule_refresh()
        self.async_write_ha_state()

    @callback
    def _cancel_refresh(self) -> None:
        if self._unsub_refresh is not None:
            self._unsub_refresh()
            self._unsub_refresh = None

    @callback
    def _schedule_refresh(self) -> None:
        """For daily/weekly plans, move on to the next occurrence when it passes."""
        self._cancel_refresh()
        value = self.native_value
        plan = self._plan
        if value is None or not isinstance(plan, dict):
            return
        if plan.get("frequency", {}).get("selected") not in ("daily", "weekly"):
            return

        @callback
        def refresh(_now: datetime) -> None:
            self._unsub_refresh = None
            self._handle_update()

        self._unsub_refresh = async_track_point_in_time(
            self.hass, refresh, value + timedelta(seconds=1)
        )

    async def async_set_value(self, value: datetime) -> None:
        """Set a one-time departure: frequency "once" with this date and time.

        Date, time and frequency are published in one message. The weekly
        days are left unchanged.
        """
        local = dt_util.as_local(value).replace(second=0, microsecond=0)
        if local <= dt_util.now():
            raise ServiceValidationError(
                f"The departure {local:%Y-%m-%d %H:%M} is in the past"
            )
        plan_path = self.entity_description.plan_path
        await self._manager.async_set_many(
            [
                ((*plan_path, "frequency", "selected"), "once"),
                ((*plan_path, "frequency", "once"), local.date().isoformat()),
                ((*plan_path, "time"), local.strftime("%H:%M")),
            ]
        )
