from typing import List, Tuple


class TextChunker:
    """
    Recursive character text splitter respecting semantic boundaries
    (paragraphs, sentences, and words) while maintaining configurable overlap.
    """

    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
        separators: List[str] = None,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", ". ", "? ", "! ", "; ", " ", ""]

    def split_text(self, text: str) -> List[str]:
        """Split a string into chunks using recursive separator hierarchy."""
        return self._split(text, self.separators)

    def _split(self, text: str, separators: List[str]) -> List[str]:
        final_chunks = []
        separator = separators[-1]
        new_separators = []

        for i, sep in enumerate(separators):
            if sep == "":
                separator = ""
                break
            if sep in text:
                separator = sep
                new_separators = separators[i + 1:]
                break

        splits = text.split(separator) if separator else list(text)

        current_doc = []
        current_len = 0

        for s in splits:
            if not s:
                continue
            seg_len = len(s) + (len(separator) if current_doc else 0)

            if current_len + seg_len > self.chunk_size:
                if current_doc:
                    doc_text = separator.join(current_doc).strip()
                    if doc_text:
                        final_chunks.append(doc_text)

                    # Build overlap from recent items
                    while current_doc and current_len > self.chunk_overlap:
                        removed = current_doc.pop(0)
                        current_len -= len(removed) + len(separator)

                if len(s) > self.chunk_size and new_separators:
                    sub_chunks = self._split(s, new_separators)
                    final_chunks.extend(sub_chunks)
                    current_doc = []
                    current_len = 0
                    continue

            current_doc.append(s)
            current_len += seg_len

        if current_doc:
            doc_text = separator.join(current_doc).strip()
            if doc_text:
                final_chunks.append(doc_text)

        return final_chunks

    def chunk_document_pages(
        self,
        pages: List[Tuple[str, int | None]],
    ) -> List[Tuple[str, int | None]]:
        """
        Split multi-page document into chunks with page metadata.
        Returns: List of tuples (chunk_text, page_number)
        """
        all_chunks = []
        for page_text, page_num in pages:
            if not page_text or not page_text.strip():
                continue
            page_chunks = self.split_text(page_text)
            for c in page_chunks:
                if c.strip():
                    all_chunks.append((c.strip(), page_num))
        return all_chunks
