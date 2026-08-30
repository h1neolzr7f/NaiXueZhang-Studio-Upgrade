(function () {
  const $ = (id) => document.getElementById(id);
  const DRAFT_KEY = "aitag.studio.draft.v1";
  const HISTORY_KEY = "aitag.studio.history.v1";
  const COPIES_KEY = "aitag.studio.copies.v1";
  const SERIES_KEY = "aitag.studio.seriesAll.v1";
  const JOB_KEY = "aitag.studio.job.v1";
  let COPIES_MAX = 20;

  const state = {
    workId: 0,
    pageIndex: 0,
    comment: null,
    params: {},
    beforeTexts: null,
    generating: false,
    currentTaskId: "",
    lastTaskId: "",
    undoStack: [],
    defaultOptimizeMode: "smart",
    sizePresets: [],
    samplers: [],
    history: [],
    draftId: "",
    sourceProvider: "",
    sourceLabel: "",
    /** AITag remote identity for generate grouping / labels */
    onlineWorkIdStr: "",
    onlineSourceTitle: "",
    onlineSourceThumb: "",
    /** @type {Array<{image_index:number, draft:object, slot_indexes?:number[]}>} */
    aitagPages: [],
  };
