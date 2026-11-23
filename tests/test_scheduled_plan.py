"""Tests for the target charging (Zielladen) plan entities (MQTT)."""

from datetime import datetime
import json
from typing import Any
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
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
from custom_components.openwb2mqtt.datetime import next_departure
from homeassistant.components.datetime import (
    ATTR_DATETIME,
    DOMAIN as DATETIME_DOMAIN,
    SERVICE_SET_VALUE as SERVICE_SET_DATETIME,
)
from homeassistant.components.number import (
    ATTR_MAX,
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .test_charge_template import (
    _publish_template,
    _published_templates,
    charge_template,
    scheduled_plan,
)

# HA's MQTT client keeps a periodic timer running after the test.
pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 23, 10, 0, tzinfo=TZ)  # a Monday

# entity_id -> enabled by default
PLAN_ENTITIES = {
    "datetime.openwb_chargepoint_1_abfahrt_zielladen": True,
    "number.openwb_chargepoint_1_ziel_soc_zielladen": True,
    "number.openwb_chargepoint_1_soc_limit_zielladen": True,
    "switch.openwb_chargepoint_1_plan_aktiv_zielladen": True,
    "select.openwb_chargepoint_1_begrenzung_zielladen": True,
    "number.openwb_chargepoint_1_energiemenge_zielladen": False,
    "number.openwb_chargepoint_1_ladestrom_zielladen": False,
    "select.openwb_chargepoint_1_phasen_zielladen": False,
    "select.openwb_chargepoint_1_phasen_pv_zielladen": False,
    "select.openwb_chargepoint_1_wiederholung_zielladen": False,
}
ABFAHRT = "datetime.openwb_chargepoint_1_abfahrt_zielladen"
ZIEL_SOC = "number.openwb_chargepoint_1_ziel_soc_zielladen"
SOC_LIMIT = "number.openwb_chargepoint_1_soc_limit_zielladen"
AKTIV = "switch.openwb_chargepoint_1_plan_aktiv_zielladen"
BEGRENZUNG = "select.openwb_chargepoint_1_begrenzung_zielladen"
ENERGIE = "number.openwb_chargepoint_1_energiemenge_zielladen"
STROM = "number.openwb_chargepoint_1_ladestrom_zielladen"
PHASEN = "select.openwb_chargepoint_1_phasen_zielladen"
PHASEN_PV = "select.openwb_chargepoint_1_phasen_pv_zielladen"


@pytest.fixture(autouse=True)
async def berlin_time(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Use the wallbox's time zone and a fixed 'now'."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(NOW)


async def _setup(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    power: str = "11",
    enable_all: bool = True,
) -> MockConfigEntry:
    """Set up chargepoint 1; optionally enable the disabled-by-default entities."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="openWB-chargepoint-1",
        title="openWB-chargepoint-1",
        data={
            COMMUNICATION_METHOD: COMM_METHOD_MQTT,
            MQTT_ROOT_TOPIC: "openWB",
            DEVICETYPE: "chargepoint",
            DEVICEID: 1,
            CONF_WALLBOX_POWER: power,
        },
    )
    entry.add_to_hass(hass)
    if enable_all:
        for entity_id, enabled in PLAN_ENTITIES.items():
            if not enabled:
                domain, object_id = entity_id.split(".")
                entity_registry.async_get_or_create(
                    domain,
                    DOMAIN,
                    object_id,
                    config_entry=entry,
                    suggested_object_id=object_id,
                )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _plan_published(mqtt_mock: MqttMockHAClient) -> dict[str, Any]:
    (template,) = _published_templates(mqtt_mock)
    return template["chargemode"]["scheduled_charging"]["plans"][0]


async def _call(hass: HomeAssistant, domain: str, service: str, data: dict) -> None:
    await hass.services.async_call(domain, service, data, blocking=True)


# --- entities ---------------------------------------------------------------


async def test_plan_entities_and_ids(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    entity_registry: er.EntityRegistry,
) -> None:
    """All plan entities exist with fixed IDs; the detail ones start disabled."""
    entry = await _setup(hass, entity_registry, enable_all=False)

    for entity_id, enabled in PLAN_ENTITIES.items():
        registry_entry = entity_registry.async_get(entity_id)
        assert registry_entry is not None, entity_id
        assert registry_entry.config_entry_id == entry.entry_id
        assert registry_entry.unique_id == entity_id.split(".")[1]
        assert (registry_entry.disabled_by is None) is enabled, entity_id


async def test_unavailable_without_plan(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    entity_registry: er.EntityRegistry,
) -> None:
    """Without a plan in openWB all plan entities are unavailable."""
    await _setup(hass, entity_registry)
    _publish_template(hass, charge_template(plans=[]))
    await hass.async_block_till_done()

    for entity_id in PLAN_ENTITIES:
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE, entity_id
    # Existing template entities are not affected.
    assert hass.states.get("select.openwb_chargepoint_1_lademodus").state == (
        "Instant Charging"
    )

    # HA does not call services on unavailable entities; nothing is published.
    await _call(
        hass,
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: ZIEL_SOC, ATTR_VALUE: 80},
    )
    assert _published_templates(mqtt_mock) == []


async def test_states_from_plan(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    entity_registry: er.EntityRegistry,
) -> None:
    """The entities show the plan published by openWB."""
    await _setup(hass, entity_registry)
    _publish_template(hass, charge_template())
    await hass.async_block_till_done()

    abfahrt = hass.states.get(ABFAHRT)
    assert datetime.fromisoformat(abfahrt.state) == datetime(
        2026, 5, 24, 7, 0, tzinfo=TZ
    )
    assert abfahrt.attributes["plan_name"] == "neuer Zielladen-Plan"
    assert abfahrt.attributes["plan_id"] == 0
    assert float(hass.states.get(ZIEL_SOC).state) == 80
    assert float(hass.states.get(SOC_LIMIT).state) == 90
    aktiv = hass.states.get(AKTIV)
    assert aktiv.state == "off"
    assert aktiv.attributes["plan_name"] == "neuer Zielladen-Plan"
    assert hass.states.get(BEGRENZUNG).state == "Energiemenge"
    assert float(hass.states.get(ENERGIE).state) == 1.0
    assert float(hass.states.get(STROM).state) == 14
    assert hass.states.get(PHASEN).state == "Automatik"
    assert hass.states.get(PHASEN_PV).state == "Automatik"


# --- E1 departure ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("frequency", "time", "expected"),
    [
        (
            {"selected": "once", "once": "2026-12-01"},
            "06:30",
            datetime(2026, 12, 1, 6, 30),
        ),
        # daily: still ahead today / already passed today
        ({"selected": "daily"}, "11:15", datetime(2026, 11, 23, 11, 15)),
        ({"selected": "daily"}, "07:00", datetime(2026, 11, 24, 7, 0)),
        # weekly, Monday = index 0; today (Monday) 07:00 has passed
        (
            {
                "selected": "weekly",
                "weekly": [True, False, False, True, False, False, False],
            },
            "07:00",
            datetime(2026, 11, 26, 7, 0),
        ),
        (
            {"selected": "weekly", "weekly": [True] + [False] * 6},
            "07:00",
            datetime(2026, 11, 30, 7, 0),
        ),
        ({"selected": "weekly", "weekly": [False] * 7}, "07:00", None),
        # unparsable
        ({"selected": "once", "once": "kaputt"}, "07:00", None),
        ({"selected": "daily"}, "7 Uhr", None),
        ({"selected": "monthly"}, "07:00", None),
    ],
)
def test_next_departure(
    frequency: dict[str, Any], time: str, expected: datetime | None
) -> None:
    """The departure is calculated like openWB's timecheck."""
    plan = scheduled_plan(
        frequency={"once": "2026-05-24", "weekly": [False] * 7, **frequency},
        time=time,
    )
    result = next_departure(plan, NOW)
    assert result == (expected.replace(tzinfo=TZ) if expected else None)


async def test_set_departure(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    entity_registry: er.EntityRegistry,
) -> None:
    """Setting the departure publishes frequency, date and time in one message."""
    await _setup(hass, entity_registry)
    weekly = [True, False, True, False, False, False, False]
    _publish_template(
        hass,
        charge_template(
            plans=[
                scheduled_plan(
                    frequency={
                        "selected": "weekly",
                        "once": "2026-05-24",
                        "weekly": weekly,
                    }
                )
            ]
        ),
    )
    await hass.async_block_till_done()

    departure = datetime(2026, 11, 24, 7, 30, 42, tzinfo=TZ)
    await _call(
        hass,
        DATETIME_DOMAIN,
        SERVICE_SET_DATETIME,
        {ATTR_ENTITY_ID: ABFAHRT, ATTR_DATETIME: departure},
    )
    assert _plan_published(mqtt_mock) == scheduled_plan(
        frequency={"selected": "once", "once": "2026-11-24", "weekly": weekly},
        time="07:30",
    )


async def test_set_departure_in_the_past(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    entity_registry: er.EntityRegistry,
) -> None:
    """A departure in the past is rejected."""
    await _setup(hass, entity_registry)
    _publish_template(hass, charge_template())
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await _call(
            hass,
            DATETIME_DOMAIN,
            SERVICE_SET_DATETIME,
            {
                ATTR_ENTITY_ID: ABFAHRT,
                ATTR_DATETIME: datetime(2026, 11, 23, 9, 0, tzinfo=TZ),
            },
        )
    assert _published_templates(mqtt_mock) == []


async def test_daily_departure_moves_on(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A daily departure shows the next day once today's time has passed."""
    await _setup(hass, entity_registry)
    _publish_template(
        hass,
        charge_template(
            plans=[
                scheduled_plan(
                    frequency={
                        "selected": "daily",
                        "once": "2026-05-24",
                        "weekly": [False] * 7,
                    },
                    time="10:30",
                )
            ]
        ),
    )
    await hass.async_block_till_done()
    assert datetime.fromisoformat(hass.states.get(ABFAHRT).state) == datetime(
        2026, 11, 23, 10, 30, tzinfo=TZ
    )

    freezer.move_to(datetime(2026, 11, 23, 10, 31, tzinfo=TZ))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert datetime.fromisoformat(hass.states.get(ABFAHRT).state) == datetime(
        2026, 11, 24, 10, 30, tzinfo=TZ
    )


# --- numbers, switch, selects -------------------------------------------------


@pytest.mark.parametrize(
    ("entity_id", "value", "limit"),
    [
        (
            ZIEL_SOC,
            80,
            {"selected": "soc", "amount": 1000, "soc_limit": 90, "soc_scheduled": 80},
        ),
        (
            ZIEL_SOC,
            60,
            {"selected": "soc", "amount": 1000, "soc_limit": 90, "soc_scheduled": 60},
        ),
        (
            SOC_LIMIT,
            100,
            {
                "selected": "amount",
                "amount": 1000,
                "soc_limit": 100,
                "soc_scheduled": 80,
            },
        ),
        (
            ENERGIE,
            15,
            {
                "selected": "amount",
                "amount": 15000,
                "soc_limit": 90,
                "soc_scheduled": 80,
            },
        ),
    ],
)
async def test_limit_numbers(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    entity_registry: er.EntityRegistry,
    entity_id: str,
    value: float,
    limit: dict[str, Any],
) -> None:
    """Target SoC switches to 'soc', energy to 'amount', in the same publish."""
    await _setup(hass, entity_registry)
    _publish_template(hass, charge_template())
    await hass.async_block_till_done()

    await _call(
        hass,
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: value},
    )
    assert _plan_published(mqtt_mock) == scheduled_plan(limit=limit)


async def test_plan_active_switch(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    entity_registry: er.EntityRegistry,
) -> None:
    """The switch writes plans[0].active, nothing else (not the charge mode)."""
    await _setup(hass, entity_registry)
    _publish_template(hass, charge_template())
    await hass.async_block_till_done()

    await _call(hass, SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: AKTIV})
    (published,) = _published_templates(mqtt_mock)
    assert published == {
        **charge_template(),
        "chargemode": {
            **charge_template()["chargemode"],
            "scheduled_charging": {"plans": [scheduled_plan(active=True)]},
        },
    }
    _publish_template(hass, published)
    await hass.async_block_till_done()
    assert hass.states.get(AKTIV).state == "on"

    mqtt_mock.async_publish.reset_mock()
    await _call(hass, SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: AKTIV})
    assert _plan_published(mqtt_mock)["active"] is False


@pytest.mark.parametrize(("power", "maximum"), [("11", 16), ("22", 32)])
async def test_plan_current(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    entity_registry: er.EntityRegistry,
    power: str,
    maximum: int,
) -> None:
    """The grid current is limited by the wallbox power option."""
    await _setup(hass, entity_registry, power=power)
    _publish_template(hass, charge_template())
    await hass.async_block_till_done()
    assert hass.states.get(STROM).attributes[ATTR_MAX] == maximum

    await _call(
        hass, NUMBER_DOMAIN, SERVICE_SET_VALUE, {ATTR_ENTITY_ID: STROM, ATTR_VALUE: 10}
    )
    assert _plan_published(mqtt_mock)["current"] == 10


@pytest.mark.parametrize("entity_id", [PHASEN, PHASEN_PV])
@pytest.mark.parametrize(
    ("value", "option"), [(0, "Automatik"), (1, "1 Phase"), (3, "Max. Phasen")]
)
async def test_plan_phases(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    entity_registry: er.EntityRegistry,
    entity_id: str,
    value: int,
    option: str,
) -> None:
    """Phase selects map openWB's 0/1/3 both ways."""
    key = "phases_to_use" if entity_id == PHASEN else "phases_to_use_pv"
    await _setup(hass, entity_registry)
    _publish_template(hass, charge_template(plans=[scheduled_plan(**{key: value})]))
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == option

    other = next(o for o in ("Automatik", "1 Phase", "Max. Phasen") if o != option)
    await _call(
        hass,
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: other},
    )
    assert (
        _plan_published(mqtt_mock)[key]
        == {"Automatik": 0, "1 Phase": 1, "Max. Phasen": 3}[other]
    )


async def test_plan_limit_select(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    entity_registry: er.EntityRegistry,
) -> None:
    """The limit select writes plans[0].limit.selected."""
    await _setup(hass, entity_registry)
    _publish_template(hass, charge_template())
    await hass.async_block_till_done()

    await _call(
        hass,
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: BEGRENZUNG, ATTR_OPTION: "SoC"},
    )
    assert _plan_published(mqtt_mock)["limit"]["selected"] == "soc"


async def test_unrelated_fields_unchanged(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    entity_registry: er.EntityRegistry,
) -> None:
    """Everything outside the changed value survives a JSON round trip unchanged."""
    template = charge_template(
        plans=[
            scheduled_plan(),
            scheduled_plan(id=1, name="zweiter Plan", time="18:00"),
        ]
    )
    template["prio"] = False  # keys the integration does not know
    await _setup(hass, entity_registry)
    _publish_template(hass, template)
    await hass.async_block_till_done()

    await _call(
        hass,
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: SOC_LIMIT, ATTR_VALUE: 95},
    )
    (published,) = _published_templates(mqtt_mock)
    template["chargemode"]["scheduled_charging"]["plans"][0]["limit"]["soc_limit"] = 95
    assert json.dumps(published, sort_keys=True) == json.dumps(template, sort_keys=True)


async def test_script_without_pauses(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    entity_registry: er.EntityRegistry,
) -> None:
    """Four quick changes all stick although openWB's echoes interleave.

    Replays the order seen in production: departure, target SoC, plan on and
    charge mode, each sent before openWB echoed the previous one. Before the
    fix only the departure and the charge mode survived.
    """
    await _setup(hass, entity_registry)
    _publish_template(hass, charge_template())
    await hass.async_block_till_done()

    def echo(index: int) -> None:
        # openWB stores and republishes exactly what it received.
        _publish_template(hass, _published_templates(mqtt_mock)[index])

    departure = datetime(2026, 11, 24, 7, 30, tzinfo=TZ)
    await _call(
        hass,
        DATETIME_DOMAIN,
        SERVICE_SET_DATETIME,
        {ATTR_ENTITY_ID: ABFAHRT, ATTR_DATETIME: departure},
    )
    await _call(
        hass,
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: ZIEL_SOC, ATTR_VALUE: 80},
    )
    echo(0)
    await hass.async_block_till_done()
    await _call(hass, SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: AKTIV})
    echo(1)
    await hass.async_block_till_done()
    await _call(
        hass,
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {
            ATTR_ENTITY_ID: "select.openwb_chargepoint_1_lademodus",
            ATTR_OPTION: "Target Charging",
        },
    )
    echo(2)
    echo(3)
    await hass.async_block_till_done()

    final = _published_templates(mqtt_mock)[-1]
    assert final["chargemode"]["selected"] == "scheduled_charging"
    assert final["chargemode"]["scheduled_charging"]["plans"][0] == scheduled_plan(
        active=True,
        frequency={"selected": "once", "once": "2026-11-24", "weekly": [False] * 7},
        time="07:30",
        limit={"selected": "soc", "amount": 1000, "soc_limit": 90, "soc_scheduled": 80},
    )
    assert datetime.fromisoformat(hass.states.get(ABFAHRT).state) == departure
    assert float(hass.states.get(ZIEL_SOC).state) == 80
    assert hass.states.get(BEGRENZUNG).state == "SoC"
    assert hass.states.get(AKTIV).state == "on"
    assert (
        hass.states.get("select.openwb_chargepoint_1_lademodus").state
        == "Target Charging"
    )
