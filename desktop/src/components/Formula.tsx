import { useMemo } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import { cx } from "./ui";

export function Formula({
  latex,
  display = true,
  className,
}: {
  latex: string;
  display?: boolean;
  className?: string;
}) {
  const html = useMemo(() => {
    try {
      return katex.renderToString(latex, {
        displayMode: display,
        throwOnError: false,
        output: "html",
        strict: "ignore",
      });
    } catch {
      return latex;
    }
  }, [display, latex]);

  return (
    <div
      className={cx("overflow-x-auto text-text", className)}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
