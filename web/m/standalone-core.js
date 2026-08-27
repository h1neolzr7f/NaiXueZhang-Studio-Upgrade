/**
 * Phone-local remix/generate helpers. No network, no fetch.
 * Used by the Android standalone shell and Node contract tests.
 */
(function (root) {
  const MAX_FREE_LONG_EDGE = 1216;
  const MAX_FREE_STEPS = 28;
  const MAX_FREE_PIXELS = 1024 * 1024;
  const SUBJECT_RE = /^(\d+)(girl|girls|boy|boys|other|others)$/;
  const SUBJECT_KIND = {
    girl: "girl",
    girls: "girl",
    boy: "boy",
    boys: "boy",
    other: "other",
    others: "other",
  };
  const GENERIC_IDENTITY = {
    "1girl": 1,
    "1boy": 1,
    female_focus: 1,
    male_focus: 1,
    original_character: 1,
  };

  function asObject(value) {
    if (value && typeof value === "object" && !Array.isArray(value)) return value;
    if (typeof value !== "string") return {};
    const text = value.trim();
    if (!text || text === "[object Object]") return {};
    try {
      const parsed = JSON.parse(text);
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch (_) {
      return {};
    }
  }

  function parseComment(raw) {
    if (raw && typeof raw === "object" && !Array.isArray(raw)) return raw;
    return asObject(raw);
  }

  function normalizeComment(comment) {
    if (!comment || typeof comment !== "object") return {};
    const normalized = Object.assign({}, comment);
    ["v4_prompt", "v4_negative_prompt"].forEach((key) => {
      if (key in normalized) normalized[key] = asObject(normalized[key]);
    });
    return normalized;
  }

  function effectiveComment(aiJson) {
    const source = asObject(aiJson);
    const parsed = parseComment(source.Comment);
    return normalizeComment(Object.keys(parsed).length ? parsed : source);
  }

  function splitPromptTags(value) {
    return String(value || "")
      .replace(/\n/g, ",")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function tagKey(value) {
    return String(value || "").trim().toLowerCase().replace(/_/g, " ");
  }

  function uniqueTags(values) {
    const seen = Object.create(null);
    const out = [];
    (values || []).forEach((item) => {
      const text = String(item || "").trim();
      const key = tagKey(text);
      if (!text || seen[key]) return;
      seen[key] = 1;
      out.push(text);
    });
    return out;
  }

  const GENDER_TOKENS = {
    "1girl": "female",
    "2girls": "female",
    "3girls": "female",
    "4girls": "female",
    "5girls": "female",
    "6girls": "female",
    girl: "female",
    girls: "female",
    female: "female",
    "female focus": "female",
    "girls only": "female",
    "1boy": "male",
    "2boys": "male",
    "3boys": "male",
    "4boys": "male",
    boy: "male",
    boys: "male",
    male: "male",
    "male focus": "male",
    "boys only": "male",
    "1other": "unknown",
    "2others": "unknown",
  };
  const BODY_RE = /\b(petite|slim|plump|muscular|tall|short|loli|oppai|flat chest|small breasts|medium breasts|large breasts|huge breasts|breasts|penis|pussy|ass|thighs|hips|belly|stomach)\b/;
  const APPEAR_RE = /\b(\w+ hair|\w+ eyes|long hair|short hair|very long hair|twintails|ponytail|ahoge|bangs|animal ears|fox ears|cat ears|wolf ears|horse ears|dragon horns|horns|halo|tail|fox tail|wolf tail|wings|pointy ears|dark skin|pale skin|freckles|heterochromia)\b/;
  const ACTION_RE = /\b(standing|sitting|lying|kneeling|walking|running|looking|holding|grabbing|smile|smiling|closed mouth|open mouth|from side|from above|from below|cowboy shot|upper body|full body|portrait|close-up|spread legs|bent over|arms up|hands? up|solo focus)\b/;
  const SCENE_RE = /\b(classroom|street|indoors|outdoors|night|day|sunset|moonlit|sky|city|forest|beach|bedroom|kitchen|office|school|watercolor|oil painting|anime coloring|cinematic lighting|depth of field|blurry background|simple background|white background|scenery)\b/;
  const CHAR_SUFFIX_RE = /^(.+?)(?:_\(([^)]+)\)|\s*\(([^)]+)\))$/;
  const WEIGHT_RE = /^-?\d+(?:\.\d+)?::(.+?)(?:::)?$/;

  function weightedInner(token) {
    const text = String(token || "").trim();
    const match = WEIGHT_RE.exec(text);
    return match ? String(match[1] || "").trim() : text;
  }

  function genderFromText(key) {
    const compact = String(key || "").replace(/\s+/g, " ").trim();
    if (GENDER_TOKENS[compact] || GENDER_TOKENS[compact.replace(/\s+/g, "")]) {
      return GENDER_TOKENS[compact] || GENDER_TOKENS[compact.replace(/\s+/g, "")];
    }
    if (/\b(1boy|2boys|3boys|4boys|boys only|male focus|male|boy|man|men)\b/.test(compact)) return "male";
    if (/\b(1girl|2girls|3girls|4girls|girls only|female focus|female|girl|woman|women|lady)\b/.test(compact)) return "female";
    return "";
  }

  function classifyToken(token) {
    const raw = String(token || "").trim();
    const inner = weightedInner(raw);
    const key = tagKey(inner);
    if (!key) return "meta";
    if (genderFromText(key)) return "gender";
    if (GENERIC_IDENTITY[key.replace(/\s+/g, "_")]) return "gender";
    if (CHAR_SUFFIX_RE.test(inner) || CHAR_SUFFIX_RE.test(inner.replace(/\s+/g, "_"))) return "identity";
    if (/\barknights\b/.test(key) && (inner.indexOf("(") >= 0 || inner.indexOf("_(") >= 0)) return "identity";
    if (/_\(oc\)$|\(oc\)$/.test(key.replace(/\s+/g, "_"))) return "identity";
    if (BODY_RE.test(key)) return "body";
    if (APPEAR_RE.test(key)) return "appearance";
    if (ACTION_RE.test(key)) return "action";
    if (SCENE_RE.test(key)) return "scene";
    if (/(hair|eyes|ears|tail|horns|halo|wings)$/.test(key.replace(/\s+/g, " "))) return "appearance";
    return "action";
  }

  function identityNameFromTag(token) {
    const inner = weightedInner(token);
    const compact = inner.replace(/\s+/g, "_");
    const match = CHAR_SUFFIX_RE.exec(inner) || CHAR_SUFFIX_RE.exec(compact);
    if (!match) return "";
    const series = String(match[2] || match[3] || "").toLowerCase();
    const name = String(match[1] || "").replace(/_/g, " ").trim();
    if (!name || GENERIC_IDENTITY[tagKey(name).replace(/\s+/g, "_")]) return "";
    if (series === "arknights" || series === "oc" || series) return name;
    return name;
  }

  function analyzeSlotCaption(caption, roleHint) {
    const tokens = splitPromptTags(caption);
    const groups = { identity: [], gender: [], body: [], appearance: [], action: [], scene: [], meta: [] };
    tokens.forEach((token) => {
      const kind = classifyToken(token);
      (groups[kind] || groups.meta).push(token);
    });
    let role = String(roleHint || "").toLowerCase();
    if (role !== "male" && role !== "female") {
      role = "unknown";
      groups.gender.forEach((token) => {
        const mapped = genderFromText(tagKey(weightedInner(token)));
        if (mapped === "male" || mapped === "female") role = mapped;
      });
    }
    let identityName = "";
    groups.identity.forEach((token) => {
      if (!identityName) identityName = identityNameFromTag(token);
    });
    const display = identityName || (role === "male" ? "未知男角色" : role === "female" ? "未知女角色" : "未知角色");
    return {
      caption: String(caption || ""),
      role: role,
      identity_name: identityName,
      display_name: display,
      replaceable: role === "male" || role === "female" || !!identityName,
      token_groups: groups,
      identity_tags: uniqueTags([].concat(groups.gender, groups.identity)),
      appearance_tags: uniqueTags([].concat(groups.body, groups.appearance)),
      action_tags: uniqueTags(groups.action),
      scene_tags: uniqueTags(groups.scene),
    };
  }

  function characterTokensFromPrompt(prompt) {
    const analysis = analyzeSlotCaption(prompt);
    const charBits = uniqueTags([].concat(
      analysis.token_groups.gender,
      analysis.token_groups.identity,
      analysis.token_groups.body,
      analysis.token_groups.appearance
    ));
    const charKeys = Object.create(null);
    charBits.forEach((token) => { charKeys[tagKey(token)] = 1; });
    const baseBits = splitPromptTags(prompt).filter((token) => !charKeys[tagKey(token)]);
    return {
      analysis: analysis,
      character_caption: charBits.join(", ") || String(prompt || "").trim(),
      base_caption: baseBits.join(", "),
    };
  }

  function subjectCount(value) {
    const match = SUBJECT_RE.exec(tagKey(value).replace(/\s+/g, ""));
    if (!match) return null;
    return { kind: SUBJECT_KIND[match[2]], count: Number(match[1]) };
  }

  function subjectTag(kind, count) {
    if (kind === "girl") return count === 1 ? "1girl" : count + "girls";
    if (kind === "boy") return count === 1 ? "1boy" : count + "boys";
    return count === 1 ? "1other" : count + "others";
  }

  function replaceBaseSubject(basePrompt, sourceSubject, targetSubject) {
    const source = subjectCount(sourceSubject);
    const target = subjectCount(targetSubject);
    if (!target || (source && source.kind === target.kind)) return basePrompt;
    const counts = { girl: 0, boy: 0, other: 0 };
    const kept = [];
    splitPromptTags(basePrompt).forEach((token) => {
      const parsed = subjectCount(token);
      if (!parsed) {
        kept.push(token);
        return;
      }
      counts[parsed.kind] += parsed.count;
    });
    if (source && counts[source.kind]) counts[source.kind] = Math.max(0, counts[source.kind] - 1);
    counts[target.kind] += 1;
    const subjects = ["girl", "boy", "other"]
      .filter((kind) => counts[kind] > 0)
      .map((kind) => subjectTag(kind, counts[kind]));
    return subjects.concat(kept).join(", ").replace(/^[, ]+|[, ]+$/g, "");
  }

  function stripCharacterTags(prompt, record) {
    const drop = Object.create(null);
    const source = record || {};
    []
      .concat(source.identity || [], source.appearance || [], source.body || [], source.character_tags || [])
      .concat([source.trigger, source.base_subject_tag])
      .forEach((item) => {
        const key = tagKey(item);
        if (key) drop[key] = 1;
      });
    const kept = splitPromptTags(prompt).filter((token) => {
      const key = tagKey(token);
      if (drop[key]) return false;
      if (subjectCount(token)) return true;
      return !/^(1girl|1boy|female focus|male focus)$/.test(key);
    });
    return kept.join(", ").replace(/^[, ]+|[, ]+$/g, "");
  }

  function inferGender(record) {
    const raw = String((record && (record.gender || record.role)) || "").toLowerCase();
    if (raw === "male" || raw === "female") return raw;
    const tags = uniqueTags([].concat((record && record.identity) || [], (record && record.core_tags) || []));
    const blob = tags.map(tagKey).join(" ");
    if (/\b1boy\b|\bmale focus\b|\bboys only\b/.test(blob)) return "male";
    if (/\b1girl\b|\bfemale focus\b|\bgirls only\b/.test(blob)) return "female";
    return "unknown";
  }

  function adaptCharacter(record, model) {
    const raw = record || {};
    const gender = inferGender(raw);
    const subject = gender === "male" ? "1boy" : gender === "female" ? "1girl" : "";
    const identity = uniqueTags(raw.identity || raw.identity_tags || []);
    const appearance = uniqueTags([].concat(raw.body || [], raw.appearance || raw.appearance_tags || []));
    const trigger = String(
      raw.trigger
      || identity.find((item) => !GENERIC_IDENTITY[tagKey(item).replace(/\s+/g, "_")])
      || raw.tag
      || ""
    ).trim();
    const tags = uniqueTags([subject, trigger, raw.copyright, raw.series].concat(identity, appearance))
      .filter(Boolean)
      .slice(0, 24);
    if (subject && tags[0] !== subject) {
      const without = tags.filter((item) => tagKey(item) !== tagKey(subject));
      tags.splice(0, tags.length, subject, ...without);
    }
    return {
      id: String(raw.id || raw.source_id || trigger || ""),
      label: String(raw.label || raw.name || raw.character || trigger || raw.id || ""),
      source: String(raw.source || "phone-local"),
      source_id: String(raw.source_id || raw.id || ""),
      model_dialect: String(model || ""),
      base_subject_tag: subject,
      character_caption: tags.join(", "),
      character_tags: tags,
      gender: gender,
    };
  }

  function ensureV4Slot(comment, slotIndex, caption) {
    const next = comment;
    const v4 = (next.v4_prompt && typeof next.v4_prompt === "object") ? next.v4_prompt : {};
    next.v4_prompt = v4;
    const cap = (v4.caption && typeof v4.caption === "object") ? v4.caption : {};
    v4.caption = cap;
    const slots = Array.isArray(cap.char_captions) ? cap.char_captions.slice() : [];
    while (slots.length <= slotIndex) slots.push({ char_caption: "", centers: [{ x: 0.5, y: 0.5 }] });
    const current = slots[slotIndex] && typeof slots[slotIndex] === "object"
      ? slots[slotIndex]
      : { centers: [{ x: 0.5, y: 0.5 }] };
    if (caption && !String(current.char_caption || "").trim()) {
      slots[slotIndex] = Object.assign({}, current, { char_caption: caption });
    } else {
      slots[slotIndex] = current;
    }
    cap.char_captions = slots.slice(0, 6);
    return next;
  }

  function applyCharacterToComment(comment, record, slotIndex, model, sourceCaption) {
    if (slotIndex < 0 || slotIndex > 5) throw new Error("角色槽必须在 0 到 5 之间");
    const card = adaptCharacter(record, model || (comment && comment.model) || "");
    const patched = JSON.parse(JSON.stringify(comment || {}));
    ensureV4Slot(patched, slotIndex, "");
    const v4 = patched.v4_prompt;
    const cap = v4.caption;
    const previous = cap.char_captions[slotIndex] || {};
    const currentCaption = String(sourceCaption || previous.char_caption || "").trim();
    const source = analyzeSlotCaption(currentCaption);
    const ocCaption = String((record && record.char_caption) || "").trim();
    const inject = ocCaption
      ? uniqueTags([].concat(card.character_tags || [], splitPromptTags(ocCaption)))
      : (card.character_tags || []);
    const captionText = uniqueTags(inject.concat(source.action_tags || [])).join(", ");
    if (!captionText) throw new Error("目标角色没有可用标签");
    cap.char_captions[slotIndex] = {
      char_caption: captionText,
      centers: previous.centers || [{ x: 0.5, y: 0.5 }],
    };
    const base = String(cap.base_caption || patched.prompt || "");
    cap.base_caption = base;
    patched.prompt = base;
    patched._phone_reference = {
      source_id: card.source_id,
      slot_index: slotIndex,
      label: card.label,
    };
    return { comment: patched, card: card };
  }

  function imageComment(image) {
    let raw = image && (image.ai_json || image.aiJson || image.metadata);
    if (typeof raw === "string") raw = asObject(raw);
    const comment = effectiveComment(raw);
    if (String(comment.prompt || (comment.v4_prompt && comment.v4_prompt.caption && comment.v4_prompt.caption.base_caption) || "").trim()) {
      return comment;
    }
    const prompt = String((image && (image.prompt_text || image.promptText)) || "").trim();
    if (prompt) comment.prompt = prompt;
    return comment;
  }

  function candidateGender(caption, role) {
    const raw = String(role || "").toLowerCase();
    if (raw === "male" || raw === "female") return raw;
    return genderFromText(tagKey(caption)) || analyzeSlotCaption(caption).role || "unknown";
  }

  function discoverCandidates(workPayload) {
    const work = (workPayload && (workPayload.work || workPayload)) || {};
    const images = (workPayload && workPayload.images) || work.images || [];
    const workId = String(work.work_id || work.id || "");
    const out = [];
    images.forEach((image, imageIndex) => {
      const comment = imageComment(image);
      const v4 = comment.v4_prompt || {};
      const cap = v4.caption || {};
      const slots = Array.isArray(cap.char_captions) ? cap.char_captions : [];
      const filled = [];
      slots.forEach((slot, slotIndex) => {
        const caption = slot && typeof slot === "object" ? String(slot.char_caption || "").trim() : "";
        if (caption) filled.push({ slotIndex: slotIndex, caption: caption, synthesized: false });
      });
      if (!filled.length) {
        const fallback = String(comment.prompt || cap.base_caption || image.prompt_text || "").trim();
        if (fallback) {
          const split = characterTokensFromPrompt(fallback);
          filled.push({
            slotIndex: 0,
            caption: split.character_caption || fallback,
            synthesized: true,
            base_caption: split.base_caption,
          });
        }
      }
      filled.slice(0, 6).forEach((item) => {
        const analysis = analyzeSlotCaption(item.caption);
        const role = analysis.role !== "unknown" ? analysis.role : candidateGender(item.caption, "");
        const imageId = String(image.image_id || image.id || (workId + "_p" + imageIndex));
        out.push({
          candidate_id: workId + "/" + imageId + "/slot-" + item.slotIndex,
          image_index: imageIndex,
          slot_index: item.slotIndex,
          caption: item.caption,
          role: role,
          label: analysis.identity_name || analysis.display_name || work.title || ("槽" + (item.slotIndex + 1)),
          identity_name: analysis.identity_name,
          identity_tags: analysis.identity_tags,
          appearance_tags: analysis.appearance_tags,
          action_tags: analysis.action_tags,
          replaceable: analysis.replaceable,
          synthesized: !!item.synthesized,
          suggested_base: item.base_caption || "",
        });
      });
    });
    return out;
  }

  function decorateWork(payload) {
    const data = payload && typeof payload === "object" ? JSON.parse(JSON.stringify(payload)) : {};
    const work = data.work || {};
    const images = Array.isArray(data.images) ? data.images : (work.images || []);
    images.forEach((image, index) => {
      image.page_index = index;
      image.id = image.image_id || image.id || String(index);
    });
    data.images = images;
    if (data.work) data.work.images = images;
    data.character_candidates = discoverCandidates(data);
    data.generation_calls = 0;
    data.source = data.source || "aitag-online";
    return data;
  }

  function targetRecord(item, referenceId) {
    const raw = item || {};
    const gender = String(raw.gender || "female").toLowerCase() === "male" ? "male" : "female";
    const identity = uniqueTags(raw.identity || raw.identity_tags || []);
    const appearance = uniqueTags([].concat(raw.body || [], raw.appearance || raw.appearance_tags || []));
    const caption = String(raw.char_caption || "").trim();
    const trigger = identity.find((itemTag) => !GENERIC_IDENTITY[tagKey(itemTag).replace(/\s+/g, "_")])
      || String(raw.tag || raw.trigger || raw.label || raw.name || "").trim();
    if (!identity.length && trigger) identity.push(trigger);
    if (gender === "female" && !identity.some((tag) => tagKey(tag) === "1girl")) identity.unshift("1girl");
    if (gender === "male" && !identity.some((tag) => tagKey(tag) === "1boy")) identity.unshift("1boy");
    return {
      id: String(raw.id || trigger || ""),
      reference_id: String(referenceId || raw.reference_id || ""),
      name: String(raw.label || raw.name || raw.id || ""),
      character: String(raw.label || raw.name || raw.id || ""),
      gender: gender,
      kind: String(raw.kind || (String(referenceId || "").indexOf("custom:") === 0 ? "oc" : "")),
      char_caption: caption,
      trigger: trigger,
      identity: identity,
      appearance: appearance,
      body: uniqueTags(raw.body || []),
      core_tags: uniqueTags(identity.concat(appearance)),
      tag: String(raw.tag || trigger || ""),
      source: String(raw.source || "phone-local"),
      source_id: String(raw.id || ""),
    };
  }

  function countGenderSlots(candidates, imageIndex, gender) {
    const scope = String(gender || "female").toLowerCase();
    return (candidates || []).filter((item) => (
      Number(item.image_index) === Number(imageIndex)
      && candidateGender(item.caption, item.role) === scope
    )).length;
  }

  function genderSlotIndexOf(candidates, slot) {
    if (!slot) return -1;
    const scope = candidateGender(slot.caption, slot.role);
    if (scope !== "female" && scope !== "male") return -1;
    const page = (candidates || []).filter((item) => (
      Number(item.image_index) === Number(slot.image_index)
      && candidateGender(item.caption, item.role) === scope
    ));
    return page.findIndex((item) => String(item.candidate_id) === String(slot.candidate_id));
  }

  function resolveAssignments(candidates, imageIndex, opts) {
    const raw = opts && Array.isArray(opts.slot_targets) ? opts.slot_targets : [];
    if (!raw.length) return [];
    const page = (candidates || []).filter((item) => Number(item.image_index) === Number(imageIndex));
    const out = [];
    raw.forEach((item) => {
      if (!item || !item.target_record) return;
      let slotIndex = item.slot_index;
      if (item.gender_slot_index !== undefined && item.gender_slot_index !== null && String(item.gender_slot_index) !== "") {
        const gender = String(item.gender || item.role || "female").toLowerCase();
        const gendered = page.filter((row) => candidateGender(row.caption, row.role) === gender);
        const hit = gendered[Number(item.gender_slot_index)];
        if (!hit) return;
        slotIndex = hit.slot_index;
      }
      if (slotIndex === undefined || slotIndex === null || String(slotIndex) === "") return;
      out.push({
        slot: Math.max(0, Math.min(5, Number(slotIndex))),
        record: item.target_record,
        ref: item.target_reference_id || "",
      });
    });
    return out;
  }

  function resolveSlots(candidates, imageIndex, slotIndex, genderScope, candidateId) {
    const page = (candidates || []).filter((item) => Number(item.image_index) === Number(imageIndex));
    const wanted = String(candidateId || "").trim();
    if (wanted) {
      const hit = page.find((item) => String(item.candidate_id) === wanted);
      if (!hit) throw new Error("没找到这个角色槽");
      if (slotIndex !== undefined && slotIndex !== null && String(slotIndex) !== ""
        && Number(slotIndex) !== Number(hit.slot_index)) {
        throw new Error("没找到这个角色槽");
      }
      return [Math.max(0, Math.min(5, Number(hit.slot_index)))];
    }
    const scope = String(genderScope || "").toLowerCase();
    if (scope === "female" || scope === "male") {
      const matched = page
        .filter((item) => candidateGender(item.caption, item.role) === scope)
        .map((item) => Number(item.slot_index));
      if (matched.length) return Array.from(new Set(matched));
      throw new Error(scope === "female" ? "这一页没有可替换的女性角色槽" : "这一页没有可替换的男性角色槽");
    }
    return [Math.max(0, Math.min(5, Number(slotIndex) || 0))];
  }

  function baseCommentFromImage(image, sourceRecord) {
    const comment = imageComment(image);
    const v4 = (comment.v4_prompt && typeof comment.v4_prompt === "object") ? comment.v4_prompt : {};
    const cap = (v4.caption && typeof v4.caption === "object") ? v4.caption : {};
    const existingSlots = Array.isArray(cap.char_captions) ? cap.char_captions : [];
    const sourcePrompt = String(cap.base_caption || comment.prompt || image.prompt_text || "").trim();
    const hasSlots = existingSlots.some((slot) => slot && String(slot.char_caption || "").trim());
    let basePrompt = sourcePrompt;
    if (!hasSlots) {
      const split = characterTokensFromPrompt(sourcePrompt);
      basePrompt = split.base_caption || stripCharacterTags(sourcePrompt, sourceRecord) || sourcePrompt;
    }
    comment.v4_prompt = v4;
    v4.caption = cap;
    cap.base_caption = basePrompt;
    comment.prompt = basePrompt;
    if (!hasSlots && sourceRecord && sourceRecord.caption) {
      ensureV4Slot(comment, Number(sourceRecord.slot_index || 0), sourceRecord.caption);
    }
    if (image.width) comment.width = comment.width || image.width;
    if (image.height) comment.height = comment.height || image.height;
    if (image.model) comment.model = comment.model || image.model;
    return comment;
  }

  function compileDraft(workPayload, options) {
    const opts = options || {};
    const work = (workPayload && workPayload.work) || {};
    const images = (workPayload && workPayload.images) || [];
    const imageIndex = Math.max(0, Number(opts.image_index) || 0);
    if (imageIndex >= images.length) throw new Error("作品页码超出范围");
    const image = images[imageIndex] || {};
    const candidates = Array.isArray(workPayload.character_candidates)
      ? workPayload.character_candidates
      : discoverCandidates(workPayload);
    const assignments = resolveAssignments(candidates, imageIndex, opts);
    const slots = assignments.length
      ? assignments.map((item) => item.slot)
      : resolveSlots(
        candidates,
        imageIndex,
        Object.prototype.hasOwnProperty.call(opts, "slot_index") ? opts.slot_index : undefined,
        opts.gender_scope,
        opts.candidate_id
      );
    const primary = slots.length ? slots[0] : 0;
    const source = candidates.find((item) => Number(item.image_index) === imageIndex && Number(item.slot_index) === primary) || null;
    const comment = JSON.parse(JSON.stringify(baseCommentFromImage(image, source)));
    let card = null;
    const applyOne = (record, slot) => {
      const sourceSlot = candidates.find((item) => Number(item.image_index) === imageIndex && Number(item.slot_index) === slot);
      const adapted = sourceSlot ? adaptCharacter(targetRecord({
        identity: sourceSlot.identity_tags,
        appearance: sourceSlot.appearance_tags,
        label: sourceSlot.label,
        gender: sourceSlot.role,
      })) : {};
      const applied = applyCharacterToComment(
        comment,
        record,
        slot,
        opts.model || image.model || "",
        sourceSlot && sourceSlot.caption
      );
      Object.assign(comment, applied.comment);
      card = applied.card;
      return String(adapted.base_subject_tag || "");
    };
    if (assignments.length) {
      const preserved = String((comment.v4_prompt && comment.v4_prompt.caption && comment.v4_prompt.caption.base_caption) || comment.prompt || "");
      const sourceSubjects = [];
      assignments.forEach((item) => {
        sourceSubjects.push(applyOne(item.record, item.slot));
      });
      let finalBase = preserved;
      sourceSubjects.forEach((subject) => {
        finalBase = replaceBaseSubject(finalBase, subject, (card && card.base_subject_tag) || "");
      });
      comment.prompt = finalBase;
      if (comment.v4_prompt && comment.v4_prompt.caption) comment.v4_prompt.caption.base_caption = finalBase;
    } else if (opts.target_record) {
      const target = opts.target_record;
      const preserved = String((comment.v4_prompt && comment.v4_prompt.caption && comment.v4_prompt.caption.base_caption) || comment.prompt || "");
      const sourceSubjects = [];
      slots.forEach((slot) => {
        sourceSubjects.push(applyOne(target, slot));
      });
      let finalBase = preserved;
      sourceSubjects.forEach((subject) => {
        finalBase = replaceBaseSubject(finalBase, subject, (card && card.base_subject_tag) || "");
      });
      comment.prompt = finalBase;
      if (comment.v4_prompt && comment.v4_prompt.caption) comment.v4_prompt.caption.base_caption = finalBase;
    }
    if (opts.style_record) applyStyleToComment(comment, opts.style_record);
    const workId = String(work.work_id || work.id || "");
    const draft = {
      galleryId: "aitag-online",
      workId: 0,
      pageIndex: imageIndex,
      title: work.title || ("AITag " + workId),
      thumb: image.thumbnail_url || image.url || "",
      comment: comment,
      texts: promptSnapshot(comment),
      params: {
        width: comment.width,
        height: comment.height,
        steps: comment.steps,
        scale: comment.scale,
        sampler: comment.sampler,
        seed: comment.seed,
        batch: 1,
      },
      refs: { vibe: "", char: "", strength: "0.6" },
      source: {
        provider: "aitag-online",
        workId: workId,
        workIdStr: workId,
        imageId: image.image_id || image.id || "",
        imageIndex: imageIndex,
        title: work.title || ("AITag " + workId),
        thumb: image.thumbnail_url || image.url || "",
      },
    };
    if (assignments.length) {
      draft.reference = {
        slotIndexes: slots,
        replacements: assignments.map((item) => ({ slotIndex: item.slot, referenceId: item.ref })),
      };
    } else if (opts.target_reference_id) {
      draft.reference = { referenceId: opts.target_reference_id, slotIndex: primary };
      if (slots.length > 1) draft.reference.slotIndexes = slots;
    }
    return {
      ok: true,
      draft: draft,
      card: card,
      work_id: workId,
      image_index: imageIndex,
      slot_index: primary,
      slot_indexes: slots,
      generation_calls: 0,
      message: "草稿已就绪，还没扣 Anlas",
    };
  }

  function compileDrafts(workPayload, options) {
    const opts = Object.assign({}, options || {});
    delete opts.candidate_id;
    const images = (workPayload && workPayload.images) || [];
    const pages = [];
    const skipped = [];
    images.forEach((_, index) => {
      try {
        pages.push(compileDraft(workPayload, Object.assign({}, opts, {
          image_index: index,
        })));
      } catch (error) {
        skipped.push({
          image_index: index,
          error: String((error && error.message) || error || "这一页不能换"),
        });
      }
    });
    if (!pages.length) {
      throw new Error((skipped[0] && skipped[0].error) || "没有可换的页");
    }
    return {
      ok: true,
      draft: pages[0] && pages[0].draft,
      pages: pages,
      skipped: skipped,
      generation_calls: 0,
      message: skipped.length
        ? ("已为 " + pages.length + " 页写好零费用草稿，跳过 " + skipped.length + " 页")
        : ("已为 " + pages.length + " 页写好零费用草稿"),
    };
  }

  function promptSnapshot(comment) {
    const v4 = (comment && comment.v4_prompt) || {};
    const cap = v4.caption || {};
    const characters = [];
    (cap.char_captions || []).forEach((item, index) => {
      if (!item || typeof item !== "object") return;
      const centers = item.centers || [{ x: 0.5, y: 0.5 }];
      characters.push({
        index: index,
        caption: String(item.char_caption || ""),
        center: centers[0] || { x: 0.5, y: 0.5 },
      });
    });
    return {
      base_caption: String(cap.base_caption || (comment && comment.prompt) || "").slice(0, 2000),
      char_captions: characters,
    };
  }

  const STYLE_HINT_RE = /(style|artstyle|official art|official_art|watercolor|sketch|lineart|cel shading|cel_shading|flat color|flat_color|pixel art|pixel_art|chibi|manga|game cg|visual novel|oil painting|cinematic|painterly|monochrome|pastel|neon|impasto|gouache|1990s|2000s|light novel|manhwa|realistic|anime coloring)/i;

  const STYLE_LABELS = {
    "official art": "官方画风",
    "anime style": "动画风",
    "manga style": "漫画风",
    manga: "漫画风",
    "game cg": "游戏 CG",
    "visual novel": "视觉小说 CG",
    "visual novel cg": "视觉小说 CG",
    watercolor: "水彩",
    "oil painting": "油画",
    sketch: "线稿素描",
    lineart: "干净线稿",
    "cel shading": "赛璐璐",
    "flat color": "平涂",
    "pixel art": "像素",
    chibi: "Q 版",
    "retro artstyle": "复古画风",
    "1990s": "90 年代动画",
    "1990s (style)": "90 年代动画",
    "2000s": "2000 年代动画",
    "2000s (style)": "2000 年代动画",
    "light novel": "轻小说插画",
    manhwa: "条漫",
    cinematic: "电影光影",
    "cinematic lighting": "电影光影",
    painterly: "厚涂",
    realistic: "偏写实",
    monochrome: "单色",
    pastel: "粉彩",
    "pastel colors": "粉彩",
    neon: "霓虹",
    "neon lights": "霓虹",
    impasto: "厚颜料",
    gouache: "水粉",
    "gouache (medium)": "水粉",
    "anime coloring": "赛璐璐上色",
  };

  function styleTokenLabel(token, catalog) {
    const key = tagKey(token);
    if (STYLE_LABELS[key]) return STYLE_LABELS[key];
    if (Array.isArray(catalog)) {
      const hit = catalog.find((item) => item && tagKey(item.tag || item.replace || item.style || "") === key);
      if (hit) return String(hit.label || hit.name || token);
    }
    return String(token || key);
  }

  function collectStyleText(source) {
    if (!source) return "";
    if (typeof source === "string") return source;
    if (source.prompt_text || source.ai_json || source.aiJson || source.metadata) {
      try {
        return collectStyleText(imageComment(source));
      } catch (_) {
        return String(source.prompt_text || "");
      }
    }
    const prompt = String(source.prompt || "");
    const base = source.v4_prompt && source.v4_prompt.caption
      ? String(source.v4_prompt.caption.base_caption || "")
      : "";
    const tags = Array.isArray(source.tags) ? source.tags.join(", ") : "";
    return [prompt, base, tags].filter(Boolean).join(", ");
  }

  function recognizeStyles(source, catalog) {
    const extra = Array.isArray(catalog) ? catalog : [];
    const tokens = uniqueTags(splitPromptTags(collectStyleText(source)).filter((token) => {
      if (STYLE_HINT_RE.test(token) || STYLE_HINT_RE.test(tagKey(token))) return true;
      return extra.some((item) => item && tagKey(item.tag || item.replace || item.style || "") === tagKey(token));
    }));
    const labels = tokens.map((token) => styleTokenLabel(token, extra));
    return {
      tokens: tokens,
      labels: labels,
      text: tokens.join(" / "),
      label_text: labels.join(" / "),
    };
  }

  function recognizeWorkStyles(workPayload, catalog) {
    const work = (workPayload && (workPayload.work || workPayload)) || {};
    const images = (workPayload && workPayload.images) || work.images || [];
    const pages = images.map((image, index) => Object.assign({ image_index: index }, recognizeStyles(image, catalog)));
    const fromTags = recognizeStyles({ tags: work.tags || [] }, catalog);
    const tokens = uniqueTags(pages.reduce((acc, page) => acc.concat(page.tokens || []), fromTags.tokens || []));
    const labels = tokens.map((token) => styleTokenLabel(token, catalog));
    return {
      tokens: tokens,
      labels: labels,
      text: tokens.join(" / "),
      label_text: labels.join(" / "),
      pages: pages,
    };
  }

  function applyStyleToComment(comment, styleRecord) {
    if (!comment || !styleRecord) return comment;
    const incoming = uniqueTags(splitPromptTags(String(styleRecord.tag || styleRecord.replace || styleRecord.style || "")));
    if (!incoming.length) return comment;
    const current = String((comment.v4_prompt && comment.v4_prompt.caption && comment.v4_prompt.caption.base_caption) || comment.prompt || "");
    const kept = splitPromptTags(current).filter((token) => !STYLE_HINT_RE.test(tagKey(token)));
    const next = uniqueTags(kept.concat(incoming)).join(", ");
    comment.prompt = next;
    if (comment.v4_prompt && comment.v4_prompt.caption) comment.v4_prompt.caption.base_caption = next;
    comment._style = {
      id: String(styleRecord.id || ""),
      label: String(styleRecord.label || styleRecord.name || incoming[0] || ""),
      tag: incoming.join(", "),
    };
    return comment;
  }

  function inferModel(source, explicit) {
    const model = String(explicit || "").trim();
    if (model.indexOf("nai-diffusion-") === 0) return model;
    const value = String(source || "");
    const lower = value.toLowerCase();
    if (value.indexOf("V4.5") >= 0 || lower.indexOf("v4.5") >= 0) return "nai-diffusion-4-5-full";
    if (value.indexOf("V4") >= 0 || lower.indexOf("v4") >= 0) return "nai-diffusion-4-full";
    return "nai-diffusion-4-5-full";
  }

  function fitOpusFreeSize(width, height) {
    let w = Number(width) || 0;
    let h = Number(height) || 0;
    if (w <= 0 || h <= 0) return { width: 832, height: 1216, resized: true };
    const longEdge = Math.max(w, h);
    const pixels = w * h;
    if (longEdge <= MAX_FREE_LONG_EDGE && pixels <= MAX_FREE_PIXELS) {
      return { width: w, height: h, resized: false };
    }
    const scale = Math.min(MAX_FREE_LONG_EDGE / longEdge, Math.sqrt(MAX_FREE_PIXELS / pixels));
    let newWidth = Math.max(64, Math.floor((w * scale) / 64) * 64);
    let newHeight = Math.max(64, Math.floor((h * scale) / 64) * 64);
    while (newWidth * newHeight > MAX_FREE_PIXELS) {
      if (newWidth >= newHeight && newWidth > 64) newWidth -= 64;
      else if (newHeight > 64) newHeight -= 64;
      else break;
    }
    return { width: newWidth, height: newHeight, resized: true };
  }

  function normalizedV4(comment, baseCaption, negativePrompt) {
    const v4 = JSON.parse(JSON.stringify((comment && comment.v4_prompt) || {}));
    const caption = (v4.caption && typeof v4.caption === "object") ? v4.caption : {};
    caption.base_caption = String(caption.base_caption || baseCaption || "");
    caption.char_captions = Array.isArray(caption.char_captions) ? caption.char_captions : [];
    v4.caption = caption;
    v4.use_coords = v4.use_coords !== false;
    const negative = JSON.parse(JSON.stringify((comment && comment.v4_negative_prompt) || {}));
    const negCap = (negative.caption && typeof negative.caption === "object") ? negative.caption : {};
    negCap.base_caption = String(negCap.base_caption || negativePrompt || "");
    let negChars = Array.isArray(negCap.char_captions) ? negCap.char_captions : [];
    if (caption.char_captions.length && negChars.length < caption.char_captions.length) {
      caption.char_captions.slice(negChars.length).forEach((item) => {
        const centers = item && item.centers ? item.centers : [{ x: 0.5, y: 0.5 }];
        negChars.push({ char_caption: "", centers: [centers[0] || { x: 0.5, y: 0.5 }] });
      });
    }
    negCap.char_captions = negChars;
    negative.caption = negCap;
    negative.use_coords = negative.use_coords !== false;
    return { v4_prompt: v4, v4_negative_prompt: negative };
  }

  function buildGeneratePayload(patchedComment, forceFree) {
    const comment = patchedComment || {};
    let width = Number(comment.width) || 832;
    let height = Number(comment.height) || 1216;
    let steps = Number(comment.steps) || 28;
    let resized = false;
    const enforceFree = forceFree !== false;
    if (enforceFree) {
      const fitted = fitOpusFreeSize(width, height);
      width = fitted.width;
      height = fitted.height;
      resized = fitted.resized;
      steps = Math.min(steps, MAX_FREE_STEPS);
    }
    const source = String(comment.Source || "");
    const model = inferModel(source, comment.model);
    const v4 = comment.v4_prompt || {};
    const cap = v4.caption || {};
    const base = String(cap.base_caption || comment.prompt || "");
    const negativePrompt = String(comment.negative_prompt || comment.uc || "");
    const normalized = normalizedV4(comment, base, negativePrompt);
    const parameters = {
      params_version: Number(comment.params_version) || 3,
      width: width,
      height: height,
      scale: Number(comment.scale) || 5,
      sampler: String(comment.sampler || "k_euler_ancestral"),
      steps: steps,
      n_samples: 1,
      ucPreset: 0,
      qualityToggle: comment.qualityToggle !== false,
      autoSmea: !!comment.autoSmea,
      negative_prompt: negativePrompt,
      legacy: false,
      legacy_uc: false,
      legacy_v3_extend: false,
      add_original_image: true,
      characterPrompts: comment.characterPrompts || [],
      uc: negativePrompt,
      v4_prompt: normalized.v4_prompt,
      v4_negative_prompt: normalized.v4_negative_prompt,
      noise_schedule: comment.noise_schedule || "karras",
      cfg_rescale: comment.cfg_rescale || 0,
      use_coords: normalized.v4_prompt.use_coords !== false,
    };
    const seed = comment.seed;
    if (seed !== undefined && String(seed).trim() !== "") {
      const seedValue = Number(seed);
      if (seedValue === -1 || seedValue >= 0) parameters.seed = seedValue;
    }
    return {
      input: base,
      model: model,
      action: "generate",
      parameters: parameters,
      free_eligible: enforceFree && steps <= MAX_FREE_STEPS && Math.max(width, height) <= MAX_FREE_LONG_EDGE && width * height <= MAX_FREE_PIXELS,
      resized_for_free: resized,
      width: width,
      height: height,
      steps: steps,
    };
  }

  function naiRequestBody(payload) {
    return {
      input: payload.input,
      model: payload.model,
      action: payload.action || "generate",
      parameters: payload.parameters,
    };
  }

  function applyOptimizeTexts(comment, texts) {
    const patched = JSON.parse(JSON.stringify(comment || {}));
    const incoming = texts || {};
    const prompt = String(incoming.prompt || patched.prompt || "");
    const uc = incoming.uc != null ? String(incoming.uc) : String(patched.uc || "");
    const base = String(incoming.base_caption || prompt || "");
    const nextCaps = Array.isArray(incoming.char_captions) ? incoming.char_captions : null;
    if (nextCaps && nextCaps.length) {
      const v4 = patched.v4_prompt && typeof patched.v4_prompt === "object" ? patched.v4_prompt : {};
      const cap = v4.caption && typeof v4.caption === "object" ? v4.caption : {};
      const existing = Array.isArray(cap.char_captions) ? cap.char_captions : [];
      cap.char_captions = nextCaps.map((raw, index) => {
        const text = raw && typeof raw === "object"
          ? String(raw.char_caption || raw.caption || "")
          : String(raw || "");
        const old = existing[index] || {};
        const centers = old.centers && old.centers.length ? old.centers : [{ x: 0.5, y: 0.5 }];
        return { char_caption: text, centers: centers };
      });
      cap.base_caption = base;
      v4.caption = cap;
      patched.v4_prompt = v4;
      patched.prompt = base || prompt;
    } else {
      patched.prompt = prompt || base;
      if (patched.v4_prompt && patched.v4_prompt.caption && base) {
        patched.v4_prompt.caption.base_caption = base;
      }
    }
    patched.uc = uc;
    return patched;
  }

  function applyDraftEdits(comment, edits) {
    const patched = JSON.parse(JSON.stringify(comment || {}));
    const incoming = edits || {};
    if (incoming.prompt != null) {
      patched.prompt = String(incoming.prompt);
      if (!patched.v4_prompt || typeof patched.v4_prompt !== "object") patched.v4_prompt = {};
      if (!patched.v4_prompt.caption || typeof patched.v4_prompt.caption !== "object") patched.v4_prompt.caption = {};
      patched.v4_prompt.caption.base_caption = patched.prompt;
    }
    if (incoming.uc != null) {
      patched.uc = String(incoming.uc);
      patched.negative_prompt = patched.uc;
      if (!patched.v4_negative_prompt || typeof patched.v4_negative_prompt !== "object") patched.v4_negative_prompt = {};
      if (!patched.v4_negative_prompt.caption || typeof patched.v4_negative_prompt.caption !== "object") patched.v4_negative_prompt.caption = {};
      patched.v4_negative_prompt.caption.base_caption = patched.uc;
    }
    if (incoming.seed != null && String(incoming.seed).trim() !== "") {
      const seedValue = Number(incoming.seed);
      if (seedValue === -1 || seedValue >= 0) patched.seed = seedValue;
    }
    if (incoming.steps != null && String(incoming.steps).trim() !== "") {
      patched.steps = Math.max(1, Math.min(28, Number(incoming.steps) || 28));
    }
    return patched;
  }

  const api = {
    effectiveComment: effectiveComment,
    splitPromptTags: splitPromptTags,
    adaptCharacter: adaptCharacter,
    applyCharacterToComment: applyCharacterToComment,
    analyzeSlotCaption: analyzeSlotCaption,
    discoverCandidates: discoverCandidates,
    imageComment: imageComment,
    decorateWork: decorateWork,
    targetRecord: targetRecord,
    compileDraft: compileDraft,
    compileDrafts: compileDrafts,
    countGenderSlots: countGenderSlots,
    genderSlotIndexOf: genderSlotIndexOf,
    resolveAssignments: resolveAssignments,
    buildGeneratePayload: buildGeneratePayload,
    naiRequestBody: naiRequestBody,
    applyOptimizeTexts: applyOptimizeTexts,
    applyDraftEdits: applyDraftEdits,
    applyStyleToComment: applyStyleToComment,
    recognizeStyles: recognizeStyles,
    recognizeWorkStyles: recognizeWorkStyles,
    fitOpusFreeSize: fitOpusFreeSize,
    promptSnapshot: promptSnapshot,
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.StandaloneCore = api;
})(typeof window !== "undefined" ? window : globalThis);
