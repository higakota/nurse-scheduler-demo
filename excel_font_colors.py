"""Excel医師欄の文字色。判定できない色は出勤候補にしない。"""
import re
from doctor_import import NS, xml_read


class FontColors:
    def __init__(self, book):
        self.theme = []
        self.fonts = []
        self.indexed = []
        self.differentials = []
        if "xl/theme/theme1.xml" in book.namelist():
            root = xml_read(book, "xl/theme/theme1.xml")
            ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
            scheme = root.find("a:themeElements/a:clrScheme", ns)
            if scheme is not None:
                self.theme = [next(iter(item)).get("val") if next(iter(item)).tag.endswith("srgbClr")
                              else next(iter(item)).get("lastClr") for item in scheme]
                # Spreadsheet theme indexes put light1 before dark1, then light2/dark2.
                if len(self.theme) >= 4:
                    self.theme[:4] = [self.theme[1], self.theme[0], self.theme[3], self.theme[2]]
        if "xl/styles.xml" in book.namelist():
            root = xml_read(book, "xl/styles.xml")
            self.fonts = root.findall("s:fonts/s:font", NS)
            self.differentials = root.findall("s:dxfs/s:dxf", NS)
            self.indexed = [node.get("rgb") for node in root.findall("s:colors/s:indexedColors/s:rgbColor", NS)]

    def conditional_font_uncertain(self, conditional):
        """背景色・罫線だけの書式を、文字色の変更と混同しない。"""
        for rule in conditional:
            if rule.tag != "{" + NS["s"] + "}cfRule":
                return True
            identifier = rule.get("dxfId")
            if identifier is None:
                if rule.get("type") not in ("colorScale", "dataBar", "iconSet"):
                    return True
                continue
            try:
                index = int(identifier)
                if index < 0:
                    return True
                style = self.differentials[index]
            except (ValueError, IndexError):
                return True
            if style.find("s:font/s:color", NS) is not None or style.find("s:extLst", NS) is not None:
                return True
        return False

    def red(self, color):
        if color is None or color.get("auto") in ("1", "true"):
            return False
        rgb = color.get("rgb")
        try:
            if color.get("theme") is not None:
                rgb = self.theme[int(color.get("theme"))]
            if color.get("indexed") is not None:
                index = int(color.get("indexed"))
                palette = self.indexed or ["000000", "FFFFFF", "FF0000", "00FF00",
                                           "0000FF", "FFFF00", "FF00FF", "00FFFF"] * 2 + ["800000"]
                rgb = palette[index]
            if not rgb or not re.fullmatch(r"(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", rgb):
                return None
            r, g, b = (int(rgb[-6:][i:i+2], 16) for i in (0, 2, 4))
            tint = float(color.get("tint", "0"))
            if not -1 <= tint <= 1:
                return None
            r, g, b = [v * (1+tint) if tint < 0 else v+(255-v)*tint for v in (r,g,b)]
            # 黒字や青字から区別できる赤系。曖昧な赤系は手動確認へ回す。
            if r >= 100 and r > g * 1.5 and r > b * 1.5:
                return True
            if r > g and r > b:
                return None
            return False
        except (IndexError, ValueError, TypeError):
            return None

    def characters(self, node, text, style):
        try:
            font = self.fonts[int(style.get("fontId", "0"))] if style is not None and self.fonts else None
            base = self.red(font.find("s:color", NS)) if font is not None else False
        except (IndexError, ValueError):
            base = None
        if node is None:
            return [base] * len(text)
        flags = []
        for child in node:
            if child.tag == "{" + NS["s"] + "}t":
                flags.extend([base] * len(child.text or ""))
            elif child.tag == "{" + NS["s"] + "}r":
                value = child.find("s:t", NS)
                color = child.find("s:rPr/s:color", NS)
                flags.extend([self.red(color) if color is not None else base] * len(value.text or "" if value is not None else ""))
        return flags


def clinical_groups(text, flags):
    """左右の空列を保持したまま、赤字で書かれた医師名全体を除外する。"""
    spans = []
    start = 0
    for match in re.finditer(r"(?:[ \u3000]{2,}|[\r\n]+)", text):
        if text[start:match.start()].strip():
            spans.append((start, match.start()))
        start = match.end()
    if text[start:].strip():
        spans.append((start, len(text)))
    groups, excluded, uncertain = [], [], False
    for start, end in spans:
        names = []
        for match in re.finditer(r"[^/／、,\n]+", text[start:end]):
            raw = match.group()
            name = raw.strip()
            if not name:
                continue
            left = start + match.start() + len(raw) - len(raw.lstrip())
            states = flags[left:left+len(name)]
            if len(states) != len(name) or None in states or (True in states and False in states):
                uncertain = True
            elif states and all(states):
                excluded.append(name)
            else:
                names.append(name)
        groups.append("/".join(names))
    return groups, excluded, uncertain
