import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("standardWorkbench", {
  platform: process.platform,
  selectDirectory: () => ipcRenderer.invoke("workspace:select-directory"),
  openPath: (path: string) => ipcRenderer.invoke("workspace:open-path", path),
  getAppAuthSecret: () => ipcRenderer.invoke("auth:get-app-secret"),
  getBackendUrl: () => ipcRenderer.invoke("backend:get-url"),
});
