// Tests for _extensions/version-selector/version-selector.js (run: npm test)
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const SCRIPT = fs.readFileSync(
    path.join(__dirname, "../../_extensions/version-selector/version-selector.js"),
    "utf8",
);

const VERSIONS = [
    { version: "dev", title: "dev", aliases: [] },
    { version: "1.1", title: "1.1", aliases: ["latest"] },
    { version: "1.0", title: "1.0", aliases: [] },
];

const NAVBAR = `
<header id="quarto-header"><nav class="navbar"><div class="container-fluid">
  <div class="collapse navbar-collapse"></div>
  <div class="quarto-navbar-tools"><a id="gh">gh</a></div>
</div></nav></header>`;

// The script assigns window.location.href, which jsdom cannot follow;
// rewrite those assignments to push onto a recorder array instead.
const PATCHED = SCRIPT.replace(/window\.location\.href = ([^;]+);/g, "window.__nav.push($1);");

const tick = () => new Promise((r) => setTimeout(r, 0));

/** Load the script into a jsdom page and let its fetches settle. */
async function setup(opts) {
  const ctx = loadRaw(opts, PATCHED);
  await tick();
  await tick();
  return ctx;
}

/**
 * Build a jsdom page and evaluate `source` in it.
 * `responses` maps absolute URLs to {status, body} or "network-error"; others are 404.
 */
function loadRaw(opts = {}, source) {
    const {
        url = "https://example.org/site/1.1/guide/page.html",
        offset = "../",
        body = NAVBAR,
        versions = VERSIONS,
        versionsUrl = "https://example.org/site/versions.json",
        placement,
        versionsFile,
        responses = {},
    } = opts;
    const metas = [
        `<meta name="quarto:offset" content="${offset}">`,
        placement ? `<meta name="version-selector:placement" content="${placement}">` : "",
        versionsFile ? `<meta name="version-selector:versions-file" content="${versionsFile}">` : "",
    ].join("");
    const dom = new JSDOM(`<!DOCTYPE html><html><head>${metas}</head><body>${body}</body></html>`, {
        url,
        runScripts: "outside-only",
    });
    const win = dom.window;
    const calls = [];
    const all = { ...responses };
    if (versions !== null) all[versionsUrl] = { status: 200, body: versions };
    win.fetch = (target, fopts = {}) => {
        calls.push({ url: String(target), method: fopts.method || "GET" });
        const r = all[String(target)];
        if (r === "network-error") return Promise.reject(new Error("offline"));
        const status = r ? r.status : 404;
        return Promise.resolve({
            ok: status >= 200 && status < 300,
            status,
            json: () => Promise.resolve(r ? r.body : null),
        });
    };
    win.__nav = [];
    win.eval(source);
    return { win, doc: win.document, calls, nav: win.__nav };
}

const selector = (doc) => doc.querySelector(".quarto-version-selector");
const items = (doc) => [...doc.querySelectorAll(".quarto-version-selector .dropdown-item")];

test("fetches versions.json from the site root", async () => {
    const { calls } = await setup();
    assert.equal(calls[0].url, "https://example.org/site/versions.json");
});

test("honours a custom versions-file", async () => {
    const { calls, doc } = await setup({
        versionsFile: "meta/v.json",
        versionsUrl: "https://example.org/site/meta/v.json",
    });
    assert.equal(calls[0].url, "https://example.org/site/meta/v.json");
    assert.ok(selector(doc));
});

test("renders versions in order with aliases and marks the current one", async () => {
    const { doc } = await setup();
    const its = items(doc);
    assert.deepEqual(
        its.map((a) => a.querySelector(".quarto-version-selector-title").textContent),
        ["dev", "1.1", "1.0"],
    );
    assert.deepEqual(
        [...its[1].querySelectorAll(".quarto-version-selector-alias")].map((s) => s.textContent),
        ["latest"],
    );
    assert.ok(its[1].classList.contains("active"));
    assert.equal(its[1].getAttribute("aria-current"), "true");
    assert.equal(doc.querySelector(".quarto-version-selector-toggle").textContent, "1.1");
});

test("an alias directory resolves to its version", async () => {
    const { doc } = await setup({ url: "https://example.org/site/latest/index.html", offset: "./" });
    assert.ok(items(doc)[1].classList.contains("active"));
    assert.equal(doc.querySelector(".quarto-version-selector-toggle").textContent, "1.1");
});

test("unknown current version shows directory name and nothing active", async () => {
    const { doc } = await setup({ url: "https://example.org/site/2.0/index.html", offset: "./" });
    assert.equal(doc.querySelector(".quarto-version-selector-toggle").textContent, "2.0");
    assert.equal(doc.querySelectorAll(".dropdown-item.active").length, 0);
});

test("links point to the same page in each version", async () => {
    const { doc } = await setup({ url: "https://example.org/site/1.1/guide/page.html#sec" });
    assert.deepEqual(
        items(doc).map((a) => a.href),
        [
            "https://example.org/site/dev/guide/page.html#sec",
            "https://example.org/site/1.1/guide/page.html#sec",
            "https://example.org/site/1.0/guide/page.html#sec",
        ],
    );
});

test("clicking navigates to the same page when it exists", async () => {
    const { doc, nav, calls } = await setup({
        responses: { "https://example.org/site/1.0/guide/page.html": { status: 200 } },
    });
    items(doc)[2].click();
    await tick();
    await tick();
    assert.ok(calls.some((c) => c.method === "HEAD"));
    assert.deepEqual(nav, ["https://example.org/site/1.0/guide/page.html"]);
});

test("clicking falls back to the version root when the page is missing", async () => {
    const { doc, nav } = await setup();
    items(doc)[0].click();
    await tick();
    await tick();
    assert.deepEqual(nav, ["https://example.org/site/dev/"]);
});

test("clicking falls back to the version root on network error", async () => {
    const { doc, nav } = await setup({
        responses: { "https://example.org/site/dev/guide/page.html": "network-error" },
    });
    items(doc)[0].click();
    await tick();
    await tick();
    assert.deepEqual(nav, ["https://example.org/site/dev/"]);
});

test("auto placement mounts at the start of the navbar tools", async () => {
    const { doc } = await setup();
    const tools = doc.querySelector(".quarto-navbar-tools");
    assert.equal(tools.firstElementChild, selector(doc));
    assert.ok(selector(doc).classList.contains("quarto-version-selector-navbar"));
});

test("falls back to the navbar collapse when there are no tools", async () => {
    const body = `<header id="quarto-header"><nav class="navbar"><div class="container-fluid">
    <div class="collapse navbar-collapse"></div></div></nav></header>`;
    const { doc } = await setup({ body });
    assert.equal(selector(doc).parentElement, doc.querySelector(".navbar-collapse"));
});

test("without a navbar the selector is fixed to the body", async () => {
    const { doc } = await setup({ body: "<main></main>" });
    assert.equal(selector(doc).parentElement, doc.body);
    assert.ok(selector(doc).classList.contains("quarto-version-selector-fixed"));
});

test("placement=fixed ignores the navbar", async () => {
    const { doc } = await setup({ placement: "fixed" });
    assert.equal(selector(doc).parentElement, doc.body);
});

test("a #version-selector element takes precedence", async () => {
    const { doc } = await setup({ body: NAVBAR + '<div id="version-selector"></div>', placement: "none" });
    assert.equal(selector(doc).parentElement.id, "version-selector");
});

test("placement=none renders nothing without a mount point", async () => {
    const { doc } = await setup({ placement: "none" });
    assert.equal(selector(doc), null);
});

for (const [name, versions] of [
    ["missing versions.json", null],
    ["empty list", []],
    ["non-list JSON", { version: "1.0" }],
]) {
    test(`renders nothing for ${name}`, async () => {
        const { doc } = await setup({ versions });
        assert.equal(selector(doc), null);
    });
}

test("fallback toggle shows and hides the menu and syncs aria-expanded", async () => {
    const { doc } = await setup();
    const menu = doc.querySelector(".quarto-version-selector-menu");
    const button = doc.querySelector(".quarto-version-selector-toggle");
    assert.equal(button.getAttribute("aria-expanded"), "false");
    button.click();
    assert.ok(menu.classList.contains("show"));
    assert.equal(button.getAttribute("aria-expanded"), "true");
    button.click();
    assert.ok(!menu.classList.contains("show"));
    assert.equal(button.getAttribute("aria-expanded"), "false");
    button.click();
    doc.body.click();
    assert.ok(!menu.classList.contains("show"));
    assert.equal(button.getAttribute("aria-expanded"), "false");
});

test("Escape closes the fallback menu", async () => {
    const { doc, win } = await setup();
    const menu = doc.querySelector(".quarto-version-selector-menu");
    const button = doc.querySelector(".quarto-version-selector-toggle");
    button.click();
    doc.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));
    assert.ok(!menu.classList.contains("show"));
    assert.equal(button.getAttribute("aria-expanded"), "false");
    assert.equal(doc.activeElement, button);
});

test("stylesheet hides the menu until it is opened, without Bootstrap", () => {
    const css = fs.readFileSync(
        path.join(__dirname, "../../_extensions/version-selector/version-selector.css"),
        "utf8",
    );
    const dom = new JSDOM(
        `<style>${css}</style><ul class="dropdown-menu quarto-version-selector-menu"></ul>`,
    );
    const menu = dom.window.document.querySelector("ul");
    assert.equal(dom.window.getComputedStyle(menu).display, "none");
    menu.classList.add("show");
    assert.equal(dom.window.getComputedStyle(menu).display, "block");
});

test("version names are escaped as text, not HTML", async () => {
    const { doc } = await setup({
        versions: [{ version: "<img src=x>", title: "<b>x</b>", aliases: [] }],
    });
    assert.equal(doc.querySelector(".quarto-version-selector img, .quarto-version-selector b"), null);
    assert.ok(items(doc)[0].href.includes("%3Cimg%20src%3Dx%3E"));
});
