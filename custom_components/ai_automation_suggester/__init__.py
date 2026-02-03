"""The AI Automation Suggester integration v2.0.

Changelog:
- Added AIAutomationProvidersView for dynamic provider selection in dashboard.
- Combined migration and service logic with automatic resource registration.
- Added automatic creation of ai_automations.yaml.
- Added static path registration for dashboard card.
- Implemented temperature handling in generate_suggestions service.
"""

import logging
import uuid
import os
import json
from datetime import datetime
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers.typing import ConfigType
from homeassistant.components.http import HomeAssistantView
from homeassistant.components import persistent_notification

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_PROVIDER,
    SERVICE_GENERATE_SUGGESTIONS,
    ATTR_PROVIDER_CONFIG,
    ATTR_CUSTOM_PROMPT,
    CONFIG_VERSION
)
from .coordinator import AIAutomationCoordinator

_LOGGER = logging.getLogger(__name__)

# --- KONSTANTER TIL AUTOMATISK SETUP ---
URL_BASE = "/ai_suggester_static"
CARD_FILENAME = "ai-automation-suggester-card.js"
CARD_PATH = f"{URL_BASE}/{CARD_FILENAME}"

async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.info("Migrating from version %s", config_entry.version)
    if config_entry.version < CONFIG_VERSION:
        new_data = {**config_entry.data}
        new_data.pop('scan_frequency', None)
        new_data.pop('initial_lag_time', None)
        config_entry.version = CONFIG_VERSION
        hass.config_entries.async_update_entry(config_entry, data=new_data)
        return True
    return True

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the AI Automation Suggester component."""
    hass.data.setdefault(DOMAIN, {})

    # 1. Registrer statisk sti til JS-kortet
    static_dir = Path(__file__).parent / "www" / "ai_automation_suggester"
    if static_dir.exists():
        hass.http.register_static_path(URL_BASE, str(static_dir), cache_headers=False)

    # Registrer API views for frontend-interaktion
    hass.http.register_view(AIAutomationSuggestionsView())
    hass.http.register_view(AIAutomationActionView())
    hass.http.register_view(AIAutomationProvidersView()) # <--- NYT VIEW TIL DROPDOWN

    async def handle_generate_suggestions(call: ServiceCall) -> None:
        """Service handler med fuld support for v2.0 parametre."""
        provider_config = call.data.get(ATTR_PROVIDER_CONFIG)
        custom_prompt = call.data.get(ATTR_CUSTOM_PROMPT)
        all_entities = call.data.get("all_entities", False)
        domains = call.data.get("domains", {})
        entity_limit = call.data.get("entity_limit", 200)
        automation_read_yaml = call.data.get("automation_read_yaml", False)
        automation_limit = call.data.get("automation_limit", 100)
        temp = call.data.get("temperature", 0.1)

        if isinstance(domains, str):
            domains = [d.strip() for d in domains.split(',') if d.strip()]
        elif isinstance(domains, dict):
            domains = list(domains.keys())

        try:
            coordinator = None
            if provider_config:
                coordinator = hass.data[DOMAIN].get(provider_config)
            else:
                for entry_id, coord in hass.data[DOMAIN].items():
                    if isinstance(coord, AIAutomationCoordinator):
                        coordinator = coord
                        break

            if coordinator is None:
                raise ServiceValidationError("No AI Automation Suggester provider configured")

            original_prompt = coordinator.SYSTEM_PROMPT
            if custom_prompt:
                coordinator.SYSTEM_PROMPT = f"{coordinator.SYSTEM_PROMPT}\n\nAdditional User Context:\n{custom_prompt}"

            coordinator.scan_all = all_entities
            coordinator.selected_domains = domains
            coordinator.entity_limit = entity_limit
            coordinator.automation_read_file = automation_read_yaml
            coordinator.automation_limit = automation_limit
            coordinator.current_temperature = float(temp)

            try:
                await coordinator.async_request_refresh()
            finally:
                coordinator.SYSTEM_PROMPT = original_prompt
                coordinator.scan_all = False
                coordinator.selected_domains = []
                coordinator.current_temperature = 0.1

        except Exception as err:
            raise ServiceValidationError(f"Failed to generate suggestions: {err}")

    hass.services.async_register(DOMAIN, SERVICE_GENERATE_SUGGESTIONS, handle_generate_suggestions)
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up entry from config UI."""
    await async_ensure_files(hass)
    await async_register_resource(hass)

    try:
        if CONF_PROVIDER not in entry.data:
            raise ConfigEntryNotReady("Provider not specified in config")

        coordinator = AIAutomationCoordinator(hass, entry)
        await coordinator.async_added_to_hass()
        hass.data[DOMAIN][entry.entry_id] = coordinator

        async def handle_save_suggestion(call: ServiceCall):
            await coordinator.handle_save_suggestion(call)

        async def handle_clear_history(call: ServiceCall):
            await coordinator.handle_clear_history(call)

        hass.services.async_register(DOMAIN, "save_suggestion", handle_save_suggestion)
        hass.services.async_register(DOMAIN, "clear_suggestion_history", handle_clear_history)

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        entry.async_on_unload(entry.add_update_listener(async_reload_entry))

        return True
    except Exception as err:
        _LOGGER.error("Failed to setup integration: %s", err)
        raise ConfigEntryNotReady from err

async def async_ensure_files(hass: HomeAssistant):
    """Sikrer at ai_automations.yaml eksisterer."""
    path = hass.config.path("ai_automations.yaml")
    if not os.path.exists(path):
        def create_file():
            with open(path, 'w', encoding='utf-8') as f:
                f.write("# AI Generated Automations - DO NOT DELETE\n")
        await hass.async_add_executor_job(create_file)

async def async_register_resource(hass: HomeAssistant):
    """Registrerer automatisk dashboard-kortet i Lovelace."""
    resources = hass.data.get("lovelace", {}).get("resources")
    if resources:
        if not any(CARD_PATH in r.get("url", "") for r in resources.async_items()):
            await resources.async_create_item({
                "res_type": "module",
                "url": CARD_PATH
            })

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)

# ─────────────────────────────────────────────────────────────
# API Views
# ─────────────────────────────────────────────────────────────

class AIAutomationProvidersView(HomeAssistantView):
    """API View der lister alle installerede AI-instanser til dropdown menuen."""
    url = "/api/ai_automation_suggester/providers"
    name = "api:ai_automation_suggester:providers"
    requires_auth = True

    async def get(self, request):
        hass = request.app["hass"]
        providers = []
        for entry in hass.config_entries.async_entries(DOMAIN):
            providers.append({
                "name": entry.title,
                "entry_id": entry.entry_id,
                "provider_type": entry.data.get(CONF_PROVIDER)
            })
        return self.json(providers)

class AIAutomationSuggestionsView(HomeAssistantView):
    """API View der leverer data til det visuelle JS-kort."""
    url = "/api/ai_automation_suggester/suggestions"
    name = "api:ai_automation_suggester:suggestions"
    requires_auth = True

    async def get(self, request):
        hass = request.app["hass"]
        all_suggestions = []

        if DOMAIN in hass.data:
            for entry_id, coordinator in hass.data[DOMAIN].items():
                if isinstance(coordinator, AIAutomationCoordinator):
                    data = coordinator.data
                    suggestions_list = data.get("suggestions_list", [])
                    
                    if isinstance(suggestions_list, list):
                        for item in suggestions_list:
                            if not isinstance(item, dict): continue
                            
                            all_suggestions.append({
                                "id": str(uuid.uuid4()),
                                "suggestion_id": item.get("suggestion_id", "unknown"),
                                "title": item.get("title", "New Suggestion"),
                                "shortDescription": item.get("description", "")[:100] + "...",
                                "detailedDescription": item.get("description", ""),
                                "yamlCode": item.get("yaml", ""),
                                "type": item.get("type", "unknown"),
                                "timestamp": str(data.get("last_update", "")),
                                "provider": coordinator._entry.title, # Viser instansens navn
                                "showDetails": False
                            })
        return self.json(all_suggestions)

class AIAutomationActionView(HomeAssistantView):
    """API View der håndterer 'Accept/Decline'."""
    url = "/api/ai_automation_suggester/{action}/{suggestion_id}"
    name = "api:ai_automation_suggester:action"
    requires_auth = True

    async def post(self, request, action, suggestion_id):
        hass = request.app["hass"]
        if action == "accept":
            for entry_id, coordinator in hass.data[DOMAIN].items():
                if isinstance(coordinator, AIAutomationCoordinator):
                    await coordinator.handle_save_suggestion({"suggestion_id": suggestion_id})
            return self.json({"success": True})
        
        elif action == "decline":
            return self.json({"success": True, "message": "Suggestion ignored."})

        return self.json({"success": False, "error": "Invalid action"}, status_code=400)
