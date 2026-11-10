"""Subconjunto do contrato de chat/completions da OpenAI."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class Message(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: str | list[dict[str, Any]] | None = None


class ChatCompletionRequest(BaseModel):
    # metadata, extra_body, top_p, and similar fields are accepted and ignored.
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    messages: list[Message]
    temperature: float | None = None  # agy has no corresponding flag; ignored
    max_tokens: int | None = None  # likewise
    response_format: dict[str, Any] | None = None
    stream: bool = False  # emulated: the entire response is sent in one chunk
    stream_options: dict[str, Any] | None = None


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChoiceMessage(BaseModel):
    role: str = "assistant"
    content: str


class Choice(BaseModel):
    index: int = 0
    message: ChoiceMessage
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage
