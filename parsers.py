from bs4 import Tag


def parse_title_attr(tag: Tag) -> str:
    return (tag.get("title") or tag.get_text(" ", strip=True)).strip()


def parse_h2_child(tag: Tag) -> str:
    h2 = tag.find("h2")
    if isinstance(h2, Tag):
        return h2.get_text(" ", strip=True)
    return tag.get_text(" ", strip=True)


def parse_text_content(tag: Tag) -> str:
    return tag.get_text(" ", strip=True)


def parse_notice_title(tag: Tag) -> str:
    title = tag.select_one(".title, h1, h2, h3")
    if isinstance(title, Tag):
        return title.get_text(" ", strip=True)

    title_attr = tag.get("title")
    if title_attr:
        return str(title_attr).strip()

    text_parts: list[str] = []
    for node in tag.find_all(string=True):
        parent = node.parent
        excluded = False
        ancestor = parent
        while isinstance(ancestor, Tag):
            if any(
                "date" in class_name.lower() or "info" in class_name.lower()
                for class_name in ancestor.get("class", [])
            ):
                excluded = True
                break
            if ancestor is tag:
                break
            ancestor = ancestor.parent
        if excluded:
            continue
        text = str(node).strip()
        if text:
            text_parts.append(text)
    return " ".join(text_parts).strip()
