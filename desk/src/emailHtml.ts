import DOMPurify from "dompurify";

// Email HTML is untrusted. A private instance keeps these settings and hooks
// apart from any other user of DOMPurify on the page.
const purify = DOMPurify(window);

/**
 * Sanitize an email's HTML for display in the email frame.
 *
 * The frame is isolated from the page, so this keeps what makes an email look
 * right (style blocks, classes, ids) and drops the rest. Returns an empty
 * string when the browser can't sanitize, rather than the raw HTML.
 */
export function sanitizeEmailHtml(html: string | null | undefined): string {
  if (!html || !purify.isSupported) return "";
  return purify.sanitize(html, {
    USE_PROFILES: { html: true },
    // Keeps a leading <style> that would otherwise be hoisted into <head> and dropped.
    FORCE_BODY: true,
    // Forms can't be submitted from the frame; drop the controls with them.
    FORBID_TAGS: [
      "form",
      "input",
      "button",
      "select",
      "option",
      "optgroup",
      "textarea",
      "datalist",
      "fieldset",
      "legend",
      "label",
      "output",
    ],
    // rel: links open through the frame's <base target="_blank">, whose implied
    // noopener an explicit rel could undo. download: an email doesn't get to
    // choose how a link is saved.
    FORBID_ATTR: ["rel", "download"],
  });
}

/**
 * Sanitize an email quoted in a reply.
 *
 * Unlike the email frame, the quote lives in the page itself, so it keeps
 * only plain formatting: no style blocks, classes, ids, names or data
 * attributes. Inline styles stay, for the email's formatting.
 */
export function sanitizeQuotedEmail(html: string | null | undefined): string {
  if (!html || !purify.isSupported) return "";
  return purify.sanitize(html, {
    ALLOWED_TAGS: [
      "p",
      "br",
      "div",
      "span",
      "b",
      "strong",
      "i",
      "em",
      "u",
      "s",
      "strike",
      "del",
      "ins",
      "sub",
      "sup",
      "small",
      "big",
      "tt",
      "code",
      "kbd",
      "mark",
      "abbr",
      "cite",
      "q",
      "h1",
      "h2",
      "h3",
      "h4",
      "h5",
      "h6",
      "hr",
      "ul",
      "ol",
      "li",
      "dl",
      "dt",
      "dd",
      "pre",
      "blockquote",
      "table",
      "caption",
      "colgroup",
      "col",
      "thead",
      "tbody",
      "tfoot",
      "tr",
      "td",
      "th",
      "a",
      "img",
      "font",
      "center",
    ],
    ALLOWED_ATTR: [
      "href",
      "src",
      "alt",
      "title",
      "width",
      "height",
      "align",
      "valign",
      "style",
      "colspan",
      "rowspan",
      "span",
      "border",
      "cellpadding",
      "cellspacing",
      "bgcolor",
      "color",
      "face",
      "size",
      "dir",
      "lang",
      "start",
      "type",
    ],
    ALLOW_DATA_ATTR: false,
    ALLOW_ARIA_ATTR: false,
  });
}
