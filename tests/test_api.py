from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def test_health_is_available():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_rejects_unsupported_extension():
    response = client.post(
        "/api/v1/analyses",
        files={"video": ("not-a-video.txt", b"nope", "text/plain")},
    )
    assert response.status_code == 415


def test_safe_name_preserves_chinese_stem_and_normalizes_extension():
    assert main.safe_name("测试视频.mp4") == "测试视频.mp4"
    assert main.safe_name("纯中文.MP4") == "纯中文.mp4"
    assert main.safe_name(r"C:\\fakepath\\座舱体验视频.MOV") == "座舱体验视频.mov"


def test_upload_accepts_chinese_filename():
    response = client.post(
        "/api/v1/analyses",
        files={"video": ("中文座舱体验.mp4", b"not-a-real-video", "video/mp4")},
    )
    # It may fail downstream video decoding, but filename validation must accept it.
    assert response.status_code == 202
    assert response.json()["analysis_id"]


def test_rubric_endpoint():
    response = client.get("/api/v1/rubric")
    assert response.status_code == 200
    assert response.json()["rubric_id"] == "cockpit-basic-usability"


def test_no_model_report_cannot_be_approved_but_can_be_rejected():
    from uuid import uuid4
    from app.storage import create_job, result_file, write_json_atomic, get_job

    analysis_id = uuid4().hex[:16]
    create_job({
        "analysis_id": analysis_id,
        "status": "completed_unscored",
        "stage": "awaiting_human_review",
        "created_at": "2026-10-28T00:00:00+00:00",
        "video_metadata": {"original_filename": "synthetic.mp4"},
    })
    write_json_atomic(result_file(analysis_id), {
        "analysis_id": analysis_id,
        "mode": "no_model",
        "review_status": "pending",
        "overall_score_100": None,
        "scores": [{"metric_id": "ui_legibility", "score": None}],
    })

    approve = client.post(f"/api/v1/analyses/{analysis_id}/review", json={"reviewer": "tester", "decision": "approved"})
    assert approve.status_code == 409

    reject = client.post(f"/api/v1/analyses/{analysis_id}/review", json={"reviewer": "tester", "decision": "rejected", "notes": "仅测试抽帧，不存在模型分数"})
    assert reject.status_code == 200
    assert reject.json()["review_status"] == "rejected"
    assert get_job(analysis_id)["review_status"] == "rejected"


def test_invalid_analysis_id_is_not_found():
    response = client.get("/api/v1/analyses/../../etc/passwd")
    assert response.status_code in (404, 405)


def test_status_response_does_not_leak_filesystem_path():
    from uuid import uuid4
    from app.storage import create_job

    analysis_id = uuid4().hex[:16]
    create_job({
        "analysis_id": analysis_id, "status": "queued", "stage": "queued",
        "created_at": "2026-10-28T00:00:00+00:00", "video_path": "/private/server/path/video.mp4",
        "video_metadata": {"original_filename": "video.mp4"}
    })
    response = client.get(f"/api/v1/analyses/{analysis_id}")
    assert response.status_code == 200
    assert "video_path" not in response.json()



def test_evidence_endpoint_serves_frame_jpeg():
    from uuid import uuid4
    from app.storage import create_job, job_dir

    analysis_id = uuid4().hex[:16]
    create_job({
        "analysis_id": analysis_id,
        "status": "completed_unscored",
        "stage": "awaiting_human_review",
        "created_at": "2026-10-29T00:00:00+00:00",
        "video_metadata": {"original_filename": "中文座舱.mp4"},
    })
    frames = job_dir(analysis_id) / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    payload = b"fake-jpeg-bytes-for-route-test"
    (frames / "frame_001.jpg").write_bytes(payload)

    response = client.get(f"/api/v1/analyses/{analysis_id}/evidence/frame_001.jpg")
    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"].startswith("image/jpeg")


def test_evidence_endpoint_rejects_unexpected_filename():
    from uuid import uuid4
    from app.storage import create_job

    analysis_id = uuid4().hex[:16]
    create_job({
        "analysis_id": analysis_id,
        "status": "completed_unscored",
        "stage": "awaiting_human_review",
        "created_at": "2026-10-29T00:00:00+00:00",
        "video_metadata": {"original_filename": "test.mp4"},
    })
    response = client.get(f"/api/v1/analyses/{analysis_id}/evidence/secret.txt")
    assert response.status_code == 400


def test_supplemental_timestamp_parser_accepts_seconds_and_deduplicates():
    assert main._parse_supplemental_timestamps("12.5, 18;12.5, 0") == [0.0, 12.5, 18.0]
    assert main._parse_supplemental_timestamps(None) == []
    assert main._parse_supplemental_timestamps(" , ; ") == []


def test_supplemental_timestamp_parser_rejects_invalid_values():
    from fastapi import HTTPException
    import pytest

    for value in ("NaN", "inf", "-1", "not-a-time"):
        with pytest.raises(HTTPException) as error:
            main._parse_supplemental_timestamps(value)
        assert error.value.status_code == 422


def test_supplemental_timestamp_parser_enforces_count_limit():
    from fastapi import HTTPException
    import pytest

    raw = ",".join(str(i) for i in range(51))
    with pytest.raises(HTTPException) as error:
        main._parse_supplemental_timestamps(raw)
    assert error.value.status_code == 422
