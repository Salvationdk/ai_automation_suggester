"""Sensor platform for AI Automation Suggester.

Changelog:
- Retained multi-sensor architecture from GitHub (Tokens, Model, Status).
- Enhanced AISuggestionsSensor with 'history' and 'entities_processed_count'.
- Maintained DeviceInfo for clean integration in HA UI.
"""
from __future__ import annotations
import logging
from typing import cast

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import *

_LOGGER = logging.getLogger(__name__)

# Kortlægning af udbydere til model-nøgler
PROVIDER_TO_MODEL_KEY_MAP: dict[str, str] = {
    "OpenAI": CONF_OPENAI_MODEL,
    "Anthropic": CONF_ANTHROPIC_MODEL,
    "Google": CONF_GOOGLE_MODEL,
    "Groq": CONF_GROQ_MODEL,
    "LocalAI": CONF_LOCALAI_MODEL,
    "Ollama": CONF_OLLAMA_MODEL,
    "Custom OpenAI": CONF_CUSTOM_OPENAI_MODEL,
    "Mistral AI": CONF_MISTRAL_MODEL,
    "Perplexity AI": CONF_PERPLEXITY_MODEL,
    "OpenRouter": CONF_OPENROUTER_MODEL,
    "OpenAI Azure": CONF_OPENAI_AZURE_DEPLOYMENT_ID,
    "Generic OpenAI": CONF_GENERIC_OPENAI_MODEL,
}

# Sensor beskrivelser
SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(key=SENSOR_KEY_SUGGESTIONS, name="AI Automation Suggestions", icon="mdi:robot-happy-outline"),
    SensorEntityDescription(key=SENSOR_KEY_STATUS, name="AI Provider Status", icon="mdi:lan-check", entity_category=EntityCategory.DIAGNOSTIC),
    SensorEntityDescription(key=SENSOR_KEY_INPUT_TOKENS, name="Max Input Tokens", icon="mdi:format-letter-starts-with", entity_category=EntityCategory.DIAGNOSTIC, native_unit_of_measurement="tokens", state_class=SensorStateClass.MEASUREMENT),
    SensorEntityDescription(key=SENSOR_KEY_OUTPUT_TOKENS, name="Max Output Tokens", icon="mdi:format-letter-ends-with", entity_category=EntityCategory.DIAGNOSTIC, native_unit_of_measurement="tokens", state_class=SensorStateClass.MEASUREMENT),
    SensorEntityDescription(key=SENSOR_KEY_MODEL, name="AI Model In Use", icon="mdi:brain", entity_category=EntityCategory.DIAGNOSTIC),
    SensorEntityDescription(key=SENSOR_KEY_LAST_ERROR, name="Last Error Message", icon="mdi:alert-circle-outline", entity_category=EntityCategory.DIAGNOSTIC),
)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Sætter alle sensorer op baseret på beskrivelserne ovenfor."""
    coordinator = cast(DataUpdateCoordinator, hass.data[DOMAIN][entry.entry_id])
    provider_name = entry.data.get(CONF_PROVIDER, "Unknown Provider")
    entities: list[SensorEntity] = []

    for description in SENSOR_DESCRIPTIONS:
        formatted_name = f"{description.name} ({provider_name})"
        spec = SensorEntityDescription(
            key=description.key, name=formatted_name, icon=description.icon,
            entity_category=description.entity_category, native_unit_of_measurement=description.native_unit_of_measurement,
            state_class=description.state_class, device_class=description.device_class,
        )
        if description.key == SENSOR_KEY_SUGGESTIONS:
            entities.append(AISuggestionsSensor(coordinator, entry, spec))
        elif description.key == SENSOR_KEY_STATUS:
            entities.append(AIProviderStatusSensor(coordinator, entry, spec))
        elif description.key == SENSOR_KEY_INPUT_TOKENS:
            entities.append(MaxInputTokensSensor(coordinator, entry, spec))
        elif description.key == SENSOR_KEY_OUTPUT_TOKENS:
            entities.append(MaxOutputTokensSensor(coordinator, entry, spec))
        elif description.key == SENSOR_KEY_MODEL:
            entities.append(AIModelSensor(coordinator, entry, spec))
        elif description.key == SENSOR_KEY_LAST_ERROR:
            entities.append(AILastErrorSensor(coordinator, entry, spec))

    async_add_entities(entities, True)

class AIBaseSensor(CoordinatorEntity[DataUpdateCoordinator], SensorEntity):
    """Base klasse for alle AI sensorer."""
    def __init__(self, coordinator, entry, description) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"{INTEGRATION_NAME} ({entry.data.get(CONF_PROVIDER, 'Unknown')})",
            manufacturer="Community",
            model=entry.data.get(CONF_PROVIDER, "Unknown"),
            sw_version=str(entry.version) if entry.version else "N/A",
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Håndter opdatering fra koordinatoren."""
        if self.coordinator.last_update_success:
            self._update_state_and_attributes()
        super()._handle_coordinator_update()

class AISuggestionsSensor(AIBaseSensor):
    """Hovedsensoren der viser forslag og nu også historik."""
    
    def _update_state_and_attributes(self) -> None:
        data = self.coordinator.data or {}
        s_list = data.get("suggestions_list", [])
        history = data.get("history", [])
        
        # Sæt statustekst
        if s_list:
            self._attr_native_value = "New Suggestions Available"
        else:
            self._attr_native_value = "No Suggestions"

        # Eksponer forslag og historik som attributter
        first_sug = s_list[0] if s_list else {}
        self._attr_extra_state_attributes = {
            "suggestions_list": s_list,
            "history": history, # NY: Bruges til historik-kortet
            "suggestions": first_sug.get("title"),
            "description": first_sug.get("description"),
            "yaml_block": first_sug.get("yaml"),
            "last_update": data.get("last_update"),
            "entities_processed": data.get("entities_processed", []),
            "entities_processed_count": len(data.get("entities_processed", [])), # NY: Statistik
            "provider": self._entry.data.get(CONF_PROVIDER, "unknown"),
        }

class AIProviderStatusSensor(AIBaseSensor):
    def _update_state_and_attributes(self) -> None:
        data = self.coordinator.data or {}
        if not self.coordinator.last_update_success: self._attr_native_value = PROVIDER_STATUS_ERROR
        elif not data: self._attr_native_value = PROVIDER_STATUS_INITIALIZING
        elif data.get("last_error"): self._attr_native_value = PROVIDER_STATUS_ERROR
        else: self._attr_native_value = PROVIDER_STATUS_CONNECTED
        self._attr_extra_state_attributes = {"last_error_message": data.get("last_error"), "last_attempted_update": data.get("last_update")}

class MaxInputTokensSensor(AIBaseSensor):
    def _update_state_and_attributes(self) -> None:
        self._attr_native_value = self._entry.options.get(CONF_MAX_INPUT_TOKENS, self._entry.data.get(CONF_MAX_INPUT_TOKENS, DEFAULT_MAX_INPUT_TOKENS))

class MaxOutputTokensSensor(AIBaseSensor):
    def _update_state_and_attributes(self) -> None:
        self._attr_native_value = self._entry.options.get(CONF_MAX_OUTPUT_TOKENS, self._entry.data.get(CONF_MAX_OUTPUT_TOKENS, DEFAULT_MAX_OUTPUT_TOKENS))

class AIModelSensor(AIBaseSensor):
    def _update_state_and_attributes(self) -> None:
        provider = self._entry.data.get(CONF_PROVIDER)
        model_key = PROVIDER_TO_MODEL_KEY_MAP.get(provider)
        self._attr_native_value = self._entry.options.get(model_key, self._entry.data.get(model_key, DEFAULT_MODELS.get(provider, "unknown")))

class AILastErrorSensor(AIBaseSensor):
    def _update_state_and_attributes(self) -> None:
        data = self.coordinator.data or {}
        err = data.get("last_error")
        self._attr_native_value = str(err) if err else "No Error"
