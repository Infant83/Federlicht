from feather.linkedin_ops import (
    extract_activity_id,
    extract_images,
    extract_links,
    html_to_text,
)


def test_extract_activity_id() -> None:
    assert extract_activity_id("https://www.linkedin.com/posts/test-activity-12345") == "12345"
    assert extract_activity_id("https://www.linkedin.com/feed/update/urn:li:activity:98765") == "98765"
    assert extract_activity_id("https://example.com/") is None


def test_extract_links_and_text() -> None:
    html_fragment = (
        'Hello <a href="https://www.linkedin.com/redir/redirect?url=https%3A%2F%2Fexample.com">'
        "link</a><br>Line2"
    )
    assert extract_links(html_fragment) == ["https://example.com"]
    assert html_to_text(html_fragment) == "Hello https://example.com\nLine2"


def test_extract_images() -> None:
    html_text = (
        '<meta property="og:image" content="https://img.com/cover.png">'
        '<img data-delayed-url="https://img.com/a.png">'
        '<img data-delayed-url="https://img.com/b.png">'
    )
    images = extract_images(html_text)
    assert images[0] == "https://img.com/cover.png"
    assert "https://img.com/a.png" in images
    assert "https://img.com/b.png" in images
