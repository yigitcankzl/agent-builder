import unittest

from builder.fallback_llm import PROMPT


class FallbackPromptContract(unittest.TestCase):
    def test_cross_node_api_values_are_mapped(self):
        self.assertIn("API results are not reliably visible to a later node", PROMPT)
        self.assertIn("response_mapping", PROMPT)
        self.assertIn("no required request field may be left for the model to guess", PROMPT)

    def test_already_identified_callers_are_not_reverified(self):
        self.assertIn("If the brief says the caller is already identified", PROMPT)


if __name__ == "__main__":
    unittest.main()
