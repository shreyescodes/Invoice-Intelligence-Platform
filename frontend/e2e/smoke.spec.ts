import { expect, test } from "@playwright/test";

import { signIn, signOut } from "./helpers";

test("an approver can find, inspect and query invoices", async ({ page }) => {
  await signIn(page, "approver");
  await expect(page.getByText("Straight-through rate")).toBeVisible();

  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: /Review queue/ }).click();
  await expect(page.getByRole("heading", { name: "Review queue" })).toBeVisible();
  await page.locator("main a[href^='/invoices/']").first().click();
  await expect(page.getByRole("heading", { name: "Validation" })).toBeVisible();
  await expect(page.getByRole("img", { name: /page 1/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();

  await page.getByRole("link", { name: "Ask" }).click();
  await page.getByRole("button", { name: "Which invoices are waiting for review?" }).click();
  await expect(page.getByText("Curated query", { exact: true })).toBeVisible();

  await signOut(page);
});

test("a clerk can review details but cannot approve", async ({ page }) => {
  await signIn(page, "clerk");
  await page.goto("/invoices?tab=review");
  await page.locator("tbody tr").first().click();
  await expect(page.getByRole("heading", { name: "Validation" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
});

test("unauthenticated users are sent to sign in", async ({ page }) => {
  await page.goto("/invoices");
  await expect(page).toHaveURL(/\/login$/);
});
