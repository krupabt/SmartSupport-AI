import os
import json
import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class BaseLLMProvider(ABC):
    """Abstract Base Class for LLM Provider Integrations."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @abstractmethod
    def is_available(self) -> bool:
        pass

    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        pass


class GeminiProvider(BaseLLMProvider):
    """Google Gemini LLM Integration Provider."""

    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-1.5-flash"):
        if api_key is not None:
            self._api_key = api_key if api_key != "" else None
        else:
            self._api_key = os.getenv("GEMINI_API_KEY")

        self._model_name = os.getenv("GEMINI_MODEL", model_name)
        self._client_initialized = False

        if self._api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self._api_key)
                self._client_initialized = True
                logger.info(f"GeminiProvider initialized with model '{self._model_name}'")
            except Exception as e:
                logger.warning(f"Failed to configure Gemini SDK: {str(e)}")

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model_name

    def is_available(self) -> bool:
        return bool(self._api_key and self._client_initialized)

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        if not self.is_available():
            raise RuntimeError("GeminiProvider is not configured or missing GEMINI_API_KEY.")

        import google.generativeai as genai

        generation_config = {
            "temperature": 0.1,
            "max_output_tokens": 800,
        }

        # Set system instruction if supported
        try:
            model = genai.GenerativeModel(
                model_name=self._model_name,
                system_instruction=system_prompt if system_prompt else None,
                generation_config=generation_config,
            )
            response = model.generate_content(prompt)
            if response and response.text:
                return response.text.strip()
            raise RuntimeError("Empty response received from Gemini.")
        except Exception as e:
            logger.error(f"Gemini API generation error: {str(e)}", exc_info=True)
            raise e


class OpenAIProvider(BaseLLMProvider):
    """OpenAI API Provider Integration."""

    def __init__(self, api_key: Optional[str] = None, model_name: str = "gpt-4o-mini"):
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._model_name = os.getenv("OPENAI_MODEL", model_name)

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model_name

    def is_available(self) -> bool:
        return bool(self._api_key)

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        if not self.is_available():
            raise RuntimeError("OpenAIProvider is not configured or missing OPENAI_API_KEY.")

        from openai import OpenAI
        client = OpenAI(api_key=self._api_key)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=self._model_name,
            messages=messages,
            temperature=0.1,
            max_tokens=800,
        )
        return response.choices[0].message.content.strip()


class FakeLLMProvider(BaseLLMProvider):
    """Deterministic Mock LLM Provider for unit testing and offline verification."""

    def __init__(self, custom_response: Optional[str] = None):
        self._custom_response = custom_response

    @property
    def provider_name(self) -> str:
        return "fake_test_provider"

    @property
    def model_name(self) -> str:
        return "fake-llm-v1"

    def is_available(self) -> bool:
        return True

    def set_response(self, response_str: str):
        self._custom_response = response_str

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        if self._custom_response:
            return self._custom_response

        # Check if this is a RAG grounded resolution prompt
        sys_str = (system_prompt or "").lower()
        p_lower = prompt.lower()
        is_rag_prompt = (
            "knowledge base" in sys_str
            or "grounding" in sys_str
            or "source_chunk_ids" in sys_str
            or "knowledge base context" in p_lower
        )

        if is_rag_prompt:
            if "no knowledge base context available" in p_lower:
                return json.dumps({
                    "answer": "I have escalated your inquiry to our specialized support team, as our current knowledge base does not have specific policy details matching your request.",
                    "confidence": 0.35,
                    "needs_escalation": True,
                    "reason": "No relevant policy or FAQ documentation found in the knowledge base.",
                    "source_chunk_ids": [],
                })
            else:
                return json.dumps({
                    "answer": "According to our official policy, customers are eligible for a 100% full refund within 14 calendar days of purchase. Requests between 15 and 30 days receive store credit. Refunds reflect on card statements within 3 to 5 business days.",
                    "confidence": 0.96,
                    "needs_escalation": False,
                    "reason": "Found explicit match in the verified knowledge base documentation.",
                    "source_chunk_ids": [1],
                })

        # Heuristic simulation for complaint analysis
        if "hacked" in p_lower or "security" in p_lower or "unauthorized" in p_lower:
            return json.dumps({
                "category": "Security",
                "sentiment": "Very Negative",
                "priority": "Critical",
                "confidence": 0.98,
                "reason": "Customer reports unauthorized account transactions and security compromise."
            })
        elif "outage" in p_lower or "panic" in p_lower or "corrupted" in p_lower or "critical" in p_lower:
            return json.dumps({
                "category": "Technical Issue",
                "sentiment": "Very Negative",
                "priority": "Critical",
                "confidence": 0.99,
                "reason": "Severe critical outage or fatal crash reported by customer."
            })
        elif "refund" in p_lower or "return" in p_lower:
            return json.dumps({
                "category": "Refund",
                "sentiment": "Negative",
                "priority": "High",
                "confidence": 0.94,
                "reason": "Customer reports a delayed refund for an order."
            })
        elif "charge" in p_lower or "invoice" in p_lower or "bill" in p_lower:
            return json.dumps({
                "category": "Billing",
                "sentiment": "Negative",
                "priority": "High",
                "confidence": 0.92,
                "reason": "Customer is reporting incorrect billing charges."
            })
        elif "deliver" in p_lower or "shipping" in p_lower or "package" in p_lower:
            return json.dumps({
                "category": "Delivery",
                "sentiment": "Negative",
                "priority": "Medium",
                "confidence": 0.89,
                "reason": "Customer is inquiring about parcel shipping delay."
            })
        elif "crash" in p_lower or "bug" in p_lower or "error" in p_lower:
            return json.dumps({
                "category": "Technical Issue",
                "sentiment": "Negative",
                "priority": "High",
                "confidence": 0.91,
                "reason": "Application crash reported by user."
            })
        else:
            return json.dumps({
                "category": "General",
                "sentiment": "Neutral",
                "priority": "Low",
                "confidence": 0.85,
                "reason": "General customer inquiry."
            })


class LLMService:
    """Unified service interface for LLM provider operations."""

    def __init__(self, provider: Optional[BaseLLMProvider] = None):
        if provider:
            self._provider = provider
        else:
            self._provider = self._init_default_provider()

    def _init_default_provider(self) -> BaseLLMProvider:
        provider_type = None
        try:
            from flask import current_app, has_app_context
            if has_app_context() and current_app:
                provider_type = current_app.config.get("LLM_PROVIDER")
        except Exception:
            pass

        if not provider_type:
            provider_type = os.getenv("LLM_PROVIDER", "gemini")

        provider_type = str(provider_type).lower()
        if provider_type == "openai":
            return OpenAIProvider()
        elif provider_type in ("fake", "test", "testing"):
            return FakeLLMProvider()
        else:
            return GeminiProvider()

    def set_provider(self, provider: BaseLLMProvider):
        """Allows swapping provider (e.g., during tests)."""
        self._provider = provider

    @property
    def provider(self) -> BaseLLMProvider:
        return self._provider

    def is_available(self) -> bool:
        return self._provider.is_available()

    def generate(self, prompt: str, system_prompt: Optional[str] = None, max_retries: int = 2) -> str:
        """Execute LLM generation with retry support."""
        if not self.is_available():
            raise RuntimeError(
                f"AI service provider '{self._provider.provider_name}' is not configured with an API key."
            )

        attempts = 0
        last_err = None

        while attempts < max_retries:
            attempts += 1
            try:
                return self._provider.generate(prompt, system_prompt=system_prompt)
            except Exception as e:
                last_err = e
                logger.warning(f"LLM generation attempt {attempts} failed: {str(e)}")

        raise last_err or RuntimeError("LLM generation failed after maximum retries.")
