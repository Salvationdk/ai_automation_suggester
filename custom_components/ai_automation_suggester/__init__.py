"""The AI Automation Suggester integration."""
import logging
import uuid
from datetime import datetime
import json

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

async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entry if necessary."""
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

    # Register API Views
    hass.http.register_view(AIAutomationSuggestionsView)
    hass.http.register_view(AIAutomationActionView)

    async def handle_generate_suggestions(call: ServiceCall) -> None:
        """Handle the generate_suggestions service call."""
        provider_config = call.data.get(ATTR_PROVIDER_CONFIG)
        custom_prompt = call.data.get(ATTR_CUSTOM_PROMPT)
        all_entities = call.data.get("all_entities", False)
        domains = call.data.get("domains", {})
        entity_limit = call.data.get("entity_limit", 200)
        automation_read_yaml = call.data.get("automation_read_yaml", False)
        automation_limit = call.data.get("automation_limit", 100)

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

            if custom_prompt:
                original_prompt = coordinator.SYSTEM_PROMPT
                # Append custom prompt but keep the JSON instruction at the top
                coordinator.SYSTEM_PROMPT = f"{coordinator.SYSTEM_PROMPT}\n\nAdditional User Context:\n{custom_prompt}"
            else:
                original_prompt = None

            coordinator.scan_all = all_entities
            coordinator.selected_domains = domains
            coordinator.entity_limit = entity_limit
            coordinator.automation_read_file = automation_read_yaml
            coordinator.automation_limit = automation_limit

            try:
                await coordinator.async_request_refresh()
            finally:
                if original_prompt is not None:
                    coordinator.SYSTEM_PROMPT = original_prompt
                coordinator.scan_all = False
                coordinator.selected_domains = []
                coordinator.entity_limit = 200
                coordinator.automation_read_file = False

        except KeyError:
            raise ServiceValidationError("Provider configuration not found")
        except Exception as err:
            raise ServiceValidationError(f"Failed to generate suggestions: {err}")

    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_SUGGESTIONS,
        handle_generate_suggestions
    )

    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AI Automation Suggester from a config entry."""
    try:
        if CONF_PROVIDER not in entry.data:
            raise ConfigEntryNotReady("Provider not specified in config")

        coordinator = AIAutomationCoordinator(hass, entry)
        hass.data[DOMAIN][entry.entry_id] = coordinator

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        entry.async_on_unload(entry.add_update_listener(async_reload_entry))

        @callback
        def handle_custom_event(event):
            hass.async_create_task(coordinator_request_all_suggestions())

        async def coordinator_request_all_suggestions():
            coordinator.scan_all = True
            await coordinator.async_request_refresh()
            coordinator.scan_all = False

        entry.async_on_unload(hass.bus.async_listen("ai_automation_suggester_update", handle_custom_event))

        return True

    except Exception as err:
        _LOGGER.error("Failed to setup integration: %s", err)
        raise ConfigEntryNotReady from err

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    try:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        if unload_ok:
            coordinator = hass.data[DOMAIN].pop(entry.entry_id)
            await coordinator.async_shutdown()
        return unload_ok
    except Exception as err:
        return False

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


# ─────────────────────────────────────────────────────────────
# API Views classes (UPDATED FOR JSON LIST)
# ─────────────────────────────────────────────────────────────

class AIAutomationSuggestionsView(HomeAssistantView):
    """View to return suggestions to the frontend card."""
    url = "/api/ai_automation_suggester/suggestions"
    name = "api:ai_automation_suggester:suggestions"
    requires_auth = True

    async def get(self, request):
        """Retrieve the latest suggestions from the coordinator."""
        hass = request.app["hass"]
        all_suggestions = []

        if DOMAIN in hass.data:
            for entry_id, coordinator in hass.data[DOMAIN].items():
                if isinstance(coordinator, AIAutomationCoordinator):
                    data = coordinator.data
                    # Access the new list key
                    suggestions_list = data.get("suggestions_list", [])
                    
                    if isinstance(suggestions_list, list):
                        for item in suggestions_list:
                            if not isinstance(item, dict): continue
                            
                            suggestion_entry = {
                                "id": str(uuid.uuid4()), # Dynamic ID for UI actions
                                "title": item.get("title", "New Suggestion"),
                                "shortDescription": item.get("description", "")[:100] + "...",
                                "detailedDescription": item.get("description", ""),
                                "yamlCode": item.get("yaml", ""),
                                "type": item.get("type", "unknown"),
                                "timestamp": str(data.get("last_update", "")),
                                "provider": data.get("provider", "AI"),
                                "showDetails": False
                            }
                            all_suggestions.append(suggestion_entry)
        
        return self.json(all_suggestions)

class AIAutomationActionView(HomeAssistantView):
    """View to handle Accept/Decline actions from the card."""
    url = "/api/ai_automation_suggester/{action}/{suggestion_id}"
    name = "api:ai_automation_suggester:action"
    requires_auth = True

    async def post(self, request, action, suggestion_id):
        """Handle the action."""
        hass = request.app["hass"]
        _LOGGER.info(f"UI Action received: {action} on suggestion {suggestion_id}")

        if action == "accept":
            persistent_notification.async_create(
                hass,
                message="Code accepted. In the future this will auto-save to automations.yaml.",
                title="Automation Accepted"
            )
            return self.json({"success": True})
        
        elif action == "decline":
            return self.json({"success": True})

        return self.json({"success": False, "error": "Invalid action"}, status_code=400)
