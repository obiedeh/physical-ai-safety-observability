from edge.adapters.openai_compatible import (
    _extract_assistant_text,
    _media_content_from_frame,
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
                        '<answer>{"detections":[{"label":"person",'
                        '"confidence":0.91,"bbox":[1,2,3,4]}]}</answer>'
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
    parsed = parse_adapter_response({"detections": [{"label": "robot", "confidence": 0.88}, "bad"]})

    assert parsed == {"detections": [{"label": "robot", "confidence": 0.88}]}


def test_openai_chat_completion_json_content_is_accepted() -> None:
    parsed = parse_adapter_response(
        {"choices": [{"message": {"content": '```json\n{"detections":[{"label":"pallet"}]}\n```'}}]}
    )

    assert parsed["detections"][0]["label"] == "pallet"


def test_malformed_adapter_payload_falls_back_to_empty_detections() -> None:
    assert parse_adapter_response({"choices": [{"message": {"content": "not json"}}]}) == {
        "detections": []
    }


def test_live_frame_bytes_are_sent_as_image_content() -> None:
    content = _media_content_from_frame({"frame_bytes": b"jpeg-bytes"})

    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_video_url_is_used_when_frame_bytes_are_absent() -> None:
    content = _media_content_from_frame({"video_url": "rtsp://example/stream1"})

    assert content == [{"type": "video_url", "video_url": {"url": "rtsp://example/stream1"}}]


def test_ppe_aliases_are_normalized_for_rule_engine() -> None:
    parsed = parse_adapter_response(
        {
            "detections": [
                {
                    "label": "Worker",
                    "confidence": 0.9,
                    "ppe": {"helmet": "missing", "safety_vest": "present"},
                }
            ]
        }
    )

    assert parsed["detections"] == [
        {
            "label": "person",
            "confidence": 0.9,
            "ppe": {"hard_hat": False, "vest": True},
        }
    ]


def test_missing_ppe_label_is_normalized_as_person_violation() -> None:
    parsed = parse_adapter_response(
        {"choices": [{"message": {"content": '{"detections":[{"label":"missing PPE"}]}'}}]}
    )

    assert parsed["detections"] == [{"label": "person", "ppe": {"hard_hat": False, "vest": False}}]
