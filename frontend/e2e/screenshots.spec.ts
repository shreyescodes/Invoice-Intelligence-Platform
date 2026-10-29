import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

import { signIn, signOut } from "./helpers";

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(here, "../../docs/screenshots");
const SAMPLE = path.resolve(here, "../../samples/invoices/12-sharda-stationery-try-me.pdf");

async function shot(page: Page, name: string) {
  await page.waitForLoadState("networkidle");
  await page.locator("[data-sonner-toast]").first().waitFor({ state: "detached", timeout: 10_000 }).catch(() => {});
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: path.join(OUT, `${name}.png`), animations: "disabled" });
}

test("product tour", async ({ page }) => {
  test.setTimeout(240_000);

  await page.goto("/login");
  await expect(page.getByText("Demo accounts")).toBeVisible();
  await shot(page, "01-sign-in");

  // A clerk uploads an invoice: it is extracted, matched, auto-approved and posted to the ERP.
  await signIn(page, "clerk");
  await page.getByRole("button", { name: "Upload invoices" }).click();
  await page.getByTestId("upload-input").setInputFiles(SAMPLE);
  await expect(page.getByText(/Queued for processing|Already uploaded/)).toBeVisible();
  await shot(page, "02-upload");
  await page.getByRole("dialog").getByRole("link", { name: "View", exact: true }).click();
  await expect(page.getByText(/Posted to the ERP as document/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("img", { name: /page 1/ })).toBeVisible();
  await shot(page, "03-invoice-auto-approved");
  await signOut(page);

  // An approver works the exception queue.
  await signIn(page, "approver");
  await expect(page.getByRole("heading", { name: "Approved spend by month" })).toBeVisible();
  await shot(page, "04-overview");

  await page.getByRole("link", { name: "Invoices", exact: true }).click();
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await shot(page, "05-invoices");

  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: /Review queue/ }).click();
  await expect(page.getByText(/VIT-HYD-26-0318/)).toBeVisible();
  await shot(page, "06-review-queue");

  await page.getByText("Vertex IT Hardware Pvt Ltd").first().click();
  await expect(page.getByRole("heading", { name: "Validation" })).toBeVisible();
  await expect(page.getByRole("img", { name: /page 1/ })).toBeVisible();
  await shot(page, "07-invoice-exception");

  await page.getByRole("button", { name: "Approve" }).click();
  await page.getByLabel(/Comment/).fill("Price revision for the i7 configuration agreed with Vertex on 2 Oct; PO amendment raised.");
  await shot(page, "08-approve-override");
  await page.getByRole("button", { name: "Approve and post" }).click();
  await expect(page.getByText(/Posted to the ERP as document/)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("heading", { name: "Activity" }).scrollIntoViewIfNeeded();
  await shot(page, "09-invoice-approved-audit-trail");

  await page.goto("/review");
  await page.getByText("Ganesh Freight & Logistics LLP").first().click();
  await expect(page.getByText(/only 4 received/).first()).toBeVisible();
  await shot(page, "10-three-way-match-exception");

  await page.getByRole("link", { name: "Vendors" }).click();
  await expect(page.getByText("Kaveri Industrial Components Ltd")).toBeVisible();
  await shot(page, "11-vendors");

  await page.getByRole("link", { name: "Ask" }).click();
  await page.getByRole("button", { name: "Show monthly invoice spend for the last 6 months" }).click();
  await expect(page.getByText("Curated query", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "What is our total spend by vendor this year?" }).click();
  await expect(page.getByText("Curated query", { exact: true })).toHaveCount(2);
  await page.getByRole("button", { name: "Show SQL" }).first().click();
  await shot(page, "12-ask");

  await page.getByRole("link", { name: "Overview" }).click();
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(page.getByRole("heading", { name: "Approved spend by month" })).toBeVisible();
  await shot(page, "13-overview-dark");
  await page.getByRole("button", { name: "Switch to light theme" }).click();

  await page.goto("/api/docs");
  await expect(page.getByText("Invoice Intelligence Platform API").first()).toBeVisible();
  await shot(page, "14-api-docs");
});
