const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("m3", {
  request: (method, params = {}) => ipcRenderer.invoke("m3:request", method, params),
});
