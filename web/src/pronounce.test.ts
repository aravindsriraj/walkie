import { expect, test } from "vitest";
import { formatPronunciations, parsePronunciations } from "./pronounce";

test("each line is word = how to say it; lines without both halves are skipped", () => {
  expect(parsePronunciations(" SQL = sequel \nnginx=engine x\n\njust a word\n= nothing\nA = B = C")).toEqual({
    SQL: "sequel", nginx: "engine x", A: "B = C",
  });
});

test("formatting gives back the same lines", () => {
  const words = { SQL: "sequel", nginx: "engine x" };
  expect(parsePronunciations(formatPronunciations(words))).toEqual(words);
  expect(formatPronunciations(words)).toBe("SQL = sequel\nnginx = engine x");
});
