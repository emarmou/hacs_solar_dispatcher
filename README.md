# Solar Dispatcher

**Solar Dispatcher** is a Home Assistant custom integration that automatically turns your electrical loads on and off based on the solar power surplus available at any given moment. Instead of wasting excess solar production by exporting it to the grid, it routes that energy into your home appliances — washing machines, dishwashers, water heaters, pool pumps, EV chargers, and so on — in a configurable priority order, with optional battery protection thresholds.

---

## Table of contents

1. [What it does](#what-it-does)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration walkthrough](#configuration-walkthrough)
   - [Initial setup — energy inputs](#initial-setup--energy-inputs)
   - [Adding dispatch devices](#adding-dispatch-devices)
   - [Editing the configuration later](#editing-the-configuration-later)
5. [How the algorithm works](#how-the-algorithm-works)
   - [Surplus calculation](#surplus-calculation)
   - [Priority dispatch](#priority-dispatch)
   - [Preemption](#preemption)
   - [Battery protection](#battery-protection)
   - [Allowance ratio — handling uncertainty](#allowance-ratio--handling-uncertainty)
6. [Entities created per device](#entities-created-per-device)
7. [Live tuning from the dashboard](#live-tuning-from-the-dashboard)

---

## What it does

Solar Dispatcher runs a configurable dispatch algorithm on a fixed schedule (default 30 s). On every cycle it:

1. Reads the power exchanged with the grid and, optionally, the battery charging power to compute the currently available **solar surplus**.
2. Iterates through all configured loads, sorted from highest to lowest **priority**.
3. Turns a load **on** when sufficient surplus is available and the battery state of charge (if configured) is above the load's threshold.
4. Turns a load **off** when the surplus is gone or the battery threshold is no longer satisfied.
5. Optionally **preempts** lower-priority loads that are currently on in order to free enough budget for a higher-priority load.

You keep full control at all times:

- A **Managed** switch per device lets you hand a load back to manual control without touching the configuration.
- An **Override** switch forces a load on regardless of available surplus.
- Priority, minimum battery level, and estimated power can all be adjusted live from the dashboard in between polling cycles.

---

## Prerequisites

- Home Assistant 2024.1 or later.
- A sensor entity that measures the power exchanged with the grid (in watts) — provided by your inverter, smart meter, or energy integration.
- One or more switch entities that can control your electrical loads (smart plugs, Shelly relays, etc.).
- Optionally: a sensor for battery charging power and a sensor for battery state of charge.

---

## Installation

### Via HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=emarmou&repository=hacs_solar_dispatcher&category=integration)

1. In HACS, go to **Integrations** and click the **⋮** menu → **Custom repositories**.
2. Add `https://github.com/emarmou/hacs_solar_dispatcher` with category **Integration**.
3. Find **Solar Dispatcher** in the list and click **Download**.
4. Restart Home Assistant.

### Manual

1. Copy the `custom_components/ha_solar_dispatcher` directory into your HA `config/custom_components/` folder.
2. Restart Home Assistant.

---

## Configuration walkthrough

### Initial setup — energy inputs

Go to **Settings → Devices & Services → Add integration** and search for **Solar Dispatcher**.

> *(screenshot placeholder)*

You will see the **Configure energy inputs** form:

| Field | Required | Description |
|---|---|---|
| **Grid power sensor** | Yes | Sensor measuring watts exchanged with the grid. |
| **Invert grid sign** | — | Enable when your sensor reports positive for importing from the grid (the most common convention). The sign is then flipped so that a positive surplus means you are exporting. |
| **Battery charging power sensor** | No | Power sensor in watts. Its value is added to the grid surplus. |
| **Invert battery charge sign** | — | Enable when your battery sensor reports positive when discharging instead of charging. |
| **Battery state of charge sensor** | No | Percentage sensor. Enables per-device minimum battery thresholds. |
| **Allowance entity** | No | An `input_number` or `number` entity whose value (0–1) adds a tolerance margin to the surplus. See [Allowance ratio](#allowance-ratio--handling-uncertainty). |
| **Polling interval** | Yes | How often the algorithm runs, in seconds (minimum 10 s, default 30 s). |

After submitting, the integration entry is created with no dispatch devices yet. Add devices in the next step.

---

### Adding dispatch devices

Each load you want the algorithm to control is a **dispatch device**. There are two ways to add one:

**Option A — from the integrations page**
Click the **+** button on the Solar Dispatcher integration card.

> *(screenshot placeholder)*

**Option B — from the options flow**
Click **Configure** on the integration card, then use the **Add device** action.

> *(screenshot placeholder)*

Either way you will see the **Add dispatch device** form:

| Field | Required | Description |
|---|---|---|
| **Device name** | Yes | A friendly label shown on the dashboard entities. |
| **Priority** | Yes | `highest`, `high`, `normal`, `low`, or `lowest`. Higher-priority devices are served surplus first. |
| **Minimum battery state (%)** | Yes | The battery must be at or above this percentage for the algorithm to turn this device on. Set to 0 to disable. |
| **Estimated power consumption (W)** | Yes | Expected wattage of this load. Used to deduct from the remaining surplus when the device is switched on, and to estimate how much surplus becomes available if the device is switched off. |
| **Switch entity to control** | Yes | The real switch or plug entity the algorithm will call `switch.turn_on` / `switch.turn_off` on. |
| **Power measurement sensor** | No | When provided, the actual measured power of this device is used instead of the estimate when recalculating the freed surplus after a turn-off. |

---

### Editing the configuration later

**Change energy inputs** — click **Configure** (⚙) on the Solar Dispatcher card. The first form that appears allows you to update all energy-input settings.

> *(screenshot placeholder)*

**Edit or remove a dispatch device** — from the same **Configure** form, the options flow offers **Edit device** and **Remove device** sub-steps that let you select the target device from a list.

> *(screenshot placeholder)*

**Reconfigure** — right-click (or use the ⋮ menu) on the integration card and choose **Reconfigure** to update the energy inputs without touching device settings.

---

## How the algorithm works

### Surplus calculation

Each polling cycle starts by computing a single **surplus** value in watts:

```
surplus = (grid_power + battery_charge_power) × (1 + allowance_ratio)
```

- `grid_power` — value read from the grid sensor, sign-adjusted by the invert setting so that **positive = exporting to the grid** (= available surplus).
- `battery_charge_power` — value from the battery charge sensor (0 if not configured). A charging battery is also "consuming" solar power; adding it to the surplus represents the full solar production available for dispatch.
- `allowance_ratio` — optional multiplier from an `input_number` entity (default 0, i.e. no extra margin).

**Example:**

| Measurement | Value |
|---|---|
| Grid sensor (positive = importing, invert ON) | −2 000 W (exporting) |
| Grid power after invert | +2 000 W |
| Battery charging power | +500 W |
| Allowance ratio | 0 |
| **Surplus** | **2 500 W** |

---

### Priority dispatch

Devices are processed from highest to lowest priority. For each device the algorithm decides:

| Condition | Action |
|---|---|
| Device is OFF and `estimated_power ≤ surplus` and battery OK | Turn ON, deduct `estimated_power` from surplus |
| Device is OFF, not enough surplus, but preemption possible (see below) | Preempt lower-priority ON loads, then turn ON |
| Device is OFF and conditions not met | Keep OFF |
| Device is ON and `surplus > 0` and battery above threshold | Keep ON |
| Device is ON and `surplus ≤ 0` or battery below threshold | Turn OFF, add actual power back to surplus |

**Example — two loads, 2 500 W surplus:**

| # | Device | Priority | Power | State | Decision |
|---|---|---|---|---|---|
| 1 | EV charge | normal | 1 800 W | OFF | Turn ON (1 800 ≤ 2 500). Surplus → 700 W |
| 2 | Water heater | low | 800 W | OFF | Keep OFF (800 > 700) |

---

### Preemption

When a **higher-priority** load cannot turn on due to insufficient surplus, the algorithm looks at currently ON loads with a **lower priority** and checks whether turning off the minimal necessary subset would free enough power.

Candidates are selected in reverse priority order (lowest priority sacrificed first) until the accumulated freed power covers the deficit.

**Example — preemption in action:**

Initial state: surplus = 500 W.

| # | Device | Priority | Power | State |
|---|---|---|---|---|
| 1 | Pool pump | high | 800 W | OFF |
| 2 | Water heater | normal | 1 200 W | ON |

Processing pool pump (high, 800 W):
- Direct surplus 500 W < 800 W → look for preemption candidates.
- Water heater is ON, lower priority, actual power 1 200 W.
- Available with preemption: 500 + 1 200 = 1 700 W ≥ 800 W → proceed.
- Water heater is scheduled for preemption; pool pump is turned ON. Surplus → 500 − 800 = −300 W.

Processing Water heater (normal):
- Marked for preemption → turned OFF. Surplus → −300 + 1 200 = 900 W.

End result: pool pump runs (800 W), Water heater is off, 900 W surplus remains.

---

### Battery threshold

Each device has a **minimum battery state of charge** threshold. The algorithm will not turn that device on — and will turn it off if it is already on — when the battery percentage is below the threshold.

This lets you keep your battery charged enough to cover house consumption after sunset. For example:

- Water heater: min battery = 80 % — only runs when the battery is nearly full.
- Pool pump: min battery = 20 % — protected against discharge but otherwise always eligible.

---

### Allowance ratio — handling uncertainty

Sometimes it is worth turning on a device even when the available surplus is not quite enough for that device. A small positive allowance ratio acts as a tolerance margin that makes the algorithm slightly more willing to turn loads on.

Example: `grid_power = 1 900 W`, `estimated_power = 2 000 W`.

- Without allowance: 1 900 < 2 000 → load stays OFF.
- With allowance = 0.1: surplus = 1 900 × 1.1 = 2 090 W → 2 090 ≥ 2 000 → load turns ON.

The allowance entity can be an `input_number` slider on your dashboard, letting you tune the sensitivity in real time.

---

## Entities created per device

For every dispatch device configured, the integration creates the following entities (all grouped under the integration device):

| Entity type | Name | Description |
|---|---|---|
| **Switch** — Managed | `<device name>` | ON = algorithm controls this load. Turn OFF to take manual control; the real switch is immediately turned off and the coordinator ignores the device until you re-enable it. |
| **Switch** — Override | `<device name> override` | ON = force the real switch ON regardless of available surplus. Useful for temporarily forcing a load on (e.g. you need hot water now). The override is automatically cancelled if the real switch is turned off externally. |
| **Select** — Priority | `<device name> priority` | The dispatch priority (`highest` … `lowest`). Changes take effect on the next polling cycle. |
| **Number** — Min battery | `<device name> min battery` | Minimum battery state of charge required to turn this device on. |
| **Number** — Estimated power | `<device name> estimated power` | Expected power draw in watts. |

In addition, one **Sensor** entity (`Available surplus`) is created for the whole integration. It shows the remaining dispatchable power at the end of each polling cycle. You could use this entity to trigger a notification to you for, why not, turning on a manual device that is not managed by the **Solar Dispatcher**.

---

## Live tuning from the dashboard

All per-device settings — priority, minimum battery level, and estimated power — can be changed directly from the dashboard without going through the configuration flow. Changes are picked up on the next polling cycle and are persisted across Home Assistant restarts.

Suggested dashboard card layout per device:

```yaml
type: entities
title: Washing machine dispatch
entities:
  - entity: switch.washing_machine_managed
  - entity: switch.washing_machine_override
  - entity: select.washing_machine_priority
  - entity: number.washing_machine_min_battery
  - entity: number.washing_machine_estimated_power
```
