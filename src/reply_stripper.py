import quotequail


def strip_reply(text: str | None, html: str | None) -> dict:
    stripped_text = _strip_text(text) if text else None
    stripped_html = _strip_html(html) if html else None

    return {
        "stripped-text": stripped_text,
        "stripped-html": stripped_html,
    }


def _strip_text(text: str) -> str:
    result = quotequail.unwrap(text)
    if result and result.get("text_top"):
        return result["text_top"].strip()
    return text


def _strip_html(html: str) -> str:
    result = quotequail.unwrap_html(html)
    if result and result.get("html_top"):
        return result["html_top"].strip()
    return html
