import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional
from dotenv import load_dotenv

from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# ==========================================
# 1. Knowledge Graph Schema
# ==========================================
class Triple(BaseModel):
    """Represents a single relationship in the Knowledge Graph."""
    subject: str = Field(description="The source entity (e.g., a Company name, Facility, or 'Scope 3').")
    predicate: str = Field(description="The relationship type (e.g., REPORTS_EMISSION, HAS_SUPPLIER, SETS_TARGET). Use uppercase with underscores.")
    object_value: str = Field(description="The target entity, metric, or value (e.g., 'Supplier X', '5000', '2050').")
    metadata: Optional[Dict[str, str]] = Field(default_factory=dict, description="Additional context, such as {'unit': 'tCO2e', 'year': '2023'}.")

class ExtractionResult(BaseModel):
    """The expected output format from the LLM."""
    triples: List[Triple]

# ==========================================
# 2. Extraction Agent
# ==========================================
class Scope3Extractor:
    def __init__(self, model_name="gemini-3-flash-preview", temperature=0):
        if not os.getenv("GOOGLE_API_KEY"):
            logger.error("GOOGLE_API_KEY not found in environment variables.")
            raise ValueError("Missing Google API Key.")

        self.llm = ChatGoogleGenerativeAI(model=model_name, temperature=0)
        self.structured_llm = self.llm.with_structured_output(ExtractionResult)
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert ESG and Supply Chain data analyst. 
            Extract carbon footprint data, decarbonization targets, and supply chain relationships 
            from the provided text. Convert the information into Knowledge Graph triples.
            Focus specifically on Scope 1, 2, and 3 emissions, net-zero commitments, and supplier networks."""),
            ("human", "Extract triples from this text:\n\n{text}")
        ])
        
        self.extraction_chain = self.prompt | self.structured_llm

    def process_document(self, input_path: Path, output_dir: Path):
        """Extracts triples from a single JSON file and saves them."""
        logger.info(f"Extracting knowledge triples from: {input_path.name}")
        
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                elements = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from {input_path.name}: {e}")
            return

        all_extracted_triples = []
        
        # Filter for meaningful content (skip page numbers, short headers)
        meaningful_chunks = [
            el.get('text', '') for el in elements 
            if el.get('type') in ['CompositeElement', 'Table'] and len(el.get('text', '')) > 100
        ]

        for i, chunk in enumerate(meaningful_chunks):
            try:
                result = self.extraction_chain.invoke({"text": chunk})
                
                if result and result.triples:
                    triples_dict = [t.model_dump() for t in result.triples]
                    all_extracted_triples.extend(triples_dict)
                    
                if (i + 1) % 10 == 0:
                    logger.info(f"Processed {i + 1}/{len(meaningful_chunks)} chunks...")
                    
            except Exception as e:
                logger.warning(f"Error extracting from chunk {i}: {str(e)}")
                continue

        output_file = output_dir / f"{input_path.stem}_triples.json"
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(all_extracted_triples, f, indent=4)
            logger.info(f"Successfully saved {len(all_extracted_triples)} triples to {output_file}")
        except IOError as e:
            logger.error(f"Failed to save extracted triples: {e}")

    def process_all_documents(self):
        """Locates the root data folders and processes all parsed files."""
        # Dynamically find the project root relative to this specific script
        # tools.py is in src/agents/ -> parent is agents/ -> parent is src/ -> parent is Ecograph/
        current_script_path = Path(__file__).resolve()
        project_root = current_script_path.parent.parent.parent

        input_dir = project_root / "data" / "parsed_content"
        output_dir = project_root / "data" / "triples"
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if not input_dir.exists():
            logger.error(f"Input directory {input_dir} not found.")
            return

        json_files = list(input_dir.glob("*.json"))
        
        if not json_files:
            logger.warning(f"No JSON files found in {input_dir}.")
            return
            
        logger.info(f"Found {len(json_files)} reports. Starting batch extraction...")

        for file_path in json_files:
            logger.info(f"========== Processing: {file_path.name} ==========")
            self.process_document(file_path, output_dir)
                
        logger.info("Batch extraction complete. Ready for Neo4j ingestion.")

if __name__ == "__main__":
    try:
        extractor = Scope3Extractor()
        extractor.process_all_documents()
    except Exception as main_e:
        logger.critical(f"Script execution failed: {main_e}")