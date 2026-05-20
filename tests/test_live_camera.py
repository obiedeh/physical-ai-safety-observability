from edge.live_camera import _build_uri, _candidate_profiles


def test_build_uri_url_encodes_credentials() -> None:
    uri = _build_uri("192.168.1.146", 554, "stream1", "user@example.com", "p@ss word")

    assert uri == "rtsp://user%40example.com:p%40ss%20word@192.168.1.146:554/stream1"


def test_auto_profile_tries_tapo_before_generic_paths() -> None:
    candidates = _candidate_profiles("auto")

    assert candidates[0] == ("tapo", "stream1")
    assert ("tapo", "stream2") in candidates
    assert ("generic", "live") in candidates
