# Candidate Data Transformer

Production-oriented candidate data transformation system for recruiter and HR workflows. The application ingests candidate data from structured sources, GitHub profile URLs, and uploaded resumes, normalizes the data, detects duplicate candidates, merges records into canonical profiles, calculates confidence, preserves provenance, validates output, and presents results in a Streamlit ATS-style dashboard.

## Technology Stack

- Python 3.11+
- Streamlit
- Pydantic v2
- pandas
- phonenumbers
- RapidFuzz
- PyMuPDF
- python-docx
- pytest
- Groq API, optional AI enrichment

## Architecture

The project follows a modular pipeline architecture. Each stage has one responsibility and can be tested or replaced independently.

```text
Read Inputs
  -> Parse Sources
  -> Create CandidateRecord
  -> Resume Matching
  -> Optional AI Input Enrichment
  -> Normalize
  -> Duplicate Detection
  -> Merge Engine
  -> Confidence Calculation
  -> Provenance Tracking
  -> Canonical Candidate Profile
  -> Projection Layer
  -> Validation
  -> Final Output
```

Key design choices:

- Parsers return `CandidateRecord` before normalization.
- AI enrichment is optional and runs before deterministic normalization.
- Normalization is separate from ingestion.
- Matching uses deterministic identifiers first, then RapidFuzz.
- Resume parsing is isolated behind a service so parse failures never stop the pipeline.
- AI failures never stop the pipeline; the original parsed record continues unchanged.
- Merge behavior is source-priority driven and deterministic.
- Confidence and provenance are calculated separately from merge logic.
- Projection allows configurable output schemas without changing code.
- Validation returns structured errors and never crashes callers.
- Streamlit is a thin UI layer over the backend pipeline.

## Folder Structure

```text
src/candidate_transformer/
|-- app/                 Streamlit ATS dashboard
|-- core/                Configuration and core exceptions
|-- domain/              Pydantic domain models
|-- ingestion/           CSV, ATS JSON, LinkedIn, GitHub source parsers
|-- matching/            Candidate duplicate detection
|-- merging/             Merge engine
|-- normalization/       Email, phone, skill, date, location normalization
|-- output/              Projection and output validation
|-- parsers/             Resume document parsers
|-- provenance/          Field-level provenance builder
|-- scoring/             Confidence calculator
|-- services/            Pipeline, GitHub API, resume, and AI enrichment services
`-- utils/               Shared helpers such as link classification
```

## Installation

```bash
python -m pip install -e .
python -m pip install -e ".[dev]"
```

If editable install is not used, run commands from the repository root so `src/` is available.

## Running

```bash
python -m streamlit run src/candidate_transformer/app/streamlit_app.py
```

Then open:

```text
http://localhost:8501
```

## Dashboard

The Streamlit UI is designed like a lightweight Applicant Tracking System.

Inputs:

- Recruiter CSV
- ATS JSON
- GitHub profile URLs, one per line
- Resume files, multiple upload, PDF or DOCX
- Optional Config JSON

Views:

- Candidate Summary: searchable and filterable candidate table
- Candidate Details: personal info, experience, education, skills, projects, certifications, resume information, links, confidence, provenance, validation, and selected-candidate download

Screenshots:

- `docs/screenshots/candidate-summary.png`
- `docs/screenshots/candidate-details.png`

The screenshots can be captured from the running Streamlit dashboard after launching the app locally.

## Sample Input

Recruiter CSV:

```csv
candidate_id,name,email,phone,current_company,current_title,total_experience,current_location,github_url,resume_file,recruiter_notes
C001,Alice Johnson,alice@gmail.com,+14155552671,Google,Backend Engineer,4,"San Francisco",https://github.com/octocat,resumes/alice_johnson.pdf,Strong backend developer
C002,Bob Smith,bob@gmail.com,+442079460958,Amazon,Data Engineer,6,"London",,,
```

ATS JSON:

```json
{
  "candidates": [
    {
      "id": "ats-1",
      "profile": {
        "full_name": "Alice Johnson",
        "headline": "Backend Engineer",
        "skills": ["Python", "AWS"]
      },
      "contact": {
        "emails": ["alice@gmail.com"]
      },
      "employment_history": [
        {"company": "Google", "title": "Backend Engineer"}
      ]
    }
  ]
}
```

Optional Config JSON:

```json
{
  "output_fields": [
    {"name": "candidate_id", "required": true},
    {"name": "full_name", "required": true},
    {"name": "emails"},
    {"name": "skills"},
    {"name": "projects"},
    {"name": "certifications"},
    {"name": "resume_summary"},
    {"name": "overall_confidence"}
  ],
  "field_renaming": {
    "candidate_id": "id",
    "full_name": "name"
  },
  "missing_value_strategy": "omit",
  "source_priorities": {
    "linkedin": 10,
    "github": 8,
    "resume": 8,
    "json": 7,
    "csv": 5
  },
  "apply_normalization": true,
  "use_ai": false
}
```

## Sample Output

```json
[
  {
    "id": "alice@gmail.com",
    "name": "Alice Johnson",
    "emails": ["alice@gmail.com"],
    "skills": ["Python", "AWS"],
    "projects": [{"name": "Payments Platform", "description": null, "technologies": []}],
    "certifications": ["AWS Certified Developer"],
    "overall_confidence": 0.91
  }
]
```

## GitHub Integration

The app accepts GitHub profile URLs from:

- `github_url` in Recruiter CSV
- GitHub URL text area in the dashboard

For each URL, the system extracts the username and calls:

```text
GET https://api.github.com/users/{username}
GET https://api.github.com/users/{username}/repos
```

The GitHub service extracts profile metadata, repository names, repository count, and unique repository languages. It does not crawl external websites.

## AI Input Enrichment

AI enrichment is an optional pre-normalization layer. It does not replace the deterministic pipeline.

```text
Input Sources
  -> Parsers
  -> AI Input Enrichment Agent
  -> Normalization
  -> Candidate Matching
  -> Merge Engine
  -> Confidence
  -> Provenance
  -> Projection
  -> Validation
```

The agent lives in `src/candidate_transformer/services/ai_agent.py` as `AIInputAgent`. Its public method is:

```python
process_candidate_record(record: CandidateRecord) -> CandidateRecord
```

The agent sends one parsed `CandidateRecord` at a time to Groq chat completions and asks the model to return valid JSON. The default model is `llama-3.3-70b-versatile`; set `GROQ_MODEL` to use another configured Llama model.

Set the API key in `.env` or the environment:

```text
GROQ_API_KEY=your_key_here
GROQ_MODEL=llama-3.3-70b-versatile
```

Enable AI in config:

```json
{
  "output_fields": [{"name": "candidate_id"}, {"name": "skills"}],
  "use_ai": true
}
```

When `use_ai` is `false`, the AI stage is skipped completely.

### Prompt Design

The system prompt defines the model as an expert HR data extraction assistant. It instructs the model to:

- Extract only from the provided candidate input.
- Never hallucinate or invent values.
- Return null or empty lists for missing values.
- Return only valid JSON.
- Follow the existing `CandidateRecord` shape.
- Avoid matching, merging, confidence calculation, validation, or provenance changes.

The agent can enrich names, skills, experience, education, projects, certifications, links, GitHub bio, recruiter notes, and resume text when those signals are already present in the input. It also stores AI insight metadata such as summary, strengths, suggested skills, missing information, and field-level confidence reasons in `raw_payload["ai_enrichment"]`.

### Fallback Behavior

AI enrichment is non-fatal. If the Groq API key is missing, the API fails, the response is malformed, or the returned JSON fails `CandidateRecord` validation, the agent returns the original record with AI status metadata:

```text
AI enrichment unavailable. Continuing with rule-based processing.
```

The downstream deterministic stages still run:

- Normalization
- Candidate matching
- Merge engine
- Confidence
- Provenance
- Projection
- Validation

The dashboard shows AI information in the Candidate Details `AI Insights` tab. The section is collapsible and only displays available AI insight fields.

## Resume Processing

The dashboard accepts multiple resume uploads under the Resume Files input. Supported formats are:

- PDF
- DOCX

PDF text is extracted with PyMuPDF. DOCX text is extracted with python-docx. OCR is intentionally not used, so scanned image-only resumes may not produce useful text.

The resume parser extracts candidate information when available:

- Personal information: name, email, phone, location
- Professional information: skills, companies, job titles, durations
- Education: degree, college, graduation year
- Projects and certifications
- Links: GitHub, LinkedIn, portfolio, LeetCode, HackerRank
- Resume summary from the summary/profile section

Resume records are normalized with the same email, phone, date, skill, location, and link utilities used by the rest of the pipeline.

## Resume Matching

Each uploaded resume is matched to an existing parsed candidate before downstream deduplication. The matching priority is:

1. Uploaded filename matches the CSV `resume_file` column.
2. Email extracted from the resume.
3. Phone extracted from the resume.
4. Candidate name using RapidFuzz.

If no candidate matches, the resume becomes a new `CandidateRecord` and continues through matching, merge, confidence, provenance, projection, and validation.

Resume parsing failures are collected and shown in the dashboard as validation-style feedback. One failed resume does not stop the remaining candidates from being processed.

## Updated Pipeline

```text
Load Configuration
  -> Recruiter CSV
  -> ATS JSON
  -> GitHub Profiles
  -> Resume Parser
  -> Optional AI Input Enrichment
  -> Normalization
  -> Candidate Matching
  -> Merge
  -> Confidence
  -> Provenance
  -> Canonical Candidate
  -> Projection
  -> Validation
  -> Dashboard
```

## Link Classification

`LinkClassifier` classifies known link hosts:

- `linkedin.com` -> `linkedin`
- `leetcode.com` -> `leetcode`
- `hackerrank.com` -> `hackerrank`
- `github.com` -> `github`
- unknown personal domains -> `portfolio`
- known non-portfolio/social hosts -> `other`

## Testing

Run all tests:

```bash
python -m pytest tests/unit
```

Coverage currently includes:

- GitHub service
- GitHub URL parser
- Link classifier
- Recruiter CSV parser
- ATS JSON parser
- Resume parser
- Resume matching and failure handling
- AI input enrichment
- AI disabled, retry, malformed response, validation, and failure fallback
- Merge with resume fields
- Candidate matching
- Merge engine
- Normalization
- Confidence calculation
- Provenance
- Projection
- Validation
- End-to-end pipeline orchestration

## Future Improvements

- Add authenticated GitHub API support for higher rate limits.
- Add async GitHub fetches for large URL batches.
- Add richer resume parsing.
- Add persistent job/session storage.
- Add export to ATS-specific formats.
- Add stronger field-level validation rules for custom projected schemas.
- Add screenshot automation for dashboard documentation.
