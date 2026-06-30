"""Unit tests for resume parsing."""

import pytest

from candidate_transformer.ingestion.exceptions import ParserSchemaError
from candidate_transformer.parsers import ResumeParser


def test_resume_parser_extracts_candidate_information(monkeypatch, tmp_path):
    resume_path = tmp_path / "alice_johnson.pdf"
    resume_path.write_bytes(b"fake")
    resume_text = """
Alice Johnson
alice@gmail.com | +1 415 555 2671 | San Francisco, USA
https://github.com/alice
https://www.linkedin.com/in/alice

Summary
Strong backend developer with Python and AWS experience.

Skills
Python, JavaScript, Node.js, AWS

Experience
Software Engineer at Google - Jan 2020 - Present

Education
Stanford University, Bachelor of Science, 2019

Projects
Payments Platform: Built APIs with Python

Certifications
AWS Certified Developer
"""
    parser = ResumeParser()
    monkeypatch.setattr(parser, "extract_text", lambda path: resume_text)

    record = parser.parse(resume_path)[0]

    assert record.source.source_type == "resume"
    assert record.full_name == "Alice Johnson"
    assert record.emails == ["alice@gmail.com"]
    assert record.phones == ["+14155552671"]
    assert "Python" in record.skills
    assert record.experience[0]["company"].startswith("Google")
    assert record.education[0]["institution"] == "Stanford University"
    assert record.projects[0]["name"] == "Payments Platform"
    assert record.certifications == ["AWS Certified Developer"]
    assert record.resume_summary.startswith("Strong backend developer")


def test_resume_parser_rejects_unsupported_format(tmp_path):
    resume_path = tmp_path / "resume.txt"
    resume_path.write_text("Alice", encoding="utf-8")

    with pytest.raises(ParserSchemaError):
        ResumeParser().parse(resume_path)
