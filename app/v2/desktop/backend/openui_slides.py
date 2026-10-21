"""Deterministic slide layout and editable PPTX export of validated OpenUI trees."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from typing import cast

LAYOUT = json.loads(
    (Path(__file__).parent / "openui_runtime/slide_layout.json").read_text()
)


def validate_slide(props):
    children = props["children"]
    if props["layout"] == "cover" and len(props["title"]) > 32:
        raise ValueError("Cover title exceeds 32 characters")
    limit = {"cover": 1, "content": 2, "split": 4}[props["layout"]]
    if len(children) > limit:
        raise ValueError(
            f"Slide {props['title']!r} has too many blocks for its layout: "
            f"{props['layout']} allows at most {limit}, got {len(children)}"
        )
    for child in children:
        name, p = child["component"], child["props"]
        if name not in {"Text", "Metric", "Table", "Chart"}:
            raise ValueError(
                f"Unsupported slide block {name!r} in Slide {props['title']!r}. "
                "Direct children must be Text, Metric, Table or Chart; "
                "use these directly without layout containers."
            )
        if props["layout"] == "cover" and name != "Text":
            raise ValueError(
                f"Cover supports Text only; Slide {props['title']!r} contains {name!r}"
            )
        if name == "Text" and p["content"].count("\n") > (
            4 if len(children) > 2 else 8
        ):
            raise ValueError("Slide text has too many lines; split across slides")
        if name == "Text" and len(p["content"]) > (
            120 if props["layout"] == "split" and len(children) > 2 else 240
        ):
            raise ValueError("Slide text exceeds 240 characters")
        if name == "Metric" and any(
            len(p.get(k, "")) > 40 for k in ("label", "value", "change")
        ):
            raise ValueError("Slide metric is too long")
        if (
            name in {"Table", "Chart"}
            and props["layout"] == "split"
            and len(children) > 2
        ):
            raise ValueError("Tables and charts need a full-height slide block")
        if name == "Table" and (
            len(p["columns"]) > 5
            or len(p["rows"]) > 6
            or any(len(str(v)) > 40 for row in [p["columns"], *p["rows"]] for v in row)
        ):
            raise ValueError("Slide table is too large")
        if name == "Chart" and (
            len(p["title"]) > 40
            or any(len(series["name"]) > 20 for series in p["series"])
            or len(p["labels"]) > 12
            or len(p["series"]) > 3
            or any(len(v) > 20 for v in p["labels"])
            or any(
                isinstance(v, str) for series in p["series"] for v in series["values"]
            )
        ):
            raise ValueError("Slide charts require bounded literal data")


def slide_slots(layout, count):
    if count == 0:
        return []
    columns = 2 if layout == "split" and count > 1 else 1
    rows = (count + columns - 1) // columns
    width = (
        LAYOUT["width"] - 2 * LAYOUT["margin"] - (columns - 1) * LAYOUT["gap"]
    ) / columns
    height = (LAYOUT["bodyHeight"] - (rows - 1) * LAYOUT["gap"]) / rows
    return [
        (
            LAYOUT["margin"] + (i % columns) * (width + LAYOUT["gap"]),
            LAYOUT["bodyY"] + (i // columns) * (height + LAYOUT["gap"]),
            width,
            height,
        )
        for i in range(count)
    ]


def export_deck(tree, *, dark=False):
    from pptx import Presentation
    from pptx.chart.data import ChartData
    from pptx.shapes.graphfrm import GraphicFrame
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt
    from pptx.oxml.xmlchemy import OxmlElement
    from .openui import validate_tree

    validate_tree(tree)
    if tree["component"] != "Deck":
        raise ValueError("PPTX export requires a Deck root")
    palette = LAYOUT["dark" if dark else "light"]
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333333), Inches(7.5)
    prs.core_properties.title = tree["props"]["title"]

    def unit(v):
        return Inches(v / 96)

    def text(slide, value, box, size, color, bold=False, wrap=True):
        shape = slide.shapes.add_textbox(*(unit(v) for v in box))
        frame = shape.text_frame
        frame.word_wrap = wrap
        if not wrap:
            units = sum(0.6 if ch.isascii() else 1 for ch in str(value))
            size = min(size, box[2] / max(1, units))
        frame.margin_left = frame.margin_right = 0
        frame.margin_top = frame.margin_bottom = 0
        frame.text = str(value)
        for paragraph in frame.paragraphs:
            paragraph.font.name = "Arial"
            paragraph.font.size = Pt(size * 0.75)
            paragraph.font.bold = bold
            paragraph.font.color.rgb = RGBColor.from_string(color)
        return shape

    for index, node in enumerate(tree["props"]["children"]):
        p = node["props"]
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string(
            palette["background"]
        )
        accent = LAYOUT["darkAccents" if dark else "accents"][p["accent"]]
        halo = slide.shapes.add_shape(
            MSO_SHAPE.OVAL, unit(950), unit(-260), unit(600), unit(600)
        )
        halo.fill.solid()
        bg = palette["background"]
        mixed = "".join(
            f"{round(int(accent[i : i + 2], 16) * 0.07 + int(bg[i : i + 2], 16) * 0.93):02X}"
            for i in (0, 2, 4)
        )
        halo.fill.fore_color.rgb = RGBColor.from_string(mixed)
        halo.line.fill.background()
        halo._element.spPr.append(OxmlElement("a:effectLst"))
        line = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, unit(64), unit(32), unit(72), unit(6)
        )
        line.fill.solid()
        line.fill.fore_color.rgb = RGBColor.from_string(accent)
        line.line.fill.background()
        line._element.spPr.append(OxmlElement("a:effectLst"))
        text(
            slide,
            p["title"],
            (
                64,
                LAYOUT["coverTitleY"],
                LAYOUT["coverTextWidth"],
                LAYOUT["coverTitleHeight"],
            )
            if p["layout"] == "cover"
            else (64, 54, 1152, 140),
            LAYOUT[
                "coverLongTitleSize"
                if len(p["title"]) > LAYOUT["coverLongTitleThreshold"]
                else "coverTitleSize"
            ]
            if p["layout"] == "cover"
            else 44,
            palette["foreground"],
            True,
        )
        text(slide, f"{index + 1:02d}", (1152, 675, 64, 24), 16, accent)
        for child, (x, y, w, h) in zip(
            p["children"], slide_slots(p["layout"], len(p["children"]))
        ):
            name, b = child["component"], child["props"]
            if p["layout"] == "cover":
                text(
                    slide,
                    b["content"],
                    (
                        64,
                        LAYOUT["coverBodyY"],
                        LAYOUT["coverTextWidth"],
                        LAYOUT["coverBodyHeight"],
                    ),
                    LAYOUT["coverBodySize"],
                    palette["foreground"],
                )
                continue
            tile = slide.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE, unit(x), unit(y), unit(w), unit(h)
            )
            tile.fill.solid()
            tile.fill.fore_color.rgb = RGBColor.from_string(palette["tile"])
            tile.line.fill.background()
            tile.adjustments[0] = 0.03
            tile._element.spPr.append(OxmlElement("a:effectLst"))
            x, y, w, h = x + 24, y + 24, w - 48, h - 48
            if name == "Text":
                text(
                    slide,
                    b["content"],
                    (x, y, w, h),
                    30 if h > 240 else 20,
                    palette["foreground"],
                )
            elif name == "Metric":
                value_size = 56 if h > 240 else 40
                text(
                    slide,
                    b["label"],
                    (x, y, w, 29),
                    24,
                    palette["foreground"],
                    wrap=False,
                )
                text(
                    slide,
                    b["value"],
                    (x, y + 41, w, value_size * 1.2),
                    value_size,
                    accent,
                    True,
                    wrap=False,
                )
                text(
                    slide,
                    b["change"],
                    (x, y + 53 + value_size * 1.2, w, 27),
                    22,
                    palette["foreground"],
                    wrap=False,
                )
            elif name == "Table":
                rows = [b["columns"], *b["rows"]]
                table = slide.shapes.add_table(
                    len(rows), len(b["columns"]), unit(x), unit(y), unit(w), unit(h)
                ).table
                import math

                font_size = 20

                def row_height(row, size):
                    usable = w / len(b["columns"]) - 12
                    return (
                        max(
                            1,
                            max(
                                math.ceil(
                                    sum(0.6 if ch.isascii() else 1 for ch in str(value))
                                    * size
                                    / usable
                                )
                                for value in row
                            ),
                        )
                        * size
                        * 1.2
                        + 12
                    )

                while (
                    font_size > 8
                    and sum(row_height(row, font_size) for row in rows) > h
                ):
                    font_size -= 1
                for r, row in enumerate(rows):
                    table.rows[r].height = unit(row_height(row, font_size))
                    for c, value in enumerate(row):
                        cell = table.cell(r, c)
                        cell.text = "" if value is None else str(value)
                        cell.fill.solid()
                        cell.fill.fore_color.rgb = RGBColor.from_string(
                            accent if r == 0 else palette["tile"]
                        )
                        for para in cell.text_frame.paragraphs:
                            para.font.size = Pt(font_size * 0.75)
                            para.font.color.rgb = RGBColor.from_string(
                                (palette["background"] if dark else "FFFFFF")
                                if r == 0
                                else palette["foreground"]
                            )
            elif name == "Chart":
                data = ChartData()
                data.categories = b["labels"]
                for series in b["series"]:
                    data.add_series(series["name"], series["values"])
                chart_frame = slide.shapes.add_chart(
                    {
                        "line": XL_CHART_TYPE.LINE,
                        "bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
                        "pie": XL_CHART_TYPE.DOUGHNUT,
                    }[b["type"]],
                    unit(x),
                    unit(y),
                    unit(w),
                    unit(h),
                    data,
                )
                # python-pptx annotates add_chart as Chart but returns GraphicFrame.
                chart = cast(GraphicFrame, chart_frame).chart
                chart.has_title = bool(b["title"])
                if chart.has_title:
                    chart.chart_title.text_frame.text = b["title"]
                chart.has_legend = True
                assert chart.legend is not None
                chart.legend.font.size = Pt(12)
                chart.legend.font.color.rgb = RGBColor.from_string(
                    palette["foreground"]
                )
                if chart.has_title:
                    for para in chart.chart_title.text_frame.paragraphs:
                        para.font.size = Pt(16)
                        para.font.color.rgb = RGBColor.from_string(
                            palette["foreground"]
                        )
                if b["type"] != "pie":
                    for axis in (chart.category_axis, chart.value_axis):
                        axis.tick_labels.font.size = Pt(12)
                        axis.tick_labels.font.color.rgb = RGBColor.from_string(
                            palette["foreground"]
                        )
                chart_colors = [accent, "BE83C6", "40B79A"]
                for i, series in enumerate(chart.series):
                    series.format.fill.solid()
                    series.format.fill.fore_color.rgb = RGBColor.from_string(
                        chart_colors[i % len(chart_colors)]
                    )
                    series.format.line.color.rgb = RGBColor.from_string(
                        chart_colors[i % len(chart_colors)]
                    )
                # The chart background follows the slide rather than an Office white default.
                sp = OxmlElement("c:spPr")
                fill = OxmlElement("a:solidFill")
                rgb = OxmlElement("a:srgbClr")
                rgb.set("val", palette["tile"])
                fill.append(rgb)
                sp.append(fill)
                chart._chartSpace.append(sp)
        for shape in slide.shapes:
            for effect in shape._element.xpath("./p:style/a:effectRef"):
                effect.set("idx", "0")
    output = BytesIO()
    prs.save(output)
    return output.getvalue()
