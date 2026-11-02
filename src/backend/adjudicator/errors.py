"""Adjudicator failures. status_code selects retry or dead-letter."""


class AdjudicationError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
