# 🌱 EcoGraph: Multi-Modal Knowledge Graph for Scope 3 Decarbonization

## 📖 What We Are Doing (Project Overview)
**EcoGraph** is an autonomous, AI-driven pipeline designed to extract complex, unstructured environmental data from corporate ESG (Environmental, Social, and Governance) reports and transform it into a structured, queryable **Knowledge Graph**. 

**The Problem:** Tracking **Scope 3 emissions** (supply chain and indirect emissions) is notoriously difficult. This critical data is buried inside hundreds of pages of dense PDFs, complex financial tables, and qualitative narrative text across different companies using different reporting standards. 

**The Solution:** EcoGraph solves this by utilizing a **Multi-Modal Agentic AI pipeline**. Instead of relying on rigid keyword searches, it uses Large Language Models (LLMs) to "read" both text and tables, identify key entities (Companies, Emission Metrics, Net-Zero Targets), determine their relationships (Suppliers, Reporting Categories), and map them into a **Neo4j Graph Database**. This allows for advanced supply chain orchestration, making it possible to query cascading carbon footprints across a network of suppliers in real-time.

---

## 🧠 Architecture Deep Dive: How It Works Under the Hood

EcoGraph combines several cutting-edge AI and data architectures to turn unstructured human language into machine-readable logic.

### 1. The Brain: Gemini 1.5 Flash (The Large Language Model)
To extract relationships, we use `gemini-1.5-flash`. This LLM is built on two core architectural concepts: the **Transformer** and the **Mixture-of-Experts (MoE)**.

* **The Transformer & Self-Attention:** LLMs calculate the mathematical relationship between words using Self-Attention. When parsing complex ESG reports, the word "emissions" on page 2 might be related to "Scope 3" on page 4. Self-attention allows the model to connect these distant concepts accurately.
  * *The Math:* $Attention(Q, K, V) = \text{softmax}\left(\frac{Q K^T}{\sqrt{d_k}}\right) V$
* **Mixture-of-Experts (MoE):** Instead of one giant neural network, MoE divides the brain into "departments" (experts). A "Router" calculates the probability $G(x)$ of which expert is best suited for a specific word. 
  * *The Math:* $y = \sum G(x)_i E_i(x)$. 
  * *Why we use it:* This allows the model to process hundreds of pages of dense financial and environmental text incredibly fast and cheaply, which is essential for batch-processing thousands of PDFs.

### 2. The Storage: Neo4j (Knowledge Graph Architecture)
Once Gemini extracts the data, we store it in Neo4j. Neo4j is built on **Graph Theory**, which is fundamentally different from traditional SQL databases.

* **The Math of Graph Theory:** Data is stored as a mathematical structure: $G = (V, E)$
  * **V (Vertices/Nodes):** The entities (e.g., Boston Pizza, 500 tCO2e, Scope 3).
  * **E (Edges/Relationships):** The connections between them (e.g., `SUPPLIES_TO`, `REPORTS_EMISSION`). 
* *Why we use it:* Finding a supplier's emissions in SQL requires mathematical "JOINs" across massive tables, taking exponential time $O(N^2)$. In a Knowledge Graph, the database "hops" from one node to the next in constant time $O(1)$. Because supply chains are literal webs of connected companies, Neo4j is the only architecture that makes logical sense for tracking cascading Scope 3 carbon footprints.

### 3. The Orchestration: LangChain & Pydantic
We use `with_structured_output` via Pydantic to control the LLM. 
* **Probabilistic Masking:** LLMs are probability calculators. Left alone, they output conversational text (e.g., *"Here are the triples you asked for..."*) which would crash a database. LangChain and Pydantic apply a mathematical "mask" over the LLM's output layer. If the LLM wants to generate a conversational word, the framework sets its probability to 0%, forcing it to only select words that conform to our exact JSON schema.

---

## 🏗️ Method Pipeline

EcoGraph is built on a deterministic, 4-stage data transformation pipeline:

1. **Stage 1: Data Ingestion (`src/ingestion/pdf_loader.py`)**
   * Automatically downloads raw ESG documents from the Hugging Face `vidore` dataset.
2. **Stage 2: Multi-Modal Parsing (`src/ingestion/parsing.py`)**
   * Traditional OCR destroys table formatting. We utilize the `unstructured` library with a `hi_res` partitioning strategy to identify whether a block of pixels is a `NarrativeText` paragraph or a `Table`. 
   * **Output:** Structured `.json` files where tables are preserved in HTML format.
3. **Stage 3: Semantic Triple Extraction (`src/agents/tools.py`)**
   * Uses **Gemini 1.5 Flash** constrained by **Pydantic** structured outputs to read the parsed JSON and output strict Knowledge Graph Triples.
   * *Example:* `{"subject": "Cheesecake Factory", "predicate": "COMMITS_TO_NET_ZERO", "object": "2050"}`
4. **Stage 4: Graph Storage & Orchestration**
   * The extracted triples are loaded into a **Neo4j** graph database via Cypher queries, orchestrated by **LangGraph**.

---

## 🛠️ Key Technologies (Tech Stack)
* **LLM / Inference Engine:** Gemini 1.5 Flash (Google GenAI)
* **AI Orchestration:** LangChain, LangGraph
* **Data Parsing:** Unstructured (`unstructured[all-docs]`)
* **Data Structuring:** Pydantic
* **Graph Database:** Neo4j
* **Vector Database:** Qdrant (for semantic RAG capabilities)

---

## 📂 Directory Structure

```text
ECOGRAPH/
├── data/                     # Data Lake (Separated from source code)
│   ├── pdfs/                 # 1. Raw downloaded ESG reports
│   ├── parsed_content/       # 2. Parsed JSON elements (Text & Tables)
│   └── triples/              # 3. LLM-extracted Knowledge Triples
├── src/
│   ├── agents/               # AI Agent Logic
│   │   ├── state.py          # LangGraph state management
│   │   ├── supervision.py    # Agent routing and supervision
│   │   ├── tools.py          # LLM extraction tools (Scope3Extractor)
│   │   └── workflow.py       # Main orchestration flow
│   ├── graph/                # Database Logic
│   │   ├── neo4j_store.py    # Cypher queries and DB connection
│   │   ├── resolver.py       # Entity resolution (deduplication)
│   │   └── schema.py         # Graph Ontology definitions
│   └── ingestion/            # Data Collection & Parsing
│       ├── erp_loader.py     # Mock ERP data ingestion
│       ├── geo_loader.py     # Geospatial data processing
│       ├── pdf_loader.py     # HuggingFace dataset downloader
│       └── parsing.py        # Unstructured PDF to JSON parser
├── ui/                       # Streamlit frontend application
├── .env                      # Environment variables and API Keys
├── .gitignore
└── requirements.txt          # Python dependencies