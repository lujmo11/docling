#!/usr/bin/env python3
"""
Pandoc DOCX Normalizer for improving Docling processing.

This module provides functionality to normalize DOCX files using Pandoc
by converting docx -> markdown -> docx. This process can help clean up
formatting inconsistencies and structure issues that might affect Docling's
parsing capabilities.
"""

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Union


logger = logging.getLogger(__name__)


def normalize_docx_with_pandoc(
    source_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    preserve_original: bool = True,
    *,
    save_intermediate: bool = False,
    output_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """
    Normalize a DOCX file using Pandoc by converting docx -> markdown -> docx.
    
    This process helps clean up formatting and structural inconsistencies
    that might interfere with Docling's document parsing.
    
    Args:
        source_path: Path to the original DOCX file
        output_path: Optional path for the normalized DOCX file. 
                    If None, creates a normalized version next to the original
        preserve_original: If True, never overwrite the original file
        
    Returns:
        Path object pointing to the normalized DOCX file
        
    Raises:
        FileNotFoundError: If source file doesn't exist or Pandoc isn't available
        subprocess.CalledProcessError: If Pandoc conversion fails
        ValueError: If attempting to overwrite original when preserve_original=True
    """
    source_path = Path(source_path)
    
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")
    
    if not source_path.suffix.lower() == '.docx':
        raise ValueError(f"Source file must be a DOCX file, got: {source_path.suffix}")
    
    # Determine output path
    if output_path is None:
        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{source_path.stem}_normalized{source_path.suffix}"
        else:
            output_path = get_normalized_filename(source_path)
    else:
        output_path = Path(output_path)
    
    # Safety check: don't overwrite original if preserve_original is True
    if preserve_original and output_path.resolve() == source_path.resolve():
        raise ValueError("Cannot overwrite original file when preserve_original=True")
    
    logger.info(f"Normalizing DOCX with Pandoc: {source_path} -> {output_path}")
    
    try:
        # Check if Pandoc is available
        subprocess.run(['pandoc', '--version'], 
                      capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise FileNotFoundError("Pandoc is not available. Please install Pandoc.") from e
    
    # Create output directory if it doesn't exist
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Determine where to write the intermediate markdown
    temp_md_path = None
    created_temp = False
    if save_intermediate and output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        temp_md_path = output_dir / f"{source_path.stem}_normalized.md"
        # create an empty file to reserve the name
        temp_md_path.write_text("", encoding="utf-8")
    else:
        # Use a temporary markdown file for the intermediate conversion
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as temp_md:
            temp_md_path = Path(temp_md.name)
            created_temp = True
    
    try:
        # Step 1: DOCX -> Markdown
        logger.debug(f"Converting DOCX to Markdown: {source_path} -> {temp_md_path}")
        subprocess.run([
            'pandoc',
            str(source_path),
            '--to', 'markdown',
            '--output', str(temp_md_path),
            '--extract-media', str(temp_md_path.parent / 'media'),  # Extract embedded media
            '--wrap', 'none'  # Don't wrap lines in markdown
        ], check=True, capture_output=True, text=True)
        
        # Step 2: Markdown -> DOCX (normalized)
        logger.debug(f"Converting Markdown to normalized DOCX: {temp_md_path} -> {output_path}")
        cmd = [
            'pandoc',
            str(temp_md_path),
            '--from', 'markdown',
            '--to', 'docx',
            '--output', str(output_path)
        ]
        
        # Add reference document if preserving styles
        if preserve_reference_styles:
            cmd.extend(['--reference-doc', str(source_path)])
            
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info(f"Successfully normalized DOCX: {output_path}")
        return output_path

    except subprocess.CalledProcessError as e:
        logger.error(f"Pandoc conversion failed: {e}")
        logger.error(f"Pandoc stderr: {e.stderr}")
        raise
    finally:
        # Clean up temporary files only if they were created in the system temp dir
        try:
            media_dir = temp_md_path.parent / 'media'
            if created_temp:
                if temp_md_path.exists():
                    temp_md_path.unlink()
                # Clean up extracted media directory if it exists
                if media_dir.exists():
                    import shutil
                    shutil.rmtree(media_dir)
        except Exception as e:
            logger.warning(f"Failed to clean up temporary files: {e}")


def get_normalized_filename(source_path: Union[str, Path]) -> Path:
    """
    Generate a filename for the normalized version of a DOCX file.
    
    Args:
        source_path: Path to the original DOCX file
        
    Returns:
        Path object for the normalized filename
        
    Example:
        original.docx -> original_normalized.docx
        path/to/doc.docx -> path/to/doc_normalized.docx
    """
    source_path = Path(source_path)
    stem = source_path.stem
    suffix = source_path.suffix
    return source_path.parent / f"{stem}_normalized{suffix}"


def is_normalized_file(file_path: Union[str, Path]) -> bool:
    """
    Check if a file appears to be a Pandoc-normalized version.
    
    Args:
        file_path: Path to check
        
    Returns:
        True if the filename suggests it's a normalized file
    """
    return "_normalized" in Path(file_path).stem


def find_original_file(normalized_path: Union[str, Path]) -> Optional[Path]:
    """
    Given a normalized filename, try to find the original file.
    
    Args:
        normalized_path: Path to a normalized file
        
    Returns:
        Path to the original file if found, None otherwise
    """
    normalized_path = Path(normalized_path)
    if not is_normalized_file(normalized_path):
        return None
    
    # Remove _normalized suffix to get original name
    stem = normalized_path.stem.replace("_normalized", "")
    original_path = normalized_path.parent / f"{stem}{normalized_path.suffix}"
    
    return original_path if original_path.exists() else None


# Global flag to control whether to use reference styles during normalization
preserve_reference_styles = False


def set_preserve_reference_styles(preserve: bool) -> None:
    """
    Set whether to preserve reference styles from the original document.
    
    When True, Pandoc will use the original document as a reference for styles,
    potentially preserving more formatting. When False, uses default styles
    which may result in cleaner normalization.
    
    Args:
        preserve: Whether to preserve original document styles
    """
    global preserve_reference_styles
    preserve_reference_styles = preserve
    logger.debug(f"Set preserve_reference_styles to {preserve}")


if __name__ == "__main__":
    # Simple CLI for testing
    import argparse
    import sys
    
    def setup_logging(level: int = logging.INFO) -> None:
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
    
    parser = argparse.ArgumentParser(description="Normalize DOCX files using Pandoc")
    parser.add_argument("source", help="Path to DOCX file to normalize")
    parser.add_argument("--output", "-o", help="Output path for normalized file")
    parser.add_argument("--overwrite", action="store_true", 
                       help="Allow overwriting the original file")
    parser.add_argument("--preserve-styles", action="store_true",
                       help="Preserve reference styles from original document")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    setup_logging(logging.DEBUG if args.debug else logging.INFO)
    set_preserve_reference_styles(args.preserve_styles)
    
    try:
        normalized_path = normalize_docx_with_pandoc(
            args.source, 
            args.output, 
            preserve_original=not args.overwrite
        )
        print(f"Normalized file created: {normalized_path}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)