# Home Assistant Projects

This folder contains standalone Home Assistant work that is separate from the Smobot custom integration.

## Panda Green Waste

Files:

- Custom integration:
  `/Users/Cathal1/Documents/New project/Home Assistant Projects/panda-home-assistant/custom_components/panda_green_waste`
- Home Assistant package:
  `/Users/Cathal1/Documents/New project/Home Assistant Projects/panda-home-assistant/packages/panda_green_waste.yaml`
- Lovelace dashboard example:
  `/Users/Cathal1/Documents/New project/Home Assistant Projects/panda-home-assistant/lovelace/panda_green_waste_cards.yaml`

What it includes:

- Panda portal login and calendar polling
- Booking service for:
  - `Mixed Packaging`
  - `MSW Municipal Mixed`
  - `Glass`
  - `140L Food Wasre BIN`
- Persistent notification after booking
- Today and upcoming collection sensors
- Helper-backed `last ordered collection` sensor
- Drop-in package scripts and example dashboard cards

Validation:

```bash
python3 -m compileall 'Home Assistant Projects/panda-home-assistant/custom_components/panda_green_waste'
```
