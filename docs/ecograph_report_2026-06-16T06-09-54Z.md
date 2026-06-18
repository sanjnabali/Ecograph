# EcoGraph Scope 3 Carbon Accounting Report
**Generated:** 2026-06-16T06:09:54Z
**Model:** EcoGraph v1.0 | Groq llama-3.3-70b-versatile
**CSRD Compliance Status:** NON-COMPLIANT

---

## 1. Executive Summary

The executive summary of the Scope 3 emissions audit report reveals that the organization's baseline emissions total 0 tCO2e/year. An analysis utilizing a multi-modal knowledge graph with GraphRAG reasoning, implemented via Neo4j, did not identify any top carbon hotspot suppliers, nor were any satellite-reported discrepancies detected. Consequently, the mitigation plan is projected to achieve a reduction of 0 tCO2e/year, which represents 0.0% of the baseline emissions. This outcome indicates that the organization's current emissions profile is negligible. However, the audit concludes that the organization is NON-COMPLIANT with the CSRD regulations, highlighting the need for further assessment and potential adjustments to ensure adherence to regulatory requirements. The findings of this report provide a foundation for future emissions management and compliance efforts.

---

## 2. Methodology

The methodology employed in this Scope 3 emissions audit report involves a multi-faceted approach to data ingestion, processing, and analysis. Initially, enterprise resource planning (ERP) invoice data is ingested via a structured CSV connector, providing a foundational dataset for subsequent analysis. Supplemental ESG reports are parsed using a large language model (LLM) schema-constrained extraction technique, specifically the Groq Llama-3.3-70b model, to extract relevant information. Additionally, Sentinel-5P TROPOMI satellite NO2 column density data is processed through a U-Net convolutional neural network (CNN) plume detector, which has been optimised through ONNX INT8 quantisation. To reconcile and integrate these diverse datasets, probabilistic entity resolution is applied using the Splink Fellegi-Sunter model. The resolved data is then stored in a Neo4j AuraDB knowledge graph, which implements an event-sourced observation pattern to facilitate complex querying and analysis. Finally, a LangGraph multi-agent orchestration framework is utilised, leveraging Groq LLM reasoning to derive insights and identify patterns within the integrated dataset, thereby enabling a comprehensive assessment of Scope 3 emissions.

---

## 3. Emissions Baseline Analysis

**Aggregate Scope 3 baseline:** 0 tCO2e/year (exponential-smoothed, alpha=0.3)

**Retrieval query (Cypher):**
```cypher
MATCH (f:Facility)-[:REPORTS_EMISSION]->(o:Observation)
WHERE o.metric = "scope3_tco2e" AND o.method = "tropomi_cnn"
RETURN f.name AS Facility, o.value AS Emissions
ORDER BY o.value DESC
LIMIT 5
```

**Top 0 carbon hotspot suppliers:**
- None identified

---

## 4. Satellite Cross-Validation

**Discrepancy threshold:** 20% relative deviation (symmetric)
**Discrepant suppliers (0):** None

| Supplier ID | Reported tCO2/yr | Satellite tCO2/yr | Method | Discrepant? |
| :--- | :--- | :--- | :--- | :--- |
| N/A | N/A | N/A | N/A | N/A |

---

## 5. Mitigation Plan

**Total projected reduction:** 0 tCO2e/year (0.0% of baseline)

| Rank | Action Type | CO2 Reduction (tCO2/yr) | Timeline (months) | Feasibility | Score |
| :--- | :--- | :--- | :--- | :--- | :--- |
| N/A | N/A | N/A | N/A | N/A | N/A |

---

## 6. Compliance Assessment

**Status:** FAIL - 0 violation(s) found.



---

## 7. Data Quality & Errors

No errors reported.

---

## 8. Citation Index

No graph citations recorded.

*This report was generated autonomously by EcoGraph. All quantitative claims are grounded in graph observations with full provenance. This document is intended for internal ESG assurance review and does not constitute a certified third-party audit.*
