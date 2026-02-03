"""Coordinator for AI Automation Suggester v2.0."""
from __future__ import annotations

import json
import logging
import os
import re
import hashlib
from datetime import datetime
from pathlib import Path

import aiohttp
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import *

_LOGGER = logging.getLogger(__name__)

MEMORY_FILENAME = "ai_suggester_memory.json"
HISTORY_FILENAME = "ai_suggestions_history.json"

SYSTEM_PROMPT = """You are an expert Home Assistant Architect and Repair Technician.
Your tasks:
1. Analyze the provided entities and existing automations.
2. Repair: Suggest FIXES for broken ('unavailable') entities.
3. Innovate: Suggest NEW automations or Improvements.
4. Blueprints: Create a BLUEPRINT for reusable logic.

MEMORY / CONTEXT:
The user has previously REJECTED suggestions related to: {dislikes}.
DO NOT suggest these topics again.

IMPORTANT: You must output your response in strict JSON format list.
Format:
[
  {{
    "title": "Example",
    "description": "...",
    "type": "fix/innovation/blueprint",
    "yaml": "..."
  }}
]
"""

class AIAutomationCoordinator(DataUpdateCoordinator):
    """Bygger prompts, sender til AI og håndterer resultater/historik."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.previous_entities: dict[str, dict] = {}
        self.last_update: datetime | None = None
        self.SYSTEM_PROMPT = SYSTEM_PROMPT
        self.scan_all = False
        self.selected_domains: list[str] = []
        self.entity_limit = 40 
        self.automation_read_file = False
        self.automation_limit = 100
        self.current_temperature = 0.1 # Standard temperatur

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.session = async_get_clientsession(hass)
        self._last_error: str | None = None

        self.data: dict = {
            "suggestions_list": [],
            "history": [],
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

    async def async_added_to_hass(self):
        self.device_registry = dr.async_get(self.hass)
        self.entity_registry = er.async_get(self.hass)
        self.area_registry = ar.async_get(self.hass)
        await self._load_memory()
        await self._load_history()

    async def _load_memory(self):
        path = self.hass.config.path(MEMORY_FILENAME)
        if os.path.exists(path):
            try:
                def load():
                    with open(path, 'r', encoding='utf-8') as f: return json.load(f)
                self._memory_cache = await self.hass.async_add_executor_job(load)
            except Exception as e: _LOGGER.error("Failed to load memory: %s", e)

    async def _load_history(self):
        path = self.hass.config.path(HISTORY_FILENAME)
        if os.path.exists(path):
            try:
                def load():
                    with open(path, 'r', encoding='utf-8') as f: return json.load(f)
                self.data["history"] = await self.hass.async_add_executor_job(load)
            except Exception as e: _LOGGER.error("Failed to load history: %s", e)

    async def _async_update_data(self) -> dict:
        try:
            now = datetime.now()
            self.last_update = now
            self._last_error = None
            current: dict[str, dict] = {}
            unavailable: list[str] = []

            for eid in self.hass.states.async_entity_ids():
                st = self.hass.states.get(eid)
                if not st: continue
                if st.state in ["unavailable", "unknown"]:
                    unavailable.append(eid)
                    continue
                current[eid] = {
                    "state": st.state,
                    "friendly_name": st.attributes.get("friendly_name", eid),
                    "attributes": st.attributes
                }

            picked = current if self.scan_all else {k: v for k, v in current.items() if k not in self.previous_entities}
            if not picked and not unavailable:
                self.previous_entities = current
                return self.data

            prompt = await self._build_prompt(picked, unavailable)
            response = await self._dispatch(prompt)

            if response:
                raw_suggestions = self._parse_json_response(response)
                processed = []
                for s in raw_suggestions:
                    s_id = hashlib.md5(f"{s.get('title')}{now}".encode()).hexdigest()[:10]
                    s["suggestion_id"] = s_id
                    s["timestamp"] = now.isoformat()
                    processed.append(s)

                if processed:
                    await self._update_history(processed)
                
                self.data.update({
                    "suggestions_list": processed,
                    "last_update": now.isoformat(),
                    "entities_processed": list(picked.keys()),
                    "provider": self._opt(CONF_PROVIDER, "unknown"),
                    "last_error": None,
                })

            self.previous_entities = current
            return self.data
        except Exception as err:
            _LOGGER.error("Coordinator error: %s", err)
            self._last_error = str(err)
            return self.data

    async def _update_history(self, new_sugs):
        path = self.hass.config.path(HISTORY_FILENAME)
        history = self.data.get("history", [])
        for s in new_sugs: history.insert(0, s)
        self.data["history"] = history[:100]
        def save():
            with open(path, 'w', encoding='utf-8') as f: json.dump(self.data["history"], f, indent=2)
        await self.hass.async_add_executor_job(save)

    async def handle_save_suggestion(self, call: ServiceCall | dict):
        """Gemmer forslag til ai_automations.yaml eller blueprints."""
        if isinstance(call, dict):
            sug_id = call.get("suggestion_id")
        else:
            sug_id = call.data.get("suggestion_id")
        
        if isinstance(sug_id, str) and sug_id.startswith("latest_"):
            try:
                idx = int(sug_id.split("_")[1]) - 1
                s_list = self.data.get("suggestions_list", [])
                suggestion = s_list[idx] if 0 <= idx < len(s_list) else None
            except: suggestion = None
        else:
            suggestion = next((s for s in self.data["suggestions_list"] + self.data["history"] if s.get("suggestion_id") == sug_id), None)
        
        if not suggestion or "yaml" not in suggestion:
            _LOGGER.error("Kunne ikke gemme: Forslag ikke fundet.")
            return

        yaml_code = suggestion["yaml"]
        is_bp = "blueprint:" in yaml_code or suggestion.get("type") == "blueprint"

        try:
            if is_bp:
                real_id = suggestion.get("suggestion_id", "unknown")
                fname = f"ai_gen_{real_id}.yaml"
                path = self.hass.config.path(f"blueprints/automation/{fname}")
                def write_bp():
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w", encoding="utf-8") as f: f.write(yaml_code)
                await self.hass.async_add_executor_job(write_bp)
                msg = f"Blueprint gemt som {fname}"
            else:
                path = self.hass.config.path("ai_automations.yaml")
                def append_auto():
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(f"\n\n# AI Generated: {suggestion['title']} ({datetime.now()})\n{yaml_code}")
                await self.hass.async_add_executor_job(append_auto)
                msg = "Automatisering gemt i ai_automations.yaml"

            persistent_notification.async_create(self.hass, message=msg, title="AI Suggester")
        except Exception as e: _LOGGER.error("Save failed: %s", e)

    async def handle_clear_history(self, call: ServiceCall):
        path = self.hass.config.path(HISTORY_FILENAME)
        if os.path.exists(path):
            def remove(): os.remove(path)
            await self.hass.async_add_executor_job(remove)
        self.data["history"] = []
        self.async_set_updated_data(self.data)
        persistent_notification.async_create(self.hass, message="Historik slettet.", title="AI Suggester")

    def _parse_json_response(self, response: str) -> list[dict]:
        try: return json.loads(response)
        except: pass
        cleaned = response.strip()
        if not cleaned.endswith(']'):
            last_bracket = cleaned.rfind('}')
            if last_bracket != -1: cleaned = cleaned[:last_bracket + 1] + ']'
        try: return json.loads(cleaned)
        except:
            found = []
            for obj in re.finditer(r"\{[\s\S]*?\}", cleaned):
                try: found.append(json.loads(obj.group(0)))
                except: continue
            return found

    async def _build_prompt(self, entities: dict, unavailable: list[str]) -> str:
        dislikes = ", ".join(self._memory_cache.get("dislikes", [])) or "None"
        prompt = self.SYSTEM_PROMPT.format(dislikes=dislikes)
        ent_data = [f"E: {k}, N: {v['friendly_name']}, S: {v['state']}\n" for k, v in list(entities.items())[:self.entity_limit]]
        prompt += f"\nEntities:\n{''.join(ent_data)}\n"
        if unavailable: prompt += f"BROKEN: {', '.join(unavailable[:20])}\n"
        return prompt

    async def _dispatch(self, prompt: str) -> str | None:
        p = self._opt(CONF_PROVIDER, "Google")
        providers = {
            "OpenAI": self._openai, "Anthropic": self._anthropic, "Google": self._google,
            "Groq": self._groq, "LocalAI": self._localai, "Ollama": self._ollama,
            "Custom OpenAI": self._custom_openai, "Mistral AI": self._mistral,
            "Perplexity AI": self._perplexity, "OpenRouter": self._openrouter,
            "OpenAI Azure": self._openai_azure, "Generic OpenAI": self._generic_openai,
        }
        return await providers[p](prompt) if p in providers else None

    # --- AI Providers med Temperatur Support ---

    async def _google(self, prompt: str):
        try:
            api_key = self._opt(CONF_GOOGLE_API_KEY)
            model = self._opt(CONF_GOOGLE_MODEL, "gemini-1.5-flash")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            body = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": self.current_temperature}
            }
            async with self.session.post(url, json=body, timeout=90) as resp:
                res = await resp.json()
                return res["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e: return str(e)

    async def _openai(self, prompt: str):
        try:
            api_key = self._opt(CONF_OPENAI_API_KEY)
            model = self._opt(CONF_OPENAI_MODEL, "gpt-4o-mini")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": self.current_temperature}
            async with self.session.post(ENDPOINT_OPENAI, headers=headers, json=body, timeout=90) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception: return None

    async def _anthropic(self, prompt: str):
        try:
            api_key = self._opt(CONF_ANTHROPIC_API_KEY)
            model = self._opt(CONF_ANTHROPIC_MODEL, "claude-3-5-sonnet-20240620")
            headers = {"X-API-Key": api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01"}
            body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 1024, "temperature": self.current_temperature}
            async with self.session.post(ENDPOINT_ANTHROPIC, headers=headers, json=body, timeout=90) as resp:
                res = await resp.json()
                return res["content"][0]["text"]
        except Exception: return None

    async def _groq(self, prompt: str):
        try:
            api_key = self._opt(CONF_GROQ_API_KEY)
            model = self._opt(CONF_GROQ_MODEL, "llama3-70b-8192")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": self.current_temperature}
            async with self.session.post(ENDPOINT_GROQ, headers=headers, json=body, timeout=90) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception: return None

    async def _ollama(self, prompt: str):
        try:
            ip, port = self._opt(CONF_OLLAMA_IP_ADDRESS), self._opt(CONF_OLLAMA_PORT)
            model = self._opt(CONF_OLLAMA_MODEL, "llama3")
            body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False, "options": {"temperature": self.current_temperature}}
            async with self.session.post(f"http://{ip}:{port}/api/chat", json=body, timeout=90) as resp:
                res = await resp.json()
                return res["message"]["content"]
        except Exception: return None

    async def _localai(self, prompt: str):
        try:
            ip, port = self._opt(CONF_LOCALAI_IP_ADDRESS), self._opt(CONF_LOCALAI_PORT)
            model = self._opt(CONF_LOCALAI_MODEL, "gpt-4")
            endpoint = f"http://{ip}:{port}/v1/chat/completions"
            body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": self.current_temperature}
            async with self.session.post(endpoint, json=body, timeout=90) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception: return None

    async def _mistral(self, prompt: str):
        try:
            api_key = self._opt(CONF_MISTRAL_API_KEY)
            model = self._opt(CONF_MISTRAL_MODEL, "mistral-large-latest")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": self.current_temperature}
            async with self.session.post(ENDPOINT_MISTRAL, headers=headers, json=body, timeout=90) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception: return None

    async def _perplexity(self, prompt: str):
        try:
            api_key = self._opt(CONF_PERPLEXITY_API_KEY)
            model = self._opt(CONF_PERPLEXITY_MODEL, "llama-3-sonar-large-32k-online")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": self.current_temperature}
            async with self.session.post(ENDPOINT_PERPLEXITY, headers=headers, json=body, timeout=90) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception: return None

    async def _openrouter(self, prompt: str):
        try:
            api_key = self._opt(CONF_OPENROUTER_API_KEY)
            model = self._opt(CONF_OPENROUTER_MODEL, "meta-llama/llama-3-70b-instruct")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": self.current_temperature}
            async with self.session.post(ENDPOINT_OPENROUTER, headers=headers, json=body, timeout=90) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception: return None

    async def _openai_azure(self, prompt: str):
        try:
            base = self._opt(CONF_OPENAI_AZURE_ENDPOINT)
            deployment = self._opt(CONF_OPENAI_AZURE_DEPLOYMENT_ID)
            key = self._opt(CONF_OPENAI_AZURE_API_KEY)
            ver = self._opt(CONF_OPENAI_AZURE_API_VERSION, "2024-02-15-preview")
            url = f"https://{base}/openai/deployments/{deployment}/chat/completions?api-version={ver}"
            headers = {"api-key": key, "Content-Type": "application/json"}
            async with self.session.post(url, headers=headers, json={"messages": [{"role": "user", "content": prompt}], "temperature": self.current_temperature}, timeout=90) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception: return None

    async def _custom_openai(self, prompt: str):
        try:
            url, api_key = self._opt(CONF_CUSTOM_OPENAI_ENDPOINT), self._opt(CONF_CUSTOM_OPENAI_API_KEY)
            model = self._opt(CONF_CUSTOM_OPENAI_MODEL)
            headers = {"Content-Type": "application/json"}
            if api_key: headers["Authorization"] = f"Bearer {api_key}"
            body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": self.current_temperature}
            async with self.session.post(f"{url}/v1/chat/completions", headers=headers, json=body, timeout=90) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception: return None

    async def _generic_openai(self, prompt: str):
        try:
            url, api_key = self._opt(CONF_GENERIC_OPENAI_ENDPOINT), self._opt(CONF_GENERIC_OPENAI_API_KEY)
            model = self._opt(CONF_GENERIC_OPENAI_MODEL, "gpt-4")
            headers = {"Content-Type": "application/json"}
            if api_key: headers["Authorization"] = f"Bearer {api_key}"
            body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": self.current_temperature}
            async with self.session.post(url, headers=headers, json=body, timeout=90) as resp:
                res = await resp.json()
                return res["choices"][0]["message"]["content"]
        except Exception: return None

    async def async_shutdown(self):
        if self.session: await self.session.close()
