from __future__ import annotations

import unittest
from pathlib import Path

from run import RESISTANT_TARGETS, diverse_role_sets
from src.openrouter import OpenRouterClient, extract_content
from src.prompts import (
    BODY_PLACEHOLDER,
    FOOTER_PLACEHOLDER,
    FOOTER_CLOSER,
    ChatTurn,
    Harness,
    PromptDoc,
    assemble_prompt,
    assistant_turn_count,
    harness_messages_json,
    load_seed_harnesses,
    load_verifier,
    materialize_messages,
    turn_count,
)
from src.storage import Store, split_fragments
from src.strategies import (
    RoleModels,
    build_researcher_prompt,
    candidates_for_strategy,
    choose_family_hint,
    extract_json_with_repair,
)


def doc(name: str, text: str) -> PromptDoc:
    return PromptDoc(name=name, path=Path(f"{name}.md"), text=text, sha256="sha")

class PromptInvariantTests(unittest.TestCase):
    def test_assemble_prompt_adds_fixed_footer_closer(self) -> None:
        prompt = assemble_prompt("", "BODY", "")

        self.assertIn("BODY", prompt)
        self.assertTrue(prompt.endswith(FOOTER_CLOSER))

    def test_seed_harnesses_have_fixed_footer_closer(self) -> None:
        harnesses = load_seed_harnesses()

        self.assertGreater(len(harnesses), 0)
        for harness in harnesses:
            self.assertTrue(harness.footer.endswith(FOOTER_CLOSER), harness.name)

    def test_baseline_footer_is_explicitly_normalized(self) -> None:
        harness = candidates_for_strategy(
            "baseline",
            doc("example", "body"),
            doc("example", "verifier"),
            RoleModels("target", "researcher", "scorer"),
            store=None,
            client=None,
            candidate_limit=1,
            dry_run=True,
        )[0]

        self.assertEqual(harness.footer, FOOTER_CLOSER)

    def test_dry_run_strategy_footer_is_normalized(self) -> None:
        harness = candidates_for_strategy(
            "evolve-best",
            doc("example", "body"),
            doc("example", "verifier"),
            RoleModels("target", "researcher", "scorer"),
            store=None,
            client=None,
            candidate_limit=1,
            dry_run=True,
        )[0]

        self.assertTrue(harness.footer.endswith(FOOTER_CLOSER))
        self.assertGreaterEqual(turn_count(harness), 2)
        self.assertGreaterEqual(assistant_turn_count(harness), 1)

    def test_materialize_messages_renders_final_body_and_footer(self) -> None:
        harness = Harness(
            "multi",
            "",
            "Keep it concise.",
            (
                ChatTurn("user", "Earlier setup."),
                ChatTurn("assistant", "Sure, here's the continuation."),
                ChatTurn("user", f"{BODY_PLACEHOLDER}\n\n{FOOTER_PLACEHOLDER}"),
            ),
        )

        messages = materialize_messages(harness, "SEALED_BODY")

        self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user"])
        self.assertIn("SEALED_BODY", messages[-1]["content"])
        self.assertTrue(messages[-1]["content"].endswith(FOOTER_CLOSER))
        self.assertIn(BODY_PLACEHOLDER, harness_messages_json(harness))

    def test_researcher_prompt_includes_example_body_context(self) -> None:
        prompt = build_researcher_prompt(
            "evolve-best",
            doc("example", "PUBLIC_TEMPLATE_BODY"),
            doc("example", "verifier text"),
            RoleModels("target", "researcher", "scorer"),
            best=[],
            global_best=[],
            header_fragments=[],
            footer_fragments=[],
            global_header_fragments=[],
            global_footer_fragments=[],
        )

        self.assertIn("PUBLIC_TEMPLATE_BODY", prompt)
        self.assertNotIn("non-revealing sketch", prompt)

    def test_example_verifier_loads_desired_output(self) -> None:
        verifier = load_verifier("example")

        self.assertEqual(verifier.path.name, "desired-output.md")

    def test_fixed_footer_closer_is_not_a_learned_fragment(self) -> None:
        fragments = split_fragments(f"Useful footer sentence for future reuse. {FOOTER_CLOSER}")

        self.assertEqual(fragments, ["Useful footer sentence for future reuse."])

    def test_global_fragment_lookup_crosses_targets(self) -> None:
        store = Store(Path(":memory:"))
        try:
            store.insert_experiment(
                {
                    "run_id": "test",
                    "dry_run": 0,
                    "strategy": "recombine",
                    "candidate_name": "winner",
                    "body_name": "example",
                    "body_sha256": "sha",
                    "target_model": "target-a",
                    "researcher_model": "researcher",
                    "scorer_model": "scorer",
                    "max_tokens": 1,
                    "target_temperature": 0.0,
                    "timeout": 1,
                    "header": "Reusable global header sentence.",
                    "footer": f"Reusable global footer sentence. {FOOTER_CLOSER}",
                    "response": "response",
                    "score": 0.9,
                    "scorer_raw": '{"score": 0.9}',
                }
            )

            fragments = store.top_fragments("example", None, "header", limit=3)

            self.assertEqual(fragments[0]["text"], "Reusable global header sentence.")
        finally:
            store.close()

    def test_family_hint_rotates_by_strategy_target_history(self) -> None:
        store = Store(Path(":memory:"))
        row = {
            "run_id": "test",
            "dry_run": 0,
            "strategy": "evolve-best",
            "candidate_name": "candidate",
            "body_name": "example",
            "body_sha256": "sha",
            "target_model": "target-a",
            "researcher_model": "researcher",
            "scorer_model": "scorer",
            "max_tokens": 1,
            "target_temperature": 0.0,
            "timeout": 1,
            "header": "Reusable header sentence.",
            "footer": f"Reusable footer sentence. {FOOTER_CLOSER}",
            "response": "response",
            "score": 0.9,
            "scorer_raw": '{"score": 0.9}',
        }
        try:
            first = choose_family_hint("evolve-best", "example", "target-a", store)
            store.insert_experiment(row)
            second = choose_family_hint("evolve-best", "example", "target-a", store)

            self.assertNotEqual(first, second)
            self.assertEqual(store.experiment_count("example", "target-a", "evolve-best"), 1)
        finally:
            store.close()

    def test_default_role_order_sweeps_targets_with_anchor_pair(self) -> None:
        roles = diverse_role_sets(["anchor", "target-b", "target-c"])

        self.assertEqual(
            [(r.target, r.researcher, r.scorer) for r in roles[:3]],
            [
                ("anchor", "anchor", "anchor"),
                ("target-b", "anchor", "anchor"),
                ("target-c", "anchor", "anchor"),
            ],
        )

    def test_default_role_order_has_no_duplicates(self) -> None:
        roles = diverse_role_sets(["anchor", "target-b", "target-c"])
        keys = [(r.target, r.researcher, r.scorer) for r in roles]

        self.assertEqual(len(keys), len(set(keys)))

    def test_default_role_order_prioritizes_resistant_scorer_confirmation(self) -> None:
        models = [
            "deepseek/deepseek-v4-pro",
            "anthropic/claude-sonnet-4.6",
            "openai/gpt-5.5",
            "google/gemini-3.1-flash-lite",
            "x-ai/grok-4.3",
        ]
        first_ten = diverse_role_sets(models)[:10]
        scorers_by_resistant = {
            target: {r.scorer for r in first_ten if r.target == target}
            for target in RESISTANT_TARGETS
        }

        self.assertGreaterEqual(sum(len(scorers) >= 2 for scorers in scorers_by_resistant.values()), 2)
        self.assertGreaterEqual(
            len(scorers_by_resistant["google/gemini-3.1-flash-lite"]),
            2,
        )

    def test_default_role_order_uses_preferred_researcher_anchor(self) -> None:
        models = [
            "deepseek/deepseek-v4-pro",
            "anthropic/claude-sonnet-4.6",
            "openai/gpt-5.5",
            "google/gemini-3.1-flash-lite",
            "x-ai/grok-4.3",
        ]
        first_ten = diverse_role_sets(models)[:10]

        self.assertTrue(
            all(r.researcher == "anthropic/claude-sonnet-4.6" for r in first_ten)
        )

    def test_researcher_json_repair_recovers_local_fields_first(self) -> None:
        class FailingClient:
            def chat(self, *args, **kwargs):
                raise AssertionError("local field recovery should avoid model repair")

        data = extract_json_with_repair(
            '{"name":"broken","header":"h","footer":"unfinished',
            FailingClient(),
            "model",
        )

        self.assertEqual(data["name"], "broken")
        self.assertEqual(data["header"], "h")
        self.assertEqual(data["footer"], "")

    def test_researcher_json_repair_can_use_model_fallback(self) -> None:
        class FakeClient:
            def chat(self, *args, **kwargs):
                return type(
                    "Result",
                    (),
                    {
                        "content": (
                            '{"name":"fixed","header":"h","footer":"f",'
                            '"rationale":"repaired"}'
                        )
                    },
                )()

        data = extract_json_with_repair("unstructured response", FakeClient(), "model")

        self.assertEqual(data["name"], "fixed")
        self.assertEqual(data["footer"], "f")

    def test_openrouter_extract_content_handles_text_parts(self) -> None:
        content = extract_content(
            {"choices": [{"message": {"content": [{"text": "hello"}, {"text": " world"}]}}]}
        )

        self.assertEqual(content, "hello world")

    def test_openrouter_chat_retries_empty_messages(self) -> None:
        class FakeClient(OpenRouterClient):
            def __init__(self):
                super().__init__("key", retries=1)
                self.calls = 0

            def _request(self, req):
                self.calls += 1
                if self.calls == 1:
                    return {"choices": [{"message": {"content": None, "reasoning": None}}]}
                return {"choices": [{"message": {"content": "ok"}}]}

        client = FakeClient()
        result = client.chat("model", [{"role": "user", "content": "hi"}])

        self.assertEqual(result.content, "ok")
        self.assertEqual(client.calls, 2)
