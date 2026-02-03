🤖 AI Automation Suggester for Home Assistant
An intelligent integration that analyzes your Home Assistant entities and existing automations to suggest improvements, new automations, and fixes using advanced AI models (OpenAI, Gemini, Claude, LocalAI, etc.).

✨ New in Version 2.0
This integration has been upgraded with "Next Gen" features:

💾 Direct Save: Save suggested automations with a single click directly to your ai_automations.yaml or as a Blueprint file.

📚 Proposal History: Never lose a good idea. The last 100 suggestions are stored in ai_suggestions_history.json.

🧠 Memory: If you decline a suggestion, the AI remembers it and won't suggest similar things again.

🚑 Self-Healing: Automatically detects unavailable or unknown entities and suggests specific fixes to repair your smart home.

📐 Blueprints: Capable of generating reusable Blueprints instead of just single automations.

⚡ Smart Selection: Prioritizes entities that have been active recently to ensure relevance.

🎨 Visual Editor: Easily configure dashboards using the visual UI - no YAML needed!

🚀 JSON Architecture: Faster, more structured responses with a built-in "JSON Healer" to fix truncated AI code.

🔧 Installation & Crucial Setup
1. Install via HACS
Go to HACS -> Integrations -> 3 dots (top right) -> Custom repositories.

Add this repository URL.

Install "AI Automation Suggester".

Restart Home Assistant.

2. Enable the "Save" Feature (Required for v2.0)
To use the one-click "Save" functionality, you must allow Home Assistant to read the AI-generated automation file.

Open your configuration.yaml and add:

YAML
automation:
  - !include automations.yaml
  - !include ai_automations.yaml # <--- Add this line
Create an empty file named ai_automations.yaml in your /config/ directory.

Restart Home Assistant.

📊 Dashboard Card
The integration comes with a custom card that supports a Visual Editor.

How to add the card
Go to your Dashboard -> Edit Dashboard.

Click Add Card.

Search for AI Automation Suggester.

Use the Visual Editor to configure:

Title: Give your card a custom name (e.g., "My AI Assistant").

Filter Type: Choose what this card should show:

All Suggestions: Everything mixed together.

Repair Center: Only shows fixes for broken entities (Red theme).

Blueprints: Only shows reusable blueprints (Purple theme).

New Ideas: Only shows creative automation ideas (Blue theme).

Manual YAML Configuration (Optional)
YAML
# Standard View
type: custom:ai-automation-suggester-card
title: AI Suggestions
suggestion_type: all

# The "Repair Shop" (Fixes only)
type: custom:ai-automation-suggester-card
title: Repair Center
suggestion_type: fix
Note: For the full v2.0 experience (including the History Log and Save buttons), we recommend using our Advanced Dashboard Template.

🧠 Features
Memory & Learning
When you click "Ignore" (Decline) on a suggestion in the dashboard, the integration remembers this preference. It logs the rejected idea to ai_suggester_memory.json. In future scans, this list of "dislikes" is sent to the AI to prevent it from suggesting the same things again.

History Log 📚
The integration now maintains a permanent log of the latest 100 suggestions in ai_suggestions_history.json. This allows you to browse and restore ideas even after a new analysis has been run.

Self-Healing 🚑
The coordinator automatically scans for entities with state unavailable or unknown. It prioritizes these entities and explicitly asks the AI for "Fixes" or debugging steps. These suggestions appear with a Red Icon.

Blueprints 📐
The AI can detect when a logic pattern is reusable (e.g., "Motion-activated light with dimming"). In these cases, it will generate a Blueprint YAML, and the "Save" service will automatically place it in your /blueprints/automation/ folder.

🛠 Services
ai_automation_suggester.generate_suggestions: Trigger a manual scan.

Custom Prompt: Add specific instructions (e.g., "Focus on energy saving").

Entity Limit: How many entities to send to the AI (Default: 200).

Scan All Entities: Force a full re-scan.

ai_automation_suggester.save_suggestion: Saves a specific suggestion (requires suggestion_id).

ai_automation_suggester.clear_suggestion_history: Wipes the history log for a clean slate.

🤝 Supported Providers
Google Gemini (Flash 2.0, Pro)

OpenAI (GPT-4o, GPT-3.5)

Anthropic (Claude 3.5 Sonnet / 3.7)

LocalAI & Ollama (For local privacy)

Azure OpenAI, Groq, Mistral, Perplexity, OpenRouter

❤️ Contributing
Issues and Pull Requests are welcome!
