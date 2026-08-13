export type CommentMap = Record<string, unknown>;

type Caption = { char_caption?: string; caption?: string; centers?: unknown; center?: unknown };

export type CommentTexts = {
  prompt: string;
  uc: string;
  baseCaption: string;
  charCaptions: string[];
};

export function textsFromComment(comment: CommentMap | null | undefined): CommentTexts {
  const source = comment || {};
  const v4 = (source.v4_prompt && typeof source.v4_prompt === "object" ? source.v4_prompt : {}) as CommentMap;
  const cap = (v4.caption && typeof v4.caption === "object" ? v4.caption : {}) as CommentMap;
  const v4neg = (
    source.v4_negative_prompt && typeof source.v4_negative_prompt === "object"
      ? source.v4_negative_prompt
      : {}
  ) as CommentMap;
  const negCap = (v4neg.caption && typeof v4neg.caption === "object" ? v4neg.caption : {}) as CommentMap;
  const chars = Array.isArray(cap.char_captions) ? cap.char_captions : [];
  return {
    prompt: String(source.prompt || cap.base_caption || ""),
    uc: String(source.uc || source.negative_prompt || negCap.base_caption || ""),
    baseCaption: String(cap.base_caption || source.prompt || ""),
    charCaptions: chars
      .map((item) => {
        if (typeof item === "string") return item;
        const row = item as Caption;
        return String(row.char_caption || row.caption || "");
      })
      .filter(Boolean),
  };
}

export function commentFromTexts(base: CommentMap | null | undefined, texts: CommentTexts): CommentMap {
  const next = { ...(base || {}) } as CommentMap;
  const v4 = { ...((next.v4_prompt && typeof next.v4_prompt === "object" ? next.v4_prompt : {}) as CommentMap) };
  const cap = { ...((v4.caption && typeof v4.caption === "object" ? v4.caption : {}) as CommentMap) };
  const previous = Array.isArray(cap.char_captions) ? cap.char_captions : [];
  next.prompt = texts.prompt || texts.baseCaption;
  next.uc = texts.uc;
  next.negative_prompt = texts.uc;
  cap.base_caption = texts.baseCaption || texts.prompt;
  const v4neg = {
    ...((next.v4_negative_prompt && typeof next.v4_negative_prompt === "object"
      ? next.v4_negative_prompt
      : {}) as CommentMap),
  };
  const negCap = {
    ...((v4neg.caption && typeof v4neg.caption === "object" ? v4neg.caption : {}) as CommentMap),
  };
  negCap.base_caption = texts.uc;
  v4neg.caption = negCap;
  next.v4_negative_prompt = v4neg;
  if (texts.charCaptions.length) {
    cap.char_captions = texts.charCaptions.map((line, index) => {
      const prev = previous[index] && typeof previous[index] === "object" ? (previous[index] as Caption) : {};
      const centers = prev.centers || (prev.center ? [prev.center] : [{ x: 0.5, y: 0.5 }]);
      return { char_caption: line, centers };
    });
  }
  v4.caption = cap;
  next.v4_prompt = v4;
  return next;
}

export function workIdOf(raw: unknown): string {
  if (raw == null) return "";
  return String(raw).trim();
}
