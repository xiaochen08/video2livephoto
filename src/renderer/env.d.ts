interface Window {
  m3: {
    request(method: string, params?: Record<string, unknown>): Promise<any>;
    pickFile(options?: Record<string, unknown>): Promise<string | null>;
  };
}
