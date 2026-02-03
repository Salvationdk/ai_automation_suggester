"""Config flow for AI Automation Suggester v2.0."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig

from .const import *

_LOGGER = logging.getLogger(__name__)

class ProviderValidator:
    """Validerer API-nøgler ved at sende en dummy-forespørgsel til udbyderen."""

    def __init__(self, hass):
        self.session = async_get_clientsession(hass)

    async def validate_openai(self, api_key: str) -> Optional[str]:
        hdr = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        try:
            resp = await self.session.get("https://api.openai.com/v1/models", headers=hdr)
            return None if resp.status == 200 else await resp.text()
        except Exception as err: return str(err)

    async def validate_anthropic(self, api_key: str, model: str) -> Optional[str]:
        hdr = {"x-api-key": api_key, "anthropic-version": VERSION_ANTHROPIC, "content-type": "application/json"}
        payload = {"model": model, "messages": [{"role": "user", "content": [{"type": "text", "text": "ping"}]}], "max_tokens": 1}
        try:
            resp = await self.session.post(ENDPOINT_ANTHROPIC, headers=hdr, json=payload)
            return None if resp.status == 200 else await resp.text()
        except Exception as err: return str(err)

    async def validate_google(self, api_key: str, model: str) -> Optional[str]:
        url = ENDPOINT_GOOGLE.format(model=model, api_key=api_key)
        payload = {"contents": [{"parts": [{"text": "ping"}]}], "generationConfig": {"maxOutputTokens": 1}}
        try:
            resp = await self.session.post(url, json=payload)
            return None if resp.status == 200 else await resp.text()
        except Exception as err: return str(err)

    async def validate_groq(self, api_key: str) -> Optional[str]:
        hdr = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        try:
            resp = await self.session.get("https://api.groq.com/openai/v1/models", headers=hdr)
            return None if resp.status == 200 else await resp.text()
        except Exception as err: return str(err)

    async def validate_localai(self, ip: str, port: int, https: bool) -> Optional[str]:
        proto = "https" if https else "http"
        try:
            resp = await self.session.get(f"{proto}://{ip}:{port}/v1/models")
            return None if resp.status == 200 else await resp.text()
        except Exception as err: return str(err)

    async def validate_ollama(self, ip: str, port: int, https: bool) -> Optional[str]:
        proto = "https" if https else "http"
        try:
            resp = await self.session.get(f"{proto}://{ip}:{port}/api/tags")
            return None if resp.status == 200 else await resp.text()
        except Exception as err: return str(err)

class AIAutomationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Håndterer integrationens opsætning via UI."""

    VERSION = CONFIG_VERSION

    def __init__(self) -> None:
        self.provider: str | None = None
        self.data: Dict[str, Any] = {}
        self.validator: ProviderValidator | None = None

    async def async_step_user(self, user_input: Dict[str, Any] | None = None):
        errors: Dict[str, str] = {}
        if user_input:
            self.provider = user_input[CONF_PROVIDER]
            self.data.update(user_input)

            if any(ent.data.get(CONF_PROVIDER) == self.provider for ent in self._async_current_entries()):
                errors["base"] = "already_configured"
            else:
                steps = {
                    "OpenAI": self.async_step_openai, "Anthropic": self.async_step_anthropic,
                    "Google": self.async_step_google, "Groq": self.async_step_groq,
                    "LocalAI": self.async_step_localai, "Ollama": self.async_step_ollama,
                    "Custom OpenAI": self.async_step_custom_openai, "Mistral AI": self.async_step_mistral,
                    "Perplexity AI": self.async_step_perplexity, "OpenRouter": self.async_step_openrouter,
                    "OpenAI Azure": self.async_step_openai_azure, "Generic OpenAI": self.async_step_generic_openai,
                }
                return await steps[self.provider]()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_PROVIDER): vol.In(sorted(list(DEFAULT_MODELS.keys())))}),
            errors=errors,
        )

    async def _provider_form(self, step_id: str, schema: vol.Schema, validate_fn, title: str, user_input: Dict[str, Any] | None):
        errors = {}
        placeholders = {}
        if user_input:
            self.validator = ProviderValidator(self.hass)
            err = await validate_fn(user_input)
            if err is None:
                self.data.update(user_input)
                return self.async_create_entry(title=title, data=self.data)
            errors["base"] = "api_error"
            placeholders["error_message"] = err

        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors, description_placeholders=placeholders)

    def _add_token_fields(self, base: Dict[Any, Any]) -> Dict[Any, Any]:
        base[vol.Optional(CONF_MAX_INPUT_TOKENS, default=DEFAULT_MAX_INPUT_TOKENS)] = vol.All(vol.Coerce(int), vol.Range(min=100))
        base[vol.Optional(CONF_MAX_OUTPUT_TOKENS, default=DEFAULT_MAX_OUTPUT_TOKENS)] = vol.All(vol.Coerce(int), vol.Range(min=100))
        return base

    async def async_step_openai(self, user_input=None):
        schema = {
            vol.Required(CONF_OPENAI_API_KEY): TextSelector(TextSelectorConfig(type="password")),
            vol.Optional(CONF_OPENAI_MODEL, default=DEFAULT_MODELS["OpenAI"]): str,
            vol.Optional(CONF_OPENAI_TEMPERATURE, default=DEFAULT_TEMPERATURE): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
        }
        return await self._provider_form("openai", vol.Schema(self._add_token_fields(schema)), lambda ui: self.validator.validate_openai(ui[CONF_OPENAI_API_KEY]), f"{INTEGRATION_NAME} (OpenAI)", user_input)

    async def async_step_google(self, user_input=None):
        schema = {
            vol.Required(CONF_GOOGLE_API_KEY): TextSelector(TextSelectorConfig(type="password")),
            vol.Optional(CONF_GOOGLE_MODEL, default=DEFAULT_MODELS["Google"]): str,
            vol.Optional(CONF_GOOGLE_TEMPERATURE, default=DEFAULT_TEMPERATURE): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
        }
        return await self._provider_form("google", vol.Schema(self._add_token_fields(schema)), lambda ui: self.validator.validate_google(ui[CONF_GOOGLE_API_KEY], ui[CONF_GOOGLE_MODEL]), f"{INTEGRATION_NAME} (Google)", user_input)

    async def async_step_anthropic(self, user_input=None):
        schema = {
            vol.Required(CONF_ANTHROPIC_API_KEY): TextSelector(TextSelectorConfig(type="password")),
            vol.Optional(CONF_ANTHROPIC_MODEL, default=DEFAULT_MODELS["Anthropic"]): str,
            vol.Optional(CONF_ANTHROPIC_TEMPERATURE, default=DEFAULT_TEMPERATURE): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
        }
        return await self._provider_form("anthropic", vol.Schema(self._add_token_fields(schema)), lambda ui: self.validator.validate_anthropic(ui[CONF_ANTHROPIC_API_KEY], ui[CONF_ANTHROPIC_MODEL]), f"{INTEGRATION_NAME} (Anthropic)", user_input)

    async def async_step_groq(self, user_input=None):
        schema = {
            vol.Required(CONF_GROQ_API_KEY): TextSelector(TextSelectorConfig(type="password")),
            vol.Optional(CONF_GROQ_MODEL, default=DEFAULT_MODELS["Groq"]): str,
            vol.Optional(CONF_GROQ_TEMPERATURE, default=DEFAULT_TEMPERATURE): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
        }
        return await self._provider_form("groq", vol.Schema(self._add_token_fields(schema)), lambda ui: self.validator.validate_groq(ui[CONF_GROQ_API_KEY]), f"{INTEGRATION_NAME} (Groq)", user_input)

    async def async_step_ollama(self, user_input=None):
        schema = {
            vol.Required(CONF_OLLAMA_IP_ADDRESS): str,
            vol.Required(CONF_OLLAMA_PORT, default=11434): int,
            vol.Required(CONF_OLLAMA_HTTPS, default=False): bool,
            vol.Optional(CONF_OLLAMA_MODEL, default=DEFAULT_MODELS["Ollama"]): str,
            vol.Optional(CONF_OLLAMA_TEMPERATURE, default=DEFAULT_TEMPERATURE): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(CONF_OLLAMA_DISABLE_THINK, default=False): bool,
        }
        return await self._provider_form("ollama", vol.Schema(self._add_token_fields(schema)), lambda ui: self.validator.validate_ollama(ui[CONF_OLLAMA_IP_ADDRESS], ui[CONF_OLLAMA_PORT], ui[CONF_OLLAMA_HTTPS]), f"{INTEGRATION_NAME} (Ollama)", user_input)

    async def async_step_localai(self, user_input=None):
        schema = {
            vol.Required(CONF_LOCALAI_IP_ADDRESS): str,
            vol.Required(CONF_LOCALAI_PORT, default=8080): int,
            vol.Required(CONF_LOCALAI_HTTPS, default=False): bool,
            vol.Optional(CONF_LOCALAI_MODEL, default=DEFAULT_MODELS["LocalAI"]): str,
            vol.Optional(CONF_LOCALAI_TEMPERATURE, default=DEFAULT_TEMPERATURE): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
        }
        return await self._provider_form("localai", vol.Schema(self._add_token_fields(schema)), lambda ui: self.validator.validate_localai(ui[CONF_LOCALAI_IP_ADDRESS], ui[CONF_LOCALAI_PORT], ui[CONF_LOCALAI_HTTPS]), f"{INTEGRATION_NAME} (LocalAI)", user_input)

    async def async_step_mistral(self, user_input=None):
        schema = {
            vol.Required(CONF_MISTRAL_API_KEY): TextSelector(TextSelectorConfig(type="password")),
            vol.Optional(CONF_MISTRAL_MODEL, default=DEFAULT_MODELS["Mistral AI"]): str,
            vol.Optional(CONF_MISTRAL_TEMPERATURE, default=DEFAULT_TEMPERATURE): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
        }
        return await self._provider_form("mistral", vol.Schema(self._add_token_fields(schema)), lambda ui: None, f"{INTEGRATION_NAME} (Mistral AI)", user_input)

    async def async_step_perplexity(self, user_input=None):
        schema = {
            vol.Required(CONF_PERPLEXITY_API_KEY): TextSelector(TextSelectorConfig(type="password")),
            vol.Optional(CONF_PERPLEXITY_MODEL, default=DEFAULT_MODELS["Perplexity AI"]): str,
            vol.Optional(CONF_PERPLEXITY_TEMPERATURE, default=DEFAULT_TEMPERATURE): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
        }
        return await self._provider_form("perplexity", vol.Schema(self._add_token_fields(schema)), lambda ui: None, f"{INTEGRATION_NAME} (Perplexity AI)", user_input)

    async def async_step_openrouter(self, user_input=None):
        schema = {
            vol.Required(CONF_OPENROUTER_API_KEY): TextSelector(TextSelectorConfig(type="password")),
            vol.Optional(CONF_OPENROUTER_MODEL, default=DEFAULT_MODELS["OpenRouter"]): str,
            vol.Optional(CONF_OPENROUTER_TEMPERATURE, default=DEFAULT_TEMPERATURE): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(CONF_OPENROUTER_REASONING_MAX_TOKENS, default=0): int,
        }
        return await self._provider_form("openrouter", vol.Schema(self._add_token_fields(schema)), lambda ui: None, f"{INTEGRATION_NAME} (OpenRouter)", user_input)

    async def async_step_openai_azure(self, user_input=None):
        schema = {
            vol.Required(CONF_OPENAI_AZURE_API_KEY): TextSelector(TextSelectorConfig(type="password")),
            vol.Required(CONF_OPENAI_AZURE_ENDPOINT): str,
            vol.Required(CONF_OPENAI_AZURE_DEPLOYMENT_ID): str,
            vol.Optional(CONF_OPENAI_AZURE_API_VERSION, default="2025-01-01-preview"): str,
            vol.Optional(CONF_OPENAI_AZURE_TEMPERATURE, default=DEFAULT_TEMPERATURE): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
        }
        return await self._provider_form("openai_azure", vol.Schema(self._add_token_fields(schema)), lambda ui: None, f"{INTEGRATION_NAME} (Azure)", user_input)

    async def async_step_custom_openai(self, user_input=None):
        schema = {
            vol.Required(CONF_CUSTOM_OPENAI_ENDPOINT): str,
            vol.Optional(CONF_CUSTOM_OPENAI_API_KEY): TextSelector(TextSelectorConfig(type="password")),
            vol.Optional(CONF_CUSTOM_OPENAI_MODEL, default=DEFAULT_MODELS["Custom OpenAI"]): str,
            vol.Optional(CONF_CUSTOM_OPENAI_TEMPERATURE, default=DEFAULT_TEMPERATURE): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
        }
        return await self._provider_form("custom_openai", vol.Schema(self._add_token_fields(schema)), lambda ui: None, f"{INTEGRATION_NAME} (Custom OpenAI)", user_input)

    async def async_step_generic_openai(self, user_input=None):
        schema = {
            vol.Required(CONF_GENERIC_OPENAI_ENDPOINT): str,
            vol.Required(CONF_GENERIC_OPENAI_API_KEY): TextSelector(TextSelectorConfig(type="password")),
            vol.Required(CONF_GENERIC_OPENAI_MODEL, default=DEFAULT_MODELS["Generic OpenAI"]): str,
            vol.Optional(CONF_GENERIC_OPENAI_TEMPERATURE, default=DEFAULT_TEMPERATURE): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
        }
        return await self._provider_form("generic_openai", vol.Schema(self._add_token_fields(schema)), lambda ui: None, f"{INTEGRATION_NAME} (Generic OpenAI)", user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AIAutomationOptionsFlowHandler(config_entry)

class AIAutomationOptionsFlowHandler(config_entries.OptionsFlow):
    """Håndterer løbende ændringer af indstillinger."""

    def __init__(self, config_entry):
        super().__init__()
        self._config_entry = config_entry

    def _get_option(self, key, default=None):
        return self._config_entry.options.get(key, self._config_entry.data.get(key, default))

    async def async_step_init(self, user_input=None):
        if user_input:
            return self.async_create_entry(title="", data=user_input)

        provider = self._config_entry.data.get(CONF_PROVIDER)
        schema = {
            vol.Optional(CONF_MAX_INPUT_TOKENS, default=self._get_option(CONF_MAX_INPUT_TOKENS, DEFAULT_MAX_INPUT_TOKENS)): int,
            vol.Optional(CONF_MAX_OUTPUT_TOKENS, default=self._get_option(CONF_MAX_OUTPUT_TOKENS, DEFAULT_MAX_OUTPUT_TOKENS)): int,
        }

        # Tilføj redigerbare felter baseret på udbyder
        p_map = {
            "OpenAI": (CONF_OPENAI_MODEL, CONF_OPENAI_TEMPERATURE),
            "Google": (CONF_GOOGLE_MODEL, CONF_GOOGLE_TEMPERATURE),
            "Anthropic": (CONF_ANTHROPIC_MODEL, CONF_ANTHROPIC_TEMPERATURE),
            "Groq": (CONF_GROQ_MODEL, CONF_GROQ_TEMPERATURE),
            "Ollama": (CONF_OLLAMA_MODEL, CONF_OLLAMA_TEMPERATURE),
            "LocalAI": (CONF_LOCALAI_MODEL, CONF_LOCALAI_TEMPERATURE),
        }

        if provider in p_map:
            m_key, t_key = p_map[provider]
            schema[vol.Optional(m_key, default=self._get_option(m_key, ""))] = str
            schema[vol.Optional(t_key, default=self._get_option(t_key, 0.7))] = vol.Coerce(float)

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
