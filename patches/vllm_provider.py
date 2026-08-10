"""Local vLLM provider (OpenAI-compatible chat completions).

Every other provider hardcodes a cloud `base_url` and requires a cloud API key,
and the `openai` provider targets the Responses API, which vLLM does not serve.
This is a thin sibling of `FireworksProvider` pointed at a self-hosted endpoint.

Config keys (under `agent:`):
    base_url        endpoint, else $VLLM_BASE_URL, else http://localhost:8000/v1
    api_key         else $VLLM_API_KEY, else "EMPTY" (vLLM ignores the value)
    temperature     omitted from the request body when None
    top_p           omitted when None
    max_tokens      per-turn generation cap (default 4096)
    seed            per-request seed, for reproducibility where the stack allows
    timeout         per-request timeout in seconds (default 900)
"""

import os
import re

from dotenv import load_dotenv
from openai import OpenAI
from openai import (
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
)
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from agent_interp_envs.print_helpers import print_section, print_step_header
from agent_interp_envs.providers.base import BaseProvider
from agent_interp_envs.types import LLMResponse, ToolResult, ToolCall

load_dotenv()

# Fields the OpenAI chat-completions schema accepts on an input message.
# Anything else is transcript-only bookkeeping and must not be sent back:
# `run_step._recover_json_tool_call` writes a stray top-level `reasoning` key
# onto the last assistant message, and strict pydantic validators (vLLM's
# included) reject unknown message fields.
_WIRE_FIELDS = (
    "role",
    "content",
    "tool_calls",
    "tool_call_id",
    "name",
    "reasoning_content",
)

# Raw harmony control tokens must never survive into an assistant message. When
# they do, the server's parser has failed and the "message" is not a decision
# the model made.
_HARMONY_LEAK = re.compile(
    r"<\|(?:start|channel|call|end|message|constrain|return)\|>|to=functions\."
)


class MalformedGeneration(Exception):
    """A turn that the harness would misread as the agent choosing to stop.

    run_step treats "no tool calls" as task completion. That inference is only
    valid when the model actually chose to answer in prose. It is wrong when:

      * the response was cut off at max_tokens (finish_reason == "length") —
        gpt-oss reasons for thousands of tokens, so a low cap silently converts
        a working agent into a "finished" one mid-thought;
      * harmony control tokens leaked into the text, meaning the server failed
        to parse its own output;
      * the turn is entirely empty.

    All three are serving faults, and all three correlate with transcript
    length — so they terminate high-E rollouts earlier and more often, which
    would masquerade as an arm effect. Raised so the retry decorator resamples;
    if it survives every attempt the rollout dies and the runner records a
    harness failure rather than a silent data point.
    """


class VLLMProvider(BaseProvider):
    """Provider for a locally served OpenAI-compatible endpoint (vLLM).

    Mirrors FireworksProvider's message bookkeeping so that run_step.py's
    leaked-tool-call recovery, checkpoint dump/restore, and history printing
    all behave identically.
    """

    def __init__(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        temperature: float | None = None,
        top_p: float | None = None,
        reasoning_effort: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        max_tokens: int | None = 4096,
        seed: int | None = None,
        timeout: float = 900.0,
    ) -> None:
        resolved_base = (
            base_url
            or os.getenv("VLLM_BASE_URL")
            or "http://localhost:8000/v1"
        )
        self.client = OpenAI(
            base_url=resolved_base,
            api_key=api_key or os.getenv("VLLM_API_KEY") or "EMPTY",
            timeout=timeout,
            max_retries=0,  # retries are handled by the tenacity decorator
        )
        self.base_url = resolved_base
        self.model = model
        self.messages = messages

        # Tool-less runs must omit the key entirely: an empty tools array is
        # rejected upstream.
        self.kwargs: dict = {}
        if tools:
            self.kwargs["tools"] = tools
            self.kwargs["tool_choice"] = "auto"
        if temperature is not None:
            self.kwargs["temperature"] = temperature
        if top_p is not None:
            self.kwargs["top_p"] = top_p
        if max_tokens is not None:
            self.kwargs["max_tokens"] = max_tokens
        if seed is not None:
            self.kwargs["seed"] = seed
        if reasoning_effort is not None:
            self.kwargs["reasoning_effort"] = reasoning_effort

    def _wire_messages(self) -> list[dict]:
        """Project the transcript down to fields the server will accept."""
        out = []
        for msg in self.messages:
            projected = {
                k: v for k, v in msg.items() if k in _WIRE_FIELDS and v is not None
            }
            # An assistant turn carrying tool_calls may legitimately have no
            # content; the API requires the key to be present in that case.
            if projected.get("role") == "assistant" and "content" not in projected:
                projected["content"] = ""
            out.append(projected)
        return out

    # InternalServerError is retried because vLLM's harmony parser intermittently
    # crashes on gpt-oss output ("unexpected tokens remaining in message header"),
    # returning 500 and killing the rollout. The failure is generation-side, not
    # input-side: replaying an identical request 24x never reproduced it, so a
    # retry resamples and succeeds. Retrying matters for validity, not just
    # throughput — longer rollouts take more turns and so hit the crash more
    # often, which would drop high-E rollouts preferentially and bias the arm
    # comparison. `self.messages` is only appended to after a successful call,
    # so a retry starts from clean state.
    @retry(
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        retry=retry_if_exception_type((
            RateLimitError, APITimeoutError, APIConnectionError, InternalServerError,
            MalformedGeneration,
        )),
    )
    def invoke(self) -> LLMResponse:
        """Make an API call to the local endpoint using internal message history."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=self._wire_messages(),
            **self.kwargs,
        )

        choice = response.choices[0]
        raw = choice.message.model_dump()
        message = {k: v for k, v in raw.items() if v is not None}
        # Normalise onto `reasoning_content`, the field this codebase reads,
        # dumps, and prints. Some servers emit `reasoning` instead.
        if "reasoning" in message:
            message.setdefault("reasoning_content", message["reasoning"])
            message.pop("reasoning")

        # Validate BEFORE appending, so a resample starts from clean history.
        if not message.get("tool_calls"):
            text = str(message.get("content") or "")
            reasoning = str(message.get("reasoning_content") or "")
            if choice.finish_reason == "length":
                raise MalformedGeneration(
                    f"truncated at max_tokens ({self.kwargs.get('max_tokens')}); "
                    f"reasoning={len(reasoning)} chars, content={len(text)} chars"
                )
            if _HARMONY_LEAK.search(text) or _HARMONY_LEAK.search(reasoning):
                raise MalformedGeneration(f"harmony tokens leaked: {text[:200]!r}")
            if not text.strip():
                raise MalformedGeneration(
                    f"empty turn: no tool call and no content "
                    f"(finish_reason={choice.finish_reason})"
                )

        self.messages.append(message)

        tool_calls = [
            ToolCall(
                id=tool_call["id"],
                name=tool_call["function"]["name"],
                arguments=tool_call["function"]["arguments"],
            )
            for tool_call in message.get("tool_calls") or []
        ]

        return LLMResponse(
            reasoning=message.get("reasoning_content"),
            response=message.get("content"),
            tool_calls=tool_calls if tool_calls else None,
        )

    def add_tool_result(self, tool_result: ToolResult) -> None:
        """Add a tool result to message history."""
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_result.id,
                "content": tool_result.content,
            }
        )

    def print_history(self) -> None:
        """Print full message history in run_step format."""
        step = 0
        i = 0

        while i < len(self.messages):
            msg = self.messages[i]

            if msg["role"] == "system":
                print()
                print_section("SYSTEM PROMPT", msg["content"])

            elif msg["role"] == "user" and i == 1:
                print_section("USER_PROMPT", msg["content"])

            elif msg["role"] == "assistant":
                print_step_header(step)

                if msg.get("reasoning_content"):
                    print()
                    print_section("REASONING", msg["reasoning_content"])

                if msg.get("content"):
                    print_section("RESPONSE", msg["content"])

                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        tool_calls_content = (
                            f"Function: {tc['function']['name']}\n"
                            f"Arguments: {tc['function']['arguments']}"
                        )
                        print_section("TOOL CALL", tool_calls_content)

            elif msg["role"] == "tool":
                print_section("TOOL RESULT", msg["content"])
                step += 1

            elif msg["role"] == "user":
                print_section("USER MESSAGE", msg["content"])
                step += 1

            i += 1

    def revert_last_turn(self) -> None:
        """Remove the last assistant turn from history."""
        self.messages = self.messages[:-1]
