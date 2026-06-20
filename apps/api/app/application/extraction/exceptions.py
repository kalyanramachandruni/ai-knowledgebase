from __future__ import annotations


class ExtractionApplicationError(Exception):
    pass


class ConfluencePageNotFound(ExtractionApplicationError):
    pass


class ExtractionRunNotFound(ExtractionApplicationError):
    pass


class ExtractionRunNotSucceeded(ExtractionApplicationError):
    pass
