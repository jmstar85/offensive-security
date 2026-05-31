"""W0/PR0.1 placeholder — full scrubber freshness test lands in W2a/PR2a.4.

When ``backend/app/safety/conversation_scrubber.py`` lands, this file is
replaced with an AST walker that:
  - reads the L1 pattern table from conversation_scrubber.py,
  - walks every Python file under backend/ for imports of provider SDKs
    (anthropic, openai, google-generativeai, mistralai, …),
  - asserts each imported SDK has a corresponding L1 pattern entry (e.g.
    a new ``mistral_`` token format triggers a CI failure asking the
    author to add the scrubber pattern).

Until W2a lands, this file skips at collection time so pytest sees no
ImportError and the CODEOWNERS coverage test stays green.
"""
import pytest

pytest.skip(
    "conversation_scrubber.py not yet implemented — placeholder until W2a/PR2a.4",
    allow_module_level=True,
)
