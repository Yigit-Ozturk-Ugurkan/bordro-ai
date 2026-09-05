"""Conservative, deterministic normalization for Turkish payroll labels."""

import unicodedata

_SEPARATOR_PUNCTUATION = str.maketrans({".": " ", ",": " ", ":": " ", ";": " "})
_COMPATIBLE_PUNCTUATION = str.maketrans({
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
    "\u2018": "'", "\u2019": "'", "\u02bc": "'",
})


def normalize_source_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).translate(_COMPATIBLE_PUNCTUATION)
    # Python's locale-independent lowercasing maps capital I incorrectly for Turkish.
    normalized = normalized.translate(str.maketrans({"I": "ı", "İ": "i"})).lower()
    normalized = normalized.translate(_SEPARATOR_PUNCTUATION)
    normalized = " ".join(normalized.split())
    return unicodedata.normalize("NFC", normalized)


__all__ = ["normalize_source_label"]
