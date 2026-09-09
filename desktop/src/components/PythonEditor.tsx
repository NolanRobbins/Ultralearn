import CodeMirror from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import { EditorView, keymap } from "@codemirror/view";
import { Prec } from "@codemirror/state";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { tags as t } from "@lezer/highlight";

const highlight = HighlightStyle.define([
  { tag: t.comment, color: "#7d8b9c", fontStyle: "italic" },
  { tag: t.keyword, color: "#3ecf8e" },
  { tag: t.controlKeyword, color: "#3ecf8e" },
  { tag: t.definitionKeyword, color: "#3ecf8e" },
  { tag: t.operatorKeyword, color: "#3ecf8e" },
  { tag: t.string, color: "#7dd3fc" },
  { tag: t.number, color: "#fbbf24" },
  { tag: t.bool, color: "#fb7185" },
  { tag: t.null, color: "#fb7185" },
  { tag: t.definition(t.variableName), color: "#c4b5fd" },
  { tag: t.function(t.variableName), color: "#c4b5fd" },
  { tag: t.className, color: "#fbbf24" },
  { tag: t.typeName, color: "#a7b4c4" },
  { tag: t.operator, color: "#a7b4c4" },
  { tag: t.punctuation, color: "#7d8b9c" },
  { tag: t.variableName, color: "#e9eef5" },
  { tag: t.propertyName, color: "#7dd3fc" },
  { tag: t.self, color: "#fb7185" },
]);

const dark = EditorView.theme(
  {
    "&": {
      height: "100%",
      backgroundColor: "#0b0e13",
      color: "#e9eef5",
      fontSize: "13px",
    },
    ".cm-scroller": {
      fontFamily: 'ui-monospace, "SF Mono", "JetBrains Mono", Menlo, monospace',
      lineHeight: "1.55",
    },
    ".cm-content": { caretColor: "#3ecf8e", padding: "12px 0" },
    ".cm-gutters": {
      backgroundColor: "#0b0e13",
      color: "#7d8b9c",
      border: "none",
    },
    ".cm-activeLine": { backgroundColor: "#141924" },
    ".cm-activeLineGutter": { backgroundColor: "#141924", color: "#a7b4c4" },
    "&.cm-focused .cm-cursor": { borderLeftColor: "#3ecf8e" },
    ".cm-selectionBackground, &.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground":
      { backgroundColor: "#123026" },
    ".cm-matchingBracket": { outline: "1px solid #3a465c" },
  },
  { dark: true },
);

export function PythonEditor({
  value,
  onChange,
  onRun,
}: {
  value: string;
  onChange: (value: string) => void;
  onRun?: () => void;
}) {
  return (
    <CodeMirror
      value={value}
      height="100%"
      theme="none"
      basicSetup={{
        lineNumbers: true,
        foldGutter: false,
        highlightActiveLine: true,
        autocompletion: false,
        tabSize: 4,
      }}
      extensions={[
        python(),
        dark,
        syntaxHighlighting(highlight),
        Prec.high(
          keymap.of([
            {
              key: "Mod-Enter",
              run: () => {
                onRun?.();
                return true;
              },
            },
          ]),
        ),
      ]}
      onChange={onChange}
      className="python-editor h-full min-h-0 overflow-hidden"
    />
  );
}
