# Candidate Data Transformer

A production-oriented Candidate Data Transformer designed for recruiter and HR workflows.

The application ingests candidate information from multiple structured and unstructured sources, normalizes the data, detects duplicate candidates, merges records into canonical profiles, calculates confidence scores, tracks provenance, validates the output, and presents the results through a Streamlit-based Applicant Tracking System (ATS) dashboard.

The project demonstrates how modern recruitment systems can consolidate fragmented candidate information into a single, reliable candidate profile while maintaining explainability and deterministic processing.

## Features

- Recruiter CSV ingestion
- ATS JSON ingestion
- Resume parsing (PDF and DOCX)
- GitHub profile enrichment
- AI-powered candidate enrichment using Groq Llama
- Candidate matching and duplicate detection
- Canonical candidate profile generation
- Confidence score calculation
- Field-level provenance tracking
- Configurable output projection
- Output validation
- ATS-style Streamlit dashboard
- Download canonical candidate profiles as JSON

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
| AI | Groq API (Llama 3.3 70B Versatile) |
| Testing | pytest |

## Architecture

The project follows a modular pipeline where each stage has a single responsibility.

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
Streamlit ATS Dashboard
```

## Design Principles

- Modular and maintainable architecture
- Separation of concerns
- Deterministic candidate matching and merging
- Explainable confidence calculation
- Field-level provenance tracking
- Optional AI enrichment
- Graceful error handling
- Easily extensible components

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
## Installation

Clone the repository.

```bash
git clone https://github.com/<your-username>/Candidate-Data-Transformer.git
cd Candidate-Data-Transformer
```

Install the required dependencies.

```bash
pip install -r requirements.txt
```

Alternatively, if using editable mode:

```bash
pip install -e .
pip install -e ".[dev]"
```

## Environment Variables

Create a `.env` file in the project root.

```env
GITHUB_TOKEN=your_github_personal_access_token
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.3-70b-versatile
```

### GitHub Token

A GitHub Personal Access Token is optional but recommended.

Authenticated requests increase the GitHub API rate limit and improve reliability when enriching candidate profiles.

If no token is provided, the application automatically falls back to unauthenticated requests using GitHub's public API.

### Groq API

The Groq API is used for optional AI-powered candidate enrichment.

If the API key is unavailable or the AI service cannot be reached, the application continues using the deterministic pipeline without interruption.

> **Note**
>
> Never commit your `.env` file to GitHub.

## Running the Application

Launch the Streamlit application.

```bash
streamlit run src/candidate_transformer/app/streamlit_app.py
```

Once the server starts, open the application in your browser.

```
http://localhost:8501
```

## Supported Input Sources

The application accepts both structured and unstructured candidate data.

### Structured Sources

- Recruiter CSV
- ATS JSON

### Unstructured Sources

- Resume (PDF)
- Resume (DOCX)
- GitHub Profile URLs

### Optional Configuration

- Config JSON

The application automatically combines all available sources into a unified candidate profile.

## Candidate Processing Pipeline

Every candidate record passes through the following deterministic processing pipeline.

```text
Read Input Sources
        │
        ▼
Parse Candidate Data
        │
        ▼
Optional AI Input Enrichment
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
ATS Dashboard
```

Each stage is isolated, making the application modular, maintainable, and easy to test.

## Candidate Processing Pipeline

Every candidate record passes through the following deterministic processing pipeline.

```text
Read Input Sources
        │
        ▼
Parse Candidate Data
        │
        ▼
Optional AI Input Enrichment
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
ATS Dashboard
```

Each stage is isolated, making the application modular, maintainable, and easy to test.


## Candidate Matching Strategy

The application consolidates records belonging to the same candidate by combining deterministic matching with fuzzy name matching.

Matching priority:

1. Email Address
2. Phone Number
3. GitHub Profile URL
4. Resume Email
5. Resume Phone Number
6. Name Similarity using RapidFuzz
7. Name and Current Company
8. Name and Skills

Deterministic identifiers are always preferred over fuzzy matching to minimize false positives.

Once duplicate records are identified, they are merged into a single canonical candidate profile.

## Merge Strategy

After duplicate candidates are identified, the Merge Engine creates a canonical candidate profile.

Field conflicts are resolved using configurable source priorities.

Example source priority:

1. Resume
2. GitHub
3. ATS JSON
4. Recruiter CSV

Every selected field records its origin through provenance metadata, allowing recruiters to understand where each value came from.

## GitHub Integration

The application enriches candidate profiles using the GitHub REST API.

GitHub profile URLs may be provided through:

- Recruiter CSV
- GitHub URL input in the dashboard
- Resume (when detected)

For each valid profile, the application retrieves:

- Public profile information
- Repository names
- Repository count
- Programming languages
- GitHub bio
- Public profile metadata

GitHub enrichment is optional.

If a valid `GITHUB_TOKEN` is configured, authenticated requests are used to increase the API rate limit.

If no token is available, the application falls back to unauthenticated requests.

GitHub enrichment is skipped automatically when:

- No GitHub URL is available
- The profile does not exist
- Authentication fails
- API rate limits are exceeded

Failures during GitHub enrichment never stop the candidate transformation pipeline.

## Resume Processing

The application supports parsing resumes in:

- PDF
- DOCX

The parser extracts candidate information such as:

- Personal Information
- Contact Details
- Skills
- Experience
- Education
- Projects
- Certifications
- Professional Links
- Resume Summary

Each uploaded resume is matched to an existing candidate using:

1. Resume filename
2. Email address
3. Phone number
4. Candidate name (RapidFuzz)

If no existing candidate is matched, the resume becomes a new candidate record and continues through the standard processing pipeline.

Resume parsing failures are handled gracefully and never interrupt processing of other candidates.

## AI Input Enrichment

AI enrichment is an optional preprocessing stage powered by the Groq API using the Llama 3.3 70B Versatile model.

The AI enriches parsed candidate records by:

- Standardizing skills
- Understanding resume content
- Interpreting GitHub bios
- Generating professional summaries
- Identifying strengths
- Suggesting suitable job roles
- Highlighting missing candidate information

The AI **does not** perform:

- Candidate matching
- Duplicate detection
- Merge decisions
- Confidence calculation
- Provenance generation
- Output validation

These stages remain fully deterministic.

If AI enrichment is disabled or the AI service is unavailable, the application continues with the deterministic pipeline without interruption.

## Confidence Scoring

Each canonical candidate profile is assigned an overall confidence score.

The confidence score considers:

- Number of supporting data sources
- Agreement between sources
- Data completeness
- Validation results

Higher confidence indicates greater reliability of the merged candidate profile.

Confidence calculation is deterministic and independent of AI enrichment.

## Provenance Tracking

Every field in the canonical candidate profile records its source.

Example:

- Name → Resume
- Skills → GitHub
- Phone Number → Recruiter CSV
- Experience → ATS JSON

This allows recruiters to understand the origin of every piece of information and improves explainability.
