// Step text is stored as a tiny Markdown subset (**bold**, `code`) and edited as real formatting.

const escape = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** Markdown subset → HTML. Escapes first, so model-written text can never inject markup. */
export function mdToHtml(md: string): string {
  return escape(md)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}

/** What the browser produced while editing → the Markdown subset. Anything else becomes plain text. */
export function htmlToMd(root: Node): string {
  let out = "";
  root.childNodes.forEach((node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      out += (node.textContent ?? "").replace(/\u00a0/g, " ");
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const tag = (node as Element).tagName;
    const inner = htmlToMd(node);
    if (tag === "STRONG" || tag === "B") out += inner.trim() ? `**${inner}**` : inner;
    else if (tag === "CODE") out += inner.trim() ? `\`${inner}\`` : inner;
    else if (tag === "BR") out += " ";
    else if (tag === "DIV" || tag === "P") out += (out && !out.endsWith(" ") ? " " : "") + inner;
    else out += inner;
  });
  return out;
}
