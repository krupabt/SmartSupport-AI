import re
import hashlib
import unicodedata


class DocumentProcessor:
    """Cleans, normalizes, and generates integrity hashes for document content."""

    @staticmethod
    def clean_text(text: str) -> str:
        """Normalize whitespace and strip unprintable characters."""
        if not text:
            return ""

        # Normalize unicode characters
        text = unicodedata.normalize("NFKC", text)

        # Replace carriage returns and excessive tabs
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)

        # Normalize multiple newlines (keep maximum 2 newlines)
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

    @staticmethod
    def compute_hash(text: str) -> str:
        """Compute SHA256 hash of cleaned text."""
        cleaned = DocumentProcessor.clean_text(text)
        return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
