AI Automation Suggester for Home Assistant

An intelligent integration that analyzes your Home Assistant entities and existing automations to suggest improvements, new automations, and fixes using advanced AI models (OpenAI, Gemini, Claude, LocalAI, etc.).

✨ New in Version 2.0

This integration has been upgraded with "Next Gen" features:

🧠 Memory: If you decline a suggestion, the AI remembers it and won't suggest similar things again.

🚑 Self-Healing: Automatically detects unavailable or unknown entities and suggests specific fixes to repair your smart home.

📐 Blueprints: Capable of generating reusable Blueprints instead of just single automations.

⚡ Smart Selection: Prioritizes entities that have been active recently to ensure relevance.

🎨 Visual Editor: Easily configure dashboards using the visual UI - no YAML needed!

🚀 JSON Architecture: Faster and more structured responses.

🔧 Installation

Install via HACS:

Go to HACS -> Integrations -> 3 dots (top right) -> Custom repositories.

Add this repository URL.

Install "AI Automation Suggester".

Or manually: Copy the custom_components/ai_automation_suggester folder to your HA custom_components directory.

Restart Home Assistant.

Go to Settings -> Devices & Services -> Add Integration.

Search for AI Automation Suggester and configure your AI provider.

📊 Dashboard Card

The integration comes with a custom card that supports a Visual Editor.

How to add the card

Go to your Dashboard -> Edit Dashboard.

Click Add Card.

Search for AI Automation Suggester (It might appear at the bottom of the list).

Use the Visual Editor to configure:

Title: Give your card a custom name (e.g., "My AI Assistant").

Filter Type: Choose what this card should show:

All Suggestions: Everything mixed together.

Repair Center: Only shows fixes for broken entities (Red theme).

Blueprints: Only shows reusable blueprints (Purple theme).

New Ideas: Only shows creative automation ideas (Blue theme).

Manual YAML Configuration (Optional)

If you prefer YAML or want to copy-paste configurations:

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


🧠 Features

Memory & Learning

When you click "Ignore" (Decline) on a suggestion in the dashboard, the integration remembers this preference.

It logs the rejected idea to a local file (ai_suggester_memory.json).

In future scans, this list of "dislikes" is sent to the AI to prevent it from suggesting the same things again.

Self-Healing 🚑

The coordinator automatically scans for entities with state unavailable or unknown.

It prioritizes these entities in the prompt sent to the AI.

It explicitly asks for "Fixes" or debugging steps.

These suggestions appear with a Red Icon and can be filtered using the "Repair Center" dashboard view.

Blueprints 📐

Instead of just generating hard-coded automations, the AI can now detect when a logic pattern is reusable (e.g., "Motion-activated light with dimming"). In these cases, it will generate a Blueprint YAML, allowing you to easily apply the same logic to multiple rooms.

🛠 Services

You can trigger a new scan manually via Developer Tools or automations:

Service: ai_automation_suggester.generate_suggestions

Parameters:

Custom Prompt: Add specific instructions (e.g., "Focus on energy saving in the kitchen" or "Make the living room lights warmer at night").

Entity Limit: How many entities to send to the AI (Default: 200).

Scan All Entities: Force a full re-scan of all entities, instead of just the recently changed ones.

🤝 Supported Providers

OpenAI (GPT-4o, GPT-3.5)

Google Gemini (Flash 2.0, Pro)

Anthropic (Claude 3.5 Sonnet / 3.7)

LocalAI & Ollama (For local privacy-focused control)

Azure OpenAI

Groq, Mistral, Perplexity, OpenRouter

❤️ Contributing

Issues and Pull Requests are welcome!
