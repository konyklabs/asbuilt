import { expect, test } from "./fixtures";

const DAY_MS = 24 * 60 * 60 * 1000;

test.describe("refund request", () => {
  test("refuses a ride that ended 15 days ago", async ({ page }) => {
    const endedAt = new Date(Date.now() - 15 * DAY_MS).toISOString();
    await page.goto("/refund-request.html");
    await page.getByLabel("Ride", { exact: true }).fill("ride-1");
    await page.getByLabel("Ride ended at").fill(endedAt);
    await page.getByLabel("Charged (cents)").fill("1000");
    await page.getByLabel("Refund (cents)").fill("500");
    await page.getByRole("button", { name: "Request refund" }).click();
    await expect(page.locator("#refund-result")).toHaveText(
      "This ride is too old to refund: the refund window has closed.",
    );
  });
});
