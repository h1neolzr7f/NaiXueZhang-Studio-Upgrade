const assert = require("assert");
const core = require("../web/m/standalone-core.js");

assert.strictEqual(typeof core.compileDraft, "function");
assert.ok(!String(require("fs").readFileSync(require("path").join(__dirname, "../web/m/standalone-core.js"), "utf8")).includes("fetch("));

const work = core.decorateWork({
  work: { work_id: "abc123", title: "测试图" },
  images: [
    {
      image_id: "p0",
      prompt_text: "1girl, school uniform, classroom",
      ai_json: {
        Comment: {
          prompt: "1girl, school uniform, classroom",
          width: 1024,
          height: 1536,
          steps: 40,
          model: "nai-diffusion-4-5-full",
          v4_prompt: {
            caption: {
              base_caption: "1girl, school uniform, classroom",
              char_captions: [{ char_caption: "1girl, blonde_hair, blue_eyes", centers: [{ x: 0.5, y: 0.5 }] }],
            },
          },
        },
      },
    },
  ],
});
assert.ok(work.character_candidates.length >= 1);
assert.strictEqual(work.generation_calls, 0);

const target = core.targetRecord({
  id: "skadi_f",
  label: "斯卡蒂",
  gender: "female",
  identity: ["skadi_(arknights)", "1girl"],
  appearance: ["white_hair", "red_eyes"],
}, "preset:female:skadi_f");

const draft = core.compileDraft(work, {
  image_index: 0,
  slot_index: 0,
  target_record: target,
  target_reference_id: "preset:female:skadi_f",
});
assert.strictEqual(draft.generation_calls, 0);
assert.ok(draft.draft.comment.v4_prompt.caption.char_captions[0].char_caption.includes("skadi_(arknights)"));
assert.ok(String(draft.draft.comment.prompt).includes("school uniform"));

const payload = core.buildGeneratePayload(draft.draft.comment, true);
assert.strictEqual(payload.action, "generate");
assert.ok(payload.steps <= 28);
assert.ok(Math.max(payload.width, payload.height) <= 1216);
assert.ok(payload.free_eligible);
const body = core.naiRequestBody(payload);
assert.strictEqual(body.action, "generate");
assert.ok(!("free_eligible" in body));

const queued = {
  drafts: {
    0: draft,
    1: core.compileDraft(work, {
      image_index: 0,
      slot_index: 0,
      target_record: target,
      target_reference_id: "preset:female:skadi_f",
    }),
  },
};
const pages = Object.keys(queued.drafts).sort((a, b) => Number(a) - Number(b));
assert.deepStrictEqual(pages, ["0", "1"]);
pages.forEach((key) => {
  const comment = queued.drafts[key].draft.comment;
  const next = core.buildGeneratePayload(comment, true);
  assert.strictEqual(next.action, "generate");
  assert.ok(next.free_eligible);
  assert.ok(next.steps <= 28);
  assert.strictEqual(Number(queued.drafts[key].generation_calls), 0);
});

const multi = core.decorateWork({
  work: { work_id: "multi", title: "双人" },
  images: [{
    image_id: "p0",
    ai_json: {
      Comment: {
        prompt: "2girls, moonlit street, watercolor",
        v4_prompt: {
          caption: {
            base_caption: "2girls, moonlit street, watercolor",
            char_captions: [
              { char_caption: "girl, red hair, green eyes", centers: [{ x: 0.25, y: 0.5 }] },
              { char_caption: "girl, blue hair, blue eyes", centers: [{ x: 0.75, y: 0.5 }] },
            ],
          },
        },
      },
    },
  }],
});
assert.strictEqual(multi.character_candidates.length, 2);
assert.notStrictEqual(multi.character_candidates[0].label, "girl");
const boy = core.targetRecord({
  id: "target-boy",
  name: "Target boy",
  gender: "male",
  identity: ["1boy"],
  appearance: ["black hair", "golden eyes"],
}, "custom:male:target-boy");
const swapped = core.compileDraft(multi, {
  image_index: 0,
  candidate_id: multi.character_candidates[0].candidate_id,
  target_record: boy,
  target_reference_id: "custom:male:target-boy",
});
const multiCap = swapped.draft.comment.v4_prompt.caption;
assert.ok(multiCap.char_captions[0].char_caption.includes("black hair"));
assert.ok(!multiCap.char_captions[0].char_caption.includes("red hair"));
assert.strictEqual(multiCap.char_captions[1].char_caption, "girl, blue hair, blue eyes");
assert.ok(String(multiCap.base_caption).includes("moonlit street"));
assert.ok(String(multiCap.base_caption).includes("1boy"));

const ocWork = core.decorateWork({
  work: { work_id: "oc1", title: "动作" },
  images: [{
    image_id: "p0",
    ai_json: {
      Comment: {
        v4_prompt: {
          caption: {
            base_caption: "2people, indoors",
            char_captions: [
              { char_caption: "faceless boy, standing, black randoseru", centers: [{ x: 0.25, y: 0.5 }] },
              { char_caption: "woman, tall, big breasts, plump", centers: [{ x: 0.75, y: 0.5 }] },
            ],
          },
        },
      },
    },
  }],
});
assert.strictEqual(ocWork.character_candidates[0].role, "male");
const oc = core.targetRecord({
  id: "feijibei",
  label: "费济北",
  gender: "male",
  kind: "oc",
  identity: ["1boy", "male_focus"],
  char_caption: "1boy, 18 years old, slim, youthful, black hair",
}, "preset:male:feijibei");
const ocDraft = core.compileDraft(ocWork, {
  image_index: 0,
  candidate_id: ocWork.character_candidates[0].candidate_id,
  target_record: oc,
  target_reference_id: "preset:male:feijibei",
});
const ocSlot = ocDraft.draft.comment.v4_prompt.caption.char_captions[0].char_caption;
assert.ok(ocSlot.includes("18 years old"));
assert.ok(ocSlot.includes("standing"));
assert.ok(!ocSlot.includes("faceless boy"));
assert.strictEqual(ocDraft.draft.comment.v4_prompt.caption.char_captions[1].char_caption, "woman, tall, big breasts, plump");

const weightedOc = core.targetRecord({
  id: "banana",
  label: "香蕉姐",
  gender: "female",
  kind: "oc",
  oc_mode: true,
  identity: ["should_not_inject_identity"],
  appearance: ["should_not_inject_appearance"],
  char_caption: "1girl, banana_onee_(oc), {{1.2::horns}}, long hair",
  clothing: "china dress",
  extra: "earrings",
  remove: "long hair",
}, "custom:female:banana");
const weightedWork = core.decorateWork({
  work: { work_id: "oc-weight", title: "整段OC" },
  images: [{
    image_id: "p0",
    ai_json: {
      Comment: {
        v4_prompt: {
          caption: {
            base_caption: "1girl, indoors",
            char_captions: [
              { char_caption: "1girl, brown hair, standing", centers: [{ x: 0.5, y: 0.5 }] },
            ],
          },
        },
      },
    },
  }],
});
const weightedDraft = core.compileDraft(weightedWork, {
  image_index: 0,
  candidate_id: weightedWork.character_candidates[0].candidate_id,
  target_record: weightedOc,
  target_reference_id: "custom:female:banana",
});
const weightedSlot = weightedDraft.draft.comment.v4_prompt.caption.char_captions[0].char_caption;
assert.ok(weightedSlot.includes("{{1.2::horns}}"));
assert.ok(weightedSlot.includes("banana_onee_(oc)"));
assert.ok(weightedSlot.includes("standing"));
assert.ok(weightedSlot.includes("china dress"));
assert.ok(weightedSlot.includes("earrings"));
assert.ok(!weightedSlot.includes("should_not_inject"));
assert.ok(!weightedSlot.includes("long hair"));
assert.ok(core.isOcCaption(weightedOc));

const adhocWork = core.compileDraft(weightedWork, {
  image_index: 0,
  candidate_id: weightedWork.character_candidates[0].candidate_id,
  target_record: core.targetRecord({
    id: "amiya",
    label: "阿米娅",
    gender: "female",
    identity: ["amiya_(arknights)"],
    appearance: ["brown hair"],
  }, "ark:female:amiya"),
  extra_tags: "halo",
  clothing: "jacket",
  remove_tags: "brown hair",
});
const adhocSlot = adhocWork.draft.comment.v4_prompt.caption.char_captions[0].char_caption;
assert.ok(adhocSlot.includes("amiya_(arknights)"));
assert.ok(adhocSlot.includes("halo"));
assert.ok(adhocSlot.includes("jacket"));
assert.ok(!adhocSlot.includes("brown hair"));

const fat = core.decorateWork({
  work: { work_id: "fat", title: "整段提示词" },
  images: [{
    image_id: "p0",
    prompt_text: "1girl, blonde_hair, blue_eyes, school uniform, classroom",
  }],
});
assert.ok(fat.character_candidates[0].caption.includes("blonde_hair"));
assert.ok(!fat.character_candidates[0].caption.includes("classroom"));
assert.notStrictEqual(fat.character_candidates[0].label, "1girl");
const fatDraft = core.compileDraft(fat, {
  image_index: 0,
  slot_index: 0,
  target_record: target,
  target_reference_id: "preset:female:skadi_f",
});
assert.ok(String(fatDraft.draft.comment.prompt).includes("school uniform"));
assert.ok(String(fatDraft.draft.comment.prompt).includes("classroom"));
assert.ok(!String(fatDraft.draft.comment.prompt).includes("blonde_hair"));
assert.ok(fatDraft.draft.comment.v4_prompt.caption.char_captions[0].char_caption.includes("skadi_(arknights)"));

const named = core.analyzeSlotCaption("1.5::skadi (arknights)::, 1girl, standing");
assert.strictEqual(named.identity_name, "skadi");
assert.strictEqual(named.role, "female");
assert.ok(named.action_tags.join(" ").includes("standing"));

assert.throws(() => {
  core.compileDraft(multi, {
    image_index: 0,
    candidate_id: multi.character_candidates[1].candidate_id,
    slot_index: 0,
    target_record: boy,
  });
});

const stringJson = core.decorateWork({
  work: { work_id: "str", title: "字符串元数据" },
  images: [{
    image_id: "p0",
    ai_json: JSON.stringify({
      Comment: {
        v4_prompt: {
          caption: {
            base_caption: "1girl, cafe",
            char_captions: [{ char_caption: "amiya_(arknights), 1girl, sitting" }],
          },
        },
      },
    }),
  }],
});
assert.strictEqual(stringJson.character_candidates[0].identity_name, "amiya");
assert.strictEqual(stringJson.character_candidates[0].role, "female");

const optimized = core.applyOptimizeTexts(draft.draft.comment, {
  prompt: "1girl, school uniform, classroom, cinematic lighting",
  base_caption: "1girl, school uniform, classroom, cinematic lighting",
  uc: "lowres, blurry",
  char_captions: ["skadi_(arknights), 1girl, white_hair, red_eyes"],
});
assert.ok(String(optimized.prompt).includes("cinematic lighting"));
assert.strictEqual(optimized.uc, "lowres, blurry");
assert.ok(optimized.v4_prompt.caption.char_captions[0].char_caption.includes("skadi_(arknights)"));

const demoLike = core.decorateWork({
  work: { work_id: "demo-ark-amiya", title: "内置样例 · 阿米娅换角" },
  images: [{
    image_id: "demo-ark-amiya_p0",
    prompt_text: "2girls, rhodes island infirmary, soft lighting, official art",
    ai_json: {
      Comment: {
        prompt: "2girls, rhodes island infirmary, soft lighting, official art",
        v4_prompt: {
          caption: {
            base_caption: "2girls, rhodes island infirmary, soft lighting, official art",
            char_captions: [
              { char_caption: "amiya_(arknights), 1girl, brown_hair, blue_eyes, rabbit_ears, standing" },
              { char_caption: "kaltsit_(arknights), 1girl, white_hair, green_eyes, labcoat" },
            ],
          },
        },
      },
    },
  }],
});
assert.strictEqual(demoLike.character_candidates.length, 2);
assert.ok(core.imageComment(demoLike.images[0]).prompt.includes("rhodes island"));
const amiyaSwap = core.compileDraft(demoLike, {
  image_index: 0,
  candidate_id: demoLike.character_candidates[0].candidate_id,
  target_record: target,
  target_reference_id: "preset:female:skadi_f",
});
const demoSnap = core.promptSnapshot(amiyaSwap.draft.comment);
assert.ok(String(demoSnap.char_captions[0].caption).includes("skadi_(arknights)"));
assert.ok(String(demoSnap.char_captions[1].caption).includes("kaltsit_(arknights)"));
assert.ok(String(demoSnap.base_caption || demoSnap.prompt).includes("rhodes island"));

const ganyu = core.targetRecord({
  id: "ganyu_f",
  label: "甘雨",
  gender: "female",
  identity: ["ganyu_(genshin_impact)", "1girl"],
  appearance: ["blue_hair", "horns"],
}, "danbooru:female:ganyu_(genshin_impact)");
const multiSwap = core.compileDraft(demoLike, {
  image_index: 0,
  slot_targets: [
    { gender: "female", gender_slot_index: 0, target_record: target, target_reference_id: "preset:female:skadi_f" },
    { gender: "female", gender_slot_index: 1, target_record: ganyu, target_reference_id: "danbooru:female:ganyu_(genshin_impact)" },
  ],
});
const multiSnap = core.promptSnapshot(multiSwap.draft.comment);
assert.ok(String(multiSnap.char_captions[0].caption).includes("skadi_(arknights)"));
assert.ok(String(multiSnap.char_captions[1].caption).includes("ganyu_(genshin_impact)"));
assert.ok(!String(multiSnap.char_captions[1].caption).includes("kaltsit_(arknights)"));
assert.ok(String(multiSnap.base_caption || multiSnap.prompt).includes("rhodes island"));
assert.strictEqual(core.countGenderSlots(demoLike.character_candidates, 0, "female"), 2);
assert.strictEqual(core.genderSlotIndexOf(demoLike.character_candidates, demoLike.character_candidates[1]), 1);

const styled = core.compileDraft(demoLike, {
  image_index: 0,
  candidate_id: demoLike.character_candidates[0].candidate_id,
  target_record: target,
  target_reference_id: "preset:female:skadi_f",
  style_record: { id: "watercolor", label: "水彩", tag: "watercolor" },
});
assert.ok(String(styled.draft.comment.prompt).includes("watercolor"));
assert.ok(!String(styled.draft.comment.prompt).includes("official art"));
assert.ok(core.applyStyleToComment);
assert.ok(core.recognizeStyles);
assert.ok(core.recognizeWorkStyles);

const recognized = core.recognizeStyles("2girls, official art, watercolor");
assert.ok(recognized.tokens.includes("official art"));
assert.ok(recognized.tokens.includes("watercolor"));
assert.ok(recognized.labels.includes("官方画风"));
assert.ok(recognized.labels.includes("水彩"));

const recImage = core.recognizeStyles(demoLike.images[0]);
assert.ok(recImage.tokens.some((token) => /official art/i.test(token)));
assert.ok(recImage.labels.includes("官方画风"));

const seriesWork = core.decorateWork({
  work: { work_id: "series-style", title: "系列画风" },
  images: [
    demoLike.images[0],
    {
      image_id: "series-style_p1",
      prompt_text: "1girl, moonlight rooftop, official art",
      ai_json: {
        Comment: {
          prompt: "1girl, moonlight rooftop, official art",
          v4_prompt: {
            caption: {
              base_caption: "1girl, moonlight rooftop, official art",
              char_captions: [
                { char_caption: "amiya_(arknights), 1girl, brown_hair, sitting" },
              ],
            },
          },
        },
      },
    },
  ],
});
const workStyles = core.recognizeWorkStyles(seriesWork);
assert.ok(workStyles.tokens.some((token) => /official art/i.test(token)));
assert.strictEqual(workStyles.pages.length, 2);

const styleOnly = core.compileDrafts(seriesWork, {
  style_record: { id: "watercolor", label: "水彩", tag: "watercolor" },
});
assert.strictEqual(styleOnly.pages.length, 2);
styleOnly.pages.forEach((page) => {
  assert.ok(String(page.draft.comment.prompt).includes("watercolor"));
  assert.ok(!String(page.draft.comment.prompt).includes("official art"));
});
assert.ok(String(styleOnly.pages[0].draft.comment.v4_prompt.caption.char_captions[0].char_caption).includes("amiya"));

const skipWork = core.decorateWork({
  work: { work_id: "skip-male", title: "跳过男页" },
  images: [
    demoLike.images[0],
    {
      image_id: "skip-male_p1",
      prompt_text: "1boy, street",
      ai_json: {
        Comment: {
          prompt: "1boy, street",
          v4_prompt: {
            caption: {
              base_caption: "1boy, street",
              char_captions: [{ char_caption: "1boy, black_hair, jacket" }],
            },
          },
        },
      },
    },
  ],
});
const skipped = core.compileDrafts(skipWork, {
  gender_scope: "female",
  target_record: target,
  target_reference_id: "preset:female:skadi_f",
});
assert.ok(skipped.pages.length >= 1);
assert.ok(Array.isArray(skipped.skipped) && skipped.skipped.length >= 1);

const edited = core.applyDraftEdits(draft.draft.comment, {
  prompt: "1girl, classroom, hand-edited",
  uc: "lowres, worst quality",
  seed: 42,
  steps: 22,
});
assert.ok(String(edited.prompt).includes("hand-edited"));
assert.strictEqual(edited.uc, "lowres, worst quality");
assert.strictEqual(edited.seed, 42);
assert.strictEqual(edited.steps, 22);
assert.ok(String(edited.v4_prompt.caption.base_caption).includes("hand-edited"));

console.log("standalone-core ok");
