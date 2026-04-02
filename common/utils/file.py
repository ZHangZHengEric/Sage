import os


def split_file_name(file_name: str) -> tuple[str, str]:
    base = os.path.basename(file_name)
    base = base.split("?")[0].split("#")[0]
    origin, ext = os.path.splitext(base)
    return origin, ext.lower()
