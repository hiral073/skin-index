"""Files are UTF-8, pages say so, and icons are drawn with CSS or SVG, never with font characters."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted(p for folder in ("templates", "static") for p in (ROOT / folder).rglob("*")
               if p.is_file() and p.suffix in (".html", ".css", ".js"))

# Non-ASCII characters that are plain text (punctuation, currency, units), not icons
TEXT_CHARACTERS = {
    "·",  # middle dot between words
    "—",  # em dash
    "“", "”",  # double quotes
    "°", "µ", "³",  # degree, micro, superscript three (Today units)
    "₹",  # rupee sign
    "≈",  # approximately equal
    "›",  # single right angle quotation mark in a group name (Sunscreen › Face)
}


def rel(path):
    return str(path.relative_to(ROOT)).replace("\\", "/")


def test_there_are_files_to_check():
    assert len(FILES) >= 15


@pytest.mark.parametrize("path", FILES, ids=rel)
def test_the_file_is_clean_utf_8_without_control_characters(path):
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "byte order mark"
    text = raw.decode("utf-8")                                    # raises when it is not UTF-8
    assert "�" not in text, "replacement character"
    assert not re.search("[ÃÂ][\u0080-¿]|â€", text), "mojibake (UTF-8 read as another encoding)"
    bad = sorted({hex(ord(c)) for c in text if (ord(c) < 32 and c not in "\n\r\t") or 0x7f <= ord(c) < 0xa0})
    assert bad == [], f"control characters {bad}"


@pytest.mark.parametrize("path", FILES, ids=rel)
def test_no_font_character_is_used_as_an_icon(path):
    odd = sorted({c for c in path.read_text(encoding="utf-8") if ord(c) > 127 and c not in TEXT_CHARACTERS})
    assert odd == [], f"icon-like characters {[(c, hex(ord(c))) for c in odd]}: draw them with CSS or inline SVG"


@pytest.mark.parametrize("path", [p for p in FILES if p.suffix == ".html"], ids=rel)
def test_templates_use_no_arrow_or_symbol_entities(path):
    entities = re.findall(r"&(?:larr|rarr|uarr|darr|harr|lArr|rArr|times|check|star|hearts|diams|loz|#x?[0-9a-fA-F]+);",
                          path.read_text(encoding="utf-8"))
    assert entities == []


def test_css_content_properties_are_empty_or_plain_ascii():
    css = (ROOT / "static/css/style.css").read_text(encoding="utf-8")
    values = re.findall(r'content:\s*("[^"]*"|\'[^\']*\')', css)
    assert values, "the arrows use content: \"\""
    for value in values:
        assert "\\" not in value and all(32 <= ord(c) < 127 for c in value), value


def test_the_avoid_filter_arrow_is_drawn_with_css_and_turns_when_it_opens():
    css = (ROOT / "static/css/style.css").read_text(encoding="utf-8")
    closed = re.search(r"\.avoid-summary::after \{(.*?)\}", css, re.S).group(1)
    opened = re.search(r"\.avoid-filter\[open\] > \.avoid-summary::after \{(.*?)\}", css, re.S).group(1)
    assert 'content: ""' in closed and "border-right" in closed and "border-bottom" in closed
    assert "rotate(45deg)" in closed and "rotate(-135deg)" in opened


def test_the_icons_are_inline_svg(client):
    home = client.get("/").get_data(as_text=True)
    assert home.count("<svg") == 5 and home.count('class="brand-icon"') == 2     # brand twice, three features
    assert "◈" not in home and "⌕" not in home and "⇄" not in home and "◎" not in home
    for page in (home, client.get("/products").get_data(as_text=True)):
        assert "&times;" not in page and "&larr;" not in page and "&rarr;" not in page


def test_arrows_and_the_remove_buttons_have_no_font_characters(app, client):
    import json
    from urllib.parse import quote
    from contextlib import closing
    from database.db import get_db
    with closing(get_db(app.config["DATABASE"])) as conn, conn:
        conn.execute("INSERT INTO products (name, brand, price, size_text) VALUES ('Plain Serum', 'Dew', 10, '50 mL')")
    client.set_cookie("avoid_list", quote(json.dumps(["fragrance"])))
    page = client.get("/products").get_data(as_text=True)
    assert '<span class="arrow arrow-left" aria-hidden="true"></span>Previous' in page
    assert 'Next<span class="arrow arrow-right" aria-hidden="true"></span>' in page
    chip = re.search(r'<button type="button" class="chip-remove".*?</button>', page, re.S).group(0)
    assert "<svg" in chip and "×" not in chip


@pytest.mark.parametrize("url", ["/", "/products", "/compare", "/insights", "/today", "/science", "/nothing-here"])
def test_pages_send_a_utf_8_charset_and_declare_it(client, url, weather_api):
    response = client.get(url)
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert '<meta charset="UTF-8">' in response.get_data(as_text=True)


@pytest.mark.parametrize("url, kind", [
    ("/static/css/style.css", "text/css"), ("/static/js/main.js", "javascript"), ("/static/js/avoid.js", "javascript"),
])
def test_static_files_send_a_utf_8_charset(client, url, kind):
    content_type = client.get(url).headers["Content-Type"]
    assert kind in content_type and content_type.endswith("charset=utf-8")
