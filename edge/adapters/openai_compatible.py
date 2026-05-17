import base64
import json
import re
from typing import Any

import httpx

from edge.adapters.base import VLMAdapter


class OpenAICompatibleAdapter(VLMAdapter):
    adapter_name = "openai_compatible"

    def __init__(self, endpoint: str, model: str, api_key: str | None = None, timeout: float = 20.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model_version = model
        self.api_key = api_key
        self.timeout = timeout

    def analyze_frame(self, frame_context: dict[str, Any]) -> dict[str, Any]:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        text_prompt = (
            "Return JSON detections for Physical AI safety rules. "
            f"camera_id={frame_context['camera_id']}, frame_id={frame_context['frame_id']}. "
            'Schema: {"detections":[{"label":"person|robot|pallet|cart|box|unsafe_event",'
            '"confidence":0.0,"bbox":[x1,y1,x2,y2],"ppe":{"hard_hat":true,"vest":true},'
            '"blocking_emergency_path":false}]}'
        )
        content: list[dict[str, Any]] = []
        frame_bytes = frame_context.get("frame_bytes")
        media_url = frame_context.get("media_url") or frame_context.get("image_url")
        if frame_bytes:
            b64 = base64.b64encode(frame_bytes).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        elif media_url:
            content.append({"type": "image_url", "image_url": {"url": media_url}})
        content.append({"type": "text", "text": text_prompt})
        payload = {
            "model": self.model_version,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
        }
        response = httpx.post(
            f"{self.endpoint}/chat/completions",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        raw = response.json()
        parsed = parse_adapter_response(raw)
        return {
            "adapter_name": self.adapter_name,
            "model_version": self.model_version,
            "detections": parsed.get("detections", []),
            "raw_response": raw,
        }


class CosmosReason2Adapter(OpenAICompatibleAdapter):
    adapter_name = "cosmos_reason2"

    def __init__(
        self,
        endpoint: str,
        model: str = "nvidia/cosmos-reason2-2b",
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(endpoint=endpoint, model=model, api_key=api_key, timeout=timeout)

    def analyze_frame(self, frame_context: dict[str, Any]) -> dict[str, Any]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        content: list[dict[str, Any]] = []
        media_url = frame_context.get("media_url") or frame_context.get("image_url")
        video_url = frame_context.get("video_url")
        if video_url:
            content.append({"type": "video_url", "video_url": {"url": video_url}})
        elif media_url:
            content.append({"type": "image_url", "image_url": {"url": media_url}})

        content.append(
            {
                "type": "text",
                "text": (
                    "Analyze this Physical AI workcell frame for safety observability. "
                    "Return only JSON in the <answer> block with this schema: "
                    '{"detections":[{"label":"person|robot|pallet|cart|box|unsafe_event",'
                    '"confidence":0.0,"bbox":[x1,y1,x2,y2],"ppe":{"hard_hat":true,'
                    '"vest":true},"blocking_emergency_path":false,"summary":"..."}]}. '
                    "Use normalized pixel coordinates when exact image coordinates are unavailable. "
                    f"Frame metadata: camera_id={frame_context['camera_id']}, "
                    f"frame_id={frame_context['frame_id']}. "
                    "Answer the question in the following format: <think>\nyour reasoning\n"
                    "</think>\n\n<answer>\nyour JSON answer\n</answer>."
                ),
            }
        )

        payload = {
            "model": self.model_version,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a Physical AI safety reasoning model.",
                },
                {"role": "user", "content": content},
            ],
            "temperature": 0.2,
            "top_p": 0.3,
            "max_tokens": 4096,
            "stream": False,
        }
        response = httpx.post(
            f"{self.endpoint}/chat/completions",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        raw = response.json()
        assistant_text = _extract_assistant_text(raw)
        parsed = parse_adapter_response(raw)
        return {
            "adapter_name": self.adapter_name,
            "model_version": self.model_version,
            "detections": parsed.get("detections", []),
            "reasoning_text": assistant_text,
            "raw_response": raw,
        }


def _extract_assistant_text(raw: dict[str, Any]) -> str:
    choices = raw.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content)


def _parse_answer_json(text: str) -> dict[str, Any]:
    text = _strip_code_fence(text)
    answer_match = re.search(r"<answer>\s*(.*?)\s*</answer>", text, flags=re.DOTALL)
    candidate = answer_match.group(1) if answer_match else text
    json_match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
    if not json_match:
        return {"detections": []}
    try:
        parsed = json.loads(json_match.group(0))
    except json.JSONDecodeError:
        return {"detections": []}
    if not isinstance(parsed, dict):
        return {"detections": []}
    detections = parsed.get("detections", [])
    if not isinstance(detections, list):
        parsed["detections"] = []
    parsed["detections"] = [
        detection for detection in detections if isinstance(detection, dict)
    ]
    return parsed


def parse_adapter_response(raw: dict[str, Any]) -> dict[str, Any]:
    direct = raw.get("detections")
    if isinstance(direct, list):
        return {"detections": [item for item in direct if isinstance(item, dict)]}

    assistant_text = _extract_assistant_text(raw)
    if assistant_text:
        return _parse_answer_json(assistant_text)

    output = raw.get("output")
    if isinstance(output, dict):
        detections = output.get("detections", [])
        if isinstance(detections, list):
            return {"detections": [item for item in detections if isinstance(item, dict)]}
    return {"detections": []}


def _strip_code_fence(text: str) -> str:
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fence_match:
        return fence_match.group(1)
    return text
