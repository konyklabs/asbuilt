import { expect, test } from "./fixtures";

test.describe("fare preview", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/fare-preview.html");
    await page.getByLabel("Minutes").fill("200");
    await page.getByRole("button", { name: "Preview fare" }).click();
  });

  test("shows the price-sheet cap for a 200-minute casual ride", async ({ page }) => {
    await expect(page.locator("#fare-amount")).toHaveText("$25.00");
  });

  test("shows the farebox cap for a 200-minute casual ride", async ({ page }) => {
    await expect(page.locator("#fare-amount")).toHaveText("$30.00");
  });
});
