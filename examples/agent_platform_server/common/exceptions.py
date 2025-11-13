"""
全局异常定义
"""
from fastapi import HTTPException

# ============= 自定义异常类 =============

class SageHTTPException(HTTPException):
    """自定义HTTP异常，支持更多错误信息"""
    def __init__(self, status_code: int, detail: str, error_detail: str = None):
        super().__init__(status_code=status_code, detail=detail)
        self.error_detail = error_detail
