import { useEffect, useRef } from "react";
import { htmlToMd, mdToHtml } from "./markdown";

/**
 * One paragraph of editable text that shows **bold** and `code` as real formatting.
 * Uncontrolled while typing (re-rendering HTML would move the caret); it only redraws when
 * the value changes from outside, such as undo or a merge.
 */
export function RichText({ value, onChange, placeholder, className = "", label }: {
  value: string;
  onChange: (md: string) => void;
  placeholder?: string;
  className?: string;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const emitted = useRef<string | null>(null);

  useEffect(() => {
    if (ref.current && value !== emitted.current) {
      ref.current.innerHTML = mdToHtml(value);
      emitted.current = value;
    }
  }, [value]);

  const emit = () => {
    const md = htmlToMd(ref.current!);
    emitted.current = md;
    onChange(md);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const mod = e.metaKey || e.ctrlKey;
    if (e.key === "Enter") return e.preventDefault(); // one paragraph per field
    if (mod && (e.key === "i" || e.key === "u")) return e.preventDefault(); // only bold and code exist
    if (mod && e.key === "e") {
      // ⌘E wraps the selection in code, like the label of a value to type
      e.preventDefault();
      const sel = getSelection();
      if (!sel?.rangeCount || sel.isCollapsed) return;
      const code = document.createElement("code");
      code.append(sel.getRangeAt(0).extractContents());
      sel.getRangeAt(0).insertNode(code);
      emit();
    }
  };

  return (
    <div
      ref={ref}
      role="textbox"
      aria-label={label}
      aria-multiline="false"
      contentEditable
      suppressContentEditableWarning
      spellCheck
      data-placeholder={placeholder}
      className={`richtext ${className}`}
      onInput={emit}
      onKeyDown={onKeyDown}
      onPaste={(e) => {
        e.preventDefault(); // paste as plain text so foreign markup never gets in
        document.execCommand("insertText", false, e.clipboardData.getData("text/plain").replace(/\s+/g, " "));
      }}
    />
  );
}
