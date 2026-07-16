export {};

declare global {
  interface Window {
    standardWorkbench?: {
      platform: string;
      selectDirectory: () => Promise<{ name: string; path: string } | null>;
      openPath: (path: string) => Promise<boolean>;
      getAppAuthSecret: () => Promise<string>;
      getBackendUrl: () => Promise<string>;
    };
  }
}
