# Candidate Data Transformer

A production-oriented Candidate Data Transformer designed for recruiter and HR workflows. The application ingests candidate information from multiple structured and unstructured sources, normalizes the data, detects duplicate candidates, merges records into canonical profiles, calculates confidence scores, tracks provenance, validates the output, and presents the results through a Streamlit-based Applicant Tracking System (ATS) dashboard.

---

## Features

- Recruiter CSV ingestion
- ATS JSON ingestion
- Resume parsing (PDF and DOCX)
- GitHub profile enrichment
- AI-powered candidate enrichment using Groq Llama
- Candidate matching and duplicate detection
- Canonical candidate profile generation
- Confidence score calculation
- Provenance tracking
- Configurable output projection
- Output validation
- ATS-style Streamlit dashboard
- Download canonical candidate profiles as JSON

---

## Technology Stack

| Category | Technologies |
|----------|--------------|
| Language | Python 3.11+ |
| UI | Streamlit |
| Data Models | Pydantic v2 |
| Data Processing | pandas |
| Resume Parsing | PyMuPDF, python-docx |
| Candidate Matching | RapidFuzz |
| Phone Validation | phonenumbers |
| HTTP Client | requests |
| AI | Groq API (Llama 3.3 70B) |
| Testing | pytest |

---

# Architecture

The project follows a modular pipeline where every stage has a single responsibility.

```text
Recruiter CSV
ATS JSON
Resume
GitHub Profile URL
        │
        ▼
Input Parsers
        │
        ▼
AI Input Enrichment (Optional)
        │
        ▼
Normalization
        │
        ▼
Candidate Matching
        │
        ▼
Merge Engine
        │
        ▼
Confidence Calculation
        │
        ▼
Provenance Tracking
        │
        ▼
Canonical Candidate Profile
        │
        ▼
Projection Layer
        │
        ▼
Validation
        │
        ▼
Streamlit Dashboard
```

---

## Design Principles

- Modular architecture
- SOLID principles
- Deterministic matching and merging
- Explainable confidence calculation
- Field-level provenance tracking
- AI enrichment is optional
- Graceful failure handling
- Easily extensible

---

## Project Structure

```text
Candidate-Data-Transformer/
│
├── sample_data/
│
├── src/
│   └── candidate_transformer/
│       ├── app/
│       ├── core/
│       ├── domain/
│       ├── ingestion/
│       ├── matching/
│       ├── merging/
│       ├── normalization/
│       ├── output/
│       ├── parsers/
│       ├── provenance/
│       ├── scoring/
│       ├── services/
│       └── utils/
│
├── tests/
│
├── README.md
├── requirements.txt
├── pyproject.toml
└── .gitignore
```

---

# Installation

Clone the repository.

```bash
git clone <repository-url>
cd Candidate-Data-Transformer
```

Install dependencies.

```bash
pip install -r requirements.txt
```

---

# Running the Application

Start the Streamlit application.

```bash
streamlit run src/candidate_transformer/app/streamlit_app.py
```

Open the application in your browser.

```
http://localhost:8501
```

---

# Supported Input Sources

## Structured Sources

- Recruiter CSV
- ATS JSON

## Unstructured Sources

- Resume (PDF)
- Resume (DOCX)
- GitHub Profile URLs

## Optional

- Config JSON

---

# Candidate Processing Pipeline

The application processes candidate information through the following stages.

1. Read Input Sources
2. Parse Candidate Data
3. Optional AI Enrichment
4. Normalize Candidate Information
5. Detect Duplicate Candidates
6. Merge Records
7. Generate Canonical Candidate
8. Calculate Confidence Scores
9. Build Provenance
10. Validate Output
11. Render ATS Dashboard

---

# Candidate Matching Strategy

Candidates are matched using deterministic rules.

Priority order:

1. Email Address
2. Phone Number
3. GitHub URL
4. Resume Email
5. Resume Phone
6. Name Similarity (RapidFuzz)
7. Name + Company
8. Name + Skills

Every real-world candidate results in exactly one canonical profile.

---

# GitHub Integration

GitHub enrichment is optional.

The application accepts GitHub profile URLs from:

- Recruiter CSV
- GitHub URL input
- Resume (if detected)

The application retrieves:

- Profile information
- Repository list
- Repository count
- Programming languages
- Public profile metadata

GitHub API calls are skipped automatically when no valid GitHub URL is available.

---

# Resume Processing

Supported formats

- PDF
- DOCX

The parser extracts:

- Personal Information
- Contact Information
- Skills
- Experience
- Education
- Projects
- Certifications
- Links
- Resume Summary

Resume parsing failures never stop the pipeline.

---

# AI Input Enrichment

AI enrichment is optional.

When enabled, the application sends parsed candidate records to the Groq API for enrichment.

The AI is responsible for:

- Standardizing skills
- Resume understanding
- GitHub bio interpretation
- Candidate summary generation
- Suggested roles
- Strength identification
- Missing information detection

The AI does **not** perform:

- Candidate matching
- Duplicate detection
- Merge decisions
- Confidence calculation
- Validation
- Provenance tracking

If the AI is unavailable, the deterministic pipeline continues without interruption.

---

# ATS Dashboard

The dashboard provides two main views.

## Candidate Summary

- Candidate list
- Search
- Sorting
- Filtering
- Confidence
- Validation Status

## Candidate Details

- Personal Information
- Experience
- Education
- Skills
- Projects
- Certifications
- Resume Summary
- Links
- AI Insights
- Confidence
- Provenance
- Validation Results
- Raw JSON
- Download Canonical Profile

---

# Sample Data

The repository includes sample input files under:

```text
sample_data/
├── recruiter_candidates.csv
├── ats_candidates.json
├── config.json
└── resumes/
```

These files can be used to test the application.

---

# Testing

Run all unit tests.

```bash
pytest tests/unit
```

The project includes tests for:

- Recruiter CSV Parser
- ATS JSON Parser
- Resume Parser
- GitHub Integration
- Candidate Matching
- Merge Engine
- Confidence Calculator
- Provenance Builder
- Projection Engine
- Validation
- AI Enrichment
- End-to-End Pipeline

---

# Configuration

Configuration is supported through Config JSON.

Examples include:

- Output field selection
- Field renaming
- Source priority
- Missing value strategy
- AI enable/disable

---

# Future Improvements

- LinkedIn API integration
- OCR support for scanned resumes
- Multi-language resume parsing
- Job Description matching
- ATS vendor-specific adapters
- Asynchronous GitHub enrichment
- Persistent candidate storage
- Dashboard analytics
- Export to ATS-specific formats

---

# Author

Sandhya M
