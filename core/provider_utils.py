"""Small compatibility layer for AstrBot's built-in LLM providers.

The plugin used to reconstruct provider HTTP endpoints itself.  That bypassed
AstrBot's provider adapters (and their proxy, authentication, model and media
handling), so a perfectly valid provider could still fail with ``Not Found``.
All new model calls go through the helpers in this module.  The helpers are
deliberately duck-typed so the plugin keeps working with older AstrBot builds
that do not expose :meth:`Context.llm_generate` yet.
"""

from __future__ import annotations

import inspect
import json
import re
from typing import Any


class ProviderRoutingError(RuntimeError):
    """Raised when AstrBot cannot supply a usable chat provider."""


_SIGNATURE_ERROR_PATTERNS = (
    re.compile(r"unexpected keyword argument", re.IGNORECASE),
    re.compile(r"got an unexpected keyword", re.IGNORECASE),
    re.compile(r"missing .* required .* argument", re.IGNORECASE),
    re.compile(r"takes .* argument", re.IGNORECASE),
)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _is_signature_mismatch(error: TypeError) -> bool:
    """Return whether a ``TypeError`` came from an incompatible call shape.

    A provider can itself raise ``TypeError`` after a network request has
    started.  Retrying that error through ``provider.text_chat`` would send the
    same request twice, so only the standard Python signature diagnostics are
    eligible for the legacy fallback.
    """

    traceback = error.__traceback__
    if traceback is not None and traceback.tb_next is not None:
        # The exception came from inside the coroutine/provider, not from
        # Python binding this helper's keyword arguments to its signature.
        return False

    message = str(error or "")
    return any(pattern.search(message) for pattern in _SIGNATURE_ERROR_PATTERNS)


def _response_text_unchecked(response: Any) -> str:
    """Extract response text without interpreting its AstrBot role."""

    if response is None:
        return ""
    if isinstance(response, str):
        return response

    try:
        value = getattr(response, "completion_text", "")
        if isinstance(value, str) and value.strip():
            return value
    except Exception:
        pass

    chain = getattr(response, "result_chain", None)
    if chain is not None:
        try:
            value = chain.get_plain_text()
            if isinstance(value, str) and value.strip():
                return value
        except Exception:
            pass
        try:
            parts: list[str] = []
            for component in chain:
                value = getattr(component, "text", None)
                if isinstance(value, str) and value:
                    parts.append(value)
            if parts:
                return "".join(parts)
        except Exception:
            pass

    if isinstance(response, dict):
        choices = response.get("choices")
        if isinstance(choices, list):
            parts: list[str] = []
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        parts.append(content)
                    elif isinstance(content, list):
                        parts.extend(
                            str(item.get("text"))
                            for item in content
                            if isinstance(item, dict) and item.get("text")
                        )
                if isinstance(choice.get("text"), str):
                    parts.append(choice["text"])
            if parts:
                return "\n".join(parts)

        for key in ("content", "text", "message", "result", "output", "caption"):
            value = response.get(key)
            if isinstance(value, str):
                return value

        # Some compatibility adapters return the tagger's structured JSON
        # directly instead of wrapping it in an LLMResponse.
        if any(key in response for key in ("tags", "character", "series", "prompt")):
            return json.dumps(response, ensure_ascii=False)

    if isinstance(response, (list, tuple)):
        return json.dumps(response, ensure_ascii=False)

    for attr in ("text", "content", "output"):
        value = getattr(response, attr, None)
        if isinstance(value, str) and value.strip():
            return value

    # Never turn an arbitrary provider object (for example an empty
    # LLMResponse or SDK error wrapper) into pseudo-tags via ``str(obj)``.
    return ""


def _ensure_successful_response(response: Any) -> None:
    """Turn AstrBot's ``role=err`` response into a normal Python error."""

    role = ""
    if isinstance(response, dict):
        role = str(response.get("role", "") or "").strip().lower()
        raw_error = response.get("error")
        if raw_error:
            if isinstance(raw_error, dict):
                detail = next(
                    (
                        str(raw_error.get(key) or "").strip()
                        for key in ("message", "detail", "reason", "error")
                        if str(raw_error.get(key) or "").strip()
                    ),
                    "",
                )
            else:
                detail = str(raw_error).strip()
            raise ProviderRoutingError(detail or "模型供应商返回错误")
    else:
        role = str(getattr(response, "role", "") or "").strip().lower()

    if role in {"err", "error"}:
        detail = _response_text_unchecked(response).strip()
        raise ProviderRoutingError(detail or "模型供应商返回错误")


def provider_id_of(provider: Any) -> str:
    """Return a provider's stable configured ID without assuming its model API."""

    if provider is None:
        return ""

    try:
        meta = provider.meta()
        value = getattr(meta, "id", "")
        if value:
            return str(value).strip()
    except Exception:
        pass

    config = getattr(provider, "provider_config", None)
    if isinstance(config, dict):
        value = config.get("id")
        if value:
            return str(value).strip()

    return ""


def provider_model_of(provider: Any) -> str:
    """Read a provider model through AstrBot's stable API.

    ``Provider.model`` is not a stable attribute: current AstrBot providers
    expose ``get_model()``/``model_name`` instead.  The config fallbacks are
    only for older adapters and test doubles.
    """

    if provider is None:
        return ""

    getter = getattr(provider, "get_model", None)
    if callable(getter):
        try:
            value = getter()
            if value:
                return str(value).strip()
        except Exception:
            pass

    for attr in ("model_name",):
        value = getattr(provider, attr, "")
        if value:
            return str(value).strip()

    config = getattr(provider, "provider_config", None)
    if isinstance(config, dict):
        for key in ("model", "model_name", "default_model"):
            value = config.get(key)
            if value:
                return str(value).strip()

    return ""


async def resolve_provider(context: Any, configured_id: str = "") -> tuple[str, Any]:
    """Resolve a configured provider, falling back to AstrBot's active one."""

    if context is None:
        raise ProviderRoutingError("缺少 AstrBot context")

    requested = str(configured_id or "").strip()
    getter = getattr(context, "get_provider_by_id", None)

    if requested and callable(getter):
        provider = await _maybe_await(getter(requested))
        if provider is not None:
            return requested, provider

    using_getter = getattr(context, "get_using_provider", None)
    if callable(using_getter):
        provider = await _maybe_await(using_getter())
        if provider is not None:
            resolved_id = provider_id_of(provider)
            if resolved_id:
                if requested and requested != resolved_id:
                    # The selected provider disappeared; make the fallback
                    # explicit in logs/callers instead of failing silently.
                    return resolved_id, provider
                return resolved_id, provider

    if requested:
        raise ProviderRoutingError(f"找不到 LLM 提供商：{requested}")
    raise ProviderRoutingError("没有可用的 AstrBot LLM 提供商")


async def call_provider(
    context: Any,
    configured_id: str,
    *,
    prompt: str | None = None,
    system_prompt: str | None = None,
    image_urls: list[str] | None = None,
    **kwargs: Any,
) -> tuple[str, Any, Any]:
    """Call AstrBot's provider routing API and return ``(id, provider, response)``.

    ``Context.llm_generate`` is preferred because it is the public routing
    surface.  Direct ``provider.text_chat`` is the compatibility fallback for
    AstrBot versions predating that method or for lightweight test contexts.
    """

    provider_id, provider = await resolve_provider(context, configured_id)
    llm_generate = getattr(context, "llm_generate", None)
    call_kwargs = dict(kwargs)
    call_kwargs.update(
        {
            "chat_provider_id": provider_id,
            "prompt": prompt,
            "system_prompt": system_prompt,
        }
    )
    if image_urls:
        call_kwargs["image_urls"] = image_urls

    if callable(llm_generate):
        try:
            response = await _maybe_await(llm_generate(**call_kwargs))
            _ensure_successful_response(response)
            return provider_id, provider, response
        except NotImplementedError:
            # A few transitional AstrBot builds exposed the public method
            # before implementing it.  Their provider object remains usable.
            pass
        except TypeError as exc:
            if not _is_signature_mismatch(exc):
                raise
            # Older contexts may expose a narrower ``llm_generate`` signature.
            pass

    text_chat = getattr(provider, "text_chat", None)
    if not callable(text_chat):
        raise ProviderRoutingError(f"提供商 {provider_id} 不支持文本/视觉对话")

    direct_kwargs = {
        "prompt": prompt,
        "system_prompt": system_prompt,
        **kwargs,
    }
    if image_urls:
        direct_kwargs["image_urls"] = image_urls

    try:
        response = await _maybe_await(text_chat(**direct_kwargs))
    except TypeError as exc:
        if not _is_signature_mismatch(exc):
            raise
        # A few old adapters reject newer optional kwargs.  Keep the fallback
        # narrow and never rebuild an HTTP endpoint here.
        reduced = {"prompt": prompt}
        if image_urls:
            reduced["image_urls"] = image_urls
        if system_prompt:
            reduced["system_prompt"] = system_prompt
        response = await _maybe_await(text_chat(**reduced))

    _ensure_successful_response(response)
    return provider_id, provider, response


def response_text(response: Any) -> str:
    """Extract plain text from an AstrBot ``LLMResponse`` or compatible value."""

    _ensure_successful_response(response)
    return _response_text_unchecked(response)
