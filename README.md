# AI Automation Suggester for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/salvationdk/ai_automation_suggester/actions/workflows/validate.yaml/badge.svg)](https://github.com/salvationdk/ai_automation_suggester/actions/workflows/validate.yaml)
[![Hassfest](https://github.com/salvationdk/ai_automation_suggester/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/salvationdk/ai_automation_suggester/actions/workflows/hassfest.yaml)

An intelligent integration that analyzes your Home Assistant entities and existing automations to suggest improvements, new automations, and fixes using advanced AI models (OpenAI, Gemini, Claude, LocalAI, etc.).

## ✨ New in Version 2.0
This integration has been upgraded with "Next Gen" features:
* **🧠 Memory:** If you decline a suggestion, the AI remembers it and won't suggest similar things again.
* **🚑 Self-Healing:** Automatically detects `unavailable` or `unknown` entities and suggests specific fixes to repair your smart home.
* **📐 Blueprints:** Capable of generating reusable Blueprints instead of just single automations.
* **⚡ Smart Selection:** Prioritizes entities that have been active recently to ensure relevance.
* **🎨 Visual Editor:** Easily configure dashboards using the visual UI - no YAML needed!
* **🚀 JSON Architecture:** Faster and more structured responses.

---

## 🔧 Installation

1.  **Install via HACS**:
    * Go to HACS -> Integrations -> 3 dots (top right) -> Custom repositories.
    * Add this repository URL.
    * Install "AI Automation Suggester".
    * **Or manually:** Copy the `custom_components/ai_automation_suggester` folder to your HA `custom_components` directory.
2.  **Restart Home Assistant**.
3.  Go to **Settings -> Devices & Services -> Add Integration**.
4.  Search for **AI Automation Suggester** and configure your AI provider (OpenAI, Gemini, Azure, etc.).

---

## 📊 Dashboard Card

The integration comes with a custom card that supports a **Visual Editor**.

### How to add the card
1.  Go to your Dashboard -> **Edit Dashboard**.
2.  Click **Add Card**.
3.  Search for **AI Automation Suggester** (It might appear at the bottom of the list).
4.  **Use the Visual Editor** to configure:
    * **Title:** Give your card a custom name (e.g., "My AI Assistant").
    * **Filter Type:** Choose what this card should show:
        * **All Suggestions:** Everything mixed together.
        * **Repair Center:** Only shows fixes for broken entities (Red theme).
        * **Blueprints:** Only shows reusable blueprints (Purple theme).
        * **New Ideas:** Only shows creative automation ideas (Blue theme).

### Manual YAML Configuration (Optional)
If you prefer YAML or want to copy-paste configurations:

```yaml
# Standard View
type: custom:ai-automation-suggester-card
title: AI Suggestions
suggestion_type: all

# The "Repair Shop" (Fixes only)
type: custom:ai-automation-suggester-card
title: Repair Center
suggestion_type: fix

# The "Architect" (Blueprints only)
type: custom:ai-automation-suggester-card
title: New Blueprints
suggestion_type: blueprint
