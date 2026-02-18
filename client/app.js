import { APIClient } from "./lib/api_client.js";
import { DecisionController } from "./lib/decision_controller.js";
import { IndexedDBStore } from "./lib/idb_store.js";
import { SYNC_ERROR, SYNC_OK, SYNCING, SyncManager } from "./lib/sync_manager.js";

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
  el.log.textContent = `[${ts}] ${text}\n${el.log.textContent}`.slice(0, 12000);
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
    .putLastPosition(appState.projectId, { item_id: item.item_id })
    .catch((err) => logLine(`Could not persist position: ${err.message}`));
}

function setUrlState(itemId) {
  const u = new URL(window.location.href);
  u.searchParams.set("item", itemId);
  u.searchParams.set("ui_v", "1");
  history.replaceState({}, "", u);
}

function getUrlItemId() {
  return new URL(window.location.href).searchParams.get("item");
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

async function hydrateDecisionMap(projectId) {
  const local = await appState.store.getLocalDecisionMap(projectId);
  appState.decisionMap = local;
}

function bindKeyboard() {
  window.addEventListener("keydown", async (event) => {
    if (event.target === el.note) {
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      moveBy(-1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      moveBy(1);
    } else if (event.key.toLowerCase() === "p") {
      event.preventDefault();
      await appState.decisions.decide("pass", el.note.value.trim());
      await refreshQueueDepth();
      renderCurrentItem();
    } else if (event.key.toLowerCase() === "f") {
      event.preventDefault();
      await appState.decisions.decide("fail", el.note.value.trim());
      await refreshQueueDepth();
      renderCurrentItem();
    } else if (event.key.toLowerCase() === "r") {
      event.preventDefault();
      appState.sync.schedule(10);
    }
  });
}

function moveBy(delta) {
  if (!appState.items.length) {
    return;
  }
  const next = Math.max(0, Math.min(appState.items.length - 1, appState.itemIndex + delta));
  appState.itemIndex = next;
  renderCurrentItem();
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
      appState.decisionMap.set(itemId, { item_id: itemId, decision_id: decisionId });
      logLine(`Decision ${decisionId} saved locally for ${itemId}`);
    },
  });

  bindKeyboard();

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
