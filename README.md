# ARC-AGI Failure Modes & Evaluation Pipeline

An end-to-end data engineering and evaluation pipeline for studying how local and frontier LLMs behave on the ARC-AGI benchmark.

This project does **not** aim to solve ARC-AGI directly.  
Its goal is to build the infrastructure needed to:

- ingest ARC-AGI tasks from JSON,
- normalize grids and task structures,
- orchestrate large-scale inference across multiple models,
- store results in Parquet for efficient analysis,
- and characterize failure modes with a quantitative taxonomy.

## Project Goal

ARC-AGI is a benchmark for abstract reasoning on small visual tasks.  
Instead of focusing on a solver, this repository focuses on observability, reproducibility, and failure analysis.

The main question is:

> When models fail on ARC-AGI, **how** do they fail, **where** do they fail, and **what does it cost** to evaluate them?

## What This Project Does

- Reads ARC-AGI tasks in JSON format.
- Normalizes inputs, outputs, and metadata into structured tabular data.
- Generates prompts and evaluation batches for multiple LLM providers.
- Captures predictions, latency, cost, retries, and response metadata.
- Persists inference outputs in Parquet for scalable downstream analysis.
- Builds a failure taxonomy covering spatial, topological, symbolic, quantitative, operational, and financial errors.
- Compares models using metrics such as accuracy, error rate, latency, and cost.

## What This Project Does Not Do

- It does not attempt to build a new ARC solver.
- It does not optimize prompts for leaderboard performance.
- It does not treat ARC as a general IQ benchmark for humans.
- It does not focus on training or fine-tuning custom models.

## Core Pipeline

1. **Ingestion**
   - Load ARC-AGI JSON tasks.
   - Separate train and test examples.
   - Validate grid dimensions and structural consistency.

2. **Normalization**
   - Convert nested grids into analyzable tables.
   - Standardize metadata and task fields.
   - Prepare model-ready prompt structures.

3. **Inference Orchestration**
   - Run tasks across local and frontier models.
   - Handle retries, rate limits, and API errors.
   - Record model, prompt, response, latency, and cost.

4. **Persistence**
   - Store outputs in Parquet.
   - Partition by model, task type, date, or experiment id.
   - Keep the dataset queryable with Pandas, DuckDB, or PyArrow.

5. **Analysis**
   - Compute aggregate and per-task metrics.
   - Classify failures by taxonomy.
   - Compare performance across models and transformation types.

## Key Metrics

The project is designed to capture more than just accuracy.

- **Accuracy**: overall correctness rate.
- **Error rate**: proportion of incorrect predictions.
- **Latency**: time taken per inference.
- **Cost**: inference cost per model or batch.
- **Accuracy by transformation type**: performance by spatial, symbolic, or quantitative task category.
- **Failure taxonomy**: type of error observed in the model output.

## Failure Taxonomy

The analysis framework groups errors into categories such as:

- Spatial errors
- Topological errors
- Symbolic errors
- Quantitative errors
- Operational errors
- Financial tracking errors

This makes it possible to compare models not only by success rate, but by the kinds of reasoning they struggle with.

## Suggested Tech Stack

- **Python**
- **NumPy**
- **Pandas**
- **PyArrow**
- **DuckDB**
- **Parquet**
- **n8n** or **Apache Airflow**
- **Docker**
- **OpenAI API**
- **Google AI Studio API**
- **Ollama**

## Repository Structure

A suggested structure for the repository is:

```bash
.
├── data/
│   ├── raw/
│   ├── processed/
│   └── parquet/
├── notebooks/
├── src/
│   ├── ingestion/
│   ├── normalization/
│   ├── orchestration/
│   ├── inference/
│   ├── storage/
│   └── analysis/
├── configs/
├── docs/
├── tests/
└── README.md
```

## Project Phases

### Phase 1: Definition and Alignment
- Define scope, roles, and terminology.
- Review ARC-AGI format and benchmark goals.
- Establish the initial data model and evaluation plan.

### Phase 2: Base ETL and First Inference Runs
- Build the first working ingestion and normalization flow.
- Connect one or more LLM providers.
- Run controlled inference batches.

### Phase 3: Stable Storage and Data Quality
- Freeze the Parquet schema.
- Validate consistency, completeness, and reproducibility.
- Prepare the data for downstream analysis.

### Phase 4: Failure Analysis and Reporting
- Build the failure taxonomy.
- Generate comparison tables and visualizations.
- Produce the final report and presentation materials.

## Team Roles

This project is organized around specialized roles:

- **Pipeline Lead**: dataset ingestion, matrix normalization, ETL logic.
- **Cloud / ML Infrastructure Engineer**: APIs, local models, runtime environment, rate limits.
- **Automation & Orchestration Specialist**: workflow automation, retries, scheduling, persistence.
- **Data Analyst / Taxonomy Specialist**: metrics, failure modes, statistical analysis.
- **Analytics Translator**: dashboards, visualizations, and communication of results.

## Expected Deliverables

- A reproducible ARC-AGI evaluation pipeline.
- A Parquet-based results store.
- A quantitative failure taxonomy.
- Comparative analysis across models.
- Final report and presentation-ready visualizations.

## Why This Matters

ARC-AGI is a useful benchmark for studying abstract reasoning under limited examples.  
By focusing on the evaluation pipeline instead of a solver, this project creates reusable infrastructure for large-scale model assessment, error analysis, and experimental traceability.

## License

TBD.

## Status

Initial planning and project setup.