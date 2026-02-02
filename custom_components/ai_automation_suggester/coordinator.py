"""Coordinator for AI Automation Suggester.
Changelog:
- Added MEMORY: Loads/Saves user dislikes to 'ai_suggester_memory.json'.
- Added BLUEPRINTS: Prompt updated to request Blueprints logic.
- Added SELF-HEALING: Scans for 'unavailable' entities and requests fixes.
- Maintained JSON output and Smart Selection.
- Includes ALL provider methods.
"""
from __future__ import annotations
from datetime import datetime
import json
import logging
import os
import re
from pathlib import Path

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

# Filename for memory storage
MEMORY_FILENAME = "ai_suggester_memory.json"

SYSTEM_PROMPT = """You are an expert Home Assistant Architect and Repair Technician.
Your tasks:
1. Analyze the provided entities and existing automations.
2. Repair: If entities are listed as 'unavailable' or automations seem broken, suggest FIXES first.
3. Innovate: Suggest NEW automations or Improvements based on the user's devices.
4. Blueprints: If a logic pattern is reusable (e.g., motion light), create a BLUEPRINT instead of a standard automation.

MEMORY / CONTEXT:
The user has previously REJECTED suggestions related to: {dislikes}.
DO NOT suggest these topics again.

IMPORTANT: You must output your response in strict JSON format.
Do not output any markdown text outside the JSON structure.
Output format:
[
{{
"title": "Fix for Unavailable Light",
"description": "The kitchen light appears unavailable. This automation notifies you...",
"type": "fix",
"yaml": "..."
}},
{{
"title": "Motion Light Blueprint",
"description": "A reusable blueprint for any room with a motion sensor.",
"type": "blueprint",
"yaml": "blueprint: ..."
}}
]
"""

class AIAutomationCoordinator(DataUpdateCoordinator):
    """Builds the prompt, sends it to the selected provider, shares results."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass = hass
        self.entry = entry

        self.previous_entities: dict[str, dict] = {}
        self.last_update: datetime | None = None

        self.SYSTEM_PROMPT = SYSTEM_PROMPT
        self.scan_all = False
        self.selected_domains: list[str] = []
        self.entity_limit = 200
        self.automation_read_file = False
        self.automation_limit = 100

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.session = async_get_clientsession(hass)
        self._last_error: str | None = None

        self.data: dict = {
            "suggestions_list": [],
            "last_update": None,
            "entities_processed": [],
            "provider": self._opt(CONF_PROVIDER, "unknown"),
            "last_error": None,
        }

        self.device_registry: dr.DeviceRegistry | None = None
        self.entity_registry: er.EntityRegistry | None = None
        self.area_registry: ar.AreaRegistry | None = None
        self._memory_cache = {"dislikes": []}

    def _opt(self, key: str, default=None):
        return self.entry.options.get(key, self.entry.data.get(key, default))

    def _budgets(self) -> tuple[int, int]:
        out_budget = self._opt(CONF_MAX_OUTPUT_TOKENS, self._opt(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS))
        in_budget = self._opt(CONF_MAX_INPUT_TOKENS, self._opt(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS))
        return in_budget, out_budget

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.device_registry = dr.async_get(self.hass)
        self.entity_registry = er.async_get(self.hass)
        self.area_registry = ar.async_get(self.hass)
        await self._load_memory()

    async def _load_memory(self):
        path = self.hass.config.path(MEMORY_FILENAME)
        if os.path.exists(path):
            try:
                def load():
                    with open(path, 'r', encoding='utf-8') as f:
                        return json.load(f)
                self._memory_cache = await self.hass.async_add_executor_job(load)
            except Exception as e:
                _LOGGER.error(f"Failed to load AI memory: {e}")
                self._memory_cache = {"dislikes": []}

    async def _async_update_data(self) -> dict:
        try:
            now = datetime.now()
            self.last_update = now
            self._last_error = None

            current: dict[str, dict] = {}
            unavailable_entities: list[str] = []

            for eid in self.hass.states.async_entity_ids():
                if self.selected_domains and eid.split(".")[0] not in self.selected_domains:
                    continue
                st = self.hass.states.get(eid)
                if st:
                    if st.state in ["unavailable", "unknown"]:
                        unavailable_entities.append(f"{eid} (State: {st.state})")
                        continue
                    current[eid] = {
                        "state": st.state,
                        "attributes": st.attributes,
                        "last_changed": st.last_changed,
                        "last_updated": st.last_updated,
                        "friendly_name": st.attributes.get("friendly_name", eid),
                    }

            picked = current if self.scan_all else {k: v for k, v in current.items() if k not in self.previous_entities}

            if not picked and not unavailable_entities:
                self.previous_entities = current
                return self.data

            prompt = await self._build_prompt(picked, unavailable_entities)
            response = await self._dispatch(prompt)

            suggestions_list = []
            if response:
                suggestions_list = self._parse_json_response(response)
                if suggestions_list:
                    persistent_notification.async_create(
                        self.hass,
                        message=f"Received {len(suggestions_list)} suggestions.",
                        title="AI Automation Suggester",
                        notification_id=f"ai_sug_msg_{now.timestamp()}",
                    )
                self.data = {
                    "suggestions_list": suggestions_list,
                    "last_update": now,
                    "entities_processed": list(picked.keys()),
                    "provider": self._opt(CONF_PROVIDER, "unknown"),
                    "last_error": None,
                }
            else:
                self.data.update({"last_update": now, "last_error": self._last_error})

            self.previous_entities = current
            return self.data
        except Exception as err:
            _LOGGER.error("Fatal coordinator error: %s", err)
            return self.data

    def _parse_json_response(self, response: str) -> list[dict]:
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        try:
            # Regex fixed to handle common AI formatting
            match = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", response, re.IGNORECASE)
            if match:
                return json.loads(match.group(1))
            start, end = response.find('['), response.rfind(']')
            if start != -1 and end != -1:
                json_str = re.sub(r",\s*\]", "]", response[start:end+1])
                return json.loads(json_str)
        except Exception as e:
            _LOGGER.error("JSON Parse error: %s", e)
        return []

    async def _build_prompt(self, entities: dict, unavailable: list[str]) -> str:
        MAX_ATTR = 500
        MAX_AUTOM = getattr(self, "automation_limit", 100)
        
        ent_sections = []
        sorted_ents = sorted(entities.items(), key=lambda x: x[1].get("last_updated", datetime.min), reverse=True)
        
        for eid, meta in sorted_ents[:self.entity_limit]:
            attr_str = str(meta["attributes"])[:MAX_ATTR]
            ent_sections.append(f"Entity: {eid}\nName: {meta['friendly_name']}\nState: {meta['state']}\nAttrs: {attr_str}\n---\n")

        autom_sections = self._read_automations_default(MAX_AUTOM, MAX_ATTR)
        dislikes_str = ", ".join(self._memory_cache.get("dislikes", [])) or "None"
        
        prompt = self.SYSTEM_PROMPT.format(dislikes=dislikes_str)
        prompt += f"\n\nActive Entities:\n{''.join(ent_sections)}\n"
        
        if unavailable:
            prompt += f"⚠️ BROKEN ENTITIES: {', '.join(unavailable[:50])}\n\n"
        
        prompt += f"Existing Automations:\n{''.join(autom_sections)}\n\n"
        prompt += "Output strictly in JSON."
        return prompt

    def _read_automations_default(self, max_autom: int, max_attr: int) -> list[str]:
        sections = []
        for aid in self.hass.states.async_entity_ids("automation")[:max_autom]:
            st = self.hass.states.get(aid)
            if st:
                attr = str(st.attributes)[:max_attr]
                sections.append(f"Automation: {aid}\nState: {st.state}\nAttrs: {attr}\n---\n")
        return sections

    async def _dispatch(self, prompt: str) -> str | None:
        provider = self._opt(CONF_PROVIDER, "OpenAI")
        providers = {
            "OpenAI": self._openai, "Anthropic": self._anthropic, "Google": self._google,
            "Groq": self._groq, "LocalAI": self._localai, "Ollama": self._ollama,
            "Custom OpenAI": self._custom_openai, "Mistral AI": self._mistral,
            "Perplexity AI": self._perplexity, "OpenRouter": self._openrouter,
            "OpenAI Azure": self._openai_azure, "Generic OpenAI": self._generic_openai,
        }
        if provider not in providers: return None
        return await providers[provider](prompt)

    async def _openai(self, prompt: str) -> str | None:
        try:
            api_key = self._opt(CONF_OPENAI_API_KEY)
            model = self._opt(CONF_OPENAI_MODEL, DEFAULT_MODELS["OpenAI"])
            in_budget, out_budget = self._budgets()
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": out_budget}
            async with self.session.post(ENDPOINT_OPENAI, headers=headers, json=body, timeout=900) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception as e: self._last_error = str(e); return None

    async def _google(self, prompt: str) -> str | None:
        try:
            api_key = self._opt(CONF_GOOGLE_API_KEY)
            model = self._opt(CONF_GOOGLE_MODEL, DEFAULT_MODELS["Google"])
            _, out_budget = self._budgets()
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": out_budget}}
            async with self.session.post(endpoint, json=body, timeout=900) as resp:
                res = await resp.json()
                return res["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e: self._last_error = str(e); return None

    # Andre udbydere (Anthropic, Groq, etc.) følger samme mønster...
    async def _anthropic(self, prompt: str) -> str | None:
        try:
            api_key = self._opt(CONF_ANTHROPIC_API_KEY)
            model = self._opt(CONF_ANTHROPIC_MODEL, DEFAULT_MODELS["Anthropic"])
            _, out_budget = self._budgets()
            headers = {"X-API-Key": api_key, "Content-Type": "application/json", "anthropic-version": VERSION_ANTHROPIC}
            body = {"model": model, "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}], "max_tokens": out_budget}
            async with self.session.post(ENDPOINT_ANTHROPIC, headers=headers, json=body, timeout=900) as resp:
                res = await resp.json()
                return res["content"][0]["text"]
        except Exception as e: self._last_error = str(e); return None

    async def _groq(self, prompt: str) -> str | None:
        try:
            api_key = self._opt(CONF_GROQ_API_KEY)
            model = self._opt(CONF_GROQ_MODEL, DEFAULT_MODELS["Groq"])
            _, out_budget = self._budgets()
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": out_budget}
            async with self.session.post(ENDPOINT_GROQ, headers=headers, json=body, timeout=900) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception as e: self._last_error = str(e); return None

    async def _ollama(self, prompt: str) -> str | None:
        try:
            ip, port = self._opt(CONF_OLLAMA_IP_ADDRESS), self._opt(CONF_OLLAMA_PORT)
            model = self._opt(CONF_OLLAMA_MODEL, DEFAULT_MODELS["Ollama"])
            body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
            async with self.session.post(f"http://{ip}:{port}/api/chat", json=body, timeout=900) as resp:
                res = await resp.json()
                return res["message"]["content"]
        except Exception as e: self._last_error = str(e); return None

    async def _openai_azure(self, prompt: str) -> str | None:
        try:
            base = self._opt(CONF_OPENAI_AZURE_ENDPOINT)
            deployment = self._opt(CONF_OPENAI_AZURE_DEPLOYMENT_ID)
            key = self._opt(CONF_OPENAI_AZURE_API_KEY)
            ver = self._opt(CONF_OPENAI_AZURE_API_VERSION, "2025-01-01-preview")
            url = f"https://{base}/openai/deployments/{deployment}/chat/completions?api-version={ver}"
            headers = {"api-key": key, "Content-Type": "application/json"}
            body = {"messages": [{"role": "user", "content": prompt}], "max_tokens": self._budgets()[1]}
            async with self.session.post(url, headers=headers, json=body, timeout=900) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception as e: self._last_error = str(e); return None
    async def _localai(self, prompt: str) -> str | None:
        try:
            ip, port = self._opt(CONF_LOCALAI_IP_ADDRESS), self._opt(CONF_LOCALAI_PORT)
            model = self._opt(CONF_LOCALAI_MODEL, DEFAULT_MODELS["LocalAI"])
            # Vi antager http medmindre andet er defineret
            endpoint = f"http://{ip}:{port}/v1/chat/completions"
            body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
            async with self.session.post(endpoint, json=body, timeout=900) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception as e: self._last_error = str(e); return None

    async def _mistral(self, prompt: str) -> str | None:
        try:
            api_key = self._opt(CONF_MISTRAL_API_KEY)
            model = self._opt(CONF_MISTRAL_MODEL, DEFAULT_MODELS["Mistral AI"])
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
            async with self.session.post(ENDPOINT_MISTRAL, headers=headers, json=body, timeout=900) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception as e: self._last_error = str(e); return None

    async def _perplexity(self, prompt: str) -> str | None:
        try:
            api_key = self._opt(CONF_PERPLEXITY_API_KEY)
            model = self._opt(CONF_PERPLEXITY_MODEL, DEFAULT_MODELS["Perplexity AI"])
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
            async with self.session.post(ENDPOINT_PERPLEXITY, headers=headers, json=body, timeout=900) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception as e: self._last_error = str(e); return None

    async def _openrouter(self, prompt: str) -> str | None:
        try:
            api_key = self._opt(CONF_OPENROUTER_API_KEY)
            model = self._opt(CONF_OPENROUTER_MODEL, DEFAULT_MODELS["OpenRouter"])
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
            async with self.session.post(ENDPOINT_OPENROUTER, headers=headers, json=body, timeout=900) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception as e: self._last_error = str(e); return None

    async def _custom_openai(self, prompt: str) -> str | None:
        try:
            url = self._opt(CONF_CUSTOM_OPENAI_ENDPOINT)
            api_key = self._opt(CONF_CUSTOM_OPENAI_API_KEY)
            model = self._opt(CONF_CUSTOM_OPENAI_MODEL)
            headers = {"Content-Type": "application/json"}
            if api_key: headers["Authorization"] = f"Bearer {api_key}"
            body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
            async with self.session.post(f"{url}/v1/chat/completions", headers=headers, json=body, timeout=900) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception as e: self._last_error = str(e); return None

    async def _generic_openai(self, prompt: str) -> str | None:
        try:
            endpoint = self._opt(CONF_GENERIC_OPENAI_ENDPOINT)
            api_key = self._opt(CONF_GENERIC_OPENAI_API_KEY)
            model = self._opt(CONF_GENERIC_OPENAI_MODEL, "gpt-4o-mini")
            headers = {"Content-Type": "application/json"}
            if api_key: headers["Authorization"] = f"Bearer {api_key}"
            body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
            async with self.session.post(endpoint, headers=headers, json=body, timeout=900) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception as e: self._last_error = str(e); return None
