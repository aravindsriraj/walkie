/** Pronunciations as people type them, one "word = how to say it" per line, to and from the server's map. */
export function parsePronunciations(text: string): Record<string, string> {
  const words: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const at = line.indexOf("=");
    const word = line.slice(0, at).trim();
    const say = line.slice(at + 1).trim();
    if (at > 0 && word && say) words[word] = say;
  }
  return words;
}

export function formatPronunciations(words: Record<string, string>): string {
  return Object.entries(words).map(([word, say]) => `${word} = ${say}`).join("\n");
}
