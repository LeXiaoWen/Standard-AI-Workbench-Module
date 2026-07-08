export {};

declare global {
  interface Window {
    standardWorkbench?: {
      platform: string;
      selectDirectory: () => Promise<{ name: string; path: string } | null>;
      getAppAuthSecret: () => Promise<string>;
      getBackendUrl: () => Promise<string>;
    };
  }
}
