from edge.adapters.openai_compatible import (
    _extract_assistant_text,
    _parse_answer_json,
    parse_adapter_response,
)


def test_cosmos_reason2_answer_json_is_normalized() -> None:
    raw = {
        "choices": [
            {
                "message": {
                    "content": (
                        "<think>Reason about the workcell.</think>\n"
                        "<answer>{\"detections\":[{\"label\":\"person\","
                        "\"confidence\":0.91,\"bbox\":[1,2,3,4]}]}</answer>"
                    )
                }
            }
        ]
    }

    text = _extract_assistant_text(raw)
    parsed = _parse_answer_json(text)

    assert parsed["detections"][0]["label"] == "person"
    assert parsed["detections"][0]["confidence"] == 0.91


def test_direct_detection_payload_is_accepted() -> None:
    parsed = parse_adapter_response(
        {"detections": [{"label": "robot", "confidence": 0.88}, "bad"]}
    )

    assert parsed == {"detections": [{"label": "robot", "confidence": 0.88}]}


def test_openai_chat_completion_json_content_is_accepted() -> None:
    parsed = parse_adapter_response(
        {
            "choices": [
                {
                    "message": {
                        "content": "```json\n{\"detections\":[{\"label\":\"pallet\"}]}\n```"
                    }
                }
            ]
        }
    )

    assert parsed["detections"][0]["label"] == "pallet"


def test_malformed_adapter_payload_falls_back_to_empty_detections() -> None:
    assert parse_adapter_response({"choices": [{"message": {"content": "not json"}}]}) == {
        "detections": []
    }
