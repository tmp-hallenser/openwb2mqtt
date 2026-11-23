# MQTT Topic Reference

This file explains the MQTT topic patterns used by the openWB integration. Use this guide to understand which topics to bridge `in` (to read data from openWB) and `out` (to send commands to openWB) in your MQTT broker.

### Placeholders
*   `{mqttRoot}`: The root topic configured in your integration (e.g., `openWB`).
*   `{deviceID}`: The numeric ID of the device you are configuring.
*   `{vehicleID}`: The ID of the connected vehicle.

---

## Controller

### SENSORS_CONTROLLER
*   **Direction**: `in`
*   **Topic Path**: `{mqttRoot}/{key}`
*   **Keys**:
    *   `system/ip_address`
    *   `system/version`
    *   `system/lastlivevaluesJson`
    *   `vehicle/{vehicle_id}/name` (subscribes to multiple vehicle names from id 0-10)

---

## Chargepoint

### SENSORS_PER_CHARGEPOINT
*   **Direction**: `in`
*   **Topic Path**: `{mqttRoot}/chargepoint/{deviceID}/{key}`
*   **Keys**:
    *   `get/currents`
    *   `get/daily_imported`
    *   `get/daily_exported`
    *   `get/evse_current`
    *   `get/exported`
    *   `get/fault_str`
    *   `get/imported`
    *   `get/phases_in_use`
    *   `get/power`
    *   `get/state_str`
    *   `get/voltages`
    *   `get/power_factors`
    *   `get/powers`
    *   `get/frequency`
    *   `config`
    *   `get/connected_vehicle/info`
    *   `get/connected_vehicle/config`
    *   `get/connected_vehicle/soc`
    *   `get/rfid`
    *   `get/vehicle_id`

### BINARY_SENSORS_PER_CHARGEPOINT
*   **Direction**: `in`
*   **Topic Path**: `{mqttRoot}/chargepoint/{deviceID}/{key}`
*   **Keys**:
    *   `plug_state`
    *   `charge_state`
    *   `fault_state`

### Charge template (selects, numbers and three sensors)
Charge mode, limits, currents, phases and the max. price are values of the
chargepoint's active charge template. openWB only accepts changes to it as the
complete JSON document, so the integration reads the template, changes one
value and publishes the whole template.

*   **IN**: `{mqttRoot}/chargepoint/{deviceID}/set/charge_template`
*   **OUT**: `{mqttRoot}/set/chargepoint/{deviceID}/set/charge_template`

| Entity | `key` | Value in the template |
|---|---|---|
| select | `chargemode` | `chargemode.selected` |
| select | `instant_charging_limitation` | `chargemode.instant_charging.limit.selected` |
| select | `instant_charging_phases` | `chargemode.instant_charging.phases_to_use` |
| select | `pv_charging_phases` | `chargemode.pv_charging.phases_to_use` |
| select | `pv_charging_limitation` | `chargemode.pv_charging.limit.selected` |
| select | `eco_charging_limitation` | `chargemode.eco_charging.limit.selected` |
| number | `instant_charging_current_control` | `chargemode.instant_charging.current` |
| number | `instant_charging_energy_limit_control` | `chargemode.instant_charging.limit.amount` (Wh) |
| number | `instant_charging_soc_limit_control` | `chargemode.instant_charging.limit.soc` |
| number | `pv_charging_min_current_control` | `chargemode.pv_charging.min_current` |
| number | `pv_charging_min_soc_control` | `chargemode.pv_charging.min_soc` |
| number | `pv_charging_soc_limit_control` | `chargemode.pv_charging.limit.soc` |
| number | `pv_charging_energy_limit_control` | `chargemode.pv_charging.limit.amount` (Wh) |
| number | `eco_charging_soc_limit_control` | `chargemode.eco_charging.limit.soc` |
| number | `eco_charging_energy_limit_control` | `chargemode.eco_charging.limit.amount` (Wh) |
| number | `price_based_charging_max_price` | `chargemode.eco_charging.max_price` (EUR/Wh) |
| datetime | `scheduled_plan_departure` | `chargemode.scheduled_charging.plans[0]`: `time`, `frequency.selected`, `frequency.once` |
| switch | `scheduled_plan_active` | `chargemode.scheduled_charging.plans[0].active` |
| select | `scheduled_plan_limit` | `chargemode.scheduled_charging.plans[0].limit.selected` |
| select | `scheduled_plan_phases` | `chargemode.scheduled_charging.plans[0].phases_to_use` |
| select | `scheduled_plan_phases_pv` | `chargemode.scheduled_charging.plans[0].phases_to_use_pv` |
| select | `scheduled_plan_frequency` | `chargemode.scheduled_charging.plans[0].frequency.selected` |
| number | `scheduled_plan_soc_target` | `chargemode.scheduled_charging.plans[0].limit.soc_scheduled` (also sets `limit.selected` = `soc`) |
| number | `scheduled_plan_soc_limit` | `chargemode.scheduled_charging.plans[0].limit.soc_limit` |
| number | `scheduled_plan_energy` | `chargemode.scheduled_charging.plans[0].limit.amount` (Wh; also sets `limit.selected` = `amount`) |
| number | `scheduled_plan_current` | `chargemode.scheduled_charging.plans[0].current` |
| sensor | `instant_charging_current` | `chargemode.instant_charging.current` |
| sensor | `pv_charging_min_current` | `chargemode.pv_charging.min_current` |
| sensor | `price_based_charging_max_price` | `chargemode.eco_charging.max_price` (EUR/Wh) |

### LOCKS_PER_CHARGEPOINT
*   **`key`**: `manual_lock`
    *   **IN**: `{mqttRoot}/chargepoint/{deviceID}/set/manual_lock`
    *   **OUT**: `{mqttRoot}/set/chargepoint/{deviceID}/set/manual_lock`

### Connected vehicle (select)
*   **`key`**: `connected_vehicle`
    *   **IN**: `{mqttRoot}/chargepoint/{deviceID}/get/connected_vehicle/info` (JSON `id`), vehicle names from `{mqttRoot}/vehicle/{vehicleID}/name`
    *   **OUT**: `{mqttRoot}/set/chargepoint/{deviceID}/config/ev`

### Manual SoC (number)
*   **`key`**: `manual_soc`
    *   **IN**: `{mqttRoot}/chargepoint/{deviceID}/get/connected_vehicle/soc` (JSON `soc`)
    *   **IN**: `{mqttRoot}/chargepoint/{deviceID}/get/connected_vehicle/info` (JSON `id`, the vehicle to address)
    *   **OUT**: `{mqttRoot}/set/vehicle/{vehicleID}/soc_module/calculated_soc_state/manual_soc`

---

## Counter

### SENSORS_PER_COUNTER
*   **Direction**: `in`
*   **Topic Path**: `{mqttRoot}/counter/{deviceID}/{key}`
*   **Keys**:
    *   `voltages`
    *   `power_factors`
    *   `powers`
    *   `frequency`
    *   `currents`
    *   `power`
    *   `fault_str`
    *   `exported`
    *   `imported`
    *   `daily_imported`
    *   `daily_exported`

### BINARY_SENSORS_PER_COUNTER
*   **Direction**: `in`
*   **Topic Path**: `{mqttRoot}/counter/{deviceID}/{key}`
*   **Keys**:
    *   `fault_state`

---

## Battery

### SENSORS_PER_BATTERY
*   **Direction**: `in`
*   **Topic Path**: `{mqttRoot}/bat/{deviceID}/{key}`
*   **Keys**:
    *   `soc`
    *   `power`
    *   `fault_str`
    *   `exported`
    *   `imported`
    *   `daily_imported`
    *   `daily_exported`

### BINARY_SENSORS_PER_BATTERY
*   **Direction**: `in`
*   **Topic Path**: `{mqttRoot}/bat/{deviceID}/{key}`
*   **Keys**:
    *   `fault_state`

---

## PV Generator

### SENSORS_PER_PVGENERATOR
*   **Direction**: `in`
*   **Topic Path**: `{mqttRoot}/pv/{deviceID}/{key}`
*   **Keys**:
    *   `daily_exported`
    *   `monthly_exported`
    *   `yearly_exported`
    *   `exported`
    *   `power`
    *   `currents`
    *   `fault_str`

### BINARY_SENSORS_PER_PVGENERATOR
*   **Direction**: `in`
*   **Topic Path**: `{mqttRoot}/pv/{deviceID}/{key}`
*   **Keys**:
    *   `fault_state`

---

## Vehicle

### SENSORS_PER_VEHICLE
*   **Direction**: `in`
*   **Topic Path 1**: `{mqttRoot}/vehicle/{deviceID}/{key}`
    *   **Key**: `name`
*   **Topic Path 2**: `{mqttRoot}/vehicle/{deviceID}/get/{key}`
    *   **Keys**:
        *   `soc`
        *   `range`
        *   `soc_timestamp`
        *   `fault_str`

### BINARY_SENSORS_PER_VEHICLE
*   **Direction**: `in`
*   **Topic Path**: `{mqttRoot}/vehicle/{deviceID}/get/{key}`
*   **Keys**:
    *   `fault_state`
