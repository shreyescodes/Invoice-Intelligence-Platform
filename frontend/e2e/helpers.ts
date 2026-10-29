import { expect, type Page } from "@playwright/test";

export const ACCOUNTS = {
  clerk: { email: "clerk@acme.test", password: "clerk-demo-pass" },
  approver: { email: "approver@acme.test", password: "approver-demo-pass" },
  admin: { email: "admin@acme.test", password: "admin-demo-pass" },
} as const;

export async function signIn(page: Page, who: keyof typeof ACCOUNTS) {
  const account = ACCOUNTS[who];
  await page.goto("/login");
  await page.getByLabel("Email").fill(account.email);
  await page.getByLabel("Password").fill(account.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

export async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
}
