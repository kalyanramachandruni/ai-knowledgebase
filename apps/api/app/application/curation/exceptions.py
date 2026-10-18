from __future__ import annotations


class CurationApplicationError(Exception):
    pass


class ConfluencePageNotFound(CurationApplicationError):
    pass


class CurationRunNotFound(CurationApplicationError):
    pass


class CurationRunNotSucceeded(CurationApplicationError):
    pass
