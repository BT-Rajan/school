import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

/**
 * FR-I1: no user-facing text is written into the screens; it all comes from the translations.
 * Parses every screen and looks for letters in JSX text and in the attributes people read
 * (labels, placeholders, titles, alt text). Names of languages and fixed technical terms are
 * allowed.
 */
const ALLOWED = new Set(["English", "العربية", "IP", "PDF", "CSV", "ZIP", "JSON", "Excel", "D/MM/YYYY", "KB", "MB"]);
const READ_ATTRIBUTES = new Set(["aria-label", "placeholder", "title", "alt", "label"]);

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return path.endsWith(".tsx") && !path.endsWith(".test.tsx") ? [path] : [];
  });
}

function problems(path: string): string[] {
  const source = ts.createSourceFile(path, readFileSync(path, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found: string[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isJsxText(node)) {
      const text = node.text.trim();
      if (/\p{L}{2,}/u.test(text) && !ALLOWED.has(text)) found.push(text);
    } else if (ts.isJsxAttribute(node) && node.initializer && ts.isStringLiteral(node.initializer)) {
      const name = node.name.getText(source);
      const value = node.initializer.text;
      if (READ_ATTRIBUTES.has(name) && /\p{L}{2,}/u.test(value) && !ALLOWED.has(value)) found.push(`${name}="${value}"`);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

describe("translations", () => {
  it("cover every piece of text on the screens", () => {
    const report: Record<string, string[]> = {};
    for (const path of files(__dirname)) {
      const found = problems(path);
      if (found.length) report[path.replace(__dirname, "src")] = found;
    }
    expect(report).toEqual({});
  });
});
