import os
import logging
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB


class DocumentLoader:
    """Document loader supporting TXT, MD, PDF (via PyMuPDF), and DOCX (via python-docx)."""

    @staticmethod
    def is_supported(filename: str) -> bool:
        ext = Path(filename).suffix.lower()
        return ext in SUPPORTED_EXTENSIONS

    @classmethod
    def load(cls, file_path: str) -> List[Tuple[str, int | None]]:
        """
        Load a document and extract text segments with page numbers.
        Returns: List of tuples: (extracted_text, page_number or None)
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Document file not found: {file_path}")

        file_size = path.stat().st_size
        if file_size > MAX_FILE_SIZE_BYTES:
            raise ValueError(f"File size ({file_size / (1024*1024):.2f}MB) exceeds maximum limit of 15MB.")

        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported document format '{ext}'. Allowed formats: {list(SUPPORTED_EXTENSIONS)}")

        try:
            if ext in (".txt", ".md"):
                return cls._load_text(path)
            elif ext == ".pdf":
                return cls._load_pdf(path)
            elif ext == ".docx":
                return cls._load_docx(path)
            else:
                raise ValueError(f"Unhandled file extension '{ext}'")
        except Exception as e:
            logger.error(f"Error loading document '{file_path}': {str(e)}", exc_info=True)
            raise e

    @staticmethod
    def _load_text(path: Path) -> List[Tuple[str, int | None]]:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read().strip()
        if not content:
            raise ValueError("Document file is empty.")
        return [(content, 1)]

    @staticmethod
    def _load_pdf(path: Path) -> List[Tuple[str, int | None]]:
        import pymupdf
        doc = pymupdf.open(str(path))
        pages = []
        try:
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                text = page.get_text().strip()
                if text:
                    pages.append((text, page_idx + 1))
        finally:
            doc.close()

        if not pages:
            raise ValueError("No extractable text found in PDF document.")
        return pages

    @staticmethod
    def _load_docx(path: Path) -> List[Tuple[str, int | None]]:
        import docx
        doc = docx.Document(str(path))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        if not paragraphs:
            raise ValueError("No extractable text found in DOCX document.")
        content = "\n\n".join(paragraphs)
        return [(content, 1)]
