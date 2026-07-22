// Vigil browser extension event tracker with offline resilience queue.
const DEFAULT_SERVER_URL = "http://127.0.0.1:8200/track";
const MAX_QUEUE_SIZE = 20;
let lastSignature = "";

async function serverUrl() {
  const { vigilServerUrl } = await chrome.storage.local.get("vigilServerUrl");
  return vigilServerUrl || DEFAULT_SERVER_URL;
}

async function getQueue() {
  const { offlineQueue } = await chrome.storage.local.get("offlineQueue");
  return Array.isArray(offlineQueue) ? offlineQueue : [];
}

async function saveQueue(queue) {
  await chrome.storage.local.set({ offlineQueue: queue });
}

async function enqueueEvent(payload) {
  let queue = await getQueue();
  queue.push(payload);
  if (queue.length > MAX_QUEUE_SIZE) {
    queue = queue.slice(queue.length - MAX_QUEUE_SIZE);
  }
  await saveQueue(queue);
  lastSignature = ""; // Reset signature so active state is re-evaluated upon reconnect
}

async function flushQueue() {
  let queue = await getQueue();
  if (queue.length === 0) return;

  const url = await serverUrl();
  let nextQueue = [...queue];

  for (let i = 0; i < queue.length; i++) {
    const payload = queue[i];
    try {
      const res = await fetch(url, {
        method: "POST",
        mode: "cors",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        nextQueue.shift();
      } else {
        break;
      }
    } catch (error) {
      // Server still offline
      break;
    }
  }

  await saveQueue(nextQueue);
}

async function sendOrQueue(payload) {
  await flushQueue();
  const url = await serverUrl();
  try {
    const res = await fetch(url, {
      method: "POST",
      mode: "cors",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      await enqueueEvent(payload);
    }
  } catch (error) {
    console.debug("Vigil webhook unavailable; queuing event.", error);
    await enqueueEvent(payload);
  }
}

async function reportActiveTab(tab, eventType) {
  if (!tab?.active || !tab.url || !/^https?:/i.test(tab.url)) {
    return;
  }

  const signature = `${eventType}:${tab.id}:${tab.url}:${tab.title || ""}`;
  if (signature === lastSignature) {
    return;
  }
  lastSignature = signature;

  const payload = {
    source: "browser",
    url: tab.url,
    title: tab.title || null,
    event_type: eventType,
    metadata: { tab_id: tab.id, window_id: tab.windowId }
  };

  await sendOrQueue(payload);
}

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  reportActiveTab(await chrome.tabs.get(tabId), "tab_activated");
});

chrome.tabs.onUpdated.addListener((_, changeInfo, tab) => {
  if (tab.active && (changeInfo.url || changeInfo.title)) {
    reportActiveTab(tab, "tab_updated");
  }
});

chrome.windows.onFocusChanged.addListener(async (windowId) => {
  if (windowId === chrome.windows.WINDOW_ID_NONE) {
    return;
  }
  const [tab] = await chrome.tabs.query({ active: true, windowId });
  reportActiveTab(tab, "window_focused");
});

chrome.webNavigation.onHistoryStateUpdated.addListener(async ({ tabId }) => {
  const tab = await chrome.tabs.get(tabId);
  if (tab.active) {
    reportActiveTab(tab, "history_state_updated");
  }
});
