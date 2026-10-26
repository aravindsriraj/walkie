// @vitest-environment jsdom
import { expect, test } from "vitest";
import { htmlToMd, mdToHtml } from "./markdown";

const roundtrip = (md: string) => {
  const div = document.createElement("div");
  div.innerHTML = mdToHtml(md);
  return htmlToMd(div);
};

test("bold and code render as real formatting and survive a round trip", () => {
  expect(mdToHtml("Click **Sign in**, type `Q4`.")).toBe("Click <strong>Sign in</strong>, type <code>Q4</code>.");
  expect(roundtrip("Click **Sign in**, then type `Q4 Launch`.")).toBe("Click **Sign in**, then type `Q4 Launch`.");
});

test("text from the model can't inject HTML", () => {
  expect(mdToHtml('<img src=x onerror="alert(1)"> **<b>x</b>**')).toBe(
    "&lt;img src=x onerror=\"alert(1)\"&gt; <strong>&lt;b&gt;x&lt;/b&gt;</strong>",
  );
  expect(roundtrip("a < b & c > d")).toBe("a < b & c > d");
});

test("what the browser produces while editing maps back to the supported Markdown", () => {
  const div = document.createElement("div");
  div.innerHTML = "Press&nbsp;<b>Save</b><i>now</i><div>then <span>wait</span></div><br>done<strong> </strong>";
  expect(htmlToMd(div)).toBe("Press **Save**now then wait done ");
});
