import os
import json
import logging
from pathlib import Path
from unstructured.partition.pdf import partition_pdf
from unstructured.staging.base import elements_to_json


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class EcoGraphParser:
    def __init__(self, input_dir="data/pdfs", output_subdir="parsed_content"):
        self.input_dir = Path(input_dir)

        self.output_dir = Path("data") / output_subdir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def parse_all_reports(self):
        """
        Iterates through the data/pdfs folder and extracts structured text/tables.
        """
        if not self.input_dir.exists():
            logger.error(f"Input directory {self.input_dir} not found. Check pdf_loader.py output.")
            return

        pdf_files = list(self.input_dir.glob("*.pdf"))
        if not pdf_files:
            logger.warning("No PDF files found to process.")
            return

        logger.info(f"Found {len(pdf_files)} reports to parse.")

        for pdf_path in pdf_files:
            try:
                self._process_single_pdf(pdf_path)
            except Exception as e:
                # Catching individual file failures so the whole batch doesn't crash
                logger.error(f"Critical failure processing {pdf_path.name}: {str(e)}")

    def _process_single_pdf(self, file_path):
        logger.info(f"Starting partitioning for: {file_path.name}")
        
        # Extracting both narrative text and structured tables
        
        try:
            elements = partition_pdf(
                filename=str(file_path),
                strategy="hi_res",           # Best for complex ESG tables
                infer_table_structure=True,  # Essential for Scope 3 data extraction
                chunking_strategy="by_title",# Groups related text together
                max_characters=4000,
                new_after_n_chars=3800,
            )

            #Saving as JSON to preserve metadata for the Knowledge Graph
            output_filename = file_path.stem + ".json"
            output_path = self.output_dir / output_filename
            
            with open(output_path, "w", encoding="utf-8") as f:
                json_data = elements_to_json(elements)
                f.write(json_data)
                
            logger.info(f"Successfully saved structured data to: {output_path}")

        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
        except ValueError as ve:
            logger.error(f"Value error (possible empty or corrupt PDF): {ve}")
        except Exception as e:
            logger.error(f"Unexpected error during partitioning of {file_path.name}: {e}")

if __name__ == "__main__":
    parser = EcoGraphParser()
    parser.parse_all_reports()