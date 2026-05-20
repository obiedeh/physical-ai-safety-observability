import base64
import json
import re
from typing import Any

import httpx

from edge.adapters.base import VLMAdapter


class OpenAICompatibleAdapter(VLMAdapter):
    adapter_name = "openai_compatible"

    def __init__(
        self, endpoint: str, model: str, api_key: str | None = None, timeout: float = 20.0
    ) -> None:
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
        content = _media_content_from_frame(frame_context)
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

        content = _media_content_from_frame(frame_context)
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


def _media_content_from_frame(frame_context: dict[str, Any]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    frame_bytes = frame_context.get("frame_bytes")
    media_url = frame_context.get("media_url") or frame_context.get("image_url")
    video_url = frame_context.get("video_url")
    if frame_bytes:
        b64 = base64.b64encode(frame_bytes).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    elif video_url:
        content.append({"type": "video_url", "video_url": {"url": video_url}})
    elif media_url:
        content.append({"type": "image_url", "image_url": {"url": media_url}})
    return content


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
    parsed["detections"] = normalize_detections(detections)
    return parsed


def parse_adapter_response(raw: dict[str, Any]) -> dict[str, Any]:
    direct = raw.get("detections")
    if isinstance(direct, list):
        return {"detections": normalize_detections(direct)}

    assistant_text = _extract_assistant_text(raw)
    if assistant_text:
        return _parse_answer_json(assistant_text)

    output = raw.get("output")
    if isinstance(output, dict):
        detections = output.get("detections", [])
        if isinstance(detections, list):
            return {"detections": normalize_detections(detections)}
    return {"detections": []}


def _strip_code_fence(text: str) -> str:
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fence_match:
        return fence_match.group(1)
    return text


def normalize_detections(detections: list[Any]) -> list[dict[str, Any]]:
    return [_normalize_detection(item) for item in detections if isinstance(item, dict)]


def _normalize_detection(detection: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(detection)
    label = _normalize_token(str(normalized.get("label", "")))
    normalized["label"] = _canonical_label(label)

    if normalized["label"] == "person":
        ppe = _normalize_ppe(normalized, label)
        if ppe:
            normalized["ppe"] = ppe
    return normalized


def _canonical_label(label: str) -> str:
    if (
        "ppe" in label and any(token in label for token in ("missing", "no", "without"))
    ) or label in {
        "human",
        "worker",
        "operator",
        "employee",
        "person_without_ppe",
        "no_ppe",
        "missing_ppe",
        "ppe_missing",
        "person_no_ppe",
        "person_missing_ppe",
        "no_hard_hat",
        "missing_hard_hat",
        "no_helmet",
        "missing_helmet",
        "no_vest",
        "missing_vest",
    }:
        return "person"
    return label


def _normalize_ppe(detection: dict[str, Any], label: str) -> dict[str, bool]:
    ppe = detection.get("ppe")
    source = ppe if isinstance(ppe, dict) else {}
    status = _normalize_token(str(detection.get("ppe_status", detection.get("ppe_compliance", ""))))

    hard_hat = _first_bool(
        source,
        detection,
        keys=(
            "hard_hat",
            "hardhat",
            "helmet",
            "safety_helmet",
            "hard_hat_present",
            "helmet_present",
            "wearing_hard_hat",
            "wearing_helmet",
        ),
    )
    vest = _first_bool(
        source,
        detection,
        keys=(
            "vest",
            "safety_vest",
            "hi_vis_vest",
            "high_visibility_vest",
            "reflective_vest",
            "vest_present",
            "wearing_vest",
            "wearing_safety_vest",
        ),
    )

    if hard_hat is None and any(
        token in label
        for token in ("no_hard_hat", "missing_hard_hat", "no_helmet", "missing_helmet")
    ):
        hard_hat = False
    if vest is None and any(
        token in label for token in ("no_vest", "missing_vest", "without_vest")
    ):
        vest = False
    if (
        "ppe" in label and any(token in label for token in ("missing", "no", "without"))
    ) or status in {
        "missing",
        "missing_ppe",
        "no_ppe",
        "non_compliant",
        "noncompliant",
        "unsafe",
    }:
        hard_hat = False if hard_hat is None else hard_hat
        vest = False if vest is None else vest
    if status in {"present", "compliant", "safe", "ppe_present", "wearing_ppe"}:
        hard_hat = True if hard_hat is None else hard_hat
        vest = True if vest is None else vest

    normalized: dict[str, bool] = {}
    if hard_hat is not None:
        normalized["hard_hat"] = hard_hat
    if vest is not None:
        normalized["vest"] = vest
    return normalized


def _first_bool(*sources: dict[str, Any], keys: tuple[str, ...]) -> bool | None:
    for source in sources:
        for key in keys:
            if key in source:
                value = source[key]
                if isinstance(value, bool):
                    return value
                if isinstance(value, str):
                    token = _normalize_token(value)
                    if token in {"true", "yes", "present", "wearing", "detected", "compliant"}:
                        return True
                    if token in {
                        "false",
                        "no",
                        "missing",
                        "absent",
                        "not_wearing",
                        "non_compliant",
                    }:
                        return False
    return None


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
