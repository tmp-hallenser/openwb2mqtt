"""Tests for the charge template selects and numbers (MQTT)."""

import copy
from datetime import timedelta
import json
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
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
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.components.select import (
    ATTR_OPTION,
    ATTR_OPTIONS,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

# HA's MQTT client keeps a periodic timer running after the test.
pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

LADEMODUS = "select.openwb_chargepoint_1_lademodus"
BEGRENZUNG = "select.openwb_chargepoint_1_begrenzung_sofortladen"
STROM = "number.openwb_chargepoint_1_soll_ladestrom_sofortladen"
PV_MIN = "number.openwb_chargepoint_1_min_dauerstrom_pv_laden"
ENERGIE = "number.openwb_chargepoint_1_energie_limit_sofortladen"
SOC = "number.openwb_chargepoint_1_soc_limit_sofortladen"
PREIS = "number.openwb_chargepoint_1_max_preis_strompreisbasiertes_laden"


def charge_template(template_id: int = 1) -> dict[str, Any]:
    """Return a charge template with openWB core 2.3 default values."""
    limit = {"selected": "none", "amount": 50000, "soc": 50}
    return {
        "id": template_id,
        "name": "Profil",
        "load_default": False,
        "time_charging": {"active": False, "plans": []},
        "chargemode": {
            "selected": "instant_charging",
            "eco_charging": {
                "current": 6,
                "dc_current": 145,
                "limit": dict(limit),
                "max_price": 0.0002,
                "phases_to_use": 3,
            },
            "pv_charging": {
                "dc_min_current": 145,
                "dc_min_soc_current": 145,
                "limit": dict(limit),
                "min_current": 0,
                "min_soc_current": 10,
                "min_soc": 0,
                "phases_to_use": 0,
                "phases_to_use_min_soc": 3,
            },
            "scheduled_charging": {"plans": []},
            "instant_charging": {
                "current": 16,
                "dc_current": 145,
                "limit": dict(limit),
                "phases_to_use": 3,
            },
        },
    }


async def _setup_chargepoint(hass: HomeAssistant, chargepoint_id: int = 1) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"openWB-chargepoint-{chargepoint_id}",
        title=f"openWB-chargepoint-{chargepoint_id}",
        data={
            COMMUNICATION_METHOD: COMM_METHOD_MQTT,
            MQTT_ROOT_TOPIC: "openWB",
            DEVICETYPE: "chargepoint",
            DEVICEID: chargepoint_id,
            CONF_WALLBOX_POWER: "11",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _publish_template(
    hass: HomeAssistant, template: dict[str, Any], chargepoint_id: int = 1
) -> None:
    async_fire_mqtt_message(
        hass,
        f"openWB/chargepoint/{chargepoint_id}/set/charge_template",
        json.dumps(template),
        # Live updates reach existing subscribers with retain=False; HA ignores
        # repeated retained messages on an already subscribed topic.
        retain=False,
    )


def _published_templates(
    mqtt_mock: MqttMockHAClient, chargepoint_id: int = 1
) -> list[dict[str, Any]]:
    """Return the templates the integration published for a chargepoint."""
    topic = f"openWB/set/chargepoint/{chargepoint_id}/set/charge_template"
    return [
        json.loads(call.args[1])
        for call in mqtt_mock.async_publish.call_args_list
        if call.args[0] == topic
    ]


async def test_states_follow_the_active_template(
    hass: HomeAssistant, mqtt_mock: MqttMockHAClient
) -> None:
    """All selects and numbers show the values of the chargepoint's template."""
    await _setup_chargepoint(hass)
    assert hass.states.get(LADEMODUS).state == STATE_UNKNOWN

    _publish_template(hass, charge_template())
    await hass.async_block_till_done()

    assert hass.states.get(LADEMODUS).state == "Instant Charging"
    assert hass.states.get(BEGRENZUNG).state == "Keine"
    assert float(hass.states.get(STROM).state) == 16
    assert float(hass.states.get(PV_MIN).state) == 0
    assert float(hass.states.get(ENERGIE).state) == 50.0  # 50000 Wh
    assert float(hass.states.get(SOC).state) == 50
    assert float(hass.states.get(PREIS).state) == 20.0  # 0.0002 EUR/Wh

    template = charge_template()
    template["chargemode"]["selected"] = "scheduled_charging"
    template["chargemode"]["instant_charging"]["limit"]["selected"] = "amount"
    _publish_template(hass, template)
    await hass.async_block_till_done()
    assert hass.states.get(LADEMODUS).state == "Target Charging"
    assert hass.states.get(BEGRENZUNG).state == "Energiemenge"


@pytest.mark.parametrize(
    ("option", "expected"),
    [
        ("Instant Charging", "instant_charging"),
        ("PV Charging", "pv_charging"),
        ("ECO Charging", "eco_charging"),
        ("Target Charging", "scheduled_charging"),
        ("Stop", "stop"),
    ],
)
async def test_select_chargemode_publishes_complete_template(
    hass: HomeAssistant, mqtt_mock: MqttMockHAClient, option: str, expected: str
) -> None:
    """Selecting a charge mode publishes the whole template with one change."""
    await _setup_chargepoint(hass)
    _publish_template(hass, charge_template())
    await hass.async_block_till_done()

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: LADEMODUS, ATTR_OPTION: option},
        blocking=True,
    )

    expected_template = charge_template()
    expected_template["chargemode"]["selected"] = expected
    assert _published_templates(mqtt_mock) == [expected_template]
    # Nothing goes through the optional simpleAPI service any more.
    assert not [
        call
        for call in mqtt_mock.async_publish.call_args_list
        if "simpleAPI" in call.args[0]
    ]


async def test_state_changes_only_when_openwb_confirms(
    hass: HomeAssistant, mqtt_mock: MqttMockHAClient
) -> None:
    """The select keeps the old value until openWB publishes the new template."""
    await _setup_chargepoint(hass)
    _publish_template(hass, charge_template())
    await hass.async_block_till_done()

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: LADEMODUS, ATTR_OPTION: "PV Charging"},
        blocking=True,
    )
    assert hass.states.get(LADEMODUS).state == "Instant Charging"

    _publish_template(hass, _published_templates(mqtt_mock)[0])
    await hass.async_block_till_done()
    assert hass.states.get(LADEMODUS).state == "PV Charging"


async def test_instant_charging_limit_select(
    hass: HomeAssistant, mqtt_mock: MqttMockHAClient
) -> None:
    """The limit select writes chargemode.instant_charging.limit.selected."""
    await _setup_chargepoint(hass)
    _publish_template(hass, charge_template())
    await hass.async_block_till_done()

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: BEGRENZUNG, ATTR_OPTION: "SoC"},
        blocking=True,
    )
    (published,) = _published_templates(mqtt_mock)
    assert published["chargemode"]["instant_charging"]["limit"]["selected"] == "soc"


async def test_bidi_charging_is_shown_when_active(
    hass: HomeAssistant, mqtt_mock: MqttMockHAClient
) -> None:
    """A mode without a regular option (bidi) is shown instead of 'unknown'."""
    await _setup_chargepoint(hass)
    assert "Bidi Charging" not in hass.states.get(LADEMODUS).attributes[ATTR_OPTIONS]

    template = charge_template()
    template["chargemode"]["selected"] = "bidi_charging"
    _publish_template(hass, template)
    await hass.async_block_till_done()

    state = hass.states.get(LADEMODUS)
    assert state.state == "Bidi Charging"
    assert "Bidi Charging" in state.attributes[ATTR_OPTIONS]
    assert "Standby" not in state.attributes[ATTR_OPTIONS]


@pytest.mark.parametrize(
    ("entity_id", "value", "path", "expected"),
    [
        (STROM, 10, ("instant_charging", "current"), 10),
        (PV_MIN, 6, ("pv_charging", "min_current"), 6),
        (ENERGIE, 20, ("instant_charging", "limit", "amount"), 20000),
        (SOC, 80, ("instant_charging", "limit", "soc"), 80),
        (PREIS, 25, ("eco_charging", "max_price"), 0.00025),
    ],
)
async def test_numbers_publish_complete_template(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    entity_id: str,
    value: float,
    path: tuple[str, ...],
    expected: Any,
) -> None:
    """Numbers convert to openWB's units and publish the whole template."""
    await _setup_chargepoint(hass)
    _publish_template(hass, charge_template())
    await hass.async_block_till_done()

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: value},
        blocking=True,
    )

    expected_template = charge_template()
    node = expected_template["chargemode"]
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = expected
    (published,) = _published_templates(mqtt_mock)
    assert published == expected_template
    if isinstance(expected, int):
        assert isinstance(node[path[-1]], int)


async def test_quick_successive_changes_are_combined(
    hass: HomeAssistant, mqtt_mock: MqttMockHAClient
) -> None:
    """A second change made before openWB echoes the first keeps the first one."""
    await _setup_chargepoint(hass)
    _publish_template(hass, charge_template())
    await hass.async_block_till_done()

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: LADEMODUS, ATTR_OPTION: "PV Charging"},
        blocking=True,
    )
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: STROM, ATTR_VALUE: 8},
        blocking=True,
    )

    first, second = _published_templates(mqtt_mock)
    assert first["chargemode"]["selected"] == "pv_charging"
    assert second["chargemode"]["selected"] == "pv_charging"
    assert second["chargemode"]["instant_charging"]["current"] == 8


async def test_change_without_template_raises(
    hass: HomeAssistant, mqtt_mock: MqttMockHAClient
) -> None:
    """Without a template from openWB nothing is published."""
    await _setup_chargepoint(hass)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: LADEMODUS, ATTR_OPTION: "PV Charging"},
            blocking=True,
        )
    assert _published_templates(mqtt_mock) == []


async def test_each_chargepoint_writes_its_own_template(
    hass: HomeAssistant, mqtt_mock: MqttMockHAClient
) -> None:
    """Chargepoint 2 changes chargepoint 2 (simpleAPI used the lowest ID)."""
    await _setup_chargepoint(hass, 1)
    await _setup_chargepoint(hass, 2)
    template_cp2 = charge_template(template_id=7)
    _publish_template(hass, charge_template(), chargepoint_id=1)
    _publish_template(hass, template_cp2, chargepoint_id=2)
    await hass.async_block_till_done()

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {
            ATTR_ENTITY_ID: "number.openwb_chargepoint_2_energie_limit_sofortladen",
            ATTR_VALUE: 12,
        },
        blocking=True,
    )

    assert _published_templates(mqtt_mock, 1) == []
    expected = copy.deepcopy(template_cp2)
    expected["chargemode"]["instant_charging"]["limit"]["amount"] = 12000
    assert _published_templates(mqtt_mock, 2) == [expected]


def _issue(
    issue_registry: ir.IssueRegistry, hass: HomeAssistant
) -> ir.IssueEntry | None:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    return issue_registry.async_get_issue(
        DOMAIN, f"missing_charge_template_{entry.entry_id}"
    )


async def test_repair_issue_when_template_missing(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    issue_registry: ir.IssueRegistry,
) -> None:
    """A missing template (e.g. not bridged) raises a repair issue, cleared on arrival."""
    await _setup_chargepoint(hass)
    assert _issue(issue_registry, hass) is None

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    issue = _issue(issue_registry, hass)
    assert issue is not None
    assert issue.translation_key == "missing_charge_template"
    assert issue.translation_placeholders == {
        "entry_title": "openWB-chargepoint-1",
        "state_topic": "openWB/chargepoint/1/set/charge_template",
        "command_topic": "openWB/set/chargepoint/1/set/charge_template",
    }

    _publish_template(hass, charge_template())
    await hass.async_block_till_done()
    assert _issue(issue_registry, hass) is None


async def test_no_repair_issue_when_template_arrives(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    issue_registry: ir.IssueRegistry,
) -> None:
    """No issue if openWB publishes the template in time."""
    await _setup_chargepoint(hass)
    _publish_template(hass, charge_template())
    await hass.async_block_till_done()

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert _issue(issue_registry, hass) is None


async def test_repair_issue_removed_on_unload(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Removing or reloading the entry clears the issue."""
    await _setup_chargepoint(hass)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert _issue(issue_registry, hass) is not None

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert _issue(issue_registry, hass) is None


async def test_template_sensors_follow_the_active_template(
    hass: HomeAssistant, mqtt_mock: MqttMockHAClient
) -> None:
    """The template sensors read the chargepoint's template, not the vehicle's."""
    await _setup_chargepoint(hass)
    template = charge_template()
    template["chargemode"]["instant_charging"]["current"] = 12
    template["chargemode"]["pv_charging"]["min_current"] = 7
    template["chargemode"]["eco_charging"]["max_price"] = 0.00031
    _publish_template(hass, template)
    # A vehicle template with other values must not be used.
    async_fire_mqtt_message(
        hass,
        "openWB/vehicle/template/charge_template/1",
        json.dumps(charge_template()),
    )
    await hass.async_block_till_done()

    prefix = "sensor.openwb_chargepoint_1_"
    assert float(hass.states.get(f"{prefix}soll_ladestrom_sofortladen").state) == 12
    assert float(hass.states.get(f"{prefix}min_dauerstrom_pv_laden").state) == 7
    assert (
        float(hass.states.get(f"{prefix}max_preis_strompreisbasiertes_laden").state)
        == 31.0
    )


@pytest.mark.parametrize(
    ("entity_id", "option", "path", "expected", "initial"),
    [
        (
            "select.openwb_chargepoint_1_phasen_pv_laden",
            "1 Phase",
            ("pv_charging", "phases_to_use"),
            1,
            "Automatik",
        ),
        (
            "select.openwb_chargepoint_1_phasen_sofortladen",
            "1 Phase",
            ("instant_charging", "phases_to_use"),
            1,
            "Max. Phasen",
        ),
        (
            "select.openwb_chargepoint_1_begrenzung_pv_laden",
            "SoC",
            ("pv_charging", "limit", "selected"),
            "soc",
            "Keine",
        ),
        (
            "select.openwb_chargepoint_1_begrenzung_eco_laden",
            "Energiemenge",
            ("eco_charging", "limit", "selected"),
            "amount",
            "Keine",
        ),
    ],
)
async def test_pv_and_eco_selects(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    entity_id: str,
    option: str,
    path: tuple[str, ...],
    expected: Any,
    initial: str,
) -> None:
    """Phase and limit selects for PV and Eco charging (#89, #74)."""
    await _setup_chargepoint(hass)
    _publish_template(hass, charge_template())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == initial

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: option},
        blocking=True,
    )
    (published,) = _published_templates(mqtt_mock)
    node = published["chargemode"]
    for key in path:
        node = node[key]
    assert node == expected


@pytest.mark.parametrize(
    ("entity_id", "value", "path", "expected"),
    [
        ("pv_charging_soc_limit_control", 80, ("pv_charging", "limit", "soc"), 80),
        (
            "pv_charging_energy_limit_control",
            15,
            ("pv_charging", "limit", "amount"),
            15000,
        ),
        ("pv_charging_min_soc_control", 30, ("pv_charging", "min_soc"), 30),
        ("eco_charging_soc_limit_control", 70, ("eco_charging", "limit", "soc"), 70),
        (
            "eco_charging_energy_limit_control",
            8,
            ("eco_charging", "limit", "amount"),
            8000,
        ),
    ],
)
async def test_pv_and_eco_numbers(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    entity_id: str,
    value: float,
    path: tuple[str, ...],
    expected: Any,
) -> None:
    """Limit and min SoC numbers for PV and Eco charging (#74, #8)."""
    names = {
        "pv_charging_soc_limit_control": "soc_limit_pv_laden",
        "pv_charging_energy_limit_control": "energie_limit_pv_laden",
        "pv_charging_min_soc_control": "min_soc_pv_laden",
        "eco_charging_soc_limit_control": "soc_limit_eco_laden",
        "eco_charging_energy_limit_control": "energie_limit_eco_laden",
    }
    full_id = f"number.openwb_chargepoint_1_{names[entity_id]}"
    await _setup_chargepoint(hass)
    _publish_template(hass, charge_template())
    await hass.async_block_till_done()
    assert hass.states.get(full_id) is not None

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: full_id, ATTR_VALUE: value},
        blocking=True,
    )
    (published,) = _published_templates(mqtt_mock)
    node = published["chargemode"]
    for key in path:
        node = node[key]
    assert node == expected
    assert isinstance(node, int)
