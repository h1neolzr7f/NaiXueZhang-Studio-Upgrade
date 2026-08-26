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

console.log("standalone-core ok");
