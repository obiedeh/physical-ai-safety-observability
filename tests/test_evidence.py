from evidence.hashing import hash_text


def test_hash_text_is_deterministic() -> None:
    assert hash_text("frame-1") == hash_text("frame-1")
    assert hash_text("frame-1") != hash_text("frame-2")

