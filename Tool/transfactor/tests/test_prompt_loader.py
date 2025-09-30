import unittest
from core.utils.prompt_loader import PromptLoader


class TestPromptLoader(unittest.TestCase):

    def test_prompt_loader(self):
        PromptLoader.from_paths(["../core/prompts"])
        base_system_prompt = PromptLoader.get_prompt(
            "base/system.prompt",
        )
        self.assertTrue(len(base_system_prompt) > 0)


if __name__ == "__main__":
    unittest.main()
