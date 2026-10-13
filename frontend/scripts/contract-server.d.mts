import type { Server } from 'node:http';

export interface LoggedRequest {
  method: string;
  path: string;
  query: Record<string, string>;
  auth: string | null;
  ctype: string;
  body: any;
  parts: { name: string; filename: string | null }[] | null;
}

export function createContractServer(opts?: { requireAuth?: boolean; coldStartMs?: number }): {
  server: Server;
  log: LoggedRequest[];
  setCold: (ms: number) => void;
};
