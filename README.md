# Panda Home Assistant

Custom Home Assistant integration, package, and example dashboard for automating Panda Green Waste portal bookings and surfacing Panda calendar information inside Home Assistant.

## Features

- Logs into the Panda customer portal
- Polls the Panda calendar page
- Exposes:
  - next collection sensor
  - upcoming services sensor
  - today's services sensor
  - calendar entity
- Booking service for:
  - `Mixed Packaging`
  - `MSW Municipal Mixed`
  - `Glass`
  - `140L Food Wasre BIN`
- Fixed booking access window support
- Persistent Home Assistant notification after booking
- Helper-backed `last ordered collection` sensor
- Drop-in package scripts
- Ready-to-paste Lovelace dashboard example

## Repository Layout

- Integration code: `custom_components/panda_green_waste`
- Home Assistant package: `packages/panda_green_waste.yaml`
- Lovelace example: `lovelace/panda_green_waste_cards.yaml`

## Install

1. Copy `custom_components/panda_green_waste` into your Home Assistant config directory.
2. If you want the scripts/helpers/dashboard examples too, also copy:
   - `packages/panda_green_waste.yaml`
   - `lovelace/panda_green_waste_cards.yaml`
3. Restart Home Assistant.
4. Add the `Panda Green Waste` integration from `Settings -> Devices & Services`.
5. Enter your Panda portal email and password.

## What The Package Adds

- One script per Panda bin type
- A 6-hour refresh automation
- Helper entities for the last ordered collection
- A summary sensor for today's Panda subjects

## Validation

```bash
python3 -m compileall custom_components/panda_green_waste
```

## Notes

- The booking flow is based on the live Panda portal workflow observed in browser automation.
- Calendar data is parsed from the Panda portal and may vary depending on what the tenant exposes.
- The current package is designed around a fixed access window of `09:00` to `23:00`.

## License

MIT
