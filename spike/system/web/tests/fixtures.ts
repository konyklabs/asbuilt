import { test as base, expect, type Page } from "@playwright/test";

export type Backend = "mocked" | "fake" | "real";

async function routeApiToMocks(page: Page): Promise<void> {
  await page.route(
    (url) => url.pathname === "/api/fares/preview",
    (route) => route.fulfill({ json: { amount_cents: 2500 } }),
  );
  await page.route("**/api/rides/checkout", (route) =>
    route.fulfill({ status: 409, json: { error: "checkout_limit_reached" } }),
  );
  await page.route("**/api/refunds", (route) =>
    route.fulfill({ status: 422, json: { error: "refund_window_expired" } }),
  );
}

export const test = base.extend<{ backend: Backend }>({
  backend: ["real", { option: true }],
  page: async ({ page, backend }, use) => {
    if (backend === "mocked") {
      await routeApiToMocks(page);
    }
    await use(page);
  },
});

export { expect };
