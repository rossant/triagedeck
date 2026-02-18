import { APIClient } from "./lib/api_client.js";
import { DecisionController } from "./lib/decision_controller.js";
import { IndexedDBStore } from "./lib/idb_store.js";
import { SYNC_ERROR, SYNC_OK, SYNCING, SyncManager } from "./lib/sync_manager.js";

const APP_VERSION = "0.1.0";
const baseUrl = "http://127.0.0.1:8000/api/v1";

const el = {
  user: document.getElementById("user"),
  reload: document.getElementById("reload"),
  syncBanner: document.getElementById("sync-banner"),
  syncState: document.getElementById("sync-state"),
  queueDepth: document.getElementById("queue-depth"),
  lastSync: document.getElementById("last-sync"),
  syncError: document.getElementById("sync-error"),
  prev: document.getElementById("prev"),
  next: document.getElementById("next"),
  itemTitle: document.getElementById("item-title"),
  itemImage: document.getElementById("item-image"),
  itemMetadata: document.getElementById("item-metadata"),
  pass: document.getElementById("pass"),
  fail: document.getElementById("fail"),
  note: document.getElementById("note"),
  forceSync: document.getElementById("force-sync"),
  exportState: document.getElementById("export-state"),
  importFile: document.getElementById("import-file"),
  importState: document.getElementById("import-state"),
  crashReplay: document.getElementById("crash-replay"),
  log: document.getElementById("log"),
};

const appState = {
  api: null,
  store: null,
  sync: null,
  decisions: null,
  sessionId: globalThis.crypto?.randomUUID?.() || `session-${Date.now()}`,
  projectId: null,
  items: [],
  itemIndex: 0,
  decisionMap: new Map(),
};

function logLine(text) {
  const ts = new Date().toISOString();
  el.log.textContent = `[${ts}] ${text}\n${el.log.textContent}`.slice(0, 14000);
}

function setSyncStatus({ state, lastSuccessTs, error }) {
  el.syncState.textContent = state;
  el.syncError.textContent = error ? `Error: ${error}` : "";
  el.lastSync.textContent = lastSuccessTs
    ? `Last sync: ${new Date(lastSuccessTs).toLocaleTimeString()}`
    : "Last sync: never";
  el.syncBanner.classList.remove("sync-ok", "syncing", "sync-error");
  if (state === SYNC_OK) {
    el.syncBanner.classList.add("sync-ok");
  } else if (state === SYNCING) {
    el.syncBanner.classList.add("syncing");
  } else if (state === SYNC_ERROR) {
    el.syncBanner.classList.add("sync-error");
  }
}

function setUrlState(itemId) {
  const u = new URL(window.location.href);
  if (itemId) {
    u.searchParams.set("item", itemId);
  }
  u.searchParams.set("ui_v", "1");
  history.replaceState({}, "", u);
}

function getUrlItemId() {
  return new URL(window.location.href).searchParams.get("item");
}

function getUrlState() {
  const u = new URL(window.location.href);
  return {
    item: u.searchParams.get("item"),
    variant: u.searchParams.get("variant"),
    compare: u.searchParams.get("compare"),
    compare_a: u.searchParams.get("compare_a"),
    compare_b: u.searchParams.get("compare_b"),
    reveal: u.searchParams.get("reveal"),
    zoom: u.searchParams.get("zoom"),
    pan_x: u.searchParams.get("pan_x"),
    pan_y: u.searchParams.get("pan_y"),
    ui_v: u.searchParams.get("ui_v"),
  };
}

function renderCurrentItem() {
  const item = appState.items[appState.itemIndex];
  if (!item) {
    el.itemTitle.textContent = "No item loaded";
    el.itemMetadata.textContent = "";
    el.itemImage.removeAttribute("src");
    return;
  }

  const decision = appState.decisionMap.get(item.item_id);
  const tag = decision ? ` | local decision: ${decision.decision_id}` : "";
  el.itemTitle.textContent = `${item.external_id} (${appState.itemIndex + 1}/${appState.items.length})${tag}`;
  if (item.uri && !item.uri.startsWith("/media/")) {
    el.itemImage.src = item.uri;
  } else {
    el.itemImage.removeAttribute("src");
  }
  el.itemImage.alt = item.external_id;
  el.itemMetadata.textContent = JSON.stringify(item.metadata || {}, null, 2);

  setUrlState(item.item_id);
  appState.store
    .putLastPosition(appState.projectId, { project_id: appState.projectId, item_id: item.item_id })
    .catch((err) => logLine(`Could not persist position: ${err.message}`));
}

async function refreshQueueDepth() {
  if (!appState.sync) {
    return;
  }
  const depth = await appState.sync.getQueueDepth();
  el.queueDepth.textContent = `Queued: ${depth}`;
}

async function loadAllItems(projectId) {
  const items = [];
  let cursor = null;
  for (let i = 0; i < 10; i += 1) {
    const page = await appState.api.listItems(projectId, cursor, 200);
    items.push(...page.items);
    if (!page.next_cursor) {
      break;
    }
    cursor = page.next_cursor;
  }
  return items;
}

async function loadAllServerDecisions(projectId) {
  const decisions = [];
  let cursor = null;
  for (let i = 0; i < 20; i += 1) {
    const page = await appState.api.getDecisions(projectId, cursor, 2000);
    decisions.push(...(page.decisions || []));
    if (!page.next_cursor) {
      break;
    }
    cursor = page.next_cursor;
  }
  return decisions;
}

function rankServerDecision(row) {
  return [Number(row.ts_client || 0), Number(row.ts_server || 0), String(row.event_id || "")];
}

function rankPendingEvent(row) {
  return [Number(row.ts_client || 0), Number(row.ts_server || 0), String(row.event_id || "")];
}

function compareRank(a, b) {
  if (a[0] !== b[0]) {
    return a[0] - b[0];
  }
  if (a[1] !== b[1]) {
    return a[1] - b[1];
  }
  return a[2].localeCompare(b[2]);
}

async function hydrateDecisionMap(projectId) {
  const serverDecisions = await loadAllServerDecisions(projectId);
  const pendingEvents = await appState.store.getAllPendingEvents(projectId);

  const merged = new Map();
  for (const row of serverDecisions) {
    merged.set(row.item_id, {
      project_id: projectId,
      item_id: row.item_id,
      decision_id: row.decision_id,
      note: row.note || "",
      event_id: row.event_id,
      ts_client: row.ts_client,
      ts_server: row.ts_server,
      source: "server",
    });
  }

  const pendingByItem = new Map();
  for (const ev of pendingEvents) {
    const prev = pendingByItem.get(ev.item_id);
    if (!prev || compareRank(rankPendingEvent(prev), rankPendingEvent(ev)) < 0) {
      pendingByItem.set(ev.item_id, ev);
    }
  }

  for (const [itemId, ev] of pendingByItem.entries()) {
    const prev = merged.get(itemId);
    if (!prev || compareRank(rankServerDecision(prev), rankPendingEvent(ev)) <= 0) {
      merged.set(itemId, {
        project_id: projectId,
        item_id: itemId,
        decision_id: ev.decision_id,
        note: ev.note || "",
        event_id: ev.event_id,
        ts_client: ev.ts_client,
        ts_server: 0,
        source: "pending",
      });
    } else {
      // Unsynced event must remain visible immediately even if older by rank.
      merged.set(itemId, {
        project_id: projectId,
        item_id: itemId,
        decision_id: ev.decision_id,
        note: ev.note || "",
        event_id: ev.event_id,
        ts_client: ev.ts_client,
        ts_server: 0,
        source: "pending",
      });
    }
  }

  for (const row of merged.values()) {
    await appState.store.putLocalDecision(projectId, row.item_id, row);
  }
  appState.decisionMap = merged;
}

function moveBy(delta) {
  if (!appState.items.length) {
    return;
  }
  const next = Math.max(0, Math.min(appState.items.length - 1, appState.itemIndex + delta));
  appState.itemIndex = next;
  renderCurrentItem();
}

async function exportLocalState() {
  const payload = await appState.store.exportProjectState(appState.projectId, getUrlState(), APP_VERSION);
  const text = JSON.stringify(payload, null, 2);
  const blob = new Blob([text], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  a.href = url;
  a.download = `triagedeck_local_state_${appState.projectId}_${stamp}.json`;
  a.click();
  URL.revokeObjectURL(url);
  logLine("Local state exported.");
}

function validateImportPayload(payload, projectId) {
  if (!payload || typeof payload !== "object") {
    throw new Error("Invalid payload: expected JSON object");
  }
  if (payload.schema_version !== 1) {
    throw new Error(`Unsupported schema_version: ${payload.schema_version}`);
  }
  if (payload.project_id !== projectId) {
    throw new Error(`Project mismatch: expected ${projectId}, got ${payload.project_id}`);
  }
  if (!Array.isArray(payload.pending_events) || !Array.isArray(payload.local_decisions)) {
    throw new Error("Invalid payload: missing pending_events/local_decisions arrays");
  }
}

async function importLocalState() {
  const file = el.importFile.files?.[0];
  if (!file) {
    throw new Error("Choose a JSON file first");
  }
  const text = await file.text();
  const payload = JSON.parse(text);
  validateImportPayload(payload, appState.projectId);

  await appState.store.importProjectState(appState.projectId, payload);
  await hydrateDecisionMap(appState.projectId);

  const target = payload.url_state?.item || payload.last_position?.item_id;
  if (target) {
    const idx = appState.items.findIndex((it) => it.item_id === target);
    if (idx >= 0) {
      appState.itemIndex = idx;
    }
  }

  renderCurrentItem();
  await refreshQueueDepth();
  appState.sync.schedule(10);
  logLine("Local state imported and reconciled.");
}

async function runCrashReplayTest() {
  const item = appState.items[appState.itemIndex];
  if (!item) {
    throw new Error("No active item for crash test");
  }

  const event = {
    event_id: globalThis.crypto?.randomUUID?.() || `ev-${Date.now()}`,
    project_id: appState.projectId,
    item_id: item.item_id,
    decision_id: "pass",
    note: "crash-replay",
    ts_client: Date.now(),
  };
  await appState.store.putPendingEvent(event);
  await appState.store.putLocalDecision(appState.projectId, item.item_id, {
    ...event,
    source: "pending",
  });
  appState.decisionMap.set(item.item_id, {
    ...event,
    source: "pending",
  });
  renderCurrentItem();

  appState.sync.stop();
  appState.sync = new SyncManager({
    api: appState.api,
    store: appState.store,
    projectId: appState.projectId,
    sessionId: appState.sessionId,
    onStatus: async (status) => {
      setSyncStatus(status);
      await refreshQueueDepth();
    },
  });
  await appState.sync.start();
  appState.sync.schedule(10);

  const deadline = Date.now() + 10000;
  let depth = await appState.sync.getQueueDepth();
  while (depth > 0 && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    depth = await appState.sync.getQueueDepth();
  }
  if (depth === 0) {
    logLine("Crash replay test passed: pending queue flushed after restart.");
  } else {
    throw new Error("Crash replay test failed: queue did not flush in time");
  }
}

function bindKeyboard() {
  window.addEventListener("keydown", async (event) => {
    if (event.target === el.note) {
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      moveBy(-1);
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      moveBy(1);
      return;
    }
    if (event.key.toLowerCase() === "p") {
      event.preventDefault();
      await appState.decisions.decide("pass", el.note.value.trim());
      await refreshQueueDepth();
      renderCurrentItem();
      return;
    }
    if (event.key.toLowerCase() === "f") {
      event.preventDefault();
      await appState.decisions.decide("fail", el.note.value.trim());
      await refreshQueueDepth();
      renderCurrentItem();
      return;
    }
    if (event.key.toLowerCase() === "r") {
      event.preventDefault();
      appState.sync.schedule(10);
    }
  });
}

function bindUIActions() {
  el.prev.onclick = () => moveBy(-1);
  el.next.onclick = () => moveBy(1);
  el.pass.onclick = async () => {
    await appState.decisions.decide("pass", el.note.value.trim());
    await refreshQueueDepth();
    renderCurrentItem();
  };
  el.fail.onclick = async () => {
    await appState.decisions.decide("fail", el.note.value.trim());
    await refreshQueueDepth();
    renderCurrentItem();
  };
  el.forceSync.onclick = () => appState.sync.schedule(10);

  el.exportState.onclick = () => {
    exportLocalState().catch((err) => logLine(`Export failed: ${err.message}`));
  };
  el.importState.onclick = () => {
    importLocalState().catch((err) => logLine(`Import failed: ${err.message}`));
  };
  el.crashReplay.onclick = () => {
    runCrashReplayTest().catch((err) => logLine(`Crash replay test failed: ${err.message}`));
  };
}

async function bootstrap() {
  appState.store = new IndexedDBStore();
  await appState.store.init();

  appState.api = new APIClient(baseUrl, () => el.user.value.trim());

  const projects = await appState.api.listProjects();
  if (!projects.projects.length) {
    throw new Error("No visible projects for this user");
  }

  appState.projectId = projects.projects[0].project_id;
  appState.items = await loadAllItems(appState.projectId);
  await hydrateDecisionMap(appState.projectId);

  const saved = await appState.store.getLastPosition(appState.projectId);
  const targetItemId = getUrlItemId() || saved?.item_id;
  if (targetItemId) {
    const idx = appState.items.findIndex((it) => it.item_id === targetItemId);
    if (idx >= 0) {
      appState.itemIndex = idx;
    }
  }

  appState.sync = new SyncManager({
    api: appState.api,
    store: appState.store,
    projectId: appState.projectId,
    sessionId: appState.sessionId,
    onStatus: async (status) => {
      setSyncStatus(status);
      await refreshQueueDepth();
    },
  });

  appState.decisions = new DecisionController({
    store: appState.store,
    syncManager: appState.sync,
    projectId: appState.projectId,
    getActiveItemId: () => appState.items[appState.itemIndex]?.item_id,
    onDecision: ({ itemId, decisionId }) => {
      appState.decisionMap.set(itemId, {
        project_id: appState.projectId,
        item_id: itemId,
        decision_id: decisionId,
        source: "pending",
      });
      logLine(`Decision ${decisionId} saved locally for ${itemId}`);
    },
  });

  bindKeyboard();
  bindUIActions();

  renderCurrentItem();
  await refreshQueueDepth();
  await appState.sync.start();
  logLine(`Loaded ${appState.items.length} items in project ${appState.projectId}`);
}

el.reload.addEventListener("click", () => {
  window.location.reload();
});

bootstrap().catch((err) => {
  logLine(`Bootstrap failed: ${err.message}`);
  setSyncStatus({ state: SYNC_ERROR, lastSuccessTs: null, error: err.message });
});
