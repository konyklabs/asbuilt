import { expect, test } from "./fixtures";

test.describe("check-out", () => {
  test("shows a banner when the rider is at the bike limit", async ({ page, backend }) => {
    test.skip(backend !== "mocked", "no seeding hook puts a rider at the limit in this backend");
    await page.goto("/check-out.html");
    await page.getByLabel("Rider").fill("rider-1");
    await page.getByLabel("Bike").fill("bike-3");
    await page.getByLabel("Station").fill("station-1");
    await page.getByRole("button", { name: "Check out" }).click();
    await expect(page.getByRole("alert")).toHaveText(
      "You already hold as many bikes as one rider can. Dock one, then try again.",
    );
  });
});
