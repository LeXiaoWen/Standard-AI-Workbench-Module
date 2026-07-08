import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("standardWorkbench", {
  platform: process.platform,
  selectDirectory: () => ipcRenderer.invoke("workspace:select-directory"),
  getAppAuthSecret: () => ipcRenderer.invoke("auth:get-app-secret"),
  getBackendUrl: () => ipcRenderer.invoke("backend:get-url"),
});
