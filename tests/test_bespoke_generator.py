"""Tests for bespoke LLM-authored section generation grounded in verified facts."""

from __future__ import annotations

import json
from pathlib import Path

from app.generator import generate_website
from src.engine.llm.adapter import BudgetConfig, FakeProvider, LLMAdapter, LLMResponse


def _seed_design_project(tmp_path: Path) -> Path:
    proj = tmp_path / "projects" / "gentle-paws"
    (proj / "research").mkdir(parents=True, exist_ok=True)
    (proj / "design").mkdir(parents=True, exist_ok=True)

    (proj / "research" / "business-facts.json").write_text(
        json.dumps(
            {
                "project_id": "gentle-paws",
                "facts": [
                    {
                        "fact_id": "f-name",
                        "category": "business_name",
                        "claim_value": "Gentle Paws",
                        "source_url": "https://gentlepaws.example",
                        "source_text_snippet": "Gentle Paws Dog Grooming",
                        "is_verified": True,
                        "status": "verified",
                    },
                    {
                        "fact_id": "f-svc",
                        "category": "services",
                        "claim_value": "Full Groom & Bath",
                        "source_url": "https://gentlepaws.example",
                        "source_text_snippet": "Full Groom & Bath for dogs",
                        "is_verified": True,
                        "status": "verified",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (proj / "design" / "brand.json").write_text(
        json.dumps(
            {
                "project_id": "gentle-paws",
                "business_name": "Gentle Paws",
                "primary_color": "#1B365D",
                "secondary_color": "#F5F2EB",
                "accent_color": "#C97A4B",
                "headline": "Gentle Paws",
                "tagline": "Calm dog grooming",
                "value_proposition": "Full Groom & Bath",
            }
        ),
        encoding="utf-8",
    )
    (proj / "design" / "creative-brief.json").write_text(
        json.dumps(
            {
                "project_id": "gentle-paws",
                "business_name": "Gentle Paws",
                "archetype": "salon",
                "visual_direction": "Warm editorial pet spa",
                "section_sequence": ["header", "hero", "services", "contact", "footer"],
            }
        ),
        encoding="utf-8",
    )
    return proj


def test_bespoke_generator_uses_grounded_llm_section(tmp_path: Path) -> None:
    proj = _seed_design_project(tmp_path)
    bespoke_hero = (
        '<section id="hero" class="ev-hero ev-bespoke-hero" data-section="hero">'
        "<h1>Gentle Paws</h1>"
        "<p>Full Groom &amp; Bath for dogs.</p>"
        "</section>"
    )
    provider = FakeProvider(
        canned_responses=[
            LLMResponse(
                content=json.dumps({"hero": bespoke_hero}),
                prompt_tokens=100,
                completion_tokens=60,
                total_tokens=160,
                model="fake-bespoke",
            )
        ]
    )
    adapter = LLMAdapter(
        provider,
        config=BudgetConfig(
            cache_dir=tmp_path / ".cache",
            ledger_path=tmp_path / "ledger.jsonl",
            db_path=tmp_path / "budget.sqlite3",
        ),
    )

    generate_website(proj, llm_adapter=adapter)
    hero_html = (proj / "website" / "sections" / "hero.html").read_text(encoding="utf-8")
    assert "ev-bespoke-hero" in hero_html
    assert "Full Groom &amp; Bath for dogs." in hero_html


def test_bespoke_generator_rejects_hallucinated_llm_claims_and_falls_back(
    tmp_path: Path,
) -> None:
    proj = _seed_design_project(tmp_path)
    hallucinated_hero = (
        '<section id="hero" class="ev-hero ev-bespoke-hero" data-section="hero">'
        "<h1>Gentle Paws</h1>"
        "<p>#1 Award-Winning Certified Groomer — only £999!</p>"
        "</section>"
    )
    provider = FakeProvider(
        canned_responses=[
            LLMResponse(
                content=json.dumps({"hero": hallucinated_hero}),
                prompt_tokens=100,
                completion_tokens=60,
                total_tokens=160,
                model="fake-bespoke",
            )
        ]
    )
    adapter = LLMAdapter(
        provider,
        config=BudgetConfig(
            cache_dir=tmp_path / ".cache",
            ledger_path=tmp_path / "ledger.jsonl",
            db_path=tmp_path / "budget.sqlite3",
        ),
    )

    generate_website(proj, llm_adapter=adapter)
    hero_html = (proj / "website" / "sections" / "hero.html").read_text(encoding="utf-8")
    assert "ev-bespoke-hero" not in hero_html
    assert "Award-Winning" not in hero_html
    assert "£999" not in hero_html

