from .kdb import KdbService
from .knowledge_base import DocumentInput, DocumentService


def add_doc_build_jobs(scheduler):
    from .jobs import add_doc_build_jobs as _add_doc_build_jobs

    return _add_doc_build_jobs(scheduler)

__all__ = [
    "DocumentInput",
    "DocumentService",
    "KdbService",
    "add_doc_build_jobs",
]
