// Run with playwright-cli run-code after connecting to dashboard_fixture.py.
// The fixture contains no model credentials. All requests stay on its loopback origin.
async (page) => {
  const checks = [];
  const assert = (condition, message) => {
    if (!condition) throw new Error(message);
    checks.push(message);
  };
  await page.getByRole("button", { name: /^Fix the canary behavior/ }).click();
  await page.waitForFunction(() => document.querySelector("#agents").children.length >= 4);
  assert(await page.locator("#goal").textContent() ===
    "Fix the canary behavior <script>window.compromised=true</script>", "literal untrusted task text");
  assert(await page.evaluate(() => window.compromised === undefined), "XSS did not execute");
  assert(await page.locator("#delivery").textContent() !== "Verified complete", "fake evidence not promoted");
  assert(await page.locator("#graph li").count() === 2, "actual two child writers and root verifier");
  assert(await page.locator("#token").inputValue() === "", "token input cleared");
  assert(await page.evaluate(() => localStorage.length === 0 && sessionStorage.length === 0 && document.cookie === ""), "no browser credential persistence");
  assert(!page.url().includes("token"), "no URL token");
  await page.getByRole("button", { name: "View patch", exact: true }).click();
  await page.waitForFunction(() => document.querySelector("#artifact-content").textContent.includes("diff --git"));
  assert((await page.locator("#artifact-hash").textContent()).includes("Display is redacted"), "stored digest distinguished from redacted display");
  await page.getByRole("button", { name: "Close artifact" }).click();
  await page.getByRole("button", { name: "Replay from start" }).click();
  await page.waitForFunction(() => document.querySelector("#events").textContent.includes("#1"));
  assert(await page.locator("#events li").count() <= 200, "bounded event replay");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: "output/playwright/dashboard-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "mobile no horizontal overflow");
  await page.screenshot({ path: "output/playwright/dashboard-mobile.png", fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.evaluate(() => { document.documentElement.style.fontSize = "32px"; });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "200 percent text no horizontal overflow");
  await page.screenshot({ path: "output/playwright/dashboard-zoom.png", fullPage: true });
  await page.evaluate(() => { document.documentElement.style.fontSize = ""; });
  await page.getByRole("button", { name: "Refresh", exact: true }).focus();
  await page.keyboard.press("Tab");
  assert(await page.evaluate(() => document.activeElement?.tagName === "BUTTON"), "keyboard task navigation");
  await page.context().setOffline(true);
  await page.waitForFunction(() => document.querySelector("#connection").dataset.state === "offline", undefined, { timeout: 18000 });
  assert((await page.locator("#connection").textContent()).includes("Disconnected"), "lost connection visibly stale");
  await page.context().setOffline(false);
  await page.waitForFunction(() => document.querySelector("#connection").dataset.state === "live", undefined, { timeout: 18000 });
  assert(await page.locator("#events li").count() <= 200, "reconnected event window bounded");
  await page.getByRole("button", { name: "Disconnect", exact: true }).click();
  assert(await page.locator("#workspace").isHidden(), "disconnect hides private task view");
  assert(await page.locator("#token").inputValue() === "", "disconnect forgets input");
  await page.getByRole("textbox", { name: "Access token from fleet dashboard" }).fill("invalid-fixture-token");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page.waitForFunction(() => !document.querySelector("#error").hidden);
  assert(await page.locator("#workspace").isHidden(), "unauthorized view stays hidden");
  return { checks: checks.length, passed: checks };
}
