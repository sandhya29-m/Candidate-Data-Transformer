"""Streamlit UI for the Candidate Data Transformer."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import streamlit as st

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from candidate_transformer.ingestion import ATSJSONParser, GitHubAPIError, GitHubProfileURLParser, RecruiterCSVParser
from candidate_transformer.services import CandidatePipeline, PipelineInput, PipelineResult
from candidate_transformer.utils import LinkClassifier

logger = logging.getLogger(__name__)


DEFAULT_CONFIG: dict[str, Any] = {
    "output_fields": [
        {"name": "candidate_id", "required": True},
        {"name": "full_name", "required": True},
        {"name": "emails"},
        {"name": "phones"},
        {"name": "location"},
        {"name": "links"},
        {"name": "headline"},
        {"name": "years_experience"},
        {"name": "skills"},
        {"name": "experience"},
        {"name": "education"},
        {"name": "projects"},
        {"name": "certifications"},
        {"name": "resume_summary"},
        {"name": "provenance"},
        {"name": "overall_confidence"},
    ],
    "missing_value_strategy": "keep_null",
    "source_priorities": {
        "github": 8,
        "resume": 8,
        "json": 7,
        "csv": 5,
    },
    "apply_normalization": True,
    "use_ai": False,
}


def main() -> None:
    """Render and run the Streamlit application."""
    _configure_page()
    _render_header()

    if "pipeline_result" not in st.session_state:
        st.session_state.pipeline_result = None
    if "pipeline_error" not in st.session_state:
        st.session_state.pipeline_error = None

    with st.container():
        st.subheader("Inputs")
        input_left, input_right = st.columns(2)
        with input_left:
            recruiter_csv = st.file_uploader("Recruiter CSV", type=["csv"])
            ats_json = st.file_uploader("ATS JSON", type=["json"], key="ats_json")
            st.markdown("**Resume Files**")
            resume_files = st.file_uploader(
                "Upload Multiple Files",
                type=["pdf", "docx"],
                accept_multiple_files=True,
                key="resume_files",
            )
            st.caption("Supported: PDF, DOCX")
        with input_right:
            github_url = st.text_area(
                "GitHub Profile URL(s)",
                placeholder="https://github.com/octocat",
                height=96,
            )
            use_ai = st.checkbox("Enable AI enrichment", value=False)
            config_json = st.file_uploader("Config JSON (Optional)", type=["json"], key="config_json")

        st.divider()
        button_left, button_right = st.columns([1, 1])
        generate_clicked = button_left.button("Generate Candidate Profiles", type="primary", use_container_width=True)
        reset_clicked = button_right.button("Reset", use_container_width=True)

    if reset_clicked:
        st.session_state.pipeline_result = None
        st.session_state.pipeline_error = None
        st.rerun()

    uploads = {
        "recruiter_csv": recruiter_csv,
        "ats_json": ats_json,
    }

    if generate_clicked:
        st.session_state.pipeline_result = None
        st.session_state.pipeline_error = None
        spinner_text = "Fetching GitHub data and generating candidate profile..." if github_url.strip() else "Generating candidate profile..."
        with st.spinner(spinner_text):
            try:
                st.session_state.pipeline_result = _run_pipeline(uploads, github_url, resume_files, config_json, use_ai)
            except GitHubAPIError as exc:
                logger.warning("GitHub API failed", extra={"error": str(exc)})
                st.session_state.pipeline_error = str(exc)
            except Exception as exc:
                logger.exception("Failed to generate candidate profile")
                st.session_state.pipeline_error = str(exc)

    if st.session_state.pipeline_error:
        st.error(st.session_state.pipeline_error)

    if st.session_state.pipeline_result is None:
        _render_empty_state()
        return

    _render_results(st.session_state.pipeline_result)


def _configure_page() -> None:
    """Configure Streamlit page settings and app-level styles."""
    st.set_page_config(page_title="Candidate Data Transformer", page_icon=None, layout="wide")
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
            max-width: 1280px;
        }
        section[data-testid="stSidebar"] {
            background: #f8fafc;
            border-right: 1px solid #e5e7eb;
        }
        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 0.75rem 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_header() -> None:
    """Render the application header."""
    st.title("Candidate Data Transformer")
    st.caption("Upload structured sources and resumes, fetch public GitHub data, and generate validated candidate JSON.")


def _render_empty_state() -> None:
    """Render the initial application state."""
    left, middle, right = st.columns(3)
    left.metric("Sources", "4 supported")
    middle.metric("Output", "Configurable JSON")
    right.metric("Validation", "Pydantic")
    st.info("Upload Recruiter CSV, ATS JSON, GitHub profile URLs, or resumes, optionally upload config JSON, then generate a profile.")


def _run_pipeline(
    uploads: dict[str, Any],
    github_url: str,
    resume_files: list[Any],
    config_upload: Any | None,
    use_ai: bool,
) -> PipelineResult:
    """Run the candidate pipeline from Streamlit uploads."""
    active_uploads = {name: upload for name, upload in uploads.items() if upload is not None}
    github_urls = _parse_github_urls(github_url)
    if not active_uploads and not github_urls and not resume_files:
        raise ValueError("Please provide at least one input source.")

    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        pipeline_inputs = _build_pipeline_inputs(active_uploads, temp_path)
        resume_paths = _write_resume_uploads(resume_files, temp_path)
        for github_profile_url in github_urls:
            pipeline_inputs.append(PipelineInput(source_path=github_profile_url, parser=GitHubProfileURLParser()))
        config = _load_config(config_upload, temp_path, use_ai=use_ai)
        return CandidatePipeline().run(config=config, inputs=pipeline_inputs, resume_paths=resume_paths)


def _parse_github_urls(raw_urls: str) -> list[str]:
    """Parse and keep only valid GitHub profile URLs from text input."""
    urls: list[str] = []
    seen: set[str] = set()
    classifier = LinkClassifier()
    for line in raw_urls.splitlines():
        raw_url = line.strip()
        if not raw_url:
            continue
        classification = classifier.classify(raw_url)
        if classification is None or classification.category != "github":
            continue
        key = classification.url.rstrip("/").casefold()
        if key not in seen:
            urls.append(classification.url)
            seen.add(key)
    return urls


def _write_resume_uploads(resume_files: list[Any] | None, temp_path: Path) -> list[Path]:
    """Persist uploaded resume files and return their temporary paths."""
    if not resume_files:
        return []

    resume_dir = temp_path / "resumes"
    resume_dir.mkdir(exist_ok=True)
    resume_paths: list[Path] = []
    for upload in resume_files:
        safe_name = Path(upload.name).name
        resume_path = resume_dir / safe_name
        resume_path.write_bytes(upload.getvalue())
        resume_paths.append(resume_path)
    return resume_paths


def _build_pipeline_inputs(uploads: dict[str, Any], temp_path: Path) -> list[PipelineInput]:
    """Persist uploads and attach the correct parser for each source."""
    parser_factories = {
        "recruiter_csv": RecruiterCSVParser,
        "ats_json": ATSJSONParser,
    }
    suffixes = {
        "recruiter_csv": ".csv",
        "ats_json": ".json",
    }

    pipeline_inputs: list[PipelineInput] = []
    for source_name, upload in uploads.items():
        source_path = temp_path / f"{source_name}{suffixes[source_name]}"
        source_path.write_bytes(upload.getvalue())
        pipeline_inputs.append(PipelineInput(source_path=source_path, parser=parser_factories[source_name]()))
    return pipeline_inputs


def _load_config(config_upload: Any | None, temp_path: Path, *, use_ai: bool) -> dict[str, Any] | Path:
    """Load uploaded config or return a production-friendly default config."""
    if config_upload is None:
        config = dict(DEFAULT_CONFIG)
        config["use_ai"] = use_ai
        return config

    config_path = temp_path / "config.json"
    config = json.loads(config_upload.getvalue().decode("utf-8"))
    config["use_ai"] = use_ai
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def _render_results(result: PipelineResult) -> None:
    """Render an ATS-style recruiter dashboard."""
    summary_rows = _candidate_summary_rows(result)
    report = result.merge_report

    metric_a, metric_b, metric_c, metric_d = st.columns(4)
    metric_a.metric("Candidates Read", str(report.candidates_read))
    metric_b.metric("Duplicate Records", str(report.duplicate_records))
    metric_c.metric("Canonical Candidates", str(report.canonical_candidates))
    metric_d.metric("Duplicate Reduction", f"{report.duplicate_reduction:.0%}")

    if result.resume_failures:
        st.error("Resume Parsing Failed")
        st.dataframe(
            [
                {
                    "Candidate": failure.candidate or "-",
                    "Resume File": failure.resume_file,
                    "Reason": failure.reason,
                }
                for failure in result.resume_failures
            ],
            use_container_width=True,
            hide_index=True,
        )

    if result.ai_enabled and result.ai_unavailable:
        st.warning("AI enrichment unavailable. Continuing with rule-based processing.")

    left_panel, right_panel = st.columns([1.1, 1.9], gap="large")

    with left_panel:
        st.subheader("Candidate Summary")
        search_term = st.text_input("Search by name", placeholder="Search candidates")
        status_filter = st.selectbox("Filter by validation status", ["All", "Valid", "Needs Review"])
        sort_descending = st.toggle("Sort by confidence", value=True)

        filtered_rows = _filter_summary_rows(summary_rows, search_term, status_filter, sort_descending)
        st.dataframe(
            [
                {key: value for key, value in row.items() if not key.startswith("_")}
                for row in filtered_rows
            ],
            use_container_width=True,
            hide_index=True,
        )

        candidate_options = {row["Candidate Name"]: row["_index"] for row in filtered_rows}
        if not candidate_options:
            st.warning("No candidates match the current filters.")
            return
        selected_name = st.selectbox("Candidate Details", list(candidate_options))
        selected_index = candidate_options[selected_name]

    with right_panel:
        _render_candidate_detail(result, selected_index)


def _candidate_summary_rows(result: PipelineResult) -> list[dict[str, Any]]:
    """Build dashboard summary rows."""
    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(result.canonical_candidates):
        validation = result.validation_results[index]
        confidence = candidate.overall_confidence
        rows.append(
            {
                "_index": index,
                "_confidence": confidence,
                "Candidate Name": candidate.full_name,
                "Email": candidate.emails[0] if candidate.emails else "",
                "Current Company": _current_company(candidate),
                "Confidence": f"{confidence:.0%}",
                "Validation Status": "Valid" if validation.is_valid else "Needs Review",
            }
        )
    return rows


def _filter_summary_rows(
    rows: list[dict[str, Any]],
    search_term: str,
    status_filter: str,
    sort_descending: bool,
) -> list[dict[str, Any]]:
    """Filter and sort candidate summary rows."""
    normalized_search = search_term.strip().casefold()
    filtered_rows = []
    for row in rows:
        if normalized_search and normalized_search not in row["Candidate Name"].casefold():
            continue
        if status_filter == "Valid" and row["Validation Status"] != "Valid":
            continue
        if status_filter == "Needs Review" and row["Validation Status"] == "Valid":
            continue
        filtered_rows.append(row)

    return sorted(filtered_rows, key=lambda row: row["_confidence"], reverse=sort_descending)


def _render_candidate_detail(result: PipelineResult, index: int) -> None:
    """Render detail panel for one selected candidate."""
    candidate = result.canonical_candidates[index]
    confidence = result.confidence_results[index]
    validation = result.validation_results[index]
    projected_json = result.projected_json[index]

    st.subheader(candidate.full_name)
    status_label = "Validated" if validation.is_valid else "Needs Review"
    status_fn = st.success if validation.is_valid else st.warning
    status_fn(status_label)

    detail_tabs = st.tabs(
        [
            "Profile",
            "Experience",
            "Projects",
            "Skills & Links",
            "Resume",
            "AI Insights",
            "Confidence",
            "Provenance",
            "Validation",
            "Raw JSON",
        ]
    )

    with detail_tabs[0]:
        st.markdown("#### Personal Details")
        st.write(f"**Email:** {_first_or_dash(candidate.emails)}")
        st.write(f"**Phone:** {_first_or_dash(candidate.phones)}")
        st.write(f"**Location:** {_location_text(candidate.location)}")
        st.write(f"**Headline:** {candidate.headline or '-'}")
        st.markdown("#### Merged From")
        for source in _source_labels(result.contributing_sources[index]):
            st.write(f"- {source}")

    with detail_tabs[1]:
        st.markdown("#### Experience")
        if candidate.experience:
            for item in candidate.experience:
                with st.container(border=True):
                    st.write(f"**{item.title or 'Role'}**")
                    st.write(item.company)
                    if item.description:
                        st.caption(item.description)
        else:
            st.info("No experience available.")

        st.markdown("#### Education")
        if candidate.education:
            for item in candidate.education:
                with st.container(border=True):
                    st.write(f"**{item.institution}**")
                    if item.degree:
                        st.caption(item.degree)
        else:
            st.info("No education available.")

    with detail_tabs[2]:
        st.markdown("#### Projects")
        if candidate.projects:
            for project in candidate.projects:
                with st.container(border=True):
                    st.write(f"**{project.name}**")
                    if project.description:
                        st.caption(project.description)
                    if project.technologies:
                        st.write(", ".join(project.technologies))
        else:
            st.info("No projects available.")

        st.markdown("#### Certifications")
        if candidate.certifications:
            badge_html = " ".join(
                f"<span style='display:inline-block;padding:4px 10px;margin:3px;border-radius:999px;background:#ecfdf5;color:#065f46;font-size:13px'>{certification}</span>"
                for certification in candidate.certifications
            )
            st.markdown(badge_html, unsafe_allow_html=True)
        else:
            st.info("No certifications available.")

    with detail_tabs[3]:
        st.markdown("#### Skills")
        if candidate.skills:
            badge_html = " ".join(
                f"<span style='display:inline-block;padding:4px 10px;margin:3px;border-radius:999px;background:#e0f2fe;color:#075985;font-size:13px'>{skill.name}</span>"
                for skill in candidate.skills
            )
            st.markdown(badge_html, unsafe_allow_html=True)
        else:
            st.info("No skills available.")

        st.markdown("#### Links")
        links_by_type = {link.type: link.url for link in candidate.links}
        for label, key in (
            ("GitHub", "github"),
            ("LinkedIn", "linkedin"),
            ("LeetCode", "leetcode"),
            ("HackerRank", "hackerrank"),
            ("Portfolio", "portfolio"),
            ("Other", "other"),
        ):
            if key in links_by_type:
                st.link_button(label, links_by_type[key])

    with detail_tabs[4]:
        st.markdown("#### Resume Information")
        if candidate.resume_summary:
            st.write(candidate.resume_summary)
        else:
            st.info("No resume summary available.")

    with detail_tabs[5]:
        st.markdown("#### AI Insights")
        if not result.ai_enabled:
            st.info("AI enrichment is disabled.")
        else:
            _render_ai_insights(result.ai_insights[index])

    with detail_tabs[6]:
        st.metric("Overall Confidence", f"{candidate.overall_confidence:.0%}")
        st.progress(min(max(candidate.overall_confidence, 0), 1))
        st.markdown("#### Field Confidence")
        for field, score in confidence.field_confidence.items():
            st.write(f"**{field}**")
            st.progress(min(max(score, 0), 1), text=f"{score:.0%}")

    with detail_tabs[7]:
        st.markdown("#### Provenance")
        provenance_rows = [
            {
                "Field": item.field,
                "Source": item.source,
                "Confidence": f"{item.confidence:.0%}",
            }
            for item in candidate.provenance
        ]
        st.dataframe(provenance_rows, use_container_width=True, hide_index=True)

    with detail_tabs[8]:
        if validation.is_valid:
            st.success("Passed validations.")
        else:
            st.error("Validation warnings or errors found.")
            st.dataframe(
                [error.model_dump(mode="json") for error in validation.errors],
                use_container_width=True,
                hide_index=True,
            )

    with detail_tabs[9]:
        with st.expander("Raw JSON", expanded=False):
            st.json(projected_json)
        st.download_button(
            "Download Selected Candidate JSON",
            data=json.dumps(projected_json, indent=2),
            file_name=f"{candidate.candidate_id}.json",
            mime="application/json",
            use_container_width=True,
        )


def _current_company(candidate: Any) -> str:
    """Return current or first known company for a candidate."""
    if not candidate.experience:
        return ""
    return candidate.experience[0].company


def _first_or_dash(values: list[str]) -> str:
    """Return first list value or a placeholder."""
    return values[0] if values else "-"


def _location_text(location: Any) -> str:
    """Return readable location text."""
    if location is None:
        return "-"
    return location.raw or ", ".join(part for part in [location.city, location.region, location.country] if part) or "-"


def _render_ai_insights(insights: dict[str, Any]) -> None:
    """Render collapsible AI insight metadata."""
    has_content = any(
        [
            insights.get("ai_summary"),
            insights.get("strengths"),
            insights.get("suggested_roles"),
            insights.get("suggested_skills"),
            insights.get("potential_missing_information"),
            insights.get("field_confidences"),
            insights.get("responsibilities"),
            insights.get("achievements"),
        ]
    )
    if not has_content:
        st.info("No AI insights available.")
        return

    with st.expander("AI Summary", expanded=True):
        st.write(insights.get("ai_summary") or "-")

    with st.expander("Strengths", expanded=False):
        for item in insights.get("strengths", []):
            st.write(f"- {item}")

    with st.expander("Suggested Roles", expanded=False):
        for item in insights.get("suggested_roles", []):
            st.write(f"- {item}")

    with st.expander("Suggested Skills", expanded=False):
        for item in insights.get("suggested_skills", []):
            st.write(f"- {item}")

    with st.expander("Responsibilities", expanded=False):
        for item in insights.get("responsibilities", []):
            st.write(f"- {item}")

    with st.expander("Achievements", expanded=False):
        for item in insights.get("achievements", []):
            st.write(f"- {item}")

    with st.expander("Potential Missing Information", expanded=False):
        for item in insights.get("potential_missing_information", []):
            st.write(f"- {item}")

    with st.expander("Field Confidence", expanded=False):
        field_rows = insights.get("field_confidences", [])
        if field_rows:
            st.dataframe(field_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No field confidence details available.")


def _source_labels(sources: list[str]) -> list[str]:
    """Return user-facing labels for contributing source names."""
    labels = {
        "recruiter_csv": "Recruiter CSV",
        "csv": "Recruiter CSV",
        "ats_json": "ATS JSON",
        "json": "ATS JSON",
        "github_api": "GitHub",
        "github_profile": "GitHub",
        "github": "GitHub",
        "resume": "Resume",
        "linkedin_profile": "LinkedIn",
        "linkedin": "LinkedIn",
    }
    display_labels: list[str] = []
    seen: set[str] = set()
    for source in sources:
        label = labels.get(source.casefold(), source.replace("_", " ").title())
        key = label.casefold()
        if key not in seen:
            display_labels.append(label)
            seen.add(key)
    return display_labels or ["Unknown"]


if __name__ == "__main__":
    main()
