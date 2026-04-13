import os
import json
import logging
from pathlib import Path
from unstructured.partition.pdf import partition_pdf
from unstructured.staging.base import elements_to_json


from src.config.settings import PDFS_DIR, PARSED_CONTENT_DIR

logger = logging.getLogger(__name__)


class EcoGraphParser:
    def __init__(
        self,
        input_dir: Path = PDFS_DIR,
        output_dir: Path = PARSED_CONTENT_DIR,
    ):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def parse_all_reports(self):
        """
        Iterates through the data/pdfs folder and extractes structured text/tables."""

        if not self.input_dir.exists():
            logger.error(f"Input directory {self.input_dir} not found. Check pdf_loader.py output")
            return
        pdf_files = list(self.input_dir.glob("*.pdf"))
        if not pdf_files:
            logger.warning("No pdf files found to process")
            return
        
        logger.info(f"found {len(pdf_files)} reports to parse.")


        for pdf_path in pdf_files:
            try:
                self._process_single_pdf(pdf_path)
            except Exception as e:
                logger.error(f"Critical failure processing {pdf_path.name}: {str(e)}")

    def _process_singke_pdf(self, file_path: Path) -> None:
        output_path = self.output_dir / (file_path.stem + ".json")

        if output_path.exists():
            logger.info(f"Skip (already parsed): {file_path.name}")
            return
        
        logger.info(f"Starting partitioning for: {file_path.name}")
        try:
            elements = partition_pdf(
                filename=str(file_path),
                strategy="hi_res",
                infer_table_structure=True,
                chunking_strategy="by_title",
                max_characters=4000,
                new_after_n_chars=3800,
            )

            with open(output_path, "w", encoding="utf-8") as f:
                json_data = elements_to_json(elements)
                f.write(json_data)

            logger.info(f"Successfully saved structured data to: {output_path}")

        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
        except ValueError as ve:
            logger.error(f"value error (possible empty or corrupt PDF): {ve}")
        except Exception as e:
            logger.error(f"Unexpected error during partitioning of {file_path.name}: {e}")

if __name__ == "__main__":
    parser = EcoGraphParser()
    parser.parse_all_reports()
        