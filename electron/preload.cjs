const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("m3", {
  request: (method, params = {}) => ipcRenderer.invoke("m3:request", method, params),
  pickFile: (options = {}) => ipcRenderer.invoke("m3:pick-file", options),
  pathForFile: (file) => {
    try {
      return webUtils?.getPathForFile(file) || null;
    } catch (_) {
      return null;
    }
  },
  on: (channel, listener) => {
    const allowed = new Set(["v2lp:analysis:event", "v2lp:tasks:event", "v2lp:recovery:progress", "v2lp:app:close-requested"]);
    if (!allowed.has(channel) || typeof listener !== "function") return () => undefined;
    const wrapped = (_event, payload) => {
      if (payload?.event === channel) listener(payload.payload);
    };
    ipcRenderer.on("m3:event", wrapped);
    return () => ipcRenderer.removeListener("m3:event", wrapped);
  },
  quit: () => ipcRenderer.invoke("m3:quit"),
});

contextBridge.exposeInMainWorld("v2lpBridge", {
  invoke: (channel, payload) => ipcRenderer.invoke("m3:request", channel, payload || {}),
  on: (channel, listener) => {
    const allowed = new Set(["v2lp:analysis:event", "v2lp:tasks:event", "v2lp:recovery:progress", "v2lp:app:close-requested"]);
    if (!allowed.has(channel) || typeof listener !== "function") return () => undefined;
    const wrapped = (_event, payload) => {
      if (payload?.event === channel) listener(payload.payload);
    };
    ipcRenderer.on("m3:event", wrapped);
    return () => ipcRenderer.removeListener("m3:event", wrapped);
  },
});
