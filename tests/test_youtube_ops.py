from hidair_feather.youtube_ops import detail_to_metadata, extract_video_id


def test_extract_video_id_variants() -> None:
    assert extract_video_id("https://www.youtube.com/watch?v=abc123") == "abc123"
    assert extract_video_id("https://www.youtube.com/watch?v=abc123&t=10s") == "abc123"
    assert extract_video_id("https://youtu.be/abc123") == "abc123"
    assert extract_video_id("https://youtu.be/abc123?t=15") == "abc123"
    assert extract_video_id("https://www.youtube.com/shorts/abc123") == "abc123"
    assert extract_video_id("https://www.youtube.com/embed/abc123") == "abc123"
    assert extract_video_id("https://example.com/watch?v=abc123") is None


def test_detail_to_metadata() -> None:
    item = {
        "id": "abc123",
        "snippet": {
            "title": "Title",
            "description": "Desc",
            "channelTitle": "Chan",
            "channelId": "chan123",
            "publishedAt": "2026-01-01T00:00:00Z",
            "tags": ["tag1"],
        },
        "statistics": {"viewCount": "10", "likeCount": "2", "commentCount": "1"},
        "contentDetails": {"duration": "PT1M"},
    }
    meta = detail_to_metadata(item, rank=3, source="direct_url")
    assert meta["video_id"] == "abc123"
    assert meta["url"].endswith("watch?v=abc123")
    assert meta["title"] == "Title"
    assert meta["description"] == "Desc"
    assert meta["channel_title"] == "Chan"
    assert meta["channel_id"] == "chan123"
    assert meta["published_at"] == "2026-01-01T00:00:00Z"
    assert meta["duration"] == "PT1M"
    assert meta["view_count"] == "10"
    assert meta["like_count"] == "2"
    assert meta["comment_count"] == "1"
    assert meta["search_rank"] == 3
    assert meta["source"] == "direct_url"
