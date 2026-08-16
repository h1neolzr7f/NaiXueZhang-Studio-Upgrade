from __future__ import annotations

from typing import Literal

Access = Literal["primary", "adjacent", "restricted", "deny"]

PERSONAS: dict[str, dict[str, Access]] = {
    "acquire": {
        "provider.search": "primary",
        "provider.fetch": "primary",
        "crawler.start": "restricted",
        "crawler.stop": "restricted",
        "acquire.plan": "restricted",
        "asset.preview": "primary",
        "asset.materialize": "adjacent",
        "library.search": "adjacent",
        "library.collection.add": "adjacent",
        "library.delete": "deny",
        "transform.character_replace": "deny",
        "nai.generate": "deny",
        "nai.generate_paid": "deny",
        "post.upscale": "deny",
        "publish.pixiv": "deny",
    },
    "library": {
        "library.search": "primary",
        "library.collection.add": "primary",
        "asset.preview": "primary",
        "asset.materialize": "adjacent",
        "provider.search": "adjacent",
        "provider.fetch": "adjacent",
        "transform.character_replace": "restricted",
        "library.delete": "restricted",
        "crawler.start": "deny",
        "crawler.stop": "deny",
        "acquire.plan": "deny",
        "nai.generate": "deny",
        "nai.generate_paid": "deny",
        "post.upscale": "adjacent",
        "publish.pixiv": "deny",
    },
    "studio": {
        "nai.generate": "primary",
        "nai.generate_paid": "restricted",
        "transform.character_replace": "primary",
        "post.upscale": "adjacent",
        "library.search": "adjacent",
        "asset.preview": "adjacent",
        "asset.materialize": "adjacent",
        "provider.search": "adjacent",
        "provider.fetch": "restricted",
        "library.collection.add": "adjacent",
        "library.delete": "deny",
        "crawler.start": "deny",
        "crawler.stop": "deny",
        "acquire.plan": "deny",
        "publish.pixiv": "restricted",
    },
    "service": {
        "library.search": "primary",
        "asset.preview": "primary",
        "provider.search": "primary",
        "provider.fetch": "primary",
        "library.collection.add": "deny",
        "library.delete": "deny",
        "asset.materialize": "deny",
        "crawler.start": "deny",
        "crawler.stop": "deny",
        "acquire.plan": "deny",
        "transform.character_replace": "deny",
        "nai.generate": "deny",
        "nai.generate_paid": "deny",
        "post.upscale": "deny",
        "publish.pixiv": "deny",
    },
    "orchestrator": {
        # Orchestrator never executes. It may only plan/route/request delegation.
        spec_id: "deny"
        for spec_id in (
            "provider.search",
            "provider.fetch",
            "crawler.start",
            "crawler.stop",
            "asset.preview",
            "asset.materialize",
            "library.search",
            "library.collection.add",
            "library.delete",
            "transform.character_replace",
            "nai.generate",
            "nai.generate_paid",
            "post.upscale",
            "publish.pixiv",
            "acquire.plan",
        )
    },
}


def persona_defaults(persona_id: str) -> dict[str, Access]:
    return dict(PERSONAS.get(str(persona_id or ""), {}))
