import os


def split_file_name(file_name: str) -> tuple[str, str]:
    base = os.path.basename(file_name)
    # 先去掉可能的查询参数或哈希
    base = base.split("?")[0].split("#")[0]
    origin, ext = os.path.splitext(base)
    # 统一小写后缀
    ext = ext.lower()
    return origin, ext
