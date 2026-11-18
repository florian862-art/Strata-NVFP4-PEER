"""serve/test_quoted_think_end.py - a `</think>` the model only NAMES is still reasoning.

#537 recognises a quoted end tag by the quote character written DIRECTLY before it.  A model that
types the tag escaped - "the marker `\\n</think>`" - puts its quote two characters back: the
character before the tag is then the "n" of the typed "\\n", and the thinking is cut where the model
had only named the marker.  The character after the tag is what actually distinguishes the two
cases (the template always follows a real end with a line break), so the quote is looked for in a
short window behind the tag.
"""
import unittest

from serve.frontend import OutputParser

THINK_END = "</think>"


def run(text, width):
    p = OutputParser(thinking=True, tools=[{"name": "run_commands"}])
    evs = []
    for i in range(0, len(text), width):
        evs += p.feed(text[i:i + width])
    return evs + p.finish()


def joined(evs, kind):
    return "".join(e.text for e in evs if e.kind == kind)


class EscapedQuotedThinkEnd(unittest.TestCase):
    def test_an_escaped_mention_stays_reasoning(self):
        # the shape taken from a live turn: the model writes the tag escaped, mid-sentence
        for quote in ("the marker `\\n" + THINK_END + "\\n\\n` appears once",
                      'der Marker "`\\n' + THINK_END + '\\n"` steht einmal',
                      "say \"\\n" + THINK_END + "\\n\" and stop"):
            text = "plan\n" + quote + "\ndone\n" + THINK_END + "\n\nanswer"
            for width in (1, 2, 3, 7, 100_000):
                with self.subTest(quote=quote[:20], width=width):
                    evs = run(text, width)
                    self.assertEqual(joined(evs, "reasoning"), "plan\n" + quote + "\ndone\n")
                    self.assertEqual(joined(evs, "content"), "answer")

    def test_a_real_end_after_an_escaped_mention_still_ends_the_thinking(self):
        # the same turn carries BOTH: the named tag, then the real end.  The real one must win.
        text = ("the marker `\\n" + THINK_END + "\\n\\n` appears once\n" + THINK_END + "\n\nthe answer")
        for width in (1, 2, 3, 7, 100_000):
            with self.subTest(width=width):
                evs = run(text, width)
                self.assertEqual(joined(evs, "reasoning"),
                                 "the marker `\\n" + THINK_END + "\\n\\n` appears once\n")
                self.assertEqual(joined(evs, "content"), "the answer")

    def test_an_end_with_no_quote_nearby_is_unaffected(self):
        text = "reasoning without any quote\n" + THINK_END + "\n\nanswer"
        for width in (1, 5, 100_000):
            with self.subTest(width=width):
                evs = run(text, width)
                self.assertEqual(joined(evs, "reasoning"), "reasoning without any quote\n")
                self.assertEqual(joined(evs, "content"), "answer")


if __name__ == "__main__":
    unittest.main()
