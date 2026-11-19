import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    maxWorkers: 2,
    projects: [
      { test: { name: "server", include: ["server/tests/**/*.test.ts"], environment: "node" } },
      {
        test: {
          name: "client",
          include: ["client/tests/**/*.test.{ts,tsx}"],
          environment: "node",
          env: { TZ: "UTC" },
          setupFiles: ["./client/tests/setup.tsx"],
        },
      },
    ],
  },
});
