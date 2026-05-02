"""augment_multimodal_content_list_for_llm：仅在发往 LLM 前插入图片地址说明行。"""

from sagents.utils.multimodal_image import (
    MULTIMODAL_IMAGE_ADDRESS_HINT_ZH,
    augment_multimodal_content_list_for_llm,
)


def test_augment_inserts_hint_after_image_url_standalone_md():
    content = [
        {"type": "text", "text": "hi"},
        {"type": "image_url", "image_url": {"url": "https://ex/a.jpg"}},
        {"type": "text", "text": "![a.jpg](https://ex/a.jpg)"},
    ]
    out = augment_multimodal_content_list_for_llm(content)
    assert out[0] == content[0]
    assert out[1] == content[1]
    assert out[2]["type"] == "text"
    assert out[2]["text"].startswith(MULTIMODAL_IMAGE_ADDRESS_HINT_ZH)
    assert "![a.jpg](https://ex/a.jpg)" in out[2]["text"]


def test_augment_skips_when_hint_already_present():
    prefixed = MULTIMODAL_IMAGE_ADDRESS_HINT_ZH + "![a.jpg](https://ex/a.jpg)"
    content = [
        {"type": "image_url", "image_url": {"url": "https://ex/a.jpg"}},
        {"type": "text", "text": prefixed},
    ]
    out = augment_multimodal_content_list_for_llm(content)
    assert out == content


def test_augment_skips_when_text_not_standalone_image():
    content = [
        {"type": "image_url", "image_url": {"url": "https://ex/a.jpg"}},
        {"type": "text", "text": "see ![a.jpg](https://ex/a.jpg) above"},
    ]
    out = augment_multimodal_content_list_for_llm(content)
    assert out == content
