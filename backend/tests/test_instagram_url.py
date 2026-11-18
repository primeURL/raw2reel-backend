import pytest

from app.services.instagram import InvalidInstagramUrl, parse_instagram_url


@pytest.mark.parametrize(
    "url,code,canonical",
    [
        ("https://www.instagram.com/reel/DLDXI0fylTC/", "DLDXI0fylTC", "https://www.instagram.com/reel/DLDXI0fylTC/"),
        ("https://www.instagram.com/reel/DLDXI0fylTC/?igsh=abc123", "DLDXI0fylTC", "https://www.instagram.com/reel/DLDXI0fylTC/"),
        ("instagram.com/reels/DLDXI0fylTC", "DLDXI0fylTC", "https://www.instagram.com/reel/DLDXI0fylTC/"),
        ("https://www.instagram.com/p/Cx-1_abcDE/", "Cx-1_abcDE", "https://www.instagram.com/p/Cx-1_abcDE/"),
        ("https://www.instagram.com/some.user/reel/DLDXI0fylTC/", "DLDXI0fylTC", "https://www.instagram.com/reel/DLDXI0fylTC/"),
        ("https://m.instagram.com/tv/B12345abc/", "B12345abc", "https://www.instagram.com/tv/B12345abc/"),
    ],
)
def test_valid(url, code, canonical):
    p = parse_instagram_url(url)
    assert p.shortcode == code
    assert p.canonical_url == canonical


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.com/reel/DLDXI0fylTC/",
        "https://instagram.com.evil.com/reel/DLDXI0fylTC/",
        "https://www.instagram.com/someuser/",
        "https://www.instagram.com/stories/someuser/123/",
        "http://169.254.169.254/latest/meta-data/",
        "",
    ],
)
def test_invalid(url):
    with pytest.raises(InvalidInstagramUrl):
        parse_instagram_url(url)
