import io

from PIL import Image

from sagents.utils.multimodal_image import compress_image_to_jpeg_bytes_for_llm


def _jpeg_size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as img:
        return img.size


def test_llm_image_compression_keeps_1536_long_edge_by_default():
    img = Image.new("RGB", (3000, 1800), (240, 240, 240))

    data = compress_image_to_jpeg_bytes_for_llm(img)

    assert _jpeg_size(data) == (1536, 922)


def test_llm_image_compression_falls_back_to_fit_byte_budget():
    img = Image.effect_noise((900, 900), 100).convert("RGB")

    data = compress_image_to_jpeg_bytes_for_llm(
        img,
        target_bytes=120 * 1024,
    )

    assert len(data) <= 120 * 1024
    assert max(_jpeg_size(data)) < 900
