"""Command Code model catalog snapshot.

Generated from command-code@1.47.0 by `python sync_catalog.py --write`.
Do not edit manually.
"""

from __future__ import annotations

# The CLI version this snapshot was generated from. Bump on re-sync.
COMMAND_CODE_CLI_VERSION = "1.47.0"

MODEL_EFFORTS: dict[str, tuple[str, ...]] = {
    "Qwen/Qwen3.8-27B": ("low", "medium", "xhigh"),
    "Qwen/Qwen3.8-Flash": ("low", "medium", "xhigh"),
    "Qwen/Qwen3.8-Max": ("low", "medium", "xhigh"),
    "Qwen/Qwen3.8-Max-0902": ("low", "medium", "xhigh"),
    "claude-fable-5": ("low", "medium", "high", "xhigh", "max"),
    "claude-fable-5-1": ("low", "medium", "high", "xhigh", "max"),
    "claude-opus-4-7": ("low", "medium", "high", "xhigh", "max"),
    "claude-opus-4-8": ("low", "medium", "high", "xhigh", "max"),
    "claude-opus-5": ("low", "medium", "high", "xhigh", "max"),
    "claude-sonnet-4-6": ("low", "medium", "high", "xhigh", "max"),
    "claude-sonnet-5": ("low", "medium", "high", "xhigh", "max"),
    "deepseek/deepseek-v4-flash": ("high", "max"),
    "deepseek/deepseek-v4-flash-fast": ("low", "high", "max"),
    "deepseek/deepseek-v4-flash-vision-exp": ("high", "max"),
    "deepseek/deepseek-v4-pro": ("high", "max"),
    "google/gemini-3.1-flash-lite": ("low", "medium", "high"),
    "google/gemini-3.5-flash": ("low", "medium", "high"),
    "google/gemini-3.5-flash-lite": ("low", "medium", "high"),
    "google/gemini-3.6-flash": ("low", "medium", "high"),
    "google/gemini-3.7-flash": ("low", "medium", "high"),
    "google/gemini-3.8-flash": ("low", "medium", "high"),
    "gpt-5.3-codex": ("low", "medium", "high", "xhigh"),
    "gpt-5.4": ("low", "medium", "high", "xhigh"),
    "gpt-5.4-mini": ("low", "medium", "high"),
    "gpt-5.5": ("low", "medium", "high", "xhigh"),
    "gpt-5.6-luna": ("low", "medium", "high", "xhigh", "max"),
    "gpt-5.6-sol": ("low", "medium", "high", "xhigh", "max"),
    "gpt-5.6-terra": ("low", "medium", "high", "xhigh", "max"),
    "meta/muse-spark-1.1": ("low", "medium", "high", "xhigh"),
    "meta/muse-spark-1.2": ("low", "medium", "high", "xhigh"),
    "meta/muse-spark-1.2-contributor": ("low", "medium", "high", "xhigh"),
    "meta/muse-spark-1.3": ("low", "medium", "high", "xhigh"),
    "meta/muse-spark-1.3-contributor": ("low", "medium", "high", "xhigh"),
    "moonshotai/Kimi-K3": ("low", "high", "max"),
    "sakana/fugu-ultra": ("high", "xhigh"),
    "tencent/hy4-preview": ("low", "medium", "high"),
    "xai/grok-4.5": ("low", "medium", "high"),
    "xai/grok-4.6": ("low", "medium", "high", "xhigh"),
    "z-ai/glm-5.3-flash": ("low", "high", "max"),
    "zai-org/GLM-5.2": ("high", "max"),
    "zai-org/GLM-5.3": ("low", "high", "max"),
}

MODEL_INPUT_MODALITIES: dict[str, tuple[str, ...]] = {
    "MiniMaxAI/MiniMax-M3": ("text", "image"),
    "Qwen/Qwen3.6-Plus": ("text", "image"),
    "Qwen/Qwen3.7-Flash": ("text", "image"),
    "Qwen/Qwen3.7-Plus": ("text", "image"),
    "Qwen/Qwen3.8-27B": ("text", "image"),
    "Qwen/Qwen3.8-Flash": ("text", "image"),
    "Qwen/Qwen3.8-Max": ("text", "image"),
    "Qwen/Qwen3.8-Max-0902": ("text", "image"),
    "claude-fable-5": ("text", "image"),
    "claude-fable-5-1": ("text", "image"),
    "claude-haiku-4-5-20251001": ("text", "image"),
    "claude-opus-4-7": ("text", "image"),
    "claude-opus-4-8": ("text", "image"),
    "claude-opus-5": ("text", "image"),
    "claude-sonnet-4-6": ("text", "image"),
    "claude-sonnet-5": ("text", "image"),
    "deepseek/deepseek-v4-flash-vision-exp": ("text", "image"),
    "google/gemini-3.1-flash-lite": ("text", "image"),
    "google/gemini-3.5-flash": ("text", "image"),
    "google/gemini-3.5-flash-lite": ("text", "image"),
    "google/gemini-3.6-flash": ("text", "image"),
    "google/gemini-3.7-flash": ("text", "image"),
    "google/gemini-3.8-flash": ("text", "image"),
    "gpt-5.3-codex": ("text", "image"),
    "gpt-5.4": ("text", "image"),
    "gpt-5.4-mini": ("text", "image"),
    "gpt-5.5": ("text", "image"),
    "gpt-5.6-luna": ("text", "image"),
    "gpt-5.6-sol": ("text", "image"),
    "gpt-5.6-terra": ("text", "image"),
    "meta/muse-spark-1.1": ("text", "image"),
    "meta/muse-spark-1.2": ("text", "image"),
    "meta/muse-spark-1.2-contributor": ("text", "image"),
    "meta/muse-spark-1.3": ("text", "image"),
    "meta/muse-spark-1.3-contributor": ("text", "image"),
    "moonshotai/Kimi-K2.5": ("text", "image"),
    "moonshotai/Kimi-K2.6": ("text", "image"),
    "moonshotai/Kimi-K2.7-Code": ("text", "image"),
    "moonshotai/Kimi-K2.7-Code-Highspeed": ("text", "image"),
    "moonshotai/Kimi-K3": ("text", "image"),
    "sakana/fugu-ultra": ("text", "image"),
    "stepfun/Step-3.7-Flash": ("text", "image"),
    "thinkingmachines/inkling": ("text", "image"),
    "thinkingmachines/inkling-small": ("text", "image"),
    "xai/grok-4.5": ("text", "image"),
    "xai/grok-4.6": ("text", "image"),
    "xiaomi/mimo-v2.5": ("text", "image"),
    "z-ai/glm-5.3-flash": ("text", "image"),
}

MODEL_REASONING: frozenset[str] = frozenset(
    {
    "MiniMaxAI/MiniMax-M3": True,
    "Qwen/Qwen3.6-Max-Preview": True,
    "Qwen/Qwen3.6-Plus": True,
    "Qwen/Qwen3.7-Flash": True,
    "Qwen/Qwen3.7-Max": True,
    "Qwen/Qwen3.7-Plus": True,
    "Qwen/Qwen3.8-27B": True,
    "Qwen/Qwen3.8-Flash": True,
    "Qwen/Qwen3.8-Max": True,
    "Qwen/Qwen3.8-Max-0902": True,
    "claude-fable-5": True,
    "claude-fable-5-1": True,
    "claude-opus-4-7": True,
    "claude-opus-4-8": True,
    "claude-opus-5": True,
    "claude-sonnet-4-6": True,
    "claude-sonnet-5": True,
    "deepseek/deepseek-v4-flash": True,
    "deepseek/deepseek-v4-flash-fast": True,
    "deepseek/deepseek-v4-flash-vision-exp": True,
    "deepseek/deepseek-v4-pro": True,
    "google/gemini-3.1-flash-lite": True,
    "google/gemini-3.5-flash": True,
    "google/gemini-3.5-flash-lite": True,
    "google/gemini-3.6-flash": True,
    "google/gemini-3.7-flash": True,
    "google/gemini-3.8-flash": True,
    "gpt-5.3-codex": True,
    "gpt-5.4": True,
    "gpt-5.4-mini": True,
    "gpt-5.5": True,
    "gpt-5.6-luna": True,
    "gpt-5.6-sol": True,
    "gpt-5.6-terra": True,
    "meituan/LongCat-2.0:free": True,
    "meta/muse-spark-1.1": True,
    "meta/muse-spark-1.2": True,
    "meta/muse-spark-1.2-contributor": True,
    "meta/muse-spark-1.3": True,
    "meta/muse-spark-1.3-contributor": True,
    "moonshotai/Kimi-K2.7-Code": True,
    "moonshotai/Kimi-K2.7-Code-Highspeed": True,
    "moonshotai/Kimi-K3": True,
    "nvidia/nemotron-3-ultra-550b-a55b": True,
    "poolside/laguna-s-2.1-free": True,
    "sakana/fugu-ultra": True,
    "stepfun/Step-3.5-Flash": True,
    "stepfun/Step-3.7-Flash": True,
    "tencent/hy3-paid": True,
    "tencent/hy4-preview": True,
    "thinkingmachines/inkling": True,
    "thinkingmachines/inkling-small": True,
    "xai/grok-4.5": True,
    "xai/grok-4.6": True,
    "z-ai/glm-5.3-flash": True,
    "zai-org/GLM-5.2": True,
    "zai-org/GLM-5.3": True,
    }
)

MODEL_MAX_OUTPUT_TOKENS: dict[str, int] = {
    "Qwen/Qwen3.8-27B": 32_768,
    "poolside/laguna-s-2.1-free": 32_768,
    "z-ai/glm-5.3-flash": 131_072,
}

DEFAULT_MAX_OUTPUT_TOKENS = 65_536


def input_modalities_for_model(model_id: str) -> tuple[str, ...]:
    return MODEL_INPUT_MODALITIES.get(model_id, ("text",))


def supports_image_input(model_id: str) -> bool:
    return "image" in input_modalities_for_model(model_id)


def is_reasoning_model(model_id: str) -> bool:
    return model_id in MODEL_REASONING


def efforts_for_model(model_id: str) -> tuple[str, ...]:
    return MODEL_EFFORTS.get(model_id, ())


def max_output_tokens_for_model(model_id: str) -> int:
    return MODEL_MAX_OUTPUT_TOKENS.get(model_id, DEFAULT_MAX_OUTPUT_TOKENS)
