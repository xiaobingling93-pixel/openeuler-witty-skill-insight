#!/usr/bin/env python3
"""
PDF Text Extractor - Complete Feature Set (Tasks B1.2 + B1.3 + B1.4 + B1.5 + Priority 2 & 3)

Extracts text, code blocks, and images from PDF documentation files.
Uses PyMuPDF (fitz) for fast, high-quality extraction.

Features:
    - Text and markdown extraction
    - Code block detection (font, indent, pattern)
    - Language detection with confidence scoring (19+ languages) (B1.4)
    - Syntax validation and quality scoring (B1.4)
    - Quality statistics and filtering (B1.4)
    - Image extraction to files (B1.5)
    - Image filtering by size (B1.5)
    - Page chunking and chapter detection (B1.3)
    - Code block merging across pages (B1.3)

Advanced Features (Priority 2 & 3):
    - OCR support for scanned PDFs (requires pytesseract) (Priority 2)
    - Password-protected PDF support (Priority 2)
    - Table extraction (Priority 2)
    - Parallel page processing (Priority 3)
    - Caching of expensive operations (Priority 3)

Usage:
    # Basic extraction
    python3 pdf_extractor_poc.py input.pdf
    python3 pdf_extractor_poc.py input.pdf --output output.json
    python3 pdf_extractor_poc.py input.pdf --verbose

    # Quality filtering
    python3 pdf_extractor_poc.py input.pdf --min-quality 5.0

    # Image extraction
    python3 pdf_extractor_poc.py input.pdf --extract-images
    python3 pdf_extractor_poc.py input.pdf --extract-images --image-dir images/

    # Advanced features
    python3 pdf_extractor_poc.py scanned.pdf --ocr
    python3 pdf_extractor_poc.py encrypted.pdf --password mypassword
    python3 pdf_extractor_poc.py input.pdf --extract-tables
    python3 pdf_extractor_poc.py large.pdf --parallel --workers 8

Example:
    python3 pdf_extractor_poc.py docs/manual.pdf -o output.json -v \
        --chunk-size 15 --min-quality 6.0 --extract-images \
        --extract-tables --parallel
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Import unified language detector
from .language_detector import LanguageDetector

# Check if PyMuPDF is installed
try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: PyMuPDF not installed")
    print("Install with: pip install PyMuPDF")
    sys.exit(1)

# Optional dependencies for advanced features
try:
    import pytesseract
    from PIL import Image

    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

try:
    import concurrent.futures

    CONCURRENT_AVAILABLE = True
except ImportError:
    CONCURRENT_AVAILABLE = False


class PDFExtractor:
    """Extract text and code from PDF documentation"""

    def __init__(
        self,
        pdf_path,
        verbose=False,
        chunk_size=10,
        min_quality=0.0,
        extract_images=False,
        image_dir=None,
        min_image_size=100,
        use_ocr=False,
        password=None,
        extract_tables=False,
        parallel=False,
        max_workers=None,
        use_cache=True,
    ):
        self.pdf_path = pdf_path
        self.verbose = verbose
        self.chunk_size = chunk_size  # Pages per chunk (0 = no chunking)
        self.min_quality = min_quality  # Minimum quality score (0-10)
        self.extract_images = extract_images  # Extract images to files (NEW in B1.5)
        self.image_dir = image_dir  # Directory to save images (NEW in B1.5)
        self.min_image_size = min_image_size  # Minimum image dimension (NEW in B1.5)

        # Advanced features (Priority 2 & 3)
        self.use_ocr = use_ocr  # OCR for scanned PDFs (Priority 2)
        self.password = password  # Password for encrypted PDFs (Priority 2)
        self.extract_tables = extract_tables  # Extract tables (Priority 2)
        self.parallel = parallel  # Parallel processing (Priority 3)
        self.max_workers = max_workers or os.cpu_count()  # Worker threads (Priority 3)
        self.use_cache = use_cache  # Cache expensive operations (Priority 3)

        self.doc = None
        self.pages = []
        self.chapters = []  # Detected chapters/sections
        self.extracted_images = []  # List of extracted image info (NEW in B1.5)
        self._cache = {}  # Cache for expensive operations (Priority 3)

        # Language detection
        self.language_detector = LanguageDetector(min_confidence=0.15)

    def log(self, message):
        """Print message if verbose mode enabled"""
        if self.verbose:
            print(message)

    def extract_text_with_ocr(self, page):
        """
        Extract text from scanned PDF page using OCR (Priority 2).
        Falls back to regular text extraction if OCR is not available.

        Args:
            page: PyMuPDF page object

        Returns:
            str: Extracted text
        """
        # Try regular text extraction first
        text = page.get_text("text").strip()

        # If page has very little text, it might be scanned
        if len(text) < 50 and self.use_ocr:
            if not TESSERACT_AVAILABLE:
                self.log("⚠️  OCR requested but pytesseract not installed")
                self.log("   Install with: pip install pytesseract Pillow")
                return text

            try:
                # Render page as image
                pix = page.get_pixmap()
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                # Run OCR
                ocr_text = pytesseract.image_to_string(img)
                self.log(f"   OCR extracted {len(ocr_text)} chars (was {len(text)})")
                return ocr_text if len(ocr_text) > len(text) else text

            except Exception as e:
                self.log(f"   OCR failed: {e}")
                return text

        return text

    def extract_tables_from_page(self, page):
        """
        Extract tables from PDF page (Priority 2).
        Uses PyMuPDF's table detection.

        Args:
            page: PyMuPDF page object

        Returns:
            list: List of extracted tables as dicts
        """
        if not self.extract_tables:
            return []

        tables = []
        try:
            # PyMuPDF table extraction
            tabs = page.find_tables()
            for idx, tab in enumerate(tabs.tables):
                table_data = {
                    "table_index": idx,
                    "rows": tab.extract(),
                    "bbox": tab.bbox,
                    "row_count": len(tab.extract()),
                    "col_count": len(tab.extract()[0]) if tab.extract() else 0,
                }
                tables.append(table_data)
                self.log(
                    f"   Found table {idx}: {table_data['row_count']}x{table_data['col_count']}"
                )

        except Exception as e:
            self.log(f"   Table extraction failed: {e}")

        return tables

    def get_cached(self, key):
        """
        Get cached value (Priority 3).

        Args:
            key: Cache key

        Returns:
            Cached value or None
        """
        if not self.use_cache:
            return None
        return self._cache.get(key)

    def set_cached(self, key, value):
        """
        Set cached value (Priority 3).

        Args:
            key: Cache key
            value: Value to cache
        """
        if self.use_cache:
            self._cache[key] = value

    def detect_language_from_code(self, code):
        """
        Detect programming language from code content using patterns.
        Enhanced in B1.4 with confidence scoring.

        UPDATED: Now uses shared LanguageDetector with 20+ languages

        Returns (language, confidence) tuple
        """
        return self.language_detector.detect_from_code(code)

    def validate_code_syntax(self, code, language):
        """
        Validate code syntax (basic checks).
        Enhanced in B1.4 with syntax validation.

        Returns (is_valid, issues) tuple
        """
        issues = []

        # Common syntax checks
        if not code.strip():
            return False, ["Empty code block"]

        # Language-specific validation
        if language == "python":
            # Check indentation consistency
            lines = code.split("\n")
            indent_chars = set()
            for line in lines:
                if line.startswith(" "):
                    indent_chars.add("space")
                elif line.startswith("\t"):
                    indent_chars.add("tab")

            if len(indent_chars) > 1:
                issues.append("Mixed tabs and spaces")

            # Check for unclosed brackets/parens
            open_count = code.count("(") + code.count("[") + code.count("{")
            close_count = code.count(")") + code.count("]") + code.count("}")
            if abs(open_count - close_count) > 2:  # Allow small mismatch
                issues.append("Unbalanced brackets")

        elif language in ["javascript", "java", "cpp", "c", "csharp", "go"]:
            # Check for balanced braces
            open_braces = code.count("{")
            close_braces = code.count("}")
            if abs(open_braces - close_braces) > 1:
                issues.append("Unbalanced braces")

        elif language == "json":
            # Try to parse JSON
            try:
                json.loads(code)
            except (json.JSONDecodeError, ValueError) as e:
                issues.append(f"Invalid JSON syntax: {str(e)[:50]}")

        # General checks
        # Check if code looks like natural language (too many common words)
        common_words = ["the", "and", "for", "with", "this", "that", "have", "from"]
        word_count = sum(1 for word in common_words if word in code.lower())
        if word_count > 5 and len(code.split()) < 50:
            issues.append("May be natural language, not code")

        # Check code/comment ratio
        comment_lines = sum(
            1
            for line in code.split("\n")
            if line.strip().startswith(("#", "//", "/*", "*", "--"))
        )
        total_lines = len([l for l in code.split("\n") if l.strip()])
        if total_lines > 0 and comment_lines / total_lines > 0.7:
            issues.append("Mostly comments")

        return len(issues) == 0, issues

    def score_code_quality(self, code, language, confidence):
        """
        Score the quality/usefulness of detected code block.
        New in B1.4.

        Returns quality score (0-10)
        """
        score = 5.0  # Start with neutral score

        # Factor 1: Language detection confidence
        score += confidence * 2.0

        # Factor 2: Code length (not too short, not too long)
        code_length = len(code.strip())
        if 20 <= code_length <= 500:
            score += 1.0
        elif 500 < code_length <= 2000:
            score += 0.5
        elif code_length < 10:
            score -= 2.0

        # Factor 3: Number of lines
        lines = [l for l in code.split("\n") if l.strip()]
        if 2 <= len(lines) <= 50:
            score += 1.0
        elif len(lines) > 100:
            score -= 1.0

        # Factor 4: Has function/class definitions
        if re.search(r"\b(def|function|class|func|fn|public class)\b", code):
            score += 1.5

        # Factor 5: Has meaningful variable names (not just x, y, i)
        meaningful_vars = re.findall(r"\b[a-z_][a-z0-9_]{3,}\b", code.lower())
        if len(meaningful_vars) >= 2:
            score += 1.0

        # Factor 6: Syntax validation
        is_valid, issues = self.validate_code_syntax(code, language)
        if is_valid:
            score += 1.0
        else:
            score -= len(issues) * 0.5

        # Clamp score to 0-10 range
        return max(0, min(10, score))

    def detect_code_blocks_by_font(self, page):
        """
        Detect code blocks by analyzing font properties.
        Monospace fonts typically indicate code.

        Returns list of detected code blocks with metadata.
        """
        code_blocks = []
        blocks = page.get_text("dict")["blocks"]

        monospace_fonts = ["courier", "mono", "consolas", "menlo", "monaco", "dejavu"]

        current_code = []
        current_font = None

        for block in blocks:
            if "lines" not in block:
                continue

            for line in block["lines"]:
                for span in line["spans"]:
                    font = span["font"].lower()
                    text = span["text"]

                    # Check if font is monospace
                    is_monospace = any(mf in font for mf in monospace_fonts)

                    if is_monospace:
                        # Accumulate code text
                        current_code.append(text)
                        current_font = span["font"]
                    else:
                        # End of code block
                        if current_code:
                            code_text = "".join(current_code).strip()
                            if len(code_text) > 10:  # Minimum code length
                                lang, confidence = self.detect_language_from_code(
                                    code_text
                                )
                                quality = self.score_code_quality(
                                    code_text, lang, confidence
                                )
                                is_valid, issues = self.validate_code_syntax(
                                    code_text, lang
                                )

                                code_blocks.append(
                                    {
                                        "code": code_text,
                                        "language": lang,
                                        "confidence": confidence,
                                        "quality_score": quality,
                                        "is_valid": is_valid,
                                        "validation_issues": (
                                            issues if not is_valid else []
                                        ),
                                        "font": current_font,
                                        "detection_method": "font",
                                    }
                                )
                            current_code = []
                            current_font = None

        # Handle final code block
        if current_code:
            code_text = "".join(current_code).strip()
            if len(code_text) > 10:
                lang, confidence = self.detect_language_from_code(code_text)
                quality = self.score_code_quality(code_text, lang, confidence)
                is_valid, issues = self.validate_code_syntax(code_text, lang)

                code_blocks.append(
                    {
                        "code": code_text,
                        "language": lang,
                        "confidence": confidence,
                        "quality_score": quality,
                        "is_valid": is_valid,
                        "validation_issues": issues if not is_valid else [],
                        "font": current_font,
                        "detection_method": "font",
                    }
                )

        return code_blocks

    def detect_code_blocks_by_indent(self, text):
        """
        Detect code blocks by indentation patterns.
        Code often has consistent indentation.

        Returns list of detected code blocks.
        """
        code_blocks = []
        lines = text.split("\n")
        current_block = []
        indent_pattern = None

        for line in lines:
            # Check for indentation (4 spaces or tab)
            if line.startswith("    ") or line.startswith("\t"):
                # Start or continue code block
                if not indent_pattern:
                    indent_pattern = line[:4] if line.startswith("    ") else "\t"
                current_block.append(line)
            else:
                # End of code block
                if current_block and len(current_block) >= 2:  # At least 2 lines
                    code_text = "\n".join(current_block).strip()
                    if len(code_text) > 20:  # Minimum code length
                        lang, confidence = self.detect_language_from_code(code_text)
                        quality = self.score_code_quality(code_text, lang, confidence)
                        is_valid, issues = self.validate_code_syntax(code_text, lang)

                        code_blocks.append(
                            {
                                "code": code_text,
                                "language": lang,
                                "confidence": confidence,
                                "quality_score": quality,
                                "is_valid": is_valid,
                                "validation_issues": issues if not is_valid else [],
                                "detection_method": "indent",
                            }
                        )
                current_block = []
                indent_pattern = None

        # Handle final block
        if current_block and len(current_block) >= 2:
            code_text = "\n".join(current_block).strip()
            if len(code_text) > 20:
                lang, confidence = self.detect_language_from_code(code_text)
                quality = self.score_code_quality(code_text, lang, confidence)
                is_valid, issues = self.validate_code_syntax(code_text, lang)

                code_blocks.append(
                    {
                        "code": code_text,
                        "language": lang,
                        "confidence": confidence,
                        "quality_score": quality,
                        "is_valid": is_valid,
                        "validation_issues": issues if not is_valid else [],
                        "detection_method": "indent",
                    }
                )

        return code_blocks

    def detect_code_blocks_by_pattern(self, text):
        """
        Detect code blocks by common code patterns (keywords, syntax).

        IMPROVED: Uses indentation-based detection to capture complete code blocks
        including multi-method classes and full function bodies.

        Also detects "continuation" blocks - indented code at start of text
        that is likely a continuation from previous page.

        Returns list of detected code snippets.
        """
        code_blocks = []
        lines = text.split("\n")
        processed_lines = set()  # Track which lines we've already included in blocks

        # Check if text starts with indented code (continuation from previous page)
        # Skip any leading non-Python content first
        first_code_line_idx = 0
        for idx, line in enumerate(lines):
            stripped = line.lstrip()

            # Skip empty lines
            if not stripped:
                continue

            # Skip section headers (e.g., "1. Title", "1.1 Subtitle", "1.1.1 Sub-subtitle")
            if re.match(r"^\d+(?:\.\d+)*\.?\s+", stripped):
                # Check if it has Chinese characters or looks like a title
                if re.search(r"[\u4e00-\u9fff]", stripped) or stripped[0].isupper():
                    first_code_line_idx = idx + 1
                    continue

            # Skip markdown headers
            if (
                stripped
                and re.match(r"^[\u4e00-\u9fff\s]+$", stripped)
                and len(stripped) < 50
            ):
                first_code_line_idx = idx + 1
                continue

            # Found first potential code line
            first_code_line_idx = idx
            break

        # Now check if the first code line is indented (continuation)
        if first_code_line_idx < len(lines):
            first_code_line = lines[first_code_line_idx]
            if first_code_line and first_code_line[0] in (" ", "\t"):
                # Find all indented lines starting from first_code_line_idx
                continuation_lines = []
                for i in range(first_code_line_idx, len(lines)):
                    line = lines[i]
                    stripped = line.lstrip()

                    # Stop at first top-level definition or non-code content
                    if line and line[0] not in (" ", "\t", "\xa0"):
                        # Check if it's a new top-level definition
                        if stripped.startswith(("class ", "def ", "function ", "#!")):
                            break
                        # Check if it's non-Python content
                        if re.match(
                            r"^\d+\.(?:\d+\.?)?\s+[\u4e00-\u9fff]", stripped
                        ):  # Section header
                            break
                        if stripped.startswith(
                            ("kubectl ", "#!/bin/bash", "#!/bin/sh")
                        ):  # Bash
                            break

                    # Include this line in continuation
                    continuation_lines.append(line)
                    processed_lines.add(i)

                # If we found continuation lines, create a continuation block
                if (
                    continuation_lines and len(continuation_lines) >= 3
                ):  # At least 3 lines
                    code_text = "\n".join(continuation_lines)
                    if len(code_text.strip()) > 50:  # Minimum content
                        lang, confidence = self.detect_language_from_code(code_text)
                        quality = self.score_code_quality(code_text, lang, confidence)
                        is_valid, issues = self.validate_code_syntax(code_text, lang)

                        code_blocks.append(
                            {
                                "code": code_text,
                                "language": lang,
                                "confidence": confidence,
                                "quality_score": quality,
                                "is_valid": is_valid,
                                "validation_issues": issues if not is_valid else [],
                                "detection_method": "pattern",
                                "pattern_type": "continuation",  # Mark as continuation
                                "is_continuation": True,  # Flag for merge logic
                            }
                        )

        i = 0
        while i < len(lines):
            # Skip if this line was already processed
            if i in processed_lines:
                i += 1
                continue

            line = lines[i]
            stripped = line.lstrip()

            # Detect code block starting markers
            is_class_start = stripped.startswith("class ")
            is_function_start = (
                stripped.startswith("def ")
                or stripped.startswith("function ")
                or stripped.startswith("func ")
                or stripped.startswith("async def ")
                or (
                    stripped.startswith(("public ", "private ", "protected "))
                    and (
                        " def " in stripped
                        or " function " in stripped
                        or " func " in stripped
                    )
                )
            )
            is_import_start = (
                stripped.startswith("import ")
                or stripped.startswith("from ")
                or stripped.startswith("require ")
                or stripped.startswith("use ")
                or stripped.startswith("include ")
            )

            if is_class_start or is_function_start:
                # Look backwards for import statements to include with this code block
                import_lines = []
                k = i - 1
                while k >= 0:
                    prev_line = lines[k]
                    prev_stripped = prev_line.lstrip()

                    # Stop if we hit another class/function or processed line
                    if k in processed_lines:
                        break
                    if prev_stripped.startswith(
                        ("class ", "def ", "function ", "func ", "async def ")
                    ):
                        break

                    # Collect import statements
                    if (
                        prev_stripped.startswith("import ")
                        or prev_stripped.startswith("from ")
                        or prev_stripped.startswith("require ")
                        or prev_stripped.startswith("use ")
                        or prev_stripped.startswith("include ")
                    ):
                        import_lines.insert(0, prev_line)
                        processed_lines.add(k)
                    # Also include empty lines between imports
                    elif not prev_stripped and import_lines:
                        import_lines.insert(0, prev_line)
                        processed_lines.add(k)
                    # Stop if we hit non-import, non-empty line
                    elif prev_stripped:
                        break

                    k -= 1

                # Extract complete code block based on indentation
                base_indent = len(line) - len(stripped)
                code_lines = import_lines + [line]  # Prepend imports
                processed_lines.add(i)
                j = i + 1

                # Collect all lines that belong to this block
                while j < len(lines):
                    next_line = lines[j]
                    next_stripped = next_line.lstrip()
                    next_indent = len(next_line) - len(next_stripped)

                    # Empty line or comment: continue
                    if not next_stripped or next_stripped.startswith("#"):
                        code_lines.append(next_line)
                        processed_lines.add(j)
                        j += 1
                        continue

                    # For classes: include all methods (deeper indentation)
                    if is_class_start:
                        # Include all content with deeper indentation than class definition
                        if next_indent > base_indent:
                            code_lines.append(next_line)
                            processed_lines.add(j)
                            j += 1
                            continue
                        # Also include same-level 'def' if using standard indentation
                        elif next_indent == base_indent and next_stripped.startswith(
                            "@"
                        ):
                            # Decorator at class level
                            code_lines.append(next_line)
                            processed_lines.add(j)
                            j += 1
                            continue
                        else:
                            # Less or equal indentation, not a decorator: end of class
                            break

                    # For functions: include all content with deeper indentation
                    if is_function_start:
                        if next_indent > base_indent:
                            code_lines.append(next_line)
                            processed_lines.add(j)
                            j += 1
                            continue
                        else:
                            # Less or equal indentation: end of function
                            break

                    j += 1

                # Combine code
                code_text = "\n".join(code_lines)

                # Filter: minimum length and quality checks
                if len(code_text.strip()) > 30:  # At least 30 characters
                    lang, confidence = self.detect_language_from_code(code_text)
                    quality = self.score_code_quality(code_text, lang, confidence)
                    is_valid, issues = self.validate_code_syntax(code_text, lang)

                    code_blocks.append(
                        {
                            "code": code_text,
                            "language": lang,
                            "confidence": confidence,
                            "quality_score": quality,
                            "is_valid": is_valid,
                            "validation_issues": issues if not is_valid else [],
                            "detection_method": "pattern",
                            "pattern_type": "class" if is_class_start else "function",
                        }
                    )

                i = j  # Skip to end of block
            else:
                i += 1

        return code_blocks

    def detect_headings_by_font(self, page):
        """
        通过字体属性检测标题（字体大小、粗体、位置）

        Returns:
            list: 检测到的标题列表
        """
        headings = []
        blocks = page.get_text("dict")["blocks"]

        # 分析页面所有文本块，统计字体大小分布
        font_sizes = []
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    font_sizes.append(span["size"])

        if not font_sizes:
            return []

        # 计算平均字体大小和标准差
        avg_size = sum(font_sizes) / len(font_sizes)
        std_dev = (
            sum((s - avg_size) ** 2 for s in font_sizes) / len(font_sizes)
        ) ** 0.5

        # 定义标题阈值
        # H1: 字体大小 > 平均 + 1.5*标准差
        # H2: 字体大小 > 平均 + 1.0*标准差
        # H3: 字体大小 > 平均 + 0.5*标准差
        h1_threshold = avg_size + 1.5 * std_dev
        h2_threshold = avg_size + 1.0 * std_dev
        h3_threshold = avg_size + 0.5 * std_dev

        for block in blocks:
            if "lines" not in block:
                continue

            for line in block["lines"]:
                line_text = ""
                line_size = 0
                is_bold = False

                for span in line["spans"]:
                    line_text += span["text"]
                    line_size = max(line_size, span["size"])
                    # 检查是否粗体
                    font_name = span["font"].lower()
                    if "bold" in font_name or "black" in font_name:
                        is_bold = True

                line_text = line_text.strip()

                # 跳过空行和过长文本（标题通常较短）
                if not line_text or len(line_text) > 200:
                    continue

                # 排除 shebang 和代码相关内容
                if line_text.startswith("#!"):
                    continue
                if line_text.startswith(('"""', "'''", "/*", "*/", "//")):
                    continue
                if line_text.startswith(
                    (
                        "import ",
                        "from ",
                        "def ",
                        "class ",
                        "function ",
                        "var ",
                        "const ",
                        "let ",
                    )
                ):
                    continue

                # 确定标题级别
                level = None
                if line_size >= h1_threshold or (
                    line_size >= avg_size * 1.3 and is_bold
                ):
                    level = "h1"
                elif line_size >= h2_threshold or (
                    line_size >= avg_size * 1.15 and is_bold
                ):
                    level = "h2"
                elif line_size >= h3_threshold:
                    level = "h3"

                if level:
                    headings.append(
                        {
                            "level": level,
                            "text": line_text,
                            "font_size": line_size,
                            "is_bold": is_bold,
                            "detection_method": "font_analysis",
                        }
                    )

        return headings

    def detect_headings_by_pattern(self, text):
        """
        通过文本模式检测标题（编号、大写、特定格式）

        Returns:
            list: 检测到的标题列表
        """
        headings = []
        lines = text.split("\n")

        # 常见标题模式
        patterns = [
            # "1. Introduction", "1.1 Overview"
            (r"^(\d+\.(?:\d+\.)*)\s+([A-Z].*)", "numbered"),
            # "Chapter 1: Getting Started"
            (r"^(Chapter|Section|Part)\s+(\d+)[:\s]+(.+)", "chapter"),
            # "INTRODUCTION" (全大写)
            (r"^([A-Z][A-Z\s]{5,})$", "uppercase"),
            # "Introduction" (首字母大写，短行)
            (r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,4})$", "title_case"),
        ]

        for i, line in enumerate(lines):
            line = line.strip()
            if not line or len(line) > 150:
                continue

            # 排除 shebang 和代码相关内容
            if line.startswith("#!"):
                continue
            if line.startswith(
                (
                    '"""',
                    "'''",
                    "/*",
                    "*/",
                    "//",
                    "#",
                    "import ",
                    "from ",
                    "def ",
                    "class ",
                )
            ):
                continue

            for pattern, pattern_type in patterns:
                match = re.match(pattern, line)
                if match:
                    # 确定级别
                    if pattern_type == "numbered":
                        # 根据编号深度确定级别
                        number = match.group(1)
                        depth = number.count(".")
                        level = f"h{min(depth + 1, 6)}"
                        text = match.group(2)
                    elif pattern_type == "chapter":
                        level = "h1"
                        text = match.group(3)
                    elif pattern_type == "uppercase":
                        level = "h2"
                        text = match.group(1).title()  # 转为标题格式
                    elif pattern_type == "title_case":
                        # 检查下一行是否为正文（长文本）
                        if i + 1 < len(lines) and len(lines[i + 1].strip()) > 50:
                            level = "h3"
                            text = match.group(1)
                        else:
                            continue
                    else:
                        continue

                    headings.append(
                        {
                            "level": level,
                            "text": text,
                            "pattern_type": pattern_type,
                            "detection_method": "pattern_analysis",
                        }
                    )
                    break  # 匹配成功，跳出pattern循环

        return headings

    def detect_chapter_start(self, page_data):
        """
        Detect if a page starts a new chapter/section.

        Returns (is_chapter_start, chapter_title) tuple.
        """
        headings = page_data.get("headings", [])

        # Check for h1 or h2 at start of page
        if headings:
            first_heading = headings[0]
            title = first_heading["text"]

            # 额外验证：排除一些误识别的情况
            # 排除过短的标题（可能是图示）
            if len(title.strip()) < 5 or title.startswith(("图", "表", "公式")):
                return False, None

            # 排除包含 binbash 或 usrbin 的标题（可能是 shebang 被误识别为 heading）
            if "/bin/bash" in title.lower() or "/usr/bin/env" in title.lower():
                return False, None

            # 排除纯数字或特殊字符
            if re.match(r"^[\d\.\s\-_]+$", title):
                return False, None

            # 跳过字体比较小的标题，一般标题字体大于20
            if "font_size" in first_heading and first_heading["font_size"] < 18:
                return False, None

            # 跳过类似数字1.1等小标题
            if re.match(r"^\d+\.\d+(?:\s|$)", title.strip()):
                return False, None

            # H1 headings are strong indicators of chapters
            # if first_heading['level'] in ['h1', 'h2']:
            if first_heading["level"] in ["h1"]:
                return True, first_heading["text"]

        # Check for specific chapter markers in text
        text = page_data.get("text", "")
        first_line = text.split("\n")[0] if text else ""

        chapter_patterns = [
            r"^Chapter\s+\d+",
            r"^Part\s+\d+",
            r"^Section\s+\d+",
            r"^\d+\.\s+[A-Z]",  # "1. Introduction"
        ]

        for pattern in chapter_patterns:
            if re.match(pattern, first_line, re.IGNORECASE):
                return True, first_line.strip()

        return False, None

    def merge_continued_code_blocks(self, pages):
        """
        Merge code blocks that are split across pages.

        Detects when a code block at the end of one page continues
        on the next page (possibly across empty pages).
        """
        for i in range(len(pages) - 1):
            current_page = pages[i]

            # Check if current page has code blocks
            if not current_page["code_samples"]:
                continue

            # Get last code block of current page
            last_code = current_page["code_samples"][-1]

            # Look ahead to find continuation blocks (possibly across empty pages)
            j = i + 1
            while j < len(pages):
                next_page = pages[j]

                # If next page has code blocks, check if first one is a continuation
                if next_page["code_samples"]:
                    first_next_code = next_page["code_samples"][0]

                    # Check if this is a continuation block
                    is_continuation = first_next_code.get("is_continuation", False)
                    same_language = last_code["language"] == first_next_code["language"]

                    # DON'T merge if next block starts with new script indicators
                    first_next_line = first_next_code["code"].lstrip().split("\n")[0]
                    is_new_script = (
                        first_next_line.startswith("#!")  # Shebang
                        or first_next_line.startswith("import ")  # Import statement
                        or first_next_line.startswith("from ")  # Import statement
                        or first_next_line.startswith("class ")  # New class definition
                        or first_next_line.startswith('"""')  # Module docstring
                        or first_next_line.startswith("'''")  # Module docstring
                    )

                    # Merge if it's a continuation OR if it looks incomplete
                    should_merge = False
                    if is_continuation and not is_new_script:
                        # For continuation blocks, ignore language mismatch (may be misdetected)
                        should_merge = True
                        self.log(f"  Merging continuation block from page {j+1}")
                    elif same_language and not is_new_script:
                        # Check if last code block looks incomplete
                        last_code_text = last_code["code"].rstrip()
                        continuation_indicators = [
                            not last_code_text.endswith("}"),
                            not last_code_text.endswith(";"),
                            last_code_text.endswith(","),
                            last_code_text.endswith("\\"),
                        ]
                        if any(continuation_indicators):
                            should_merge = True

                    if should_merge:
                        # Merge the code blocks
                        merged_code = last_code["code"] + "\n" + first_next_code["code"]
                        last_code["code"] = merged_code
                        last_code["merged_from_next_page"] = True

                        # Remove the first code block from next page
                        next_page["code_samples"].pop(0)
                        next_page["code_blocks_count"] -= 1

                        self.log(f"  Merged code block from page {i+1} to {j+1}")

                        # Continue looking for more continuation blocks
                        j += 1
                        continue
                    else:
                        # Not a continuation, stop looking
                        break

                # If next page has no code blocks, skip it and continue looking
                # But don't look too far ahead (max 5 pages total)
                if j - i >= 5:
                    break
                j += 1

        return pages

    def create_chunks(self, pages):
        """
        Create chunks of pages for better organization.

        Returns array of chunks, each containing:
        - chunk_number
        - start_page, end_page
        - pages (array)
        - chapter_title (if detected)
        """
        if self.chunk_size == 0:
            # No chunking - return all pages as one chunk
            return [
                {
                    "chunk_number": 1,
                    "start_page": 1,
                    "end_page": len(pages),
                    "pages": pages,
                    "chapter_title": None,
                }
            ]

        chunks = []
        current_chunk = []
        chunk_start = 0
        current_chapter = None

        for i, page in enumerate(pages):
            # Check if this page starts a new chapter
            is_chapter, chapter_title = self.detect_chapter_start(page)

            if is_chapter and current_chunk:
                # Save current chunk before starting new one
                chunks.append(
                    {
                        "chunk_number": len(chunks) + 1,
                        "start_page": chunk_start + 1,
                        "end_page": i,
                        "pages": current_chunk,
                        "chapter_title": current_chapter,
                    }
                )
                current_chunk = []
                chunk_start = i
                current_chapter = chapter_title

            if not current_chapter and is_chapter:
                current_chapter = chapter_title

            current_chunk.append(page)

            # Check if chunk size reached (but don't break chapters)
            if not is_chapter and len(current_chunk) >= self.chunk_size:
                chunks.append(
                    {
                        "chunk_number": len(chunks) + 1,
                        "start_page": chunk_start + 1,
                        "end_page": i + 1,
                        "pages": current_chunk,
                        "chapter_title": current_chapter,
                    }
                )
                current_chunk = []
                chunk_start = i + 1
                current_chapter = None

        # Add remaining pages as final chunk
        if current_chunk:
            chunks.append(
                {
                    "chunk_number": len(chunks) + 1,
                    "start_page": chunk_start + 1,
                    "end_page": len(pages),
                    "pages": current_chunk,
                    "chapter_title": current_chapter,
                }
            )

        return chunks

    def extract_images_from_page(self, page, page_num):
        """
        Extract images from a PDF page and save to disk (NEW in B1.5).

        Returns list of extracted image metadata.
        """
        if not self.extract_images:
            # Just count images, don't extract
            return []

        extracted = []
        image_list = page.get_images()

        for img_index, img in enumerate(image_list):
            try:
                xref = img[0]  # Image XREF number
                base_image = self.doc.extract_image(xref)

                if not base_image:
                    continue

                image_bytes = base_image["image"]
                image_ext = base_image["ext"]  # png, jpeg, etc.
                width = base_image.get("width", 0)
                height = base_image.get("height", 0)

                # Filter out small images (icons, bullets, etc.)
                if width < self.min_image_size or height < self.min_image_size:
                    self.log(f"    Skipping small image: {width}x{height}")
                    continue

                # Generate filename
                pdf_basename = Path(self.pdf_path).stem
                image_filename = (
                    f"{pdf_basename}_page{page_num+1}_img{img_index+1}.{image_ext}"
                )

                # Save image
                image_path = Path(self.image_dir) / image_filename
                image_path.parent.mkdir(parents=True, exist_ok=True)

                with open(image_path, "wb") as f:
                    f.write(image_bytes)

                # Store metadata
                image_info = {
                    "filename": image_filename,
                    "path": str(image_path),
                    "page_number": page_num + 1,
                    "width": width,
                    "height": height,
                    "format": image_ext,
                    "size_bytes": len(image_bytes),
                    "xref": xref,
                }

                extracted.append(image_info)
                self.extracted_images.append(image_info)
                self.log(f"    Extracted image: {image_filename} ({width}x{height})")

            except Exception as e:
                self.log(f"    Error extracting image {img_index}: {e}")
                continue

        return extracted

    def extract_page(self, page_num):
        """
        Extract content from a single PDF page.

        Returns dict with page content, code blocks, and metadata.
        """
        # Check cache first (Priority 3)
        cache_key = f"page_{page_num}"
        cached = self.get_cached(cache_key)
        if cached is not None:
            self.log(f"  Page {page_num + 1}: Using cached data")
            return cached

        page = self.doc.load_page(page_num)

        # Extract plain text (with OCR if enabled - Priority 2)
        if self.use_ocr:
            text = self.extract_text_with_ocr(page)
        else:
            text = page.get_text("text")

        # Extract markdown (better structure preservation)
        # markdown = page.get_text("markdown")
        try:
            markdown = page.get_text("markdown")
        except (AssertionError, ValueError) as e:
            from markdownify import markdownify

            # Fallback to text format if markdown is not supported
            self.log(f"Cannot get markdown context, converted from html instead: {e}")
            html_content = page.get_text("html")
            markdown = markdownify(html_content)

        # Extract tables (Priority 2)
        tables = self.extract_tables_from_page(page)

        # Get page images (for diagrams)
        images = page.get_images()

        # Extract images to files (NEW in B1.5)
        extracted_images = self.extract_images_from_page(page, page_num)

        # Detect code blocks using multiple methods
        font_code_blocks = self.detect_code_blocks_by_font(page)
        indent_code_blocks = self.detect_code_blocks_by_indent(text)
        pattern_code_blocks = self.detect_code_blocks_by_pattern(text)

        # Merge and deduplicate code blocks
        all_code_blocks = font_code_blocks + indent_code_blocks + pattern_code_blocks

        # Simple deduplication by code content
        unique_code = {}
        for block in all_code_blocks:
            code_hash = hash(block["code"])
            if code_hash not in unique_code:
                unique_code[code_hash] = block
            else:
                # Keep the one with higher quality score
                if block["quality_score"] > unique_code[code_hash]["quality_score"]:
                    unique_code[code_hash] = block

        code_samples = list(unique_code.values())

        # Filter by minimum quality (NEW in B1.4)
        if self.min_quality > 0:
            code_samples_before = len(code_samples)
            code_samples = [
                c for c in code_samples if c["quality_score"] >= self.min_quality
            ]
            filtered_count = code_samples_before - len(code_samples)
            if filtered_count > 0:
                self.log(
                    f"  Filtered out {filtered_count} low-quality code blocks (min_quality={self.min_quality})"
                )

        # Sort by quality score (highest first)
        code_samples.sort(key=lambda x: x["quality_score"], reverse=True)

        # 方法1：从Markdown提取
        headings_from_markdown = []
        for line in markdown.split("\n"):
            if line.startswith("#"):
                # 计算 # 的数量（标题级别）
                level = len(line) - len(line.lstrip("#"))
                # 检查 # 后面是否有空格（Markdown规范要求）
                if level < len(line) and line[level] == " ":
                    text = line[level:].strip()
                    if text:
                        headings_from_markdown.append(
                            {
                                "level": f"h{level}",
                                "text": text,
                                "detection_method": "markdown",
                            }
                        )

        # 方法2：基于字体属性检测
        headings_from_font = self.detect_headings_by_font(page)

        # 方法3：基于文本模式检测
        headings_from_pattern = self.detect_headings_by_pattern(text)

        # 合并并去重
        all_headings = (
            headings_from_markdown + headings_from_font + headings_from_pattern
        )

        # 去重：优先保留markdown方法，然后是font，最后是pattern
        unique_headings = {}
        for heading in all_headings:
            key = heading["text"].lower().strip()
            if key not in unique_headings:
                unique_headings[key] = heading
            else:
                # 优先级：markdown > font > pattern
                priority = {"markdown": 3, "font_analysis": 2, "pattern_analysis": 1}
                current_priority = priority.get(
                    unique_headings[key]["detection_method"], 0
                )
                new_priority = priority.get(heading["detection_method"], 0)
                if new_priority > current_priority:
                    unique_headings[key] = heading

        headings = list(unique_headings.values())
        # 按页面出现顺序排序（简化版，实际可以通过位置信息排序）
        headings.sort(key=lambda h: h["text"])

        page_data = {
            "page_number": page_num + 1,  # 1-indexed for humans
            "text": text.strip(),
            "markdown": markdown.strip(),
            "headings": headings,
            "code_samples": code_samples,
            "images_count": len(images),
            "extracted_images": extracted_images,  # NEW in B1.5
            "tables": tables,  # NEW in Priority 2
            "char_count": len(text),
            "code_blocks_count": len(code_samples),
            "tables_count": len(tables),  # NEW in Priority 2
        }

        # Cache the result (Priority 3)
        self.set_cached(cache_key, page_data)

        self.log(
            f"  Page {page_num + 1}: {len(text)} chars, {len(code_samples)} code blocks, {len(headings)} headings, {len(extracted_images)} images, {len(tables)} tables"
        )

        return page_data

    def extract_all(self):
        """
        Extract content from all pages of the PDF.
        Enhanced with password support and parallel processing.

        Returns dict with metadata and pages array.
        """
        print(f"\n📄 Extracting from: {self.pdf_path}")

        # Open PDF (with password support - Priority 2)
        try:
            self.doc = fitz.open(self.pdf_path)

            # Handle encrypted PDFs (Priority 2)
            if self.doc.is_encrypted:
                if self.password:
                    print(f"   🔐 PDF is encrypted, trying password...")
                    if self.doc.authenticate(self.password):
                        print(f"   ✅ Password accepted")
                    else:
                        print(f"   ❌ Invalid password")
                        return None
                else:
                    print(f"   ❌ PDF is encrypted but no password provided")
                    print(f"   Use --password option to provide password")
                    return None

        except Exception as e:
            print(f"❌ Error opening PDF: {e}")
            return None

        print(f"   Pages: {len(self.doc)}")
        print(f"   Metadata: {self.doc.metadata}")

        # Set up image directory (NEW in B1.5)
        if self.extract_images and not self.image_dir:
            pdf_basename = Path(self.pdf_path).stem
            self.image_dir = f"output/{pdf_basename}_images"
            print(f"   Image directory: {self.image_dir}")

        # Show feature status
        if self.use_ocr:
            status = (
                "✅ enabled"
                if TESSERACT_AVAILABLE
                else "⚠️  not available (install pytesseract)"
            )
            print(f"   OCR: {status}")
        if self.extract_tables:
            print(f"   Table extraction: ✅ enabled")
        if self.parallel:
            status = "✅ enabled" if CONCURRENT_AVAILABLE else "⚠️  not available"
            print(f"   Parallel processing: {status} ({self.max_workers} workers)")
        if self.use_cache:
            print(f"   Caching: ✅ enabled")

        print("")

        # Extract each page (with parallel processing - Priority 3)
        if self.parallel and CONCURRENT_AVAILABLE and len(self.doc) > 5:
            print(
                f"🚀 Extracting {len(self.doc)} pages in parallel ({self.max_workers} workers)..."
            )
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.max_workers
            ) as executor:
                page_numbers = list(range(len(self.doc)))
                self.pages = list(executor.map(self.extract_page, page_numbers))
        else:
            # Sequential extraction
            for page_num in range(len(self.doc)):
                page_data = self.extract_page(page_num)
                self.pages.append(page_data)

        # Merge code blocks that span across pages
        self.log("\n🔗 Merging code blocks across pages...")
        self.pages = self.merge_continued_code_blocks(self.pages)

        # Create chunks
        self.log(f"\n📦 Creating chunks (chunk_size={self.chunk_size})...")
        chunks = self.create_chunks(self.pages)

        # Build summary
        total_chars = sum(p["char_count"] for p in self.pages)
        total_code_blocks = sum(p["code_blocks_count"] for p in self.pages)
        total_headings = sum(len(p["headings"]) for p in self.pages)
        total_images = sum(p["images_count"] for p in self.pages)
        total_tables = sum(p["tables_count"] for p in self.pages)  # NEW in Priority 2

        # Detect languages used
        languages = {}
        all_code_blocks_list = []
        for page in self.pages:
            for code in page["code_samples"]:
                lang = code["language"]
                languages[lang] = languages.get(lang, 0) + 1
                all_code_blocks_list.append(code)

        # Calculate quality statistics (NEW in B1.4)
        quality_stats = {}
        if all_code_blocks_list:
            quality_scores = [c["quality_score"] for c in all_code_blocks_list]
            confidences = [c["confidence"] for c in all_code_blocks_list]
            valid_count = sum(1 for c in all_code_blocks_list if c["is_valid"])

            quality_stats = {
                "average_quality": sum(quality_scores) / len(quality_scores),
                "average_confidence": sum(confidences) / len(confidences),
                "valid_code_blocks": valid_count,
                "invalid_code_blocks": total_code_blocks - valid_count,
                "validation_rate": (
                    valid_count / total_code_blocks if total_code_blocks > 0 else 0
                ),
                "high_quality_blocks": sum(1 for s in quality_scores if s >= 7.0),
                "medium_quality_blocks": sum(
                    1 for s in quality_scores if 4.0 <= s < 7.0
                ),
                "low_quality_blocks": sum(1 for s in quality_scores if s < 4.0),
            }

        # Extract chapter information
        chapters = []
        for chunk in chunks:
            if chunk["chapter_title"]:
                chapters.append(
                    {
                        "title": chunk["chapter_title"],
                        "start_page": chunk["start_page"],
                        "end_page": chunk["end_page"],
                    }
                )

        result = {
            "source_file": self.pdf_path,
            "metadata": self.doc.metadata,
            "total_pages": len(self.doc),
            "total_chars": total_chars,
            "total_code_blocks": total_code_blocks,
            "total_headings": total_headings,
            "total_images": total_images,
            "total_extracted_images": len(self.extracted_images),  # NEW in B1.5
            "total_tables": total_tables,  # NEW in Priority 2
            "image_directory": (
                self.image_dir if self.extract_images else None
            ),  # NEW in B1.5
            "extracted_images": self.extracted_images,  # NEW in B1.5
            "total_chunks": len(chunks),
            "chapters": chapters,
            "languages_detected": languages,
            "quality_statistics": quality_stats,  # NEW in B1.4
            "chunks": chunks,
            "pages": self.pages,  # Still include all pages for compatibility
        }

        # Close document
        self.doc.close()

        print(f"\n✅ Extraction complete:")
        print(f"   Total characters: {total_chars:,}")
        print(f"   Code blocks found: {total_code_blocks}")
        print(f"   Headings found: {total_headings}")
        print(f"   Images found: {total_images}")
        if self.extract_images:
            print(f"   Images extracted: {len(self.extracted_images)}")
            if self.image_dir:
                print(f"   Image directory: {self.image_dir}")
        if self.extract_tables:
            print(f"   Tables found: {total_tables}")
        print(f"   Chunks created: {len(chunks)}")
        print(f"   Chapters detected: {len(chapters)}")
        print(f"   Languages detected: {', '.join(languages.keys())}")

        # Print quality statistics (NEW in B1.4)
        if quality_stats:
            print(f"\n📊 Code Quality Statistics:")
            print(f"   Average quality: {quality_stats['average_quality']:.1f}/10")
            print(f"   Average confidence: {quality_stats['average_confidence']:.1%}")
            print(
                f"   Valid code blocks: {quality_stats['valid_code_blocks']}/{total_code_blocks} ({quality_stats['validation_rate']:.1%})"
            )
            print(f"   High quality (7+): {quality_stats['high_quality_blocks']}")
            print(f"   Medium quality (4-7): {quality_stats['medium_quality_blocks']}")
            print(f"   Low quality (<4): {quality_stats['low_quality_blocks']}")

        return result


def main():
    parser = argparse.ArgumentParser(
        description="Extract text and code blocks from PDF documentation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract from PDF
  python3 pdf_extractor_poc.py input.pdf

  # Save to JSON file
  python3 pdf_extractor_poc.py input.pdf --output result.json

  # Verbose mode
  python3 pdf_extractor_poc.py input.pdf --verbose

  # Extract and save
  python3 pdf_extractor_poc.py docs/python.pdf -o python_extracted.json -v
        """,
    )

    parser.add_argument("pdf_file", help="Path to PDF file to extract")
    parser.add_argument(
        "-o", "--output", help="Output JSON file path (default: print to stdout)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument(
        "--pretty", action="store_true", help="Pretty-print JSON output"
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=10,
        help="Pages per chunk (0 = no chunking, default: 10)",
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Disable merging code blocks across pages",
    )
    parser.add_argument(
        "--min-quality",
        type=float,
        default=0.0,
        help="Minimum code quality score (0-10, default: 0 = no filtering)",
    )
    parser.add_argument(
        "--extract-images",
        action="store_true",
        help="Extract images to files (NEW in B1.5)",
    )
    parser.add_argument(
        "--image-dir",
        type=str,
        default=None,
        help="Directory to save extracted images (default: output/{pdf_name}_images)",
    )
    parser.add_argument(
        "--min-image-size",
        type=int,
        default=100,
        help="Minimum image dimension in pixels (filters icons, default: 100)",
    )

    # Advanced features (Priority 2 & 3)
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Use OCR for scanned PDFs (requires pytesseract)",
    )
    parser.add_argument(
        "--password", type=str, default=None, help="Password for encrypted PDF"
    )
    parser.add_argument(
        "--extract-tables",
        action="store_true",
        help="Extract tables from PDF (Priority 2)",
    )
    parser.add_argument(
        "--parallel", action="store_true", help="Process pages in parallel (Priority 3)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: CPU count)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable caching of expensive operations",
    )

    args = parser.parse_args()

    # Validate input file
    if not os.path.exists(args.pdf_file):
        print(f"❌ Error: File not found: {args.pdf_file}")
        sys.exit(1)

    if not args.pdf_file.lower().endswith(".pdf"):
        print(f"⚠️  Warning: File does not have .pdf extension")

    # Extract
    extractor = PDFExtractor(
        args.pdf_file,
        verbose=args.verbose,
        chunk_size=args.chunk_size,
        min_quality=args.min_quality,
        extract_images=args.extract_images,
        image_dir=args.image_dir,
        min_image_size=args.min_image_size,
        # Advanced features (Priority 2 & 3)
        use_ocr=args.ocr,
        password=args.password,
        extract_tables=args.extract_tables,
        parallel=args.parallel,
        max_workers=args.workers,
        use_cache=not args.no_cache,
    )
    result = extractor.extract_all()

    if result is None:
        sys.exit(1)

    # Output
    if args.output:
        # Save to file
        with open(args.output, "w", encoding="utf-8") as f:
            if args.pretty:
                json.dump(result, f, indent=2, ensure_ascii=False)
            else:
                json.dump(result, f, ensure_ascii=False)
        print(f"\n💾 Saved to: {args.output}")
    else:
        # Print to stdout
        if args.pretty:
            print("\n" + json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
