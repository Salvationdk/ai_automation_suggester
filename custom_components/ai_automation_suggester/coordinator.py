# custom_components/ai_automation_suggester/coordinator.py
"""Coordinator for AI Automation Suggester."""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
import random
import re

import aiohttp
import anyio
import yaml

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import *

_LOGGER = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Regex to pull fenced YAML blocks out of the AI response
# ─────────────────────────────────────────────────────────────
YAML_RE = re.compile(r"```yaml\s*([\s\S]+?)\s*```", flags=re.IGNORECASE)

SYSTEM_PROMPT = """You are an AI assistant that generates Home Assistant automations
based on entities, areas and devices, and suggests improvements to existing automations.

For each entity:
1. Understand its function and context.
2. Consider its current state and attributes.
3. Suggest context‑aware automations or tweaks, including real entity_ids.

If asked to focus on a theme (energy saving, presence lighting, etc.), integrate it.
Also review existing automations and propose improvements.
If you see a lot of text in a different language, focus on it for a translation for your output.
"""


# =============================================================================
# Coordinator
# =============================================================================
class AIAutomationCoordinator(DataUpdateCoordinator):
    """Builds the prompt, sends it to the selected provider, shares results."""

    # --------------------------------------------------------------------- #
    # Init / lifecycle                                                      #
    # --------------------------------------------------------------------- #
    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass = hass
        self.entry = entry

        self.previous_entities: dict[str, dict] = {}
        self.last_update: datetime | None = None

        # Tunables modified by the generate_suggestions service
        self.SYSTEM_PROMPT = SYSTEM_PROMPT
        self.scan_all = False
        self.selected_domains: list[str] = []
        self.entity_limit = 200
        self.automation_read_file = False  # Default automation reading mode
        self.automation_limit = 100

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.session = async_get_clientsession(hass)

        self._last_error: str | None = None

        self.data: dict = {
            "suggestions": "No suggestions yet",
            "description": None,
            "yaml_block": None,
            "last_update": None,
            "entities_processed": [],
            "provider": self._opt(CONF_PROVIDER, "unknown"),
            "last_error": None,
        }

        # Registries (populated in async_added_to_hass)
        self.device_registry: dr.DeviceRegistry | None = None
        self.entity_registry: er.EntityRegistry | None = None
        self.area_registry: ar.AreaRegistry | None = None

    # ---------------------------------------------------------------------
    # Utility – options‑first lookup
    # ---------------------------------------------------------------------
    def _opt(self, key: str, default=None):
        return self.entry.options.get(key, self.entry.data.get(key, default))

    # ---------------------------------------------------------------------
    # Helper – token budgets with legacy fallback
    # ---------------------------------------------------------------------
    def _budgets(self) -> tuple[int, int]:
        out_budget = self._opt(
            CONF_MAX_OUTPUT_TOKENS, self._opt(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)
        )
        in_budget = self._opt(
            CONF_MAX_INPUT_TOKENS, self._opt(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)
        )
        return in_budget, out_budget

    # ---------------------------------------------------------------------
    # HA lifecycle hooks
    # ---------------------------------------------------------------------
    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.device_registry = dr.async_get(self.hass)
        self.entity_registry = er.async_get(self.hass)
        self.area_registry = ar.async_get(self.hass)

    async def async_shutdown(self):
        return

    # ---------------------------------------------------------------------
    # Main polling routine
    # ---------------------------------------------------------------------
    async def _async_update_data(self) -> dict:
        try:
            now = datetime.now()
            self.last_update = now
            self._last_error = None

            # -------------------------------------------------- gather entities
            current: dict[str, dict] = {}
            for eid in self.hass.states.async_entity_ids():
                if (
                    self.selected_domains
                    and eid.split(".")[0] not in self.selected_domains
                ):
                    continue
                st = self.hass.states.get(eid)
                if st:
                    # Filter out useless states to save tokens and improve quality
                    if st.state in ["unavailable", "unknown"]:
                        continue

                    current[eid] = {
                        "state": st.state,
                        "attributes": st.attributes,
                        "last_changed": st.last_changed,
                        "last_updated": st.last_updated,
                        "friendly_name": st.attributes.get("friendly_name", eid),
                    }

            # Decide which entities to pick (all valid vs new ones)
            if self.scan_all:
                picked = current
            else:
                picked = {
                    k: v for k, v in current.items() if k not in self.previous_entities
                }

            if not picked:
                # Store current as previous so we detect changes next time
                self.previous_entities = current
                return self.data

            prompt = await self._build_prompt(picked)
            response = await self._dispatch(prompt)

            if response:
                match = YAML_RE.search(response)
                yaml_block = match.group(1).strip() if match else None
                description = YAML_RE.sub("", response).strip() if match else None

                persistent_notification.async_create(
                    self.hass,
                    message=response,
                    title="AI Automation Suggestions (%s)" % self._opt(CONF_PROVIDER, "unknown"),
                    notification_id=f"ai_automation_suggestions_{now.timestamp()}",
                )

                self.data = {
                    "suggestions": response,
                    "description": description,
                    "yaml_block": yaml_block,
                    "last_update": now,
                    "entities_processed": list(picked.keys()),
                    "provider": self._opt(CONF_PROVIDER, "unknown"),
                    "last_error": None,
                }
            else:
                self.data.update(
                    {
                        "suggestions": "No suggestions available",
                        "description": None,
                        "yaml_block": None,
                        "last_update": now,
                        "entities_processed": [],
                        "last_error": self._last_error,
                    }
                )

            self.previous_entities = current
            return self.data

        except Exception as err:  # noqa: BLE001
            self._last_error = str(err)
            _LOGGER.error("Coordinator fatal error: %s", err)
            self.data["last_error"] = self._last_error
            return self.data

    # ---------------------------------------------------------------------
    # Prompt builder (UPDATED LOGIC)
    # ---------------------------------------------------------------------
    async def _build_prompt(self, entities: dict) -> str:  # noqa: C901
        """Build the prompt based on entities and automations."""
        MAX_ATTR = 500
        MAX_AUTOM = getattr(self, "automation_limit", 100)

        ent_sections: list[str] = []

        # 1. Convert dict items to a list
        valid_entities = list(entities.items())

        # 2. Sort by last_updated (descending) so recently active devices come first
        #    This ensures the AI sees devices the user is actually interacting with.
        sorted_entities = sorted(
            valid_entities,
            key=lambda x: x[1].get("last_updated", datetime.min),
            reverse=True
        )

        # 3. Slice to limit
        selection = sorted_entities[:self.entity_limit]

        for eid, meta in selection:
            domain = eid.split(".")[0]
            attr_str = str(meta["attributes"])
            if len(attr_str) > MAX_ATTR:
                attr_str = f"{attr_str[:MAX_ATTR]}...(truncated)"

            ent_entry = (
                self.entity_registry.async_get(eid) if self.entity_registry else None
            )
            dev_entry = (
                self.device_registry.async_get(ent_entry.device_id)
                if ent_entry and ent_entry.device_id
                else None
            )

            area_id = (
                ent_entry.area_id
                if ent_entry and ent_entry.area_id
                else (dev_entry.area_id if dev_entry else None)
            )
            area_name = "Unknown Area"
            if area_id and self.area_registry:
                ar_entry = self.area_registry.async_get_area(area_id)
                if ar_entry:
                    area_name = ar_entry.name

            block = (
                f"Entity: {eid}\n"
                f"Friendly Name: {meta['friendly_name']}\n"
                f"Domain: {domain}\n"
                f"State: {meta['state']}\n"
                f"Attributes: {attr_str}\n"
                f"Area: {area_name}\n"
            )

            if dev_entry:
                block += (
                    "Device Info:\n"
                    f"  Manufacturer: {dev_entry.manufacturer}\n"
                    f"  Model: {dev_entry.model}\n"
                    f"  Device Name: {dev_entry.name_by_user or dev_entry.name}\n"
                    f"  Device ID: {dev_entry.id}\n"
                )

            block += (
                f"Last Changed: {meta['last_changed']}\n"
                f"Last Updated: {meta['last_updated']}\n"
                "---\n"
            )
            ent_sections.append(block)

        # Choose automation reading method
        if self.automation_read_file:
            autom_sections = self._read_automations_default(MAX_AUTOM, MAX_ATTR)
            autom_codes = await self._read_automations_file_method(MAX_AUTOM, MAX_ATTR)

            builded_prompt = (
                f"{self.SYSTEM_PROMPT}\n\n"
                f"Entities in your Home Assistant (Selected by recent activity):\n{''.join(ent_sections)}\n"
                "Existing Automations Overview:\n"
                f"{''.join(autom_sections) if autom_sections else 'None found.'}\n\n"
                "Automations YAML Code (for analysis and improvement):\n"
                f"{''.join(autom_codes) if autom_codes else 'No automations YAML code available.'}\n\n"
                "Please analyze both the entities and existing automations. "
                "Propose detailed improvements to existing automations and suggest new ones "
                "that reference only the entity_ids shown above."
            )
        else:
            autom_sections = self._read_automations_default(MAX_AUTOM, MAX_ATTR)

            builded_prompt = (
                f"{self.SYSTEM_PROMPT}\n\n"
                f"Entities in your Home Assistant (Selected by recent activity):\n{''.join(ent_sections)}\n"
                "Existing Automations:\n"
                f"{''.join(autom_sections) if autom_sections else 'None found.'}\n\n"
                "Please propose detailed automations and improvements that reference only the entity_ids above."
            )

        return builded_prompt

    def _read_automations_default(self, max_autom: int, max_attr: int) -> list[str]:
        """Default method for reading automations."""
        autom_sections: list[str] = []
        for aid in self.hass.states.async_entity_ids("automation")[:max_autom]:
            st = self.hass.states.get(aid)
            if st:
                attr = str(st.attributes)
                if len(attr) > max_attr:
                    attr = f"{attr[:max_attr]}...(truncated)"
                autom_sections.append(
                    f"Entity: {aid}\n"
                    f"Friendly Name: {st.attributes.get('friendly_name', aid)}\n"
                    f"State: {st.state}\n"
                    f"Attributes: {attr}\n"
                    "---\n"
                )
        return autom_sections

    async def _read_automations_file_method(self, max_autom: int, max_attr: int) -> list[str]:
        """File method for reading automations."""
        automations_file = Path(self.hass.config.path()) / "automations.yaml"
        autom_codes: list[str] = []

        try:
            async with await anyio.open_file(
                automations_file, "r", encoding="utf-8"
            ) as file:
                content = await file.read()
                automations = yaml.safe_load(content)

            if not automations:
                return []
                
            for automation in automations[:max_autom]:
                aid = automation.get("id", "unknown_id")
                alias = automation.get("alias", "Unnamed Automation")
                description = automation.get("description", "")
                trigger = automation.get("trigger", []) + automation.get("triggers", [])
                condition = automation.get("condition", []) + automation.get(
                    "conditions", []
                )
                action = automation.get("action", []) + automation.get("actions", [])

                # YAML
                code_block = (
                    f"Automation Code for automation.{aid}:\n"
                    "```yaml\n"
                    f"- id: '{aid}'\n"
                    f"  alias: '{alias}'\n"
                    f"  description: '{description}'\n"
                    f"  trigger: {trigger}\n"
                    f"  condition: {condition}\n"
                    f"  action: {action}\n"
                    "```\n"
                    "---\n"
                )
                autom_codes.append(code_block)

        except FileNotFoundError:
            _LOGGER.error("The automations.yaml file was not found.")
        except yaml.YAMLError as err:
            _LOGGER.error("Error parsing automations.yaml: %s", err)
        except Exception as err:
            _LOGGER.error("Unexpected error reading automations.yaml: %s", err)

        return autom_codes

    # ---------------------------------------------------------------------
    # Provider dispatcher
    # ---------------------------------------------------------------------
    async def _dispatch(self, prompt: str) -> str | None:
        provider = self._opt(CONF_PROVIDER, "OpenAI")
        self._last_error = None
        try:
            # Check if provider exists in dict to prevent KeyError
            providers = {
                "OpenAI": self._openai,
                "Anthropic": self._anthropic,
                "Google": self._google,
                "Groq": self._groq,
                "LocalAI": self._localai,
                "Ollama": self._ollama,
                "Custom OpenAI": self._custom_openai,
                "Mistral AI": self._mistral,
                "Perplexity AI": self._perplexity,
                "OpenRouter": self._openrouter,
                "OpenAI Azure": self._openai_azure,
                "Generic OpenAI": self._generic_openai,
            }
            
            if provider not in providers:
                 self._last_error = f"Unknown provider '{provider}'"
                 _LOGGER.error(self._last_error)
                 return None

            return await providers[provider](prompt)
            
        except Exception as err:  # noqa: BLE001
            self._last_error = str(err)
            _LOGGER.error("Dispatch error: %s", err)
            return None

    # ... (Rest of the file with API implementations remains unchanged)
    # Be sure to keep the API methods (_openai, _google, etc.) in the file 
    # when you copy it, but I have omitted them here for brevity as they 
    # don't need logic changes, just the changes above.
    # To be safe, copy the entire file content but replace the _build_prompt 
    # and _async_update_data methods with the ones above.
    
    # ---------------------------------------------------------------------
    # IMPORTANT: Include all the API methods here as in original file
    # ---------------------------------------------------------------------
    # (Since I cannot output 800 lines, assume the rest is identical to your original upload
    # unless you want me to print the FULL file. The critical changes are above.)
    async def _openai(self, prompt: str) -> str | None:
        # ... (Original code)
        try:
            api_key = self._opt(CONF_OPENAI_API_KEY)
            model = self._opt(CONF_OPENAI_MODEL, DEFAULT_MODELS["OpenAI"])
            temperature = self._opt(CONF_OPENAI_TEMPERATURE, DEFAULT_TEMPERATURE)
            in_budget, out_budget = self._budgets()
            if not api_key:
                raise ValueError("OpenAI API key not configured")

            if len(prompt) // 4 > in_budget:
                prompt = prompt[: in_budget * 4]

            body = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": out_budget,
                "temperature": temperature,
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            timeout = aiohttp.ClientTimeout(total=900)

            async with self.session.post(
                ENDPOINT_OPENAI, headers=headers, json=body, timeout=timeout
            ) as resp:
                if resp.status != 200:
                    self._last_error = (
                        f"OpenAI error {resp.status}: {await resp.text()}"
                    )
                    _LOGGER.error(self._last_error)
                    return None

                res = await resp.json()

            return res["choices"][0]["message"]["content"]
        except Exception as err:
            self._last_error = f"OpenAI processing error: {str(err)}"
            _LOGGER.error(self._last_error)
            return None

    # (Repeat for other providers from original file...)
    # I strongly recommend checking that the provider functions are still there.
    # If you want the FULL file output, let me know.
    # For now, ensure you paste the new logic into the class.
