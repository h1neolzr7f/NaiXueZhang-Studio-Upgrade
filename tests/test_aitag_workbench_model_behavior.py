from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_model(script_body: str) -> dict:
    script = f"""
    const fs = require("fs");
    const source = fs.readFileSync("web/tag-assets-model.js", "utf8");
    const url = "data:text/javascript;base64," + Buffer.from(source).toString("base64");
    import(url).then(async (model) => {{
      {script_body}
    }}).catch((error) => {{
      console.error(error && error.stack || error);
      process.exit(1);
    }});
    """
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    return json.loads(completed.stdout)


def test_model_preserves_multi_image_indices_and_safe_default_filter() -> None:
    result = _run_model(
        """
        const detail = model.normalizeDetail({
          generation_calls: 0,
          work: {
            id: "work-42",
            images: [
              { image_index: 0, url: "https://images.test/blue.png" },
              { image_index: 1, url: "https://images.test/red.png" },
            ],
          },
        }, {});
        const works = [
          { id: "safe", AI_type: "NovelAI", tags: ["1girl"] },
          { id: "adult", AI_type: "NovelAI", tags: ["rating:explicit"] },
          { id: "other", AI_type: "Stable Diffusion", tags: ["1girl"] },
        ];
        console.log(JSON.stringify({
          imageIndices: detail.images.map((image) => image.imageIndex),
          safeDefault: model.visibleOnlineItems(works).map(model.workIdFrom),
          explicitAdultOptIn: model.visibleOnlineItems(works, { naiOnly: true, safeOnly: false }).map(model.workIdFrom),
        }));
        """
    )

    assert result == {
        "imageIndices": [0, 1],
        "safeDefault": ["safe"],
        "explicitAdultOptIn": ["safe", "adult"],
    }


def test_model_preserves_character_candidate_slot_and_license_provenance() -> None:
    result = _run_model(
        """
        const detail = model.normalizeDetail({
          generation_calls: 0,
          source: "aitag-online",
          work: {
            id: "work-42",
            external_url: "https://aitag.win/i/work-42",
            metadata: { license: "CC-BY-4.0" },
            images: [{ image_index: 0, url: "https://images.test/pair.png" }],
          },
          character_candidates: [{
            candidate_id: "work-42/pair/slot-1",
            image_index: 0,
            slot_index: 1,
            label: "Second character",
            caption: "1boy, red hair",
          }],
        }, {});
        console.log(JSON.stringify({
          candidate: detail.characterCandidates[0],
          license: detail.license,
        }));
        """
    )

    assert result == {
        "candidate": {
            "candidateId": "work-42/pair/slot-1",
            "imageIndex": 0,
            "slotIndex": 1,
            "label": "Second character",
            "caption": "1boy, red hair",
            "role": "",
        },
        "license": {
            "name": "CC-BY-4.0",
            "status": "source-provided",
            "sourceUrl": "https://aitag.win/i/work-42",
        },
    }


def test_model_accepts_only_zero_generation_complete_draft_responses() -> None:
    result = _run_model(
        """
        const accepted = model.normalizeDraftResponse({
          ok: true,
          draft: { comment: {}, params: {}, source: { provider: "aitag-online" } },
          draft_id: "0123456789abcdef",
          recipe: { recipe_id: "recipe-42" },
          studio_url: "/studio?aitag=1&remix=1&draft=0123456789abcdef",
          generation_calls: 0,
        });
        let paidError = "";
        let emptyError = "";
        let missingIdError = "";
        try {
          model.normalizeDraftResponse({ ok: true, draft: { comment: {} }, generation_calls: 1, draft_id: "0123456789abcdef", studio_url: "/studio?draft=0123456789abcdef" });
        } catch (error) { paidError = String(error.message || error); }
        try {
          model.normalizeDraftResponse({ ok: true, generation_calls: 0, draft_id: "0123456789abcdef" });
        } catch (error) { emptyError = String(error.message || error); }
        try {
          model.normalizeDraftResponse({
            ok: true,
            draft: { comment: {} },
            generation_calls: 0,
            studio_url: "/studio?aitag=1",
          });
        } catch (error) { missingIdError = String(error.message || error); }
        console.log(JSON.stringify({
          generationCalls: accepted.generationCalls,
          studioUrl: accepted.studioUrl,
          draftId: accepted.draftId,
          recipeId: accepted.recipe.recipe_id,
          paidRejected: paidError.length > 0,
          emptyRejected: emptyError.length > 0,
          missingIdRejected: missingIdError.length > 0,
        }));
        """
    )

    assert result == {
        "generationCalls": 0,
        "studioUrl": "/studio?aitag=1&remix=1&draft=0123456789abcdef",
        "draftId": "0123456789abcdef",
        "recipeId": "recipe-42",
        "paidRejected": True,
        "emptyRejected": True,
        "missingIdRejected": True,
    }


def test_model_accepts_transient_zero_generation_draft_when_persistence_failed() -> None:
    result = _run_model(
        """
        const accepted = model.normalizeDraftResponse({
          ok: true,
          draft: { comment: { prompt: "cafe" }, params: {}, source: { provider: "aitag-online" } },
          draft_id: "",
          persisted: false,
          persistence_warning: "disk full",
          studio_url: "/studio?aitag=1&remix=1",
          generation_calls: 0,
        });
        console.log(JSON.stringify({
          persisted: accepted.persisted,
          draftId: accepted.draftId,
          studioUrl: accepted.studioUrl,
          warning: accepted.persistenceWarning,
        }));
        """
    )

    assert result == {
        "persisted": False,
        "draftId": "",
        "studioUrl": "/studio?aitag=1&remix=1",
        "warning": "disk full",
    }


def test_workbench_calls_server_draft_without_requiring_an_existing_local_draft() -> None:
    source = (ROOT / "web" / "tag-assets.js").read_text(encoding="utf-8")
    studio = (ROOT / "web" / "studio.js").read_text(encoding="utf-8")

    assert "}/draft`" in source
    assert "localStorage.setItem(DRAFT_KEY" in source
    assert "hasDraft" not in source
    assert "/api/nai/generate" not in source
    assert "/apply" not in source
    assert "draftId: normalized.draftId" in source
    assert "/api/nai/aitag/drafts/" in studio
    assert "restoreDraftFromServer" in studio
    assert "restoreLatestServerDraft" in studio
